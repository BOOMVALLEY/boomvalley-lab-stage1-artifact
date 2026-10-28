"""`bvl`: the one lifecycle CLI (Input Contract §22; T1-010).

A `bvl-study-1` study and the K0 run it opens take the authoritative gated
lifecycle (`lifecycle.gated`); every command below routes there when its
subject is a study or a journal-2 run:

    bvl validate --experiment STUDY.json                  every design cell's plan
    bvl check    --experiment STUDY.json [--cell C]       coverage + GNDCRW comparison set
                                                          + P08 strict gate-2; writes nothing;
                                                          exit 8 when REFUSED
    bvl run      --experiment STUDY.json --into DIR [--cell C] [--human-desk DESK]
                 [--tool-site SITE]                       a study with tool actors: the
                                                          directory their tools work over
                                                          RUN_OPENED -> the K0 engine, or
                                                          RUN_REFUSED and 0 calls (exit 8);
                                                          exit 9 when the run stopped
                                                          WAITING for a human answer
    bvl status   RUN
    bvl resume   RUN [--experiment STUDY.json] [--cell C] [--plan] [--human-desk DESK]
                 [--tool-site SITE] [--bind-contexts]     the site and the desk must be the
                                                          run's own (BVL-LIFE-012);
                                                          re-decided gate must be the run's
    bvl human enroll  --experiment STUDY.json --desk DESK --actor A
                      --participant participant:TOKEN --consent-terms FILE
                                                          who answers as a human actor, under
                                                          a GRANTED consent record
    bvl human pending --desk DESK                         the delivered, unanswered requests
    bvl human answer  --desk DESK --intent DIGEST         the participant's answer, once
                      (--text T | --file F) [--entered-by operator:TOKEN]
    bvl package  RUN                                      manifest-4 CONFORMANCE package
    bvl verify   RUN [--l1] [--l2] [--l3] [--l4] [--l5]   exit 4 when it does not verify
                 [--calls]
                 [--replay-world --experiment STUDY.json  (--l1 / --l2 / --l3 / --l4: or is
                  [--cell C]]                             not P18 L1 / L2 / L3 / L4 conformant;
                                                          --replay-world: or a committed
                                                          World transition is not recomputed
                                                          from its serialized evidence by the
                                                          study's World; --l3 and --l4
                                                          need --replay-world).  A verified
                                                          package also reports its
                                                          `state_chain`: World(t) ->
                                                          World(t+1) per episode
                                                          (BVL-ROUND-005 when broken) and
                                                          its `call_provenance`: who was
                                                          declared to answer each actor
                                                          call and what answered it
                                                          (--calls: or a model, tool or
                                                          human call is not a declared
                                                          caller's; --l5: or is not P18
                                                          L5 conformant - the plan's
                                                          human and tool actors answered
                                                          every call of theirs and
                                                          nothing else did; needs no
                                                          replay)
    bvl analyse  RUN                                      the pre-bound analysis of a package
                                                          that verifies

The GNDCRW engine of the comparison set is the installed `gndcrw` package; a
design with comparison edges and no engine is refused (BVL-GATE-004).

A legacy `bvl-experiment-2` input may still be validated/checked and its
existing INPUT_LOCKED evidence inspected, but it is no longer a scientific
execution path. `bvl run` and execution-form `bvl resume` retire that input
before any provider call or run creation. Scientific execution uses only the
`bvl-study-1` -> `lifecycle.gated` path. The ungated
`boomvalley-lab run` / `resume` are likewise retired.

    bvl validate --experiment F.json                      I0..I5, writes nothing
    bvl check    --experiment F.json [--gndcrw P]         I0..I6, writes nothing
                 [--expect-schedule S.json]               exit 4 unless the schedule is exact
                 [--expect-experiment-input X]            exit 4 unless the EII is exactly X
    bvl run      --experiment F.json --into DIR           LEGACY_EXECUTION_RETIRED (exit 2):
                                                          0 model calls, DIR not created
    bvl status   RUN
    bvl package  RUN [--parents DIR ...]                  EVIDENCE.json + PACKAGE.json
                 [--withhold-requests REASON]             request content WITHHELD, not published
    bvl verify   RUN [--parents DIR ...]                  exit 4 when it does not verify
                 (a gate record directory: EXECUTION_GATE.json is recomputed)
    bvl resume   RUN (--plan | --release | --recover RECORD) [--operator O --decision T]
                 (no action: LEGACY_EXECUTION_RETIRED, nothing written, 0 model calls)

Like `boomvalley-lab`, a thin adapter: it parses, calls one domain entry
(`experiment_input.pipeline`) and renders. What runs, with which adapter and
which builder, comes from the experiment input (and, on resume, from the
persisted Input Lock) only — `--model`, `--provenance`, `--run-id` and `--lock`
do not exist here. The legacy `boomvalley-lab` CLI is unchanged and keeps them
for NOT_INPUT_LOCKED runs.

Exit codes are the product's (`core.errors.EXIT_CODES`; 8 = the execution gate
did not clear: `run` NOT_STARTED, `check` MANDATORY_REQUIREMENT_NOT_MET /
EXECUTION_NOT_POSSIBLE - a decision on stdout, not an error); a refusal prints its
§20.5 error document with `--json`. An unexpected exception is an `internal`
error (exit 70) with the same document shape, never a traceback: the frames go
to the diagnostic log (`core.log`), stdout stays the renderer's.

    bvl --locale ko-KR <command> ...   human-readable text in ko-KR (en-US default)

`--locale` is a leading global option; precedence `--locale` > BVL_LOCALE > en-US.
`--json` output, codes and exit codes are identical in every locale.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from boomvalley_lab.cli import _now, _readable_output, usage_code
from boomvalley_lab.cli.render import emit, emit_error, render
from boomvalley_lab.core import log
from boomvalley_lab.core.canonical import canonical_json, wire_json
from boomvalley_lab.core.errors import (
    EXIT_CODES,
    EXIT_GATE_NOT_CLEARED,
    EXIT_WAITING,
    BoomvalleyError,
    Category,
    InternalError,
    error_code,
)
from boomvalley_lab.core.i18n import SUPPORTED_LOCALES, resolve_locale, split_locale, translate
from boomvalley_lab.evidence.requests import WITHHOLD_CHOICES

PROGRAM = "bvl"
LOG = log.get_logger("cli.bvl")


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        from boomvalley_lab.experiment_input.errors import InputRefusal

        raise InputRefusal("USAGE_ERROR", usage_code(message), message, layer="CLI",
                           path="argv#")


def _positive(text: str) -> int:
    value = int(text)
    if value < 1:
        raise ValueError(text)
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog=PROGRAM, description="BOOMVALLEY-lab experiment input: validate, "
                                               "check, run and resume an Input-Locked run.")
    commands = parser.add_subparsers(dest="command", parser_class=_Parser)
    machine = argparse.ArgumentParser(add_help=False)
    machine.add_argument("--json", action="store_true", help="machine-readable output")

    for name, help_text in (("validate", "validate an experiment input (writes nothing)"),
                            ("check", "validate and run the GNDCRW preflight (writes nothing)"),
                            ("run", "open a gated run of a bvl-study-1 study and execute it")):
        sub = commands.add_parser(name, help=help_text, parents=[machine])
        sub.add_argument("--experiment", required=True,
                         help="the bvl-study-1 study (a bvl-experiment-2 input: validate / "
                              "check only; its execution is retired)")
        if name in ("check", "run"):
            sub.add_argument("--gndcrw", help="absolute path of the gndcrw executable "
                                              "(default: one PATH lookup)")
            sub.add_argument("--expect-schedule", dest="expect_schedule", metavar="S.json",
                             help="the frozen record order (a JSON list of record keys or a "
                                  "bvl-expected-schedule-1 object); anything but an exact "
                                  "match refuses before any model call")
            sub.add_argument("--expect-experiment-input", dest="expect_experiment_input",
                             metavar="IDENTITY_OR_FILE",
                             help="the frozen ExperimentInputIdentity (as printed by "
                                  "`bvl check`, a file holding it, a "
                                  "bvl-expected-experiment-input-1 object or a frozen "
                                  "input.json); anything but an exact match refuses before "
                                  "any model call")
        if name in ("check", "run"):
            sub.add_argument("--cell", help="the design cell of a bvl-study-1 study "
                                            "(required when the design has more than one)")
        if name == "run":
            sub.add_argument("--into", required=True, help="the run directory to create")
            sub.add_argument("--human-desk", dest="human_desk", metavar="DESK",
                             help="a study with human actors: the desk directory they are "
                                  "asked through (outside the run directory)")
            sub.add_argument("--tool-site", dest="tool_site", metavar="SITE",
                             help="a study with tool actors: the directory their tools "
                                  "work over (outside the run directory)")
            sub.add_argument("--stop-after", type=_positive, dest="stop_after")

    status = commands.add_parser("status", parents=[machine],
                                 help="classification, Input Lock verification and run status")
    status.add_argument("run")

    resume = commands.add_parser("resume", parents=[machine],
                                 help="re-decide a gated run's gate, then continue it")
    resume.add_argument("run")
    resume.add_argument("--plan", action="store_true", help="show the plan; change nothing")
    resume.add_argument("--recover", metavar="RECORD")
    resume.add_argument("--release", action="store_true")
    resume.add_argument("--operator")
    resume.add_argument("--decision")
    resume.add_argument("--stop-after", type=_positive, dest="stop_after")
    resume.add_argument("--experiment", help="a gated run: the bvl-study-1 study it was "
                                             "opened from (re-decided before anything runs)")
    resume.add_argument("--cell", help="a gated run: the design cell it executes")
    resume.add_argument("--human-desk", dest="human_desk", metavar="DESK",
                        help="a gated run with human actors: the desk they are asked through")
    resume.add_argument("--tool-site", dest="tool_site", metavar="SITE",
                        help="a gated run with tool actors: the directory their tools work over")
    resume.add_argument("--bind-contexts", dest="bind_contexts", action="store_true",
                        help="a gated run opened before runs were bound to their tool site "
                             "and desk (it holds no context-binding.json): bind it to the "
                             "--tool-site / --human-desk given, on the operator's word")

    human = commands.add_parser("human", help="the desk of a study's human actors")
    actions = human.add_subparsers(dest="action", parser_class=_Parser)
    enroll = actions.add_parser("enroll", parents=[machine],
                                help="enroll a participant as a human actor")
    enroll.add_argument("--experiment", required=True)
    enroll.add_argument("--desk", required=True)
    enroll.add_argument("--actor", required=True)
    enroll.add_argument("--participant", required=True, help="a pseudonym participant:TOKEN")
    enroll.add_argument("--consent-terms", dest="consent_terms", required=True, metavar="FILE",
                        help="the consent terms the participant granted; their SHA-256 must "
                             "be the contract's")
    pending = actions.add_parser("pending", parents=[machine],
                                 help="the delivered requests that have no answer")
    pending.add_argument("--desk", required=True)
    answer = actions.add_parser("answer", parents=[machine],
                                help="enter the participant's answer to one delivered request")
    answer.add_argument("--desk", required=True)
    answer.add_argument("--intent", required=True,
                        help="the request intent digest `bvl human pending` lists")
    answer.add_argument("--text")
    answer.add_argument("--file")
    answer.add_argument("--entered-by", dest="entered_by", metavar="operator:TOKEN")

    for name, help_text in (("package", "package a SEALED run as an EPC-v1 evidence package"),
                            ("verify", "verify an EPC-v1 evidence package by recomputation")):
        sub = commands.add_parser(name, help=help_text, parents=[machine])
        sub.add_argument("run")
        sub.add_argument("--parents", nargs="*", metavar="DIR", default=[],
                         help="parent evidence packages handed to the verifier")
        if name == "package":
            sub.add_argument("--withhold-requests", dest="withhold_requests",
                             choices=sorted(WITHHOLD_CHOICES), metavar="REASON",
                             help="do not publish the request bytes; state their digest, "
                                  "size and this reason (request_content WITHHELD): "
                                  + ", ".join(sorted(WITHHOLD_CHOICES)))
        else:
            sub.add_argument("--l1", action="store_true",
                             help="a gated run: require the P18 L1 conformance claim "
                                  "(exit 4 when the package is NOT_L1)")
            sub.add_argument("--l2", action="store_true",
                             help="a gated run: require the P18 L2 conformance claim "
                                  "(exit 4 when the package is NOT_L2)")
            sub.add_argument("--l3", action="store_true",
                             help="a gated run: require the P18 L3 conformance claim, which "
                                  "needs --replay-world (exit 4 when the package is NOT_L3)")
            sub.add_argument("--l4", action="store_true",
                             help="a gated run: require the P18 L4 conformance claim (rounds, "
                                  "termination, state chain, memory), which needs "
                                  "--replay-world (exit 4 when the package is NOT_L4)")
            sub.add_argument("--l5", action="store_true",
                             help="a gated run: require the P18 L5 conformance claim (the "
                                  "plan's human and tool actors answered every call of "
                                  "theirs, hidden calls = 0, no blind tool retry; exit 4 "
                                  "when the package is NOT_L5)")
            sub.add_argument("--calls", action="store_true",
                             help="a gated run: require that every model, human and tool "
                                  "call of the run is a declared caller's (exit 4 when its "
                                  "call provenance is NOT_DECLARED: a hidden call)")
            sub.add_argument("--replay-world", action="store_true", dest="replay_world",
                             help="a gated run: recompute every committed World transition "
                                  "from the package's serialized evidence on the World of "
                                  "--experiment (exit 4 when one is not reproduced)")
            sub.add_argument("--experiment", help="--replay-world: the bvl-study-1 study the "
                                                  "run was opened from")
            sub.add_argument("--cell", help="--replay-world: the design cell the run executes")
    analyse = commands.add_parser("analyse", parents=[machine],
                                  help="the pre-bound analysis of a gated run's verified package")
    analyse.add_argument("run")
    return parser


#: options of the Input-Lock path a gated (bvl-study-1) subject does not take
INPUT_LOCK_ONLY = ("gndcrw", "expect_schedule", "expect_experiment_input", "stop_after",
                   "recover", "release", "operator", "decision", "withhold_requests")


def _gated_subject(arguments) -> bool:
    """A bvl-study-1 study, or the journal-2 run a study opened."""
    from boomvalley_lab.lifecycle import gated, study

    if arguments.command in ("validate", "check", "run"):
        try:
            subject = study.read_subject(Path(arguments.experiment))
        except Exception:  # unreadable: the Input-Lock path states its own refusal
            return False
        return study.is_study(subject)
    return arguments.command == "analyse" or gated.is_k0_run(Path(arguments.run))


def _gndcrw_engine():
    """The installed GNDCRW engine as the comparison set's injected callable (or None)."""
    try:
        from gndcrw.core.engine import verify
        from gndcrw.load import Documents, normalize
    except ImportError:
        return None

    def engine(subjects):
        return verify(normalize(Documents(
            subjects["declaration"], subjects["target_catalog"], subjects["base_surface"],
            subjects["candidate_surface"], subjects["pair_context"])))

    return engine


def _load_plugin(entry):
    """The one place an installed plugin entry point is imported (P03, T4-011)."""
    return entry.load()


def _gated(arguments) -> dict:
    """The authoritative lifecycle: one call into `lifecycle.gated` per command."""
    from functools import partial

    from boomvalley_lab.experiment_input.errors import InputRefusal
    from boomvalley_lab.lifecycle import gated, study

    load_study = partial(study.load_study, plugin_loader=_load_plugin)

    command = arguments.command
    given = [f"--{name.replace('_', '-')}" for name in INPUT_LOCK_ONLY
             if getattr(arguments, name, None) not in (None, False, [])]
    if given or getattr(arguments, "parents", None):
        raise InputRefusal("USAGE_ERROR", "OPTION_NOT_SUPPORTED",
                           f"{' '.join(given or ['--parents'])}: an Input-Lock option; a gated "
                           "study / run does not take it", layer="CLI", path="argv#")
    if command == "validate":
        return {"command": command, **gated.validate(load_study(Path(arguments.experiment)))}
    if command == "check":
        return {"command": command, **gated.check(load_study(Path(arguments.experiment)),
                                                  cell=arguments.cell, engine=_gndcrw_engine())}
    if command == "run":
        return {"command": command, **gated.run(load_study(Path(arguments.experiment)),
                                                Path(arguments.into), cell=arguments.cell,
                                                tool_site=_tool_site(arguments),
                                                engine=_gndcrw_engine(),
                                                desk=_desk_path(arguments))}
    directory = Path(arguments.run)
    if command == "resume":
        study = None if arguments.experiment is None else load_study(Path(arguments.experiment))
        return {"command": command, **gated.resume(directory, study=study, cell=arguments.cell,
                                                   engine=_gndcrw_engine(), plan=arguments.plan,
                                                   desk=_desk_path(arguments),
                                                   tool_site=_tool_site(arguments),
                                                   bind_contexts=arguments.bind_contexts)}
    if command == "verify":
        if arguments.replay_world != (arguments.experiment is not None) or (
                arguments.cell is not None and not arguments.replay_world):
            raise InputRefusal("USAGE_ERROR", "OPTION_NOT_SUPPORTED",
                               "--replay-world replays the World of the run's study: pass it "
                               "with --experiment STUDY.json (and --cell only with them)",
                               layer="CLI", path="argv#")
        if (arguments.l3 or arguments.l4) and not arguments.replay_world:
            raise InputRefusal("USAGE_ERROR", "OPTION_NOT_SUPPORTED",
                               "--l3 / --l4 claim an independently recomputed World: pass "
                               "them with --replay-world --experiment STUDY.json", layer="CLI",
                               path="argv#")
        replay = load_study(Path(arguments.experiment)) if arguments.replay_world else None
        return {"command": command, **gated.verify(directory, require_l1=arguments.l1,
                                                   require_l2=arguments.l2,
                                                   require_l3=arguments.l3,
                                                   require_l4=arguments.l4,
                                                   require_l5=arguments.l5,
                                                   require_calls=arguments.calls,
                                                   replay=replay,
                                                   cell=arguments.cell)}
    operation = {"status": gated.status, "package": gated.package,
                 "analyse": gated.analyse}[command]
    return {"command": command, **operation(directory)}


def _desk_path(arguments) -> Path | None:
    return None if getattr(arguments, "human_desk", None) is None else Path(arguments.human_desk)


def _tool_site(arguments) -> Path | None:
    return None if getattr(arguments, "tool_site", None) is None else Path(arguments.tool_site)


def _human(arguments) -> dict:
    """The desk of a study's human actors (T5-002): enrollment, deliveries, answers."""
    from boomvalley_lab.experiment_input.errors import InputRefusal
    from boomvalley_lab.lifecycle import human, study

    action = arguments.action
    if action is None:
        raise InputRefusal("USAGE_ERROR", "ARGUMENT_MISSING",
                           "bvl human enroll | pending | answer", layer="CLI", path="argv#")
    desk = Path(arguments.desk)
    if action == "enroll":
        compiled = study.load_study(Path(arguments.experiment), plugin_loader=_load_plugin)
        return {"command": "human", "action": action,
                **human.enroll(compiled, desk, actor=arguments.actor,
                               participant=arguments.participant,
                               consent_terms=Path(arguments.consent_terms))}
    if action == "pending":
        return {"command": "human", "action": action, **human.pending(desk)}
    if (arguments.text is None) == (arguments.file is None):
        raise InputRefusal("USAGE_ERROR", "ARGUMENT_MISSING",
                           "the answer is given as --text T or --file F (one of them)",
                           layer="CLI", path="argv#")
    text = (arguments.text if arguments.file is None
            else Path(arguments.file).read_bytes().decode("utf-8"))
    return {"command": "human", "action": action,
            **human.answer(desk, intent=arguments.intent, text=text,
                           entered_by=arguments.entered_by)}


def _dispatch(arguments) -> dict:
    from boomvalley_lab.experiment_input import pipeline
    from boomvalley_lab.experiment_input.errors import InputRefusal

    command = arguments.command
    _native_paths(arguments)
    if command == "human":
        return _human(arguments)
    if _gated_subject(arguments):
        return _gated(arguments)

    # T1-010: there is exactly one scientific execution path.  Legacy
    # bvl-experiment-2 inputs may still be validated/checked and old evidence
    # inspected, but they cannot start or continue model execution.  Refuse
    # before pipeline.run/resume can create a run or call a provider.
    if command == "run":
        raise InputRefusal("USAGE_ERROR", "LEGACY_EXECUTION_RETIRED",
                           "bvl-experiment-2 scientific execution is retired; use "
                           "bvl-study-1 with the authoritative gated lifecycle",
                           layer="CLI", path="argv#")
    if command == "resume" and not (arguments.plan or arguments.release or arguments.recover):
        raise InputRefusal("USAGE_ERROR", "LEGACY_EXECUTION_RETIRED",
                           "INPUT_LOCKED scientific resume is retired; use bvl-study-1 "
                           "with the authoritative gated lifecycle",
                           layer="CLI", path="argv#")

    if command == "resume" and (arguments.experiment or arguments.cell):
        raise InputRefusal("USAGE_ERROR", "OPTION_NOT_SUPPORTED",
                           "--experiment / --cell resume a gated run; this is an INPUT_LOCKED "
                           "run", layer="CLI", path="argv#")
    if command == "verify" and (arguments.l1 or arguments.l2 or arguments.l3
                                or arguments.l4 or arguments.l5 or arguments.calls
                                or arguments.replay_world
                                or arguments.experiment or arguments.cell):
        raise InputRefusal("USAGE_ERROR", "OPTION_NOT_SUPPORTED",
                           "--l1 / --l2 / --l3 / --l4 / --l5 / --calls / --replay-world claim P18 "
                           "conformance, call provenance or a World replay of a gated run; "
                           "this is an INPUT_LOCKED run",
                           layer="CLI",
                           path="argv#")
    if command == "check" and arguments.cell:
        raise InputRefusal("USAGE_ERROR", "OPTION_NOT_SUPPORTED",
                           "--cell names a design cell of a bvl-study-1 study", layer="CLI",
                           path="argv#")
    if command == "validate":
        return {"command": command, **pipeline.validate(Path(arguments.experiment))}
    if command == "check":
        return {"command": command, **pipeline.check(Path(arguments.experiment),
                                                     gndcrw_path=arguments.gndcrw,
                                                     expect_schedule=arguments.expect_schedule,
                                                     expect_experiment_input=(
                                                         arguments.expect_experiment_input))}
    if command == "status":
        return {"command": command, **pipeline.status(Path(arguments.run))}
    if command in ("package", "verify"):
        from boomvalley_lab.evidence import epc

        directory, parents = Path(arguments.run), tuple(arguments.parents)
        if command == "verify" and not (directory / epc.EVIDENCE_FILE).exists():
            from boomvalley_lab.experiment_input import gate as gates

            if gates.is_record(directory):     # a gated input: no run, a gate record (#81)
                return {"command": command, **gates.verify_record(directory)}
        if command == "package":
            withhold = arguments.withhold_requests
            manifest = epc.write_evidence_package(
                directory, parents=parents, at=_now(),
                withhold=None if withhold is None else WITHHOLD_CHOICES[withhold])
            return {"command": command, "directory": str(directory), **epc.summary(manifest)}
        return {"command": command, "directory": str(directory),
                **epc.read_evidence(directory, parents=parents).document()}
    # resume: an administrative action on existing INPUT_LOCKED evidence, never execution
    asked = [flag for flag, on in (("--plan", arguments.plan), ("--release", arguments.release),
                                   ("--recover", arguments.recover)) if on]
    if len(asked) > 1:
        raise InputRefusal("USAGE_ERROR", "OPTION_NOT_SUPPORTED",
                           f"resume was asked for {' and '.join(asked)}; one action at a time",
                           layer="CLI", path="argv#")
    who = None
    if arguments.release or arguments.recover:
        if not (arguments.operator or "").strip() or not (arguments.decision or "").strip():
            raise InputRefusal("USAGE_ERROR", "ARGUMENT_MISSING",
                               "--operator and --decision are required", layer="CLI",
                               path="argv#")
        who = (arguments.operator, arguments.decision)
    return {"command": command, **pipeline.resume(
        Path(arguments.run), clock=_now, plan=arguments.plan,
        release=who if arguments.release else None,
        recover=(arguments.recover, *who) if arguments.recover else None)}


#: the path arguments read as this OS reads them (#153 req 4: `/c/...` on Windows)
PATH_ARGUMENTS = ("experiment", "into", "gndcrw", "expect_schedule", "human_desk", "desk",
                  "tool_site",
                  "consent_terms", "file")


def _native_paths(arguments) -> None:
    from boomvalley_lab.experiment_input.schedule_gate import native_path

    for name in PATH_ARGUMENTS:
        value = getattr(arguments, name, None)
        if isinstance(value, str) and value:
            setattr(arguments, name, str(native_path(value)))


def main(argv: Sequence[str] | None = None) -> int:
    _readable_output()
    log.configure(os.environ)
    argv = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in argv
    locale, source = resolve_locale(None, None, os.environ)
    try:
        explicit, argv = split_locale(argv)
        if explicit is not None:
            if explicit not in SUPPORTED_LOCALES:
                raise _usage_locale(explicit)
            locale, source = explicit, "cli"
        log.event(LOG, logging.DEBUG, "cli.started", program=PROGRAM, locale=locale,
                  locale_source=source, json=as_json)
        arguments = build_parser().parse_args(argv)
        if arguments.command is None:
            build_parser().print_help()
            return 0
        result = _dispatch(arguments)
        emit(render(result, as_json=arguments.json, locale=locale))
        # a verification that refuses has not succeeded, though nothing raised; a gate
        # that did not clear is a decision (stdout) with its own exit code (#81)
        code = (EXIT_CODES[Category.VERIFICATION]
                if result.get("verified") is False or result.get("conformant") is False else
                EXIT_GATE_NOT_CLEARED if _gate_not_cleared(result) else
                EXIT_WAITING if result.get("execution_status") == "WAITING" else
                EXIT_CODES[Category.EXECUTION] if result.get("execution_status") == "FAILED"
                else 0)
        log.event(LOG, logging.INFO, "cli.finished", command=arguments.command, exit_code=code,
                  verified=result.get("verified"))
        return code
    except BoomvalleyError as error:
        return _refused(error, as_json, locale)
    except OSError as error:
        code = error_code(error)
        # --json: the same locale-independent document as any other error (#126)
        emit_error(wire_json(_fallback_document(Category.EXECUTION, code, str(error)))
                   if as_json else translate("error.os", {"error": error}, locale))
        log.event(LOG, logging.WARNING, "cli.os_error", error=Category.EXECUTION,
                  exit_code=EXIT_CODES[Category.EXECUTION], code=code)
        return EXIT_CODES[Category.EXECUTION]
    except Exception as exc:  # an escaped exception is a product bug, never a verdict
        log.event(LOG, logging.ERROR, "cli.internal_error", error=Category.INTERNAL,
                  exit_code=EXIT_CODES[Category.INTERNAL], exc_info=True)
        internal = InternalError(translate("error.internal",
                                           {"exc_type": type(exc).__name__}, "en-US"))
        return _refused(internal, as_json, locale)


def _gate_not_cleared(result: dict) -> bool:
    """A `run` that did not start; a `check` whose gate blocks. NOT_EVALUATED is not a
    block: a check of an input without an execution profile is legitimate."""
    from boomvalley_lab.experiment_input import gate as gates

    if result.get("lifecycle") == "k0-gate-2":
        decided = (result.get("gate_decision") or {}).get("decision")
        return result.get("command") in ("check", "run") and decided == "REFUSED"
    if result.get("command") == "run":
        return result.get("execution_status") == gates.NOT_STARTED
    return result.get("command") == "check" and result.get("execution_gate_status") in (
        gates.MANDATORY_REQUIREMENT_NOT_MET, gates.EXECUTION_NOT_POSSIBLE)


def _usage_locale(value: str) -> BoomvalleyError:
    from boomvalley_lab.experiment_input.errors import InputRefusal

    return InputRefusal("USAGE_ERROR", "OPTION_NOT_SUPPORTED",
                        translate("usage.locale_value",
                                  {"value": value, "supported": list(SUPPORTED_LOCALES)}),
                        layer="CLI", path="argv#")


def _fallback_document(category: Category, code: str, detail: str) -> dict:
    """The error document of an error without a §20.5 refusal: its category as the
    class and the boundary's stable code (`core.errors.error_code`, #126)."""
    return {"error": category.value, "class": category.value, "code": code,
            "detail": detail, "problems": []}


def _refused(error: BoomvalleyError, as_json: bool, locale: str) -> int:
    """The error report on stderr: the §20.5 document with --json (locale-independent),
    else a localized header. stdout stays empty."""
    document = (error.document() if hasattr(error, "document") else
                _fallback_document(error.category, error_code(error), str(error)))
    exit_code = EXIT_CODES[error.category]
    if as_json:
        emit_error(wire_json({**document, "error": error.category.value,
                              "problems": list(error.problems)}))
    else:
        emit_error(translate("error.header",
                             {"category": error.category.value, "message": error}, locale))
        evidence = document.get("evidence")
        decided = (evidence or {}).get("schedule_preflight")
        if isinstance(decided, dict) and decided.get("message_key"):
            emit_error(translate("error.schedule_preflight",
                                 {"status": decided.get("schedule_preflight_status"),
                                  "message": translate(decided["message_key"],
                                                       decided.get("params"), locale)},
                                 locale))
        gated = (evidence or {}).get("experiment_input_preflight")
        if isinstance(gated, dict) and gated.get("message_key"):
            emit_error(translate("error.experiment_input_preflight",
                                 {"status": gated.get("experiment_input_preflight_status"),
                                  "message": translate(gated["message_key"],
                                                       gated.get("params"), locale)},
                                 locale))
        if evidence:
            emit_error(translate("error.evidence", {"evidence": canonical_json(evidence)},
                                 locale))
    log.event(LOG, logging.WARNING, "cli.refused", error=error.category.value,
              exit_code=exit_code, klass=document.get("class"), code=document.get("code"),
              layer=document.get("layer"))
    return exit_code


def run() -> None:  # console script entry point
    sys.exit(main())


if __name__ == "__main__":  # pragma: no cover
    run()
