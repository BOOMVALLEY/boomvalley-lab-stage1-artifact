"""The one gated lifecycle of a `bvl-study-1` study (T1-010).

    validate  compile every design cell's frozen plan              writes nothing
    check     validate -> P09-ERF coverage attestation -> GNDCRW comparison
              set -> P08 strict gate-2 decision                     writes nothing
    run       check -> open_run_v2 (RUN_OPENED | RUN_REFUSED) -> the generic
              K0 engine under the CLEARED authorization only; a study with
              human actors (P17) is asked through a desk (``desk``) and stops
              WAITING while a person has not answered (T5-002,
              ``kernel/waiting.py``)
    status    the run's journal-2 / gate-2 evidence, read-only
    resume    the study recompiled and re-decided: the decision (and the bound
              build x plugin set) must be the
              run's durable gate-2 decision, then only what the evidence
              allows executes: an opened, never-started episode runs; an
              interrupted episode continues (T2-006, ``kernel/replay.py``)
              when every journaled call and World transition is committed
              or provably not started - committed outputs are restored
              from custody, never re-requested - and is refused otherwise;
              a WAITING run continues the same way once an answer is on the
              desk, and stays WAITING (nothing appended) while none is
    package   seal the run as a manifest-4 CONFORMANCE package (dataset units,
              bound analysis)
    verify    ``verify_package_v4``: everything re-derived from the package,
              then its P18 L1 conformance claim (T1-GATE; required by --l1)
              and L2 conformance claim (T2-GATE; required by --l2); with the
              run's study its World transitions are replayed and its L3
              conformance claim is decided (T3-GATE; required by --l3), and
              over it the L4 claim of a longitudinal run (T4-GATE,
              ``kernel/l4_conformance.py``; required by --l4); a
              verified package reports the World(t) -> World(t+1) chain it
              verified on (T4-005, ``kernel/state_chain.py``) and who answered
              each of its actor calls (T5-005, ``kernel/call_provenance.py``;
              a model, tool or human call that is no declared caller's is
              refused by --calls), and over those its L5 claim: the declared
              human and tool actors answered and nothing else did (T5-GATE,
              ``kernel/l5_conformance.py``; required by --l5)
    analyse   the plan's pre-bound analysis, read only from a package that
              verifies (it was recomputed over the admitted units)

A run directory has one writer (SV-09, ``writing``): ``run``,
``resume`` and ``package`` hold it exclusively and a second one is refused
(BVL-LIFE-011) before it writes.  ``status`` reads the state off the journal;
SEALED is a COMPLETED run whose readable manifest-4 lists exactly the journal
the directory holds - any other ``MANIFEST-4.json`` is reported beside the
journal's own state (``package_problem``), and such a run is not resumed.

A run is bound to its tool site and its human desk (SV-09 remediation,
``_claim``): the run holds one record naming its instance, each context holds
the same instance, and ``resume`` is refused (BVL-LIFE-012) a site or desk
that does not - before it is read, called, reconciled or asked.

There is exactly one way to reach the engine: ``_decide`` -> ``open_run_v2``
-> ``_execute``.  A REFUSED decision is journaled and nothing executes (zero
provider calls).  The GNDCRW engine is injected (``engine``): the lifecycle
never imports GNDCRW, and a design whose comparison set cannot be run has no
result for its edges and is refused (BVL-GATE-004).
"""

from __future__ import annotations

import contextlib
import os
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from typing import IO, Any

from boomvalley_lab.core.canonical import canonical_bytes
from boomvalley_lab.core.errors import (
    BoomvalleyError,
    EvidenceError,
    ExecutionError,
    IdentityError,
    VerificationRefusal,
)
from boomvalley_lab.core.strict_json import MalformedJSON, load_bytes
from boomvalley_lab.kernel.authorization import (
    ExecutionAuthorizationV2,
    ExecutionRefusedV2,
    open_run_v2,
    reconcile_authorization_v2,
)
from boomvalley_lab.kernel.bound_analysis import ANALYSIS_ROLE
from boomvalley_lab.kernel.call_executor import DurableCallExecutorV2
from boomvalley_lab.kernel.call_provenance import ALL_DECLARED, assess_call_provenance_v1
from boomvalley_lab.kernel.comparison import GNDCRWResultSetV1, run_comparison_set
from boomvalley_lab.kernel.coverage import CoverageAttestationV1, attest_execution_coverage
from boomvalley_lab.kernel.document_store import (
    EvidenceDocumentStoreV2,
    evidence_ref_from_document,
)
from boomvalley_lab.kernel.engine import GenericEpisodeEngine
from boomvalley_lab.kernel.gate import GateDecisionV2
from boomvalley_lab.kernel.handlers import (
    ActorCallHandlerV2,
    DecisionRuleHandlerV1,
    OutcomeMemoryHandlerV2,
    ProposalParseHandlerV2,
    WorldTransitionHandlerV2,
)
from boomvalley_lab.kernel.human import HumanError
from boomvalley_lab.kernel.journal2 import (
    CALL_INTENT_RECORDED,
    CUSTODY_ACCEPTED,
    EPISODE_COMPLETED,
    EPISODE_FAILED,
    EPISODE_OPENED,
    RUN_REFUSED,
    Journal2,
    held_run,
)
from boomvalley_lab.kernel.l1_conformance import L1, assess_l1_conformance_v1
from boomvalley_lab.kernel.l2_conformance import L2, assess_l2_conformance_v1
from boomvalley_lab.kernel.l3_conformance import L3, assess_l3_conformance_v1
from boomvalley_lab.kernel.l4_conformance import L4, assess_l4_conformance_v1
from boomvalley_lab.kernel.l5_conformance import L5, assess_l5_conformance_v1
from boomvalley_lab.kernel.manifest4 import ManifestMemberV4, read_manifest4
from boomvalley_lab.kernel.package4 import (
    MANIFEST_NAME,
    build_conformance_package_v4,
    verify_package_v4,
)
from boomvalley_lab.kernel.package_binding import ExecutionBindingV2, bind_execution_v2
from boomvalley_lab.kernel.plugin_registry import PluginType
from boomvalley_lab.kernel.protocol import NodeKind
from boomvalley_lab.kernel.replay import (
    ABORT,
    EXECUTE,
    ResumeRefusedError,
    plan_episode_resume,
)
from boomvalley_lab.kernel.state_chain import run_state_chain
from boomvalley_lab.kernel.strict_gate import StrictGateV1, decide_strict_gate_v2
from boomvalley_lab.kernel.tool import TOOL_EXECUTION_UNSUPPORTED, ToolError
from boomvalley_lab.kernel.tool import execution_unsupported as tool_execution_unsupported
from boomvalley_lab.kernel.tool_actor_call import ToolCallRefusedError
from boomvalley_lab.kernel.tool_call import UNKNOWN_OUTCOME_POLICY, DurableToolCallExecutorV1
from boomvalley_lab.kernel.waiting import (
    HumanDeskRefusedError,
    HumanDeskV1,
    HumanResponsePending,
    _create,
    awaiting,
    require_desk,
    require_desk_transport,
    require_unused_desk,
)
from boomvalley_lab.kernel.world_executor import WorldCustodyRefusedError
from boomvalley_lab.kernel.world_replay import (
    NOT_REPLAYED,
    REPLAYED,
    WorldReplayV1,
    replay_world_transitions,
)
from boomvalley_lab.lifecycle.plugins import resolved
from boomvalley_lab.lifecycle.study import CompiledStudy

LIFECYCLE = "k0-gate-2"
# the lifecycle's own refusals (beyond the kernel's coded ones)
RUN_DIRECTORY_IN_USE = "BVL-LIFE-002"
RUN_REFUSED_CLOSED = "BVL-LIFE-003"
GATE_DRIFT = "BVL-LIFE-004"
REPLAY_REQUIRED = "BVL-LIFE-005"
NO_BOUND_ANALYSIS = "BVL-LIFE-006"
PACKAGE_UNVERIFIED = "BVL-LIFE-007"
NOT_A_K0_RUN = "BVL-LIFE-008"
RESUME_EVIDENCE_INCONSISTENT = "BVL-LIFE-009"
RUN_BUSY = "BVL-LIFE-011"  # BVL-LIFE-010 is lifecycle/plugins.py
CONTEXT_NOT_BOUND = "BVL-LIFE-012"

# SV-09 remediation: the run's record of its external contexts, and each
# context's record of its run
BINDING_SCHEMA = "bvl-context-binding-1"
RUN_BINDING_NAME = "context-binding.json"
CONTEXT_BINDING_NAME = "bvl-run-binding.json"
TOOL_SITE, HUMAN_DESK = "tool_site", "human_desk"

# status states, read off journal-2 and the package
NOT_STARTED = "NOT_STARTED"
REFUSED = "REFUSED"
OPENED = "OPENED"
INTERRUPTED = "INTERRUPTED"
COMPLETED = "COMPLETED"
FAILED = "FAILED"
# T5-002: stopped inside an episode on a delivered human request with no answer
WAITING = "WAITING"
SEALED = "SEALED"
# the member a manifest-4 lists the run's journal under (``collect_manifest4_members``)
JOURNAL_MEMBER, JOURNAL_ROLE = "journal-2.jsonl", "episode_lineage"

GNDCRWEngine = Callable[[Mapping[str, Any]], Mapping[str, Any]]


def _held(position: int) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Run an operation holding what it reads of its run directory (T4-013).

    One operation reads the journal, the custody ledger and the committed
    transitions once instead of once per call or transition it looks at.
    *position* is where the operation takes its run directory.
    """

    def decorate(operation: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(operation)
        def holding(*args: Any, **kwargs: Any) -> Any:
            directory = args[position] if len(args) > position else kwargs["directory"]
            with held_run(Path(directory)):
                return operation(*args, **kwargs)

        return holding

    return decorate


def _no_engine(_: Mapping[str, Any]) -> Mapping[str, Any]:
    raise ExecutionError("no GNDCRW engine is installed; the comparison edge was not run")


@dataclass(frozen=True)
class Decision:
    """One strict gate-2 decision and what it was decided on (pure: nothing written)."""

    cell: str
    levels: Mapping[str, str]
    plan_document: Mapping[str, Any]
    attestation: CoverageAttestationV1
    results: GNDCRWResultSetV1
    strict: StrictGateV1

    @property
    def gate(self) -> GateDecisionV2:
        return self.strict.gate

    def document(self) -> dict[str, Any]:
        gate = self.gate
        return {
            "cell": self.cell,
            "plan": gate.plan.document(),
            "coverage": gate.coverage.document(),
            "coverage_status": self.attestation.execution_coverage,
            "coverage_findings": [f.document() for f in self.attestation.findings],
            "gndcrw_results": gate.gndcrw_results.document(),
            "comparison_edges": list(self.results.bound_edges()),
            "policy_identity": gate.policy_identity,
            "decision": "CLEARED" if gate.cleared else "REFUSED",
            "reasons": list(gate.reasons),
            "gate": gate.identity().document(),
        }


def _decide(study: CompiledStudy, cell: str | None, engine: GNDCRWEngine | None) -> Decision:
    key, levels = study.levels(cell)
    attestation = attest_execution_coverage(study.design, study.compile_cell, study.contracts)
    results = run_comparison_set(attestation, engine or _no_engine)
    plan_document, _ = study.plan(levels)
    strict = decide_strict_gate_v2(
        plan_document, attestation, results,
        parsers=resolved(study.plugins, PluginType.PROPOSAL_PARSER),
        rules=resolved(study.plugins, PluginType.DECISION_RULE),
    )
    return Decision(key, levels, plan_document, attestation, results, strict)


def _identities(study: CompiledStudy, decision: Decision) -> dict[str, Any]:
    binding = bind_execution_v2(decision.gate.plan, study.plugins)
    return {
        "plugin_set": binding.plugin_set_identity().document(),
        "build": binding.build_identity().document(),
        "execution_binding": binding.identity().document(),
    }


# ---------------------------------------------------------------- validate / check
def validate(study: CompiledStudy) -> dict[str, Any]:
    cells = {key: study.plan(levels)[1].document() for key, levels in study.design.cells()}
    result = {
        "lifecycle": LIFECYCLE,
        "experiment": study.experiment_id,
        "valid": True,
        "cells": cells,
        "analysis": None if study.analysis is None else study.analysis.analysis_id,
    }
    if study.humans is not None:  # T5-001: who answers as a person, under which contract
        result["humans"] = {
            actor_id: contract.identity().document()
            for actor_id, contract in sorted(study.humans.contracts.items())
        }
    if study.tools is not None:  # T5-003: who a tool answers, under which contract
        result["tools"] = {
            actor_id: contract.identity().document()
            for actor_id, contract in sorted(study.tools.contracts.items())
        }
        # T5-004: what an unknown outcome of each tool's call permits
        result["tool_side_effects"] = {
            actor_id: {
                "effect": contract.effect.value,
                "side_effect": contract.side_effect.value,
                "on_unknown_outcome": UNKNOWN_OUTCOME_POLICY[contract.side_effect].value,
            }
            for actor_id, contract in sorted(study.tools.contracts.items())
        }
    return result


def check(study: CompiledStudy, *, cell: str | None = None,
          engine: GNDCRWEngine | None = None) -> dict[str, Any]:
    decision = _decide(study, cell, engine)
    result = {
        "lifecycle": LIFECYCLE,
        "experiment": study.experiment_id,
        "gate_decision": decision.document(),
        "identities": _identities(study, decision),
        "execution_status": NOT_STARTED,
    }
    unsupported = _tool_unsupported(study) or _human_unsupported(study)
    if unsupported is not None:
        # the gate decides the plan; this build cannot ask its human actors or
        # call its tool actors
        result["execution_unsupported"] = unsupported.code
    else:
        if study.humans is not None:
            result["human_actors"] = sorted(study.humans.contracts)  # asked through a desk
        if study.tools is not None:
            # T5-007: called by the engine, bound to a site
            result["tool_actors"] = sorted(study.tools.contracts)
    return result


def _tool_unsupported(study: CompiledStudy) -> ToolError | None:
    """Why this build cannot call the study's tool actors, if it cannot (BVL-TOOL-009).

    A tool actor is called only with arguments its contract selects (T5-007):
    one without an ``argument_selection`` is not executed.
    """

    undeclared = () if study.tools is None else study.tools.unexecutable()
    return tool_execution_unsupported(undeclared) if undeclared else None


def _tools(study: CompiledStudy, directory: Path, site: Path | None) -> dict[str, Any]:
    """The study's tools, bound to the site they are called at, held to the study
    before anything is written (T5-007); empty for a study without tool actors.

    A tool that states ``bound`` works over a site: a directory outside the
    run's evidence, given by the operator.  What a tool does there is not
    evidence; it enters the run only as the tool call's journaled result.
    """

    if study.tools is None:
        if site is not None:
            raise ToolError(
                TOOL_EXECUTION_UNSUPPORTED,
                "a tool site was given and the study declares no tool actors: nothing is "
                "called",
            )
        return {}
    registered = resolved(study.plugins, PluginType.TOOL)
    bound: dict[str, Any] = {}
    for actor_id, contract in sorted(study.tools.contracts.items()):
        tool = registered.get(contract.tool)
        contract.require_tool(tool)
        if contract.tool in bound or not callable(getattr(tool, "bound", None)):
            bound.setdefault(contract.tool, tool)
            continue
        if site is None:
            raise ToolError(
                TOOL_EXECUTION_UNSUPPORTED,
                f"tool {contract.tool!r} of actor {actor_id!r} works over a site and none is "
                "given to call it at (--tool-site DIR): a tool is never approximated by a "
                "call",
            )
        here, run = Path(site).resolve(), Path(directory).resolve()
        if here == run or run in here.parents or here in run.parents:
            raise ToolError(
                TOOL_EXECUTION_UNSUPPORTED,
                f"tool site {site} and run {directory} hold each other: a tool's resource "
                "is not evidence and lies outside the run directory",
            )
        if not here.is_dir():
            raise ToolError(
                TOOL_EXECUTION_UNSUPPORTED, f"tool site {site} is not a directory"
            )
        bound[contract.tool] = tool.bound(here)
        contract.require_tool(bound[contract.tool])
    return bound


def _channels(study: CompiledStudy) -> dict[str, Any]:
    return resolved(study.plugins, PluginType.HUMAN_CHANNEL)


def _human_unsupported(study: CompiledStudy) -> HumanError | None:
    """Why this build cannot ask the study's human actors, if it cannot (BVL-HUMAN-009)."""

    if study.humans is None:
        return None
    channels = _channels(study)
    try:
        for _, contract in sorted(study.humans.contracts.items()):
            require_desk_transport(contract, channels.get(contract.channel))
    except HumanError as error:
        return error
    return None


def _desk(study: CompiledStudy, directory: Path, desk: Path | None) -> HumanDeskV1 | None:
    """The desk the study's human actors are asked through, held to the study
    before anything is written (T5-002); None for a study without human actors."""

    if study.humans is None:
        if desk is not None:
            raise HumanError(
                "BVL-HUMAN-009",
                "a desk was given and the study declares no human actors: nobody is asked",
            )
        return None
    held = None if desk is None else HumanDeskV1(Path(desk))
    require_desk(held, directory, study.humans, _channels(study))
    return held


# ---------------------------------------------------------------- run x context
def _contexts(study: CompiledStudy, desk: Path | None,
              tool_site: Path | None) -> dict[str, Path]:
    """kind -> directory of every external context the study's run works through.

    The desk its human actors are asked through and the site its tools are
    bound to; a site no tool of the study binds is not used and not bound.
    """

    found: dict[str, Path] = {}
    if study.humans is not None and desk is not None:
        found[HUMAN_DESK] = Path(desk)
    if study.tools is not None and tool_site is not None:
        registered = resolved(study.plugins, PluginType.TOOL)
        if any(callable(getattr(registered.get(contract.tool), "bound", None))
               for contract in study.tools.contracts.values()):
            found[TOOL_SITE] = Path(tool_site)
    return found


def _unbound(detail: str) -> ExecutionError:
    return ExecutionError(f"{CONTEXT_NOT_BOUND} {detail}", code=CONTEXT_NOT_BOUND)


def _binding_document(path: Path, members: set[str], what: str) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        document = load_bytes(path.read_bytes())
    except (OSError, MalformedJSON) as error:
        raise _unbound(f"{what} {path} is unreadable ({error}): nothing executed") from None
    if (not isinstance(document, dict) or document.get("schema") != BINDING_SCHEMA
            or not {"schema", "run"} <= set(document) <= members):
        raise _unbound(f"{what} {path} is not a {BINDING_SCHEMA}: nothing executed")
    return document


def run_binding(directory: Path) -> dict[str, Any] | None:
    """The run's record of the contexts it is bound to, while it can act on them."""

    return _binding_document(Path(directory) / RUN_BINDING_NAME,
                             {"schema", "run", "instance", "contexts"}, "the run's binding")


def context_binding(context: Path) -> dict[str, Any] | None:
    """What a tool site or a desk states about the run it belongs to, if anything."""

    return _binding_document(Path(context) / CONTEXT_BINDING_NAME,
                             {"schema", "kind", "run", "instance", "closed"},
                             "the context binding")


def _marker(kind: str, record: Mapping[str, Any]) -> dict[str, Any]:
    return {"schema": BINDING_SCHEMA, "kind": kind, "run": record["run"],
            "instance": record.get("instance")}


def _describe(kind: str, context: Path) -> str:
    return f"{'tool site' if kind == TOOL_SITE else 'desk'} {context}"


def _binding(directory: Path, run_id: str, contexts: Mapping[str, Path], *,
             fresh: bool, adopt: bool = False) -> dict[str, Any] | None:
    """The binding this execution works under, or a refusal (BVL-LIFE-012).

    Nothing is written, and of a context only its binding is read.  A run
    that works through a tool site or a desk is one execution instance of its
    study cell: a second run of the cell derives the same tool intents (and so
    the same idempotency keys) and the same human request intents, so nothing
    the run journals tells its site or desk from another run's.  The instance
    does: the run's record holds it, each context holds it, and they agree or
    nothing is called, reconciled, delivered or collected.

    *fresh*: the run opened no episode, so it touched no context yet - it may
    still be bound, to contexts no run holds.  A run that did and holds no
    record (it was opened before the binding existed, or lost it) is bound
    only on the operator's word (*adopt*, ``bvl resume --bind-contexts``),
    and then only to contexts no run holds.
    """

    record = run_binding(directory)
    if record is None:
        if not contexts:
            return None
        if not (fresh or adopt):
            raise _unbound(
                f"run {run_id} works through {sorted(contexts)} and holds no "
                f"{RUN_BINDING_NAME}: which site or desk it used is not evidenced, and a "
                "resume is never held to the command line alone.  A run opened before the "
                "binding existed is bound by its operator (--bind-contexts): nothing executed")
        record = {"schema": BINDING_SCHEMA, "run": run_id,
                  "instance": secrets.token_hex(16), "contexts": sorted(contexts)}
        fresh = True
    elif (record["run"] != run_id or record.get("contexts") != sorted(contexts)
          or not isinstance(record.get("instance"), str)):
        raise _unbound(
            f"run {run_id} is bound as run {record['run']} to {record.get('contexts')}; this "
            f"execution works through {sorted(contexts)}: nothing executed")
    for kind, context in sorted(contexts.items()):
        held = context_binding(context)
        if held is None and fresh:
            continue  # claimed by ``_claim``, once everything else is held
        if held is None:
            raise _unbound(
                f"{_describe(kind, context)} holds no {CONTEXT_BINDING_NAME}: it is not the "
                f"one run {run_id} is bound to (instance {record['instance']}), or a copy "
                "taken before the run.  What was applied or answered there is not this "
                "run's: nothing executed")
        if held != _marker(kind, record):
            owner = (f"closed by a {held['closed']} run {held['run']}" if "closed" in held
                     else f"bound to run {held['run']}, instance {held.get('instance')}")
            raise _unbound(
                f"{_describe(kind, context)} is {owner}; run {run_id} is instance "
                f"{record['instance']}: a site or desk belongs to one run, and nothing of "
                "another run's is applied again, reconciled or adopted: nothing executed")
    return record


def _claim(directory: Path, record: Mapping[str, Any] | None,
           contexts: Mapping[str, Path]) -> None:
    """Make *record* durable: in the run first, then once in each context.

    Both are created exclusively.  A process that stops in between leaves a
    run that names an instance no context holds yet; while it opened no
    episode the next resume finishes the claim (``_binding``, *fresh*).
    """

    if record is None:
        return
    path = Path(directory) / RUN_BINDING_NAME
    if not _create(path, canonical_bytes(dict(record))) and run_binding(directory) != record:
        raise _unbound(f"run {directory} was bound meanwhile: nothing executed")
    for kind, context in sorted(contexts.items()):
        marker = _marker(kind, record)
        target = Path(context) / CONTEXT_BINDING_NAME
        try:
            created = _create(target, canonical_bytes(marker))
        except OSError as error:
            raise _unbound(
                f"{_describe(kind, context)} cannot hold its binding ({error}): a run works "
                "only through a site or desk that states it is its own; nothing "
                "executed") from None
        if not created and context_binding(context) != marker:
            raise _unbound(
                f"{_describe(kind, context)} was bound by another run meanwhile: a site or "
                "desk belongs to one run; nothing executed")


def _require_unclaimed(contexts: Mapping[str, Path]) -> None:
    """A new run is given a site and a desk no run holds; nothing is written."""

    for kind, context in sorted(contexts.items()):
        held = context_binding(context)
        if held is not None:
            raise _unbound(
                f"{_describe(kind, context)} belongs to run {held['run']} "
                f"({'closed' if 'closed' in held else 'bound'}): a new run derives that "
                "run's tool and request intents and would be answered with what was applied "
                "or said for it.  A new run is given a site and a desk of its own: nothing "
                "executed")


def _settle(directory: Path, contexts: Mapping[str, Path]) -> None:
    """Close the binding of a run that will not act on its contexts again.

    A COMPLETED or FAILED run executes nothing more.  Its contexts keep, in
    place of the instance, that a run of that id closed them - they are never
    given to another run - and the run's record, which no package lists, is
    released: the directory holds evidence only.
    """

    record = run_binding(directory)
    state = _journal_state(Journal2(Path(directory)).read())
    if record is None or state not in (COMPLETED, FAILED):
        return
    for kind, context in sorted(contexts.items()):
        if context_binding(context) != _marker(kind, record):
            continue
        closed = {"schema": BINDING_SCHEMA, "kind": kind, "run": record["run"],
                  "closed": state}
        target = Path(context) / CONTEXT_BINDING_NAME
        staged = target.with_name(f".{target.name}.partial")
        staged.write_bytes(canonical_bytes(closed))
        os.replace(staged, target)
    (Path(directory) / RUN_BINDING_NAME).unlink(missing_ok=True)


# ---------------------------------------------------------------- the one writer
def lock_path(directory: Path) -> Path:
    """Where the writer lock of run *directory* is held: beside it, never in it.

    A run directory holds evidence only, and a package verifies with no
    unlisted file.
    """

    resolved = Path(directory).resolve()
    return resolved.parent / f".{resolved.name}.bvl-writer"


def _acquire(handle: IO[bytes]) -> bool:
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _current(handle: IO[bytes], path: Path) -> bool:
    """The locked file is still the one at *path* (a released lock is removed)."""

    try:
        return os.path.samestat(os.fstat(handle.fileno()), os.stat(path))
    except OSError:
        return False


class writing:  # noqa: N801 - read as ``with writing(run):``
    """Hold run *directory* as its one writer, or refuse (BVL-LIFE-011, SV-09).

    journal-2, custody-v2 and the evidence members are append-only logs and
    write-once members whose order is their meaning: an event's sequence is
    its position, and a resumed episode matches what is journaled before it
    appends.  That holds for one writer.  Two processes that ``run``,
    ``resume`` or ``package`` one directory at once each read the journal,
    each decide what comes next and both append: one sequence is journaled
    twice (the journal is unreadable from then on), a provider is asked again
    for a call already in custody, or an episode is closed twice.

    The lock is the operating system's: it is released when the process ends,
    however it ends, so a crashed writer leaves nothing to clear.  A second
    writer does not wait; it is refused and has written nothing.  Reading
    (``status``, ``verify``, ``analyse``, ``resume --plan``) takes no lock.
    """

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self.path = lock_path(directory)
        self.handle: IO[bytes] | None = None

    def __enter__(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(8):  # a lock released between our open and our lock is retried
            try:
                candidate = open(self.path, "a+b")  # noqa: SIM115 - held for the operation
            except OSError:
                break  # the holder's file is not shared: the run is being written
            if not _acquire(candidate):
                candidate.close()
                break
            if _current(candidate, self.path):
                self.handle = candidate
                return
            candidate.close()
        raise ExecutionError(
            f"{RUN_BUSY} run {self.directory} is being written by another run, resume or "
            "package: a run directory has one writer; nothing executed", code=RUN_BUSY)

    def __exit__(self, *_: object) -> None:
        if os.name != "nt":
            # removed while held: a process that opened it before finds another file
            with contextlib.suppress(OSError):
                self.path.unlink()
        self.handle.close()
        if os.name == "nt":
            with contextlib.suppress(OSError):
                self.path.unlink()  # fails while the next writer holds it open: theirs now


# ---------------------------------------------------------------- run / resume
def run_id_of(study: CompiledStudy, cell: str) -> str:
    return f"{study.experiment_id}.{cell}"


def run(study: CompiledStudy, into: Path, *, cell: str | None = None,
        engine: GNDCRWEngine | None = None, desk: Path | None = None,
        tool_site: Path | None = None) -> dict[str, Any]:
    into = Path(into)
    if into.exists() and (not into.is_dir() or any(into.iterdir())):
        raise IdentityError(
            f"{RUN_DIRECTORY_IN_USE} {into} already holds evidence; a run is opened once, "
            "into an empty directory", code=RUN_DIRECTORY_IN_USE)
    # T5-003 / T5-007: a tool is called only with declared arguments, at a site
    # it is bound to; a run that cannot call is refused before anything is written
    unsupported = _tool_unsupported(study)
    if unsupported is not None:
        raise unsupported
    tools = _tools(study, into, tool_site)
    # T5-002: a person is asked only through a desk they are enrolled on; a run
    # that cannot ask is refused before anything is written
    held = _desk(study, into, desk)
    if held is not None:
        # SV-09: a new run asks its own questions; a desk another run delivered
        # to holds that run's answers under the very intents this one derives
        require_unused_desk(held)
    # SV-09 remediation: nor a site or a desk another run is bound to
    contexts = _contexts(study, desk, tool_site)
    _require_unclaimed(contexts)
    decision = _decide(study, cell, engine)
    run_id = run_id_of(study, decision.cell)
    result = {"lifecycle": LIFECYCLE, "run": run_id, "directory": str(into),
              "gate_decision": decision.document()}
    with writing(into):
        if into.exists() and any(into.iterdir()):  # opened meanwhile by another run
            raise IdentityError(
                f"{RUN_DIRECTORY_IN_USE} {into} already holds evidence; a run is opened "
                "once, into an empty directory", code=RUN_DIRECTORY_IN_USE)
        try:
            authorization = _open(study, decision, into, run_id)
        except ExecutionRefusedV2:
            return {**result, "execution_status": NOT_STARTED, **_state(into)}
        # bound before the first episode opens: at creation, not at first use
        _claim(into, _binding(into, run_id, contexts, fresh=True), contexts)
        executed = _execute(study, decision, into, authorization, desk=held, tools=tools)
        _settle(into, contexts)
        return {**result, **executed}


def _open(study: CompiledStudy, decision: Decision, into: Path,
          run_id: str) -> ExecutionAuthorizationV2:
    return open_run_v2(
        into, run_id=run_id, binding=bind_execution_v2(decision.gate.plan, study.plugins),
        gate=decision.gate, coverage=decision.strict.coverage,
        gndcrw_results=decision.strict.gndcrw_results,
    )


@_held(2)
def _execute(study: CompiledStudy, decision: Decision, directory: Path,
             authorization: ExecutionAuthorizationV2, *, resume: bool = False,
             desk: HumanDeskV1 | None = None,
             tools: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The only engine construction in the product: under a CLEARED authorization.

    With *resume* the engine continues the episode the journal already opened.
    The run executes the episodes of the study's schedule in order (T4-004),
    one ``engine.execute`` each; a resumed run skips the ones already closed.
    """

    run_id = authorization.run_id
    actors = study.actors(decision.levels)
    information, sources = study.information(decision.levels)
    calls = DurableCallExecutorV2(directory, run_id=run_id)
    documents = EvidenceDocumentStoreV2(directory)
    seeds = study.seeds
    shared = {"journal": calls.journal, "documents": documents, "run_id": run_id}
    registry = study.plugins
    engine = GenericEpisodeEngine(
        {
            NodeKind.ACTOR_CALL: ActorCallHandlerV2(
                renderers=resolved(registry, PluginType.RENDERER),
                adapters=resolved(registry, PluginType.ADAPTER),
                calls=calls, seeds=seeds, sources=sources,
                channels=_channels(study), desk=desk,
                tools=tools,
                tool_calls=(DurableToolCallExecutorV1(directory, run_id=run_id)
                            if study.tools is not None else None),
            ),
            NodeKind.PROPOSAL_PARSE: ProposalParseHandlerV2(
                parsers={}, proposal_parsers=resolved(registry, PluginType.PROPOSAL_PARSER),
                **shared,
            ),
            NodeKind.DECISION: DecisionRuleHandlerV1(
                rules=resolved(registry, PluginType.DECISION_RULE), **shared
            ),
            NodeKind.WORLD_TRANSITION: WorldTransitionHandlerV2(
                worlds=study.worlds.worlds(), seeds=seeds, **shared
            ),
            NodeKind.MEMORY_UPDATE: OutcomeMemoryHandlerV2(**shared),
        },
        journal=calls.journal, documents=documents, run_id=run_id, authorization=authorization,
        denied_sources=() if sources is None else sources.paths,
    )
    schedule = study.episodes
    closed = _closed_episodes(directory) if resume else {}
    # a resumed run skips the episodes it closed; when it closed all of them
    # nothing is left to resume, and the engine itself refuses the last one
    pending = [key for key in schedule.episodes if key not in closed] or [
        schedule.episodes[-1]
    ]
    episode = None
    failures = len(calls.journal.of_event(EPISODE_FAILED))
    try:
        for episode_key in pending:
            episode = engine.execute(
                experiment_id=study.experiment_id, episode_key=episode_key,
                protocol=study.protocol, initial_world_state=study.initial_world_state,
                actors=actors, information=information, proposals=study.proposals,
                decisions=study.decisions(decision.levels),
                analysis=study.analysis, seeds=seeds, resume=resume, world=study.world,
                schedule=schedule, humans=study.humans, tools=study.tools,
            )
    except HumanResponsePending as pending:
        # T5-002: not an outcome; the request is delivered once and the run waits
        return {"execution_status": WAITING, "waiting": [pending.awaiting],
                **_state(directory)}
    except (ResumeRefusedError, WorldCustodyRefusedError, HumanDeskRefusedError,
            ToolCallRefusedError):
        raise  # not journaled: the run stays interrupted
    except BoomvalleyError as error:
        result = {"execution_status": FAILED, "failure": f"{type(error).__name__}: {error}",
                  **_state(directory)}
        if len(Journal2(Path(directory)).of_event(EPISODE_FAILED)) == failures:
            # SV-09: a FAILED run is a journaled EPISODE_FAILED - evidence, not a
            # crash.  A refusal the engine did not journal (the kernel was not
            # pristine, T0-016; an episode out of its schedule) failed this
            # execution and is no outcome of the run, which stays in ``state``:
            # it is said so, so that a later resume is not read as a failed run
            # that completed.
            result["failure_journaled"] = False
        return result
    result: dict[str, Any] = {"execution_status": COMPLETED}
    if episode is not None:
        result.update(rounds=episode.rounds_executed,
                      authorization=episode.authorization.document(),
                      world_state=dict(episode.world_state))
    if len(schedule.episodes) > 1:
        rounds = _closed_episodes(directory)
        result["episodes"] = [{"episode_key": key, "rounds": rounds.get(key)}
                              for key in schedule.episodes]
    return {**result, **_state(directory)}


def _closed_episodes(directory: Path) -> dict[str, int]:
    """episode key -> rounds, of every episode the run's journal completed."""

    records = Journal2(Path(directory)).read()
    keys = {r["episode"]: r["episode_key"] for r in records if r["event"] == EPISODE_OPENED}
    return {keys[r["episode"]]: r["rounds"] for r in records
            if r["event"] == EPISODE_COMPLETED and r["episode"] in keys}


@_held(0)
def resume(directory: Path, *, study: CompiledStudy | None = None, cell: str | None = None,
           engine: GNDCRWEngine | None = None, plan: bool = False,
           desk: Path | None = None, tool_site: Path | None = None,
           bind_contexts: bool = False) -> dict[str, Any]:
    if plan or not is_k0_run(directory):
        # read-only (it holds no writer, and a writer does not refuse it), or
        # not a gated run at all: refused below, nothing is locked for it
        return _resume(directory, study=study, cell=cell, engine=engine, plan=plan,
                       desk=desk, tool_site=tool_site, bind_contexts=bind_contexts)
    with writing(directory):  # SV-09: one writer, held before the run is read
        return _resume(directory, study=study, cell=cell, engine=engine, plan=False,
                       desk=desk, tool_site=tool_site, bind_contexts=bind_contexts)


def _resume(directory: Path, *, study: CompiledStudy | None, cell: str | None,
            engine: GNDCRWEngine | None, plan: bool,
            desk: Path | None, tool_site: Path | None,
            bind_contexts: bool = False) -> dict[str, Any]:
    directory = Path(directory)
    state = status(directory)
    if plan and state["state"] == REFUSED:
        return {**state, "resume_action": "NONE", "executed": False}
    if state["state"] == REFUSED:
        raise ExecutionError(f"{RUN_REFUSED_CLOSED} run {state['run']} was refused by gate-2 "
                             "and stays closed; a changed study is a new run",
                             code=RUN_REFUSED_CLOSED)
    if state["state"] not in (OPENED, INTERRUPTED, WAITING) or "package_problem" in state:
        # a closed run, or one that holds a manifest-4 that does not seal it
        # (SV-09): nothing is appended under a manifest
        return {**state, "resume_action": "NONE", "executed": False}
    # read-only: what the durable evidence allows (EXECUTE | OPERATOR_DECISION | ABORT)
    evidence = plan_episode_resume(directory)
    action = evidence.action
    if plan:
        return {**state, "resume_action": action, "resume_plan": evidence.document(),
                "executed": False}
    if action == ABORT:
        raise EvidenceError(
            f"{RESUME_EVIDENCE_INCONSISTENT} run {state['run']} stopped inside its episode and "
            "its evidence contradicts itself; nothing is restored from it: nothing executed",
            code=RESUME_EVIDENCE_INCONSISTENT, problems=evidence.reasons)
    if action != EXECUTE:
        raise ExecutionError(
            f"{REPLAY_REQUIRED} run {state['run']} stopped inside its episode with an external "
            "outcome that is not proven; the kernel never re-invokes a provider or re-applies a "
            "World on its own: nothing executed",
            code=REPLAY_REQUIRED, problems=evidence.reasons)
    if study is None:
        raise ExecutionError(f"{GATE_DRIFT} resuming an execution re-decides its study: "
                             "pass --experiment", code=GATE_DRIFT)
    decision = _decide(study, cell, engine)
    durable = reconcile_authorization_v2(directory).authorization
    if durable is None or decision.gate.identity() != durable.gate.identity():
        raise ExecutionError(
            f"{GATE_DRIFT} the study re-decides to gate {decision.gate.identity()}, the run is "
            f"opened under {None if durable is None else durable.gate.identity()}: nothing "
            "executed", code=GATE_DRIFT)
    binding = bind_execution_v2(decision.gate.plan, study.plugins).identity()
    if binding != durable.binding:
        raise ExecutionError(
            f"{GATE_DRIFT} the study binds execution {binding} (build x plugin set), the run "
            f"is opened under {durable.binding}: nothing executed", code=GATE_DRIFT)
    # SV-09 remediation: the site and the desk are the run's own, or nothing of
    # them is read (the enrollment), called, reconciled, delivered or collected
    contexts = _contexts(study, desk, tool_site)
    fresh = state["state"] == OPENED
    binding = _binding(directory, state["run"], contexts, fresh=fresh, adopt=bind_contexts)
    held = _desk(study, directory, desk)
    tools = _tools(study, directory, tool_site)
    if held is not None and fresh:
        require_unused_desk(held)  # the run delivered nothing: neither did another
    _claim(directory, binding, contexts)
    authorization = _open(study, decision, directory, state["run"])
    executed = _execute(study, decision, directory, authorization, resume=True, desk=held,
                        tools=tools)
    _settle(directory, contexts)
    return {**executed,
            "resume_action": action,
            "executed": True, "lifecycle": LIFECYCLE, "run": state["run"],
            "directory": str(directory)}


# ---------------------------------------------------------------- status
def is_k0_run(directory: Path) -> bool:
    return (Path(directory) / "journal-2.jsonl").is_file()


def _require_run(directory: Path) -> list[dict[str, Any]]:
    if not is_k0_run(directory):
        raise IdentityError(f"{NOT_A_K0_RUN} {directory} holds no journal-2: not a gated run",
                            code=NOT_A_K0_RUN)
    return Journal2(Path(directory)).read()


def _state(directory: Path) -> dict[str, Any]:
    records = _require_run(directory)
    events = [record["event"] for record in records]
    custody = {r["call"] for r in records if r["event"] == CUSTODY_ACCEPTED}
    intents = [r["call"] for r in records if r["event"] == CALL_INTENT_RECORDED]
    state = _journal_state(records)
    found = {
        "run": records[0]["run"] if records else None,
        "state": state,
        "calls": {"accepted": len(custody),
                  "pending": sorted(call for call in intents if call not in custody)},
        "events": len(events),
    }
    if state != REFUSED and (Path(directory) / MANIFEST_NAME).exists():
        # SV-09 (SV-04 m-07): a file named MANIFEST-4.json is not a seal
        problem = _seal_problem(Path(directory), state)
        if problem is None:
            found["state"] = state = SEALED
        else:
            found["package_problem"] = problem
    unanswered = awaiting(Journal2(Path(directory)))
    if unanswered:
        # T5-002: delivered human requests without a received response
        found["awaiting_human"] = unanswered
        if state == INTERRUPTED:
            found["state"] = WAITING
    return found


def _journal_state(records: list[dict[str, Any]]) -> str:
    """The state journal-2 alone puts the run in (never SEALED, never WAITING)."""

    events = [record["event"] for record in records]
    if events and events[0] == RUN_REFUSED:
        return REFUSED
    if EPISODE_FAILED in events:
        return FAILED
    opened = {r["episode"] for r in records if r["event"] == EPISODE_OPENED}
    if not opened:
        return OPENED
    # T4-006: every scheduled episode closed; one closed twice is not two.
    # SV-09: only an episode the run opened closes, and none it opened is open.
    closed = opened & {r["episode"] for r in records if r["event"] == EPISODE_COMPLETED}
    if closed == opened and len(closed) >= _scheduled(records):
        return COMPLETED
    return INTERRUPTED


def _seal_problem(directory: Path, state: str) -> str | None:
    """Why the directory's ``MANIFEST-4.json`` does not seal its run, if it does not.

    A status query, not a verification (``verify`` re-derives every member):
    the manifest is a readable manifest-4 of a COMPLETED run and lists the
    journal the directory holds now, byte for byte.
    """

    if state != COMPLETED:
        return (f"{MANIFEST_NAME} is held by a run that is {state}: a package seals a "
                "COMPLETED run")
    try:
        manifest = read_manifest4(directory / MANIFEST_NAME)
        journal = ManifestMemberV4.from_file(directory, JOURNAL_MEMBER, JOURNAL_ROLE)
    except (BoomvalleyError, OSError, ValueError) as error:
        return f"{MANIFEST_NAME} does not read as a manifest-4: {error}"
    if journal.document() not in [member.document() for member in manifest.members]:
        return (f"{MANIFEST_NAME} does not list the journal-2 this run holds: it is not the "
                "seal of this journal")
    return None


def _scheduled(records: list[dict[str, Any]]) -> int:
    """How many episodes the run's journaled experiment schedule orders (T4-004)."""

    for record in records:
        if record["event"] == EPISODE_OPENED:
            episodes = (record.get("schedule") or {}).get("episodes")
            return len(episodes) if isinstance(episodes, list) and episodes else 1
    return 1


@_held(0)
def status(directory: Path) -> dict[str, Any]:
    directory = Path(directory)
    found = _state(directory)
    try:
        bound = run_binding(directory)
    except ExecutionError as error:  # a query: said, not raised; ``resume`` refuses it
        found["context_binding"] = {"problem": str(error)}
    else:
        if bound is not None:
            # SV-09 remediation: the instance its site and desk must hold on resume
            found["context_binding"] = {"instance": bound.get("instance"),
                                        "contexts": bound.get("contexts")}
    reconciled = reconcile_authorization_v2(directory)
    gate = (reconciled.authorization.gate if reconciled.authorization is not None
            else _refused_gate(directory))
    return {
        "lifecycle": LIFECYCLE,
        "directory": str(directory),
        **found,
        "gate_decision": None if gate is None else {
            "plan": gate.plan.document(),
            "decision": "CLEARED" if gate.cleared else "REFUSED",
            "reasons": list(gate.reasons),
            "policy_identity": gate.policy_identity,
            "gate": gate.identity().document(),
        },
        "authorization": (None if reconciled.authorization is None
                          else reconciled.authorization.identity.document()),
        "authorization_problems": list(reconciled.problems),
    }


def _refused_gate(directory: Path) -> GateDecisionV2 | None:
    records = Journal2(directory).read()
    if not records or records[0]["event"] != RUN_REFUSED:
        return None
    ref = evidence_ref_from_document(records[0]["gate"], "gate")
    return GateDecisionV2.from_document(EvidenceDocumentStoreV2(directory).read(ref))


# ---------------------------------------------------------------- package / verify / analyse
@_held(0)
def package(directory: Path) -> dict[str, Any]:
    directory = Path(directory)
    if not is_k0_run(directory):
        _require_run(directory)  # refused: nothing is locked for what is not a run
    # SV-09: never sealed while a run or resume appends; held before the run is read
    with writing(directory):
        return _package(directory)


def _package(directory: Path) -> dict[str, Any]:
    if _journal_state(_require_run(directory)) == COMPLETED:
        # the binding of a run whose process stopped between its last event and
        # ``_settle``: the run acts on no context again, and a package lists
        # evidence only
        (directory / RUN_BINDING_NAME).unlink(missing_ok=True)
    sealed = build_conformance_package_v4(directory)
    roles = sorted({member.role for member in sealed.manifest.members})
    return {
        "lifecycle": LIFECYCLE,
        "directory": str(directory),
        "manifest": MANIFEST_NAME,
        "package_class": sealed.manifest.package_class,
        "manifest_identity": sealed.manifest.identity().document(),
        "plan": sealed.manifest.plan.document(),
        "members": len(sealed.manifest.members),
        "roles": roles,
        "analysis_bound": ANALYSIS_ROLE in roles,
        "verified": True,
    }


def _binding_difference(directory: Path, durable: Any, mine: ExecutionBindingV2) -> str:
    """Which half of the run's execution binding this process does not share.

    A verifier on another machine is told what to install: the run's build
    (origin and code digest) against its own, or that the plugin set differs.
    """

    if durable.binding_evidence is None:
        return ""
    try:
        theirs = ExecutionBindingV2.from_document(
            EvidenceDocumentStoreV2(directory).read(durable.binding_evidence))
    except (EvidenceError, OSError, ValueError):
        return ""
    found = []
    if theirs.build != mine.build:
        found.append(f"the run's build is {theirs.build.origin}, code "
                     f"{theirs.build.code_digest}; this process executes "
                     f"{mine.build.origin}, code {mine.build.code_digest}")
    if theirs.plugin_set_identity() != mine.plugin_set_identity():
        found.append(f"the run's plugin set is {theirs.plugin_set_identity()}, this "
                     f"process registers {mine.plugin_set_identity()}")
    return f" ({'; '.join(found)})" if found else ""


def _world_replay(directory: Path, study: CompiledStudy, cell: str | None) -> dict[str, Any]:
    """Replay the run's committed World transitions on *study*'s registered World.

    The study must be the run's: its cell compiles to the run's plan and binds
    the run's execution (build x plugin set), so the World code replayed is the
    code that ran.  Its instances are this process's own.
    """

    _, levels = study.levels(cell)
    durable = reconcile_authorization_v2(directory).authorization
    plan = study.plan(levels)[1]
    if durable is None or plan != durable.plan:
        found = None if durable is None else durable.plan
        problem = f"the study compiles to plan {plan}, the run executed {found}"
    elif (mine := bind_execution_v2(plan, study.plugins)).identity() != durable.binding:
        problem = ("the study binds another execution (build x plugin set) than the run's "
                   f"{durable.binding}{_binding_difference(directory, durable, mine)}: its "
                   "World is not the code that ran")
    else:
        return replay_world_transitions(directory, study.worlds).document()
    return WorldReplayV1(NOT_REPLAYED, None, None, 0, 0, {},
                         (f"{GATE_DRIFT} {problem}: nothing replayed",)).document()


@_held(0)
def verify(directory: Path, *, require_l1: bool = False, require_l2: bool = False,
           require_l3: bool = False, require_l4: bool = False,
           require_l5: bool = False, require_calls: bool = False,
           replay: CompiledStudy | None = None, cell: str | None = None) -> dict[str, Any]:
    """``verify_package_v4`` and the package's P18 L1 to L4 conformance claims.

    With *require_l1* / *require_l2* / *require_l3* / *require_l4* a package
    that verifies but is NOT_L1 / NOT_L2 / NOT_L3 / NOT_L4 is not accepted
    (``conformant: false``; the CLI exits as a failed verification).  With
    *replay* (the run's study) every
    committed World transition is also recomputed from the package's serialized
    evidence on this process's own World instances (T3-005, ``world_replay``);
    a package whose transitions are not REPLAYED is not accepted either.  The
    L3 claim needs that replay (its W5): without *replay* it is NOT_L3, and
    the L4 claim over it (its X1) NOT_L4.  With *require_calls* a package in
    which a model, tool or human call is not a declared caller's
    (``call_provenance`` NOT_DECLARED, T5-005) is not accepted either; with
    *replay* its frozen resources are handed to that assessment, which
    re-derives the tool arguments selected from them (T5-008).  The L5 claim
    (T5-GATE, ``kernel/l5_conformance.py``) is decided over the L1 claim and
    that call provenance: it needs no replay, and with *require_l5* a package
    that is NOT_L5 is not accepted.
    """

    directory = Path(directory)
    _require_run(directory)
    problems = verify_package_v4(directory)
    result = {"lifecycle": LIFECYCLE, "directory": str(directory), "verified": not problems,
              "problems": problems}
    if not problems:
        manifest = read_manifest4(directory / MANIFEST_NAME)
        result["manifest_identity"] = manifest.identity().document()
        result["plan"] = manifest.plan.document()
        result["l1_conformance"] = assess_l1_conformance_v1(directory, problems=problems)
        result["l2_conformance"] = assess_l2_conformance_v1(
            directory, problems=problems, l1=result["l1_conformance"])
        if replay is not None:
            result["world_replay"] = _world_replay(directory, replay, cell)
        # T4-005: the World(t) -> World(t+1) chain the package verified on
        result["state_chain"] = run_state_chain(directory)[1]
        result["l3_conformance"] = assess_l3_conformance_v1(
            directory, problems=problems, l1=result["l1_conformance"],
            replay=result.get("world_replay"))
        result["l4_conformance"] = assess_l4_conformance_v1(
            directory, problems=problems, l1=result["l1_conformance"],
            l3=result["l3_conformance"], state_chain=result["state_chain"])
        # T5-005: every model, human and tool call attributed to its declared caller
        registry = None if replay is None else replay.information_registry
        result["call_provenance"] = assess_call_provenance_v1(
            directory, resources=None if registry is None else registry.frozen_contents())
        # T5-GATE: the declared human and tool actors answered, and nothing else did
        result["l5_conformance"] = assess_l5_conformance_v1(
            directory, problems=problems, l1=result["l1_conformance"],
            call_provenance=result["call_provenance"],
            organization={f"l{n}": result[f"l{n}_conformance"]["level"] for n in (1, 2, 3, 4)})
    if (require_l1 or require_l2 or require_l3 or require_l4 or require_l5 or require_calls
            or replay is not None):
        result["conformant"] = (
            (not require_l1 or (result.get("l1_conformance") or {}).get("level") == L1)
            and (not require_l2 or (result.get("l2_conformance") or {}).get("level") == L2)
            and (not require_l3 or (result.get("l3_conformance") or {}).get("level") == L3)
            and (not require_l4 or (result.get("l4_conformance") or {}).get("level") == L4)
            and (not require_l5 or (result.get("l5_conformance") or {}).get("level") == L5)
            and (not require_calls
                 or (result.get("call_provenance") or {}).get("verdict") == ALL_DECLARED)
            # SV-04: a replay of zero transitions recomputed nothing
            and (replay is None
                 or ((result.get("world_replay") or {}).get("verdict") == REPLAYED
                     and (result["world_replay"].get("transitions") or 0) > 0)))
    return result


@_held(0)
def analyse(directory: Path) -> dict[str, Any]:
    directory = Path(directory)
    _require_run(directory)
    problems = verify_package_v4(directory)
    if problems:
        raise VerificationRefusal(
            f"{PACKAGE_UNVERIFIED} an analysis is read only from a package that verifies",
            problems=tuple(problems), code=PACKAGE_UNVERIFIED)
    manifest = read_manifest4(directory / MANIFEST_NAME)
    members = [member for member in manifest.members if member.role == ANALYSIS_ROLE]
    if not members:
        raise ExecutionError(f"{NO_BOUND_ANALYSIS} this plan pre-binds no analysis, so none "
                             "may be reported", code=NO_BOUND_ANALYSIS)
    document = load_bytes((directory / members[0].path).read_bytes())
    return {"lifecycle": LIFECYCLE, "directory": str(directory),
            "manifest_identity": manifest.identity().document(),
            "analysis_member": members[0].path, "analysis": document}
