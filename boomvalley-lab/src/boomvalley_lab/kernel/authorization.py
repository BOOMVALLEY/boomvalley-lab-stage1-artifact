"""gate-2 execution authorization boundary (T0-012).

A run's scientific work (actor calls, World transitions, episodes) exists only
under one validated authorization.  Ordering is structural:

    gate-2 decision (plan, coverage, GNDCRW results, policy)
    -> persist execution binding (role ``execution_binding``: plan x installed
       build x plugin set, T0-013) and gate evidence (role ``gate``)
    -> CLEARED: journal RUN_OPENED (plan, binding, binding evidence ref,
                AuthorizationIdentity, gate evidence ref) as journal-2 position 0
       REFUSED: journal RUN_REFUSED (plan, binding, binding evidence ref,
                gate evidence ref, reasons) and raise; nothing scientific may follow

A run is opened (and resumed) only by the build it is bound to: the binding's
build descriptor must be this process's installed build.

A gate-2 decision whose coverage is a real P09-ERF attestation (T1-006) is
opened with that attestation document: it is persisted under role
``coverage`` before the gate evidence (CLEARED or REFUSED) and must recompute
the gate's CoverageAttestationIdentity; reconciliation refuses a coverage
member any other gate did not decide on.

A strict gate (P08, T1-007) also decided on the GNDCRW result set of the
attestation's whole required comparison set: it is persisted under role
``gndcrw_results`` before the gate evidence and must recompute the gate's
GNDCRWResultSetIdentity; reconciliation refuses any other result set.

Every scientific boundary calls ``require_run_authorization_v2`` before its
first write.  It re-derives the AuthorizationIdentity from durable evidence
(RUN_OPENED + the content-addressed gate document) instead of trusting an
in-memory object, so a refused, missing, forged or tampered gate yields zero
scientific calls and zero World transitions.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from boomvalley_lab.core.errors import BoomvalleyError, EvidenceError, ExecutionError
from boomvalley_lab.kernel.document_store import (
    EvidenceDocumentRefV2,
    EvidenceDocumentStoreV2,
    evidence_ref_from_document,
)
from boomvalley_lab.kernel.gate import GateDecisionV2, identity_from_document
from boomvalley_lab.kernel.identity import (
    AuthorizationIdentity,
    CoverageAttestationIdentity,
    ExecutionBindingIdentity,
    GNDCRWResultSetIdentity,
    PlanIdentity,
    authorization_identity,
)
from boomvalley_lab.kernel.journal2 import RUN_OPENED, RUN_REFUSED, Journal2
from boomvalley_lab.kernel.package_binding import ExecutionBindingV2, verify_current_build_v2


class ExecutionRefusedV2(ExecutionError):
    """gate-2 refused: the run is closed before any scientific work."""

    def __init__(self, gate: GateDecisionV2, evidence: EvidenceDocumentRefV2) -> None:
        super().__init__(
            f"gate-2 REFUSED plan {gate.plan}: {', '.join(gate.reasons)}; "
            "no scientific call or World transition is authorized"
        )
        self.gate = gate
        self.evidence = evidence


@dataclass(frozen=True)
class ExecutionAuthorizationV2:
    """One CLEARED gate-2 decision bound to one run, plan and binding."""

    run_id: str
    plan: PlanIdentity
    binding: ExecutionBindingIdentity
    gate: GateDecisionV2
    gate_evidence: EvidenceDocumentRefV2
    identity: AuthorizationIdentity
    binding_evidence: EvidenceDocumentRefV2 | None = None


def derive_authorization_v2(
    gate: GateDecisionV2, binding: ExecutionBindingIdentity
) -> AuthorizationIdentity:
    if not gate.cleared:
        raise ExecutionError("only a CLEARED gate-2 decision derives an AuthorizationIdentity")
    return authorization_identity(
        gate.plan,
        binding,
        coverage_identity=gate.coverage,
        gndcrw_result_set_identity=gate.gndcrw_results,
        gate_identity=gate.identity(),
    )


def open_run_v2(
    run_directory: Path,
    *,
    run_id: str,
    binding: ExecutionBindingV2,
    gate: GateDecisionV2,
    coverage: Mapping[str, Any] | None = None,
    gndcrw_results: Mapping[str, Any] | None = None,
) -> ExecutionAuthorizationV2:
    """Record the gate-2 outcome as the run's first event.

    CLEARED returns the bound authorization (idempotent for the same
    authorization, so an interrupted run can be resumed).  REFUSED journals
    RUN_REFUSED and raises ExecutionRefusedV2.  *coverage*, when given, is
    the P09-ERF attestation document the gate decided on; *gndcrw_results*,
    when given, the GNDCRW comparison result set document (T1-007).
    """

    if not run_id:
        raise ValueError("run_id must be non-empty")
    if not isinstance(binding, ExecutionBindingV2):
        raise TypeError("open_run_v2 binds an ExecutionBindingV2 (plan x build x plugin set)")
    if binding.plan != gate.plan:
        raise ExecutionError("the execution binding binds another plan than the gate-2 decision")
    if coverage is not None and CoverageAttestationIdentity.of_payload(coverage) != gate.coverage:
        raise ExecutionError("the coverage attestation is not the one the gate-2 decision binds")
    if gndcrw_results is not None and (
        GNDCRWResultSetIdentity.of_payload(gndcrw_results) != gate.gndcrw_results
    ):
        raise ExecutionError("the GNDCRW result set is not the one the gate-2 decision binds")
    verify_current_build_v2(binding)
    binding_identity = binding.identity()
    run_directory = Path(run_directory)
    journal = Journal2(run_directory)
    if journal.torn_tail():
        raise ExecutionError("journal-2 has a torn tail; refusing to open the run")
    records = journal.read()
    if records:
        if any(record["event"] == RUN_REFUSED for record in records):
            raise ExecutionError(f"run {run_id} was refused by gate-2 and stays closed")
        existing = require_run_authorization_v2(run_directory, run_id=run_id, journal=journal)
        # Resume only under the build the run is bound to (T0-013).
        verify_current_build_v2(
            ExecutionBindingV2.from_document(
                EvidenceDocumentStoreV2(run_directory).read(existing.binding_evidence)
            )
        )
        if gate.cleared and existing.identity == derive_authorization_v2(gate, binding_identity):
            return existing
        raise ExecutionError(
            f"run {run_id} is already opened under {existing.identity}; "
            "one run has exactly one authorization"
        )

    store = EvidenceDocumentStoreV2(run_directory)
    binding_evidence = store.put("execution_binding", binding.document())
    if coverage is not None:
        store.put("coverage", dict(coverage))
    if gndcrw_results is not None:
        store.put("gndcrw_results", dict(gndcrw_results))
    evidence = store.put("gate", gate.document())
    if not gate.cleared:
        journal.append_event(
            RUN_REFUSED,
            run=run_id,
            plan=gate.plan.document(),
            binding=binding_identity.document(),
            binding_evidence=binding_evidence.document(),
            gate=evidence.document(),
            reasons=list(gate.reasons),
        )
        raise ExecutionRefusedV2(gate, evidence)

    identity = derive_authorization_v2(gate, binding_identity)
    journal.append_event(
        RUN_OPENED,
        run=run_id,
        plan=gate.plan.document(),
        binding=binding_identity.document(),
        binding_evidence=binding_evidence.document(),
        authorization=identity.document(),
        gate=evidence.document(),
    )
    return ExecutionAuthorizationV2(
        run_id, gate.plan, binding_identity, gate, evidence, identity, binding_evidence
    )


def require_run_authorization_v2(
    run_directory: Path,
    *,
    run_id: str,
    journal: Journal2 | None = None,
) -> ExecutionAuthorizationV2:
    """Re-derive the run's authorization from durable evidence or refuse.

    Read-only.  Raises ExecutionError unless journal-2 opens with exactly one
    RUN_OPENED for *run_id*, carries no RUN_REFUSED, and the persisted CLEARED
    gate document recomputes the recorded AuthorizationIdentity.
    """

    run_directory = Path(run_directory)
    journal = journal if journal is not None else Journal2(run_directory)
    try:
        return _verify_opening(run_directory, journal, run_id)
    except EvidenceError as error:
        raise ExecutionError(
            f"run {run_id} has no verifiable gate-2 authorization: {error}"
        ) from error


def _verify_opening(
    run_directory: Path, journal: Journal2, run_id: str
) -> ExecutionAuthorizationV2:
    refused = journal.of_event(RUN_REFUSED)
    if refused:
        raise ExecutionError(
            f"run {run_id} was refused by gate-2 ({', '.join(refused[0]['reasons'])}); "
            "no scientific work is authorized"
        )
    opened = journal.of_event(RUN_OPENED)
    # an event's sequence is its position in the journal (Journal2._admit)
    if len(opened) != 1 or opened[0]["sequence"] != 0:
        raise ExecutionError(
            f"run {run_id} is not opened by exactly one gate-2 RUN_OPENED at journal position 0"
        )
    record = opened[0]
    if record["run"] != run_id:
        raise ExecutionError(
            f"journal-2 is opened for another run {record['run']!r}, not {run_id!r}"
        )
    foreign = [run for run in journal.runs() if run != run_id]
    if foreign:
        raise ExecutionError(f"journal-2 of run {run_id} carries events of run {foreign[0]!r}")
    return verify_opened_record_v2(run_directory, record)


def verify_opened_record_v2(
    run_directory: Path, record: Mapping[str, Any]
) -> ExecutionAuthorizationV2:
    """Recompute one RUN_OPENED record against its persisted gate evidence."""

    plan = identity_from_document(PlanIdentity, record["plan"], "RUN_OPENED plan")
    binding = identity_from_document(
        ExecutionBindingIdentity, record["binding"], "RUN_OPENED binding"
    )
    recorded = identity_from_document(
        AuthorizationIdentity, record["authorization"], "RUN_OPENED authorization"
    )
    store = EvidenceDocumentStoreV2(run_directory)
    binding_ref = evidence_ref_from_document(record["binding_evidence"], "execution_binding")
    bound = ExecutionBindingV2.from_document(store.read(binding_ref))
    if bound.plan != plan or bound.identity() != binding:
        raise ExecutionError(
            "RUN_OPENED binding does not recompute from its execution_binding evidence"
        )
    ref = evidence_ref_from_document(record["gate"], "gate")
    gate = GateDecisionV2.from_document(store.read(ref))
    if not gate.cleared:
        raise ExecutionError("RUN_OPENED binds a REFUSED gate-2 decision")
    if gate.plan != plan:
        raise ExecutionError("RUN_OPENED plan is not the gate-2 decision's plan")
    if derive_authorization_v2(gate, binding) != recorded:
        raise ExecutionError(
            "RUN_OPENED AuthorizationIdentity does not recompute from its gate evidence"
        )
    return ExecutionAuthorizationV2(
        record["run"], plan, binding, gate, ref, recorded, binding_ref
    )


@dataclass(frozen=True)
class AuthorizationReconciliationV2:
    authorization: ExecutionAuthorizationV2 | None
    refused: bool
    problems: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return not self.problems


def reconcile_authorization_v2(run_directory: Path) -> AuthorizationReconciliationV2:
    """Package-level check: scientific evidence exists only under a CLEARED gate.

    An empty run is trivially complete; a refused run is complete only if it
    holds nothing but its RUN_REFUSED.
    """

    run_directory = Path(run_directory)
    journal = Journal2(run_directory)
    try:
        records = journal.read()
    except EvidenceError as error:
        return AuthorizationReconciliationV2(None, False, (str(error),))
    if not records:
        return AuthorizationReconciliationV2(None, False, ())
    if records[0]["event"] == RUN_REFUSED:
        rest = [record["event"] for record in records[1:]]
        problems = (
            [f"refused run carries scientific events after RUN_REFUSED: {sorted(set(rest))}"]
            if rest
            else []
        )
        try:
            ref = evidence_ref_from_document(records[0]["binding_evidence"], "execution_binding")
            stored = EvidenceDocumentStoreV2(run_directory).read(ref)
            bound = ExecutionBindingV2.from_document(stored)
            if bound.identity().document() != records[0]["binding"]:
                problems.append("RUN_REFUSED binding does not recompute from its evidence")
        except (EvidenceError, OSError) as error:
            problems.append(f"RUN_REFUSED binding evidence is unverifiable: {error}")
        return AuthorizationReconciliationV2(None, True, tuple(problems))
    try:
        authorization = require_run_authorization_v2(
            run_directory, run_id=records[0]["run"], journal=journal
        )
    except (ExecutionError, OSError) as error:
        return AuthorizationReconciliationV2(None, False, (str(error),))
    problems = []
    for path in sorted((run_directory / "evidence-v2" / "coverage").glob("*.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            attested = CoverageAttestationIdentity.of_payload(document)
        except (OSError, ValueError, BoomvalleyError) as error:
            problems.append(f"coverage/{path.name} is unreadable: {error}")
            continue
        if attested != authorization.gate.coverage:
            problems.append(f"coverage/{path.name} is not the gate-2 decision's coverage")
    for path in sorted((run_directory / "evidence-v2" / "gndcrw_results").glob("*.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            bound = GNDCRWResultSetIdentity.of_payload(document)
        except (OSError, ValueError, BoomvalleyError) as error:
            problems.append(f"gndcrw_results/{path.name} is unreadable: {error}")
            continue
        if bound != authorization.gate.gndcrw_results:
            problems.append(
                f"gndcrw_results/{path.name} is not the gate-2 decision's GNDCRW result set"
            )
    for role, ref, what in (
        ("gate", authorization.gate_evidence, "authorizing gate-2 decision"),
        ("execution_binding", authorization.binding_evidence, "bound build/plugin set"),
    ):
        problems.extend(
            f"{role}/{path.name} is not the run's {what}"
            for path in sorted((run_directory / "evidence-v2" / role).glob("*.json"))
            if ref is None or path.name != Path(ref.path).name
        )
    return AuthorizationReconciliationV2(authorization, False, tuple(problems))

