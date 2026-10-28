"""The command line: a thin adapter over the domain API.

    validate · lock · run · status · resume · audit · analyse · package · verify

`run` and an executing `resume` are retired (T1-010): they executed a lock with
no execution gate. They refuse (`LEGACY_EXECUTION_RETIRED`, exit 5, nothing
read or written) and redirect to the gated `bvl` lifecycle. `resume --plan`,
`--release` and `--recover` still read and reconcile existing runs.

The CLI parses arguments, calls the one authoritative entry for the operation,
and renders what comes back. It decides nothing. There is no branch here that
classifies a record, judges eligibility, computes an identity, reconciles
custody or lineage, or admits an analysis — those live in the domain and are
reachable one way only, which is why a `--force` or `--skip-audit` flag does
not exist and cannot be added without changing the domain instead.

Every command renders the SAME domain result in human text or, with `--json`,
as canonical JSON. The two are views; they never disagree, because there is
only one result.

Exit codes come from the error category (`core.errors.EXIT_CODES`): 0 success,
2 declaration/input, 3 identity, 4 verification refusal, 5 execution, 6
evidence, 70 internal. A refused claim is not a crash and does not print a
traceback; neither does an unexpected exception (an `internal` error, exit 70,
its frames in the diagnostic log `core.log`). stdout is written by
`cli.render.emit` only. A leading `--locale en-US|ko-KR` (or BVL_LOCALE) changes
human-readable text only, never `--json` output or an exit code.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections.abc import Sequence
from datetime import UTC
from pathlib import Path

from boomvalley_lab.cli.reading import read_declaration
from boomvalley_lab.cli.render import emit, emit_error, render
from boomvalley_lab.core import log
from boomvalley_lab.core.canonical import canonical_json, wire_json
from boomvalley_lab.core.errors import (
    EXIT_CODES,
    BoomvalleyError,
    Category,
    DeclarationError,
    ExecutionError,
    InternalError,
    error_code,
)
from boomvalley_lab.core.i18n import (
    DEFAULT_LOCALE,
    SUPPORTED_LOCALES,
    resolve_locale,
    split_locale,
    translate,
)
from boomvalley_lab.core.strict_json import MalformedJSON
from boomvalley_lab.core.versions import version_document
from boomvalley_lab.verify.gate import ELIGIBLE

PROGRAM = "boomvalley-lab"
LOG = log.get_logger("cli")

#: the analyses this build can run. The LOCK decides which one may run; this
#: only says which of them this installation ships. Loading arbitrary code
#: named by a declaration is not an MVP capability.
PLUGINS = {"counting": "boomvalley_lab.analysis.plugin:CountingPlugin"}


def _now() -> str:
    from datetime import datetime

    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _plugin(name: str):
    if name not in PLUGINS:
        raise ExecutionError(
            f"this installation ships no analysis named {name!r} "
            f"(it has: {', '.join(sorted(PLUGINS))}); run it through the API instead"
        )
    module, _, attribute = PLUGINS[name].partition(":")
    return getattr(__import__(module, fromlist=[attribute]), attribute)()


# =====================================================================
# commands — each one call into the domain, then render
# =====================================================================
def _validate(arguments) -> dict:
    from boomvalley_lab.declare.experiment import load

    experiment = load(read_declaration(arguments.declaration))
    return {"command": "validate", "declaration": str(arguments.declaration),
            "experiment": experiment.meta.id,
            "records": len(experiment.records), "valid": True}


def _lock(arguments) -> dict:
    from boomvalley_lab.identity.lock import lock as make_lock

    document = make_lock(read_declaration(arguments.declaration))
    text = canonical_json(document)
    if arguments.output:
        path = Path(arguments.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    else:
        emit(text)
    return {"command": "lock", "identities": document["identities"],
            "output": arguments.output, "summary": document["summary"]}


#: T1-010: scientific execution has one way in, the gated `bvl` lifecycle. This
#: CLI's `run` and executing `resume` started model calls from a bare lock with no
#: execution gate at all; they are retired and refuse before anything is read or
#: written (zero calls). Reading, auditing, custody release / recovery, analysis
#: and packaging of existing runs are unchanged.
EXECUTION_RETIRED = "LEGACY_EXECUTION_RETIRED"


def _retired(command: str) -> ExecutionError:
    return ExecutionError(
        f"`{PROGRAM} {command}` is retired: it executed without an execution gate. "
        "Scientific execution runs only through the gated lifecycle: "
        "`bvl run --experiment STUDY.json --into DIR` (bvl-study-1, P08 strict gate-2) "
        "and `bvl resume RUN`. Nothing was read and nothing was written.",
        code=EXECUTION_RETIRED)


def _run(arguments) -> dict:
    raise _retired("run")


def _status(arguments) -> dict:
    from boomvalley_lab.runtime.status import status

    return {"command": "status", **status(Path(arguments.run))}


#: what each `resume` flag does to the evidence. `--plan` reads; the others
#: write. An invocation asks for exactly one of these, because a command that
#: advertises itself as read-only and then releases a session is not a
#: read-only command whatever order the flags were typed in.
RESUME_ACTIONS = {"plan": "read-only", "release": "write", "recover": "write"}


def _requested(arguments) -> list[str]:
    """The actions this invocation asks for, named as the user typed them."""
    return [f"--{name}" for name in RESUME_ACTIONS if getattr(arguments, name, None)]


def _one_action(arguments) -> None:
    """Refuse a conflicting invocation BEFORE anything is read or written.

    Not by running the read-only part first and the write afterwards: the
    combination itself has no meaning. `--plan --release` and `--release
    --plan` are the same request and get the same refusal, because argparse
    hands them over as flags and the order they were typed is not semantics.
    """
    asked = _requested(arguments)
    if len(asked) < 2:
        return
    kinds = {RESUME_ACTIONS[name.removeprefix("--")] for name in asked}
    how = ("a read-only action cannot be combined with one that writes"
           if kinds == {"read-only", "write"} else
           "these actions each write; run them one at a time")
    raise DeclarationError(
        f"resume was asked for {' and '.join(sorted(asked))}: {how}. "
        "Nothing was read and nothing was written."
    )


def _resume(arguments) -> dict:
    from boomvalley_lab.runtime.resume import plan_for, recover, release

    _one_action(arguments)
    directory = Path(arguments.run)
    if arguments.release:
        _require(arguments, "release")
        released = release(directory, operator=arguments.operator,
                           decision=arguments.decision, clock=_now)
        return {"command": "resume", "released": released, **plan_for(directory).document()}
    if arguments.recover:
        _require(arguments, "recovery")
        entry = recover(directory, arguments.recover, operator=arguments.operator,
                        decision=arguments.decision, clock=_now)
        return {"command": "resume", "recovered": entry["record"], "origin": entry["origin"],
                **plan_for(directory).document()}
    if arguments.plan:
        return {"command": "resume", "planned": True, **plan_for(directory).document()}
    raise _retired("resume")


def _require(arguments, what: str) -> None:
    if not (arguments.operator or "").strip() or not (arguments.decision or "").strip():
        raise DeclarationError(
            f"{what} records who decided and what they decided: pass --operator and --decision"
        )


def _audit(arguments) -> dict:
    from boomvalley_lab.verify.gate import audit

    report = audit(Path(arguments.run), parents=arguments.parents or ())
    return {"command": "audit", **report.document()}


def _analyse(arguments) -> dict:
    from boomvalley_lab.analysis.run import analyse
    from boomvalley_lab.verify.gate import audit

    directory = Path(arguments.run)
    bound = audit(directory, parents=arguments.parents or ()).binding
    if bound is None:
        raise ExecutionError("this design pre-binds no analysis, so none may be recorded")
    document = analyse(directory, _plugin(bound["plugin"]),
                       parents=arguments.parents or (), clock=_now)
    return {"command": "analyse", "run": document["run"], "dataset": document["dataset"],
            "analysis": document["actual"], "records": document["records"],
            "result": document["result"]}


def _package(arguments) -> dict:
    from boomvalley_lab.evidence.package import write_package

    document = write_package(Path(arguments.run), parents=arguments.parents or (), at=_now())
    return {"command": "package", "run": document["run"], "members": len(document["members"]),
            "dataset": document["dataset"], "analysis": document["analysis"] or [],
            "producer_self_check": document["producer_self_check"]["eligibility"]}


def _verify(arguments) -> dict:
    from boomvalley_lab.evidence.package import read_package

    report = read_package(Path(arguments.run), parents=arguments.parents or ())
    return {"command": "verify", **report.document()}


COMMANDS = {
    "validate": _validate, "lock": _lock, "run": _run, "status": _status,
    "resume": _resume, "audit": _audit, "analyse": _analyse,
    "package": _package, "verify": _verify,
}

#: a command whose rendered result carries a refusal exits non-zero even
#: though nothing raised: an audit that says NOT_ELIGIBLE has not succeeded.
REFUSAL = {
    "audit": lambda result: result["eligibility"] != ELIGIBLE,
    "verify": lambda result: not result["verified"],
}


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog=PROGRAM,
        description="BOOMVALLEY-lab: declare, run, audit and package a synthetic experiment.",
    )
    parser.add_argument("--version", action="store_true", help="print version identifiers")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    # the same flag after the command, without clobbering it when given before
    machine = argparse.ArgumentParser(add_help=False)
    machine.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                         help="machine-readable output")
    commands = parser.add_subparsers(dest="command", parser_class=_Parser)

    for name, help_text in (("validate", "validate a declaration (JSON or YAML)"),
                            ("lock", "validate and emit the experiment lock")):
        sub = commands.add_parser(name, help=help_text, parents=[machine])
        sub.add_argument("declaration")
        if name == "lock":
            sub.add_argument("--output", "-o", help="write the lock here (canonical JSON)")

    run = commands.add_parser("run", parents=[machine],
                              help="execute a locked schedule with the local adapter")
    run.add_argument("lock")
    run.add_argument("--into", required=True, help="the run directory to create")
    run.add_argument("--run-id", required=True, dest="run_id")
    run.add_argument("--stop-after", type=int, dest="stop_after")
    _adapter_arguments(run)

    status = commands.add_parser("status", parents=[machine],
                                 help="what the evidence says about a run")
    status.add_argument("run")

    resume = commands.add_parser("resume", parents=[machine],
                                 help="continue a run where the evidence allows it")
    resume.add_argument("run")
    resume.add_argument("--plan", action="store_true", help="show the plan; change nothing")
    resume.add_argument("--recover", metavar="RECORD",
                        help="operator-confirmed custody recovery of one record")
    resume.add_argument("--release", action="store_true",
                        help="release a session that died holding the run")
    resume.add_argument("--operator", help="who decided (required by --recover/--release)")
    resume.add_argument("--decision", help="what they decided, in their words")
    resume.add_argument("--stop-after", type=int, dest="stop_after")
    _adapter_arguments(resume)

    for name, help_text in (("audit", "run the eligibility gate over a run"),
                            ("analyse", "analyse an ELIGIBLE run with the analysis it binds"),
                            ("package", "describe the run as an evidence package"),
                            ("verify", "verify an evidence package by recomputing it")):
        sub = commands.add_parser(name, help=help_text, parents=[machine])
        sub.add_argument("run")
        sub.add_argument("--parents", nargs="*", metavar="DIR",
                         help="parent evidence packages handed to the verifier")
    return parser


def _adapter_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--model", default="local-echo",
                        help="the model identity the local adapter reports")
    parser.add_argument("--provenance", default=None,
                        help="the adapter provenance the local adapter reports")


def usage_code(message: str) -> str:
    """The closed code of an argparse refusal (both CLIs). argparse states only a
    message, so this reads its fixed (untranslated) wording."""
    return ("ARGUMENT_MISSING" if "required" in message else
            "ARGUMENT_INVALID" if "invalid" in message else "OPTION_NOT_SUPPORTED")


class _UsageError(Exception):
    """An argv the parser refuses; `main` reports it (`_usage`)."""

    def __init__(self, message: str, usage: str) -> None:
        super().__init__(message)
        self.usage = usage


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        # argparse's own text (usage, then "<prog>: error: "), reported by `main`
        raise _UsageError(message, f"{self.format_usage()}{self.prog}: error: ")


def _usage(code: str, message: str, usage: str, as_json: bool, locale: str) -> int:
    """A usage refusal: exit 2 as before; with --json a coded document (#126), else
    argparse's own usage text."""
    if as_json:
        emit_error(wire_json({"error": Category.DECLARATION.value, "code": code,
                              "message": message, "problems": []}))
    else:
        emit_error(usage + message if usage else message)
    log.event(LOG, logging.WARNING, "cli.usage_error", error=Category.DECLARATION,
              exit_code=EXIT_CODES[Category.DECLARATION], code=code)
    return EXIT_CODES[Category.DECLARATION]


def main(argv: Sequence[str] | None = None) -> int:
    _readable_output()
    log.configure(os.environ)
    argv = list(sys.argv[1:] if argv is None else argv)
    locale, source = resolve_locale(None, None, os.environ)
    explicit, argv = split_locale(argv)
    wants_json = "--json" in argv
    if explicit is not None:
        if explicit not in SUPPORTED_LOCALES:
            params = {"value": explicit, "supported": list(SUPPORTED_LOCALES)}
            return _usage("OPTION_NOT_SUPPORTED",
                          translate("usage.locale_value", params,
                                    DEFAULT_LOCALE if wants_json else locale),
                          "", wants_json, locale)
        locale, source = explicit, "cli"
    parser = build_parser()
    try:
        arguments = parser.parse_args(argv)
    except _UsageError as error:
        return _usage(usage_code(str(error)), str(error), error.usage, wants_json, locale)
    as_json = getattr(arguments, "json", False)
    if getattr(arguments, "provenance", None) is None and hasattr(arguments, "provenance"):
        from boomvalley_lab.runtime.adapters.local import LOCAL_PROVENANCE

        arguments.provenance = LOCAL_PROVENANCE
    log.event(LOG, logging.DEBUG, "cli.started", program=PROGRAM, locale=locale,
              locale_source=source, json=as_json)
    try:
        if arguments.version:
            emit(wire_json(version_document()))
            return 0
        if arguments.command is None:
            parser.print_help()
            return 0
        result = COMMANDS[arguments.command](arguments)
        emit(render(result, as_json=as_json, locale=locale))
        refused = REFUSAL.get(arguments.command)
        code = EXIT_CODES[Category.VERIFICATION] if refused and refused(result) else 0
        log.event(LOG, logging.INFO, "cli.finished", command=arguments.command, exit_code=code)
        return code
    except BoomvalleyError as error:
        return _refused(error, as_json, locale)
    except (OSError, json.JSONDecodeError, MalformedJSON) as error:
        code = error_code(error)
        # --json: a coded, locale-independent document like every other error (#126)
        emit_error(wire_json({"error": Category.DECLARATION.value, "code": code,
                              "message": str(error), "problems": []})
                   if as_json else translate("error.os_declaration", {"error": error}, locale))
        log.event(LOG, logging.WARNING, "cli.input_error", error=Category.DECLARATION,
                  exit_code=EXIT_CODES[Category.DECLARATION], code=code)
        return EXIT_CODES[Category.DECLARATION]
    except Exception as exc:  # an escaped exception is a product bug, never a verdict
        log.event(LOG, logging.ERROR, "cli.internal_error", error=Category.INTERNAL,
                  exit_code=EXIT_CODES[Category.INTERNAL], exc_info=True)
        # the message is machine output with --json: never in the user's locale (#126)
        return _refused(InternalError(translate("error.internal",
                                                {"exc_type": type(exc).__name__},
                                                DEFAULT_LOCALE if as_json else locale)),
                        as_json, locale)


def _refused(error: BoomvalleyError, as_json: bool, locale: str) -> int:
    if as_json:
        emit_error(wire_json({"error": error.category.value, "code": error_code(error),
                              "message": str(error), "problems": list(error.problems)}))
    else:
        emit_error(translate("error.header",
                             {"category": error.category.value, "message": error}, locale))
        for problem in error.problems[1:]:
            emit_error(translate("error.problem", {"problem": problem}, locale))
    log.event(LOG, logging.WARNING, "cli.refused", error=error.category.value,
              exit_code=EXIT_CODES[error.category], code=error_code(error))
    return EXIT_CODES[error.category]


def _readable_output() -> None:
    """A console that cannot encode a character is not a reason to crash.

    Windows consoles are often a legacy code page; the CLI prints evidence,
    not art, so an unencodable character degrades instead of killing the
    command mid-audit.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError):  # pragma: no cover - not a real stream
            pass


def run() -> None:  # console script entry point
    sys.exit(main())
