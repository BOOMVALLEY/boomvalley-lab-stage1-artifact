"""L1 evidence roles and dataset units (T1-008).

Two evidence roles make an L1 run reconstructable from its package alone:

``call_binding`` (``boomvalley-lab-call-binding-1``), one per planned actor
call, durable before the call intent and named by CALL_INTENT_RECORDED
(``binding``).  It binds the call to who made it and what it could see:

    call / episode / step / round / IR node / request-2 / provider
    actor (ActorIdentity), role (RoleIdentity), ExecutionProfileIdentity,
    the profile-derived seed, and the P05 pipeline trace (considered,
    granted, denied, transforms, per-source observation digests, renderer,
    rendering digest, codec, corroboration grade)

A verifier recomputes every one of them from the frozen plan, the journal
and request-2: the CallIdentity from episode x step x round x request x
provider (BVL-REC-114), the actor / role / profile identities from the plan's
P04 binding set (BVL-REC-117), access from the plan's P05 access set and an
untransformed observation from the source's planned content digest
(BVL-REC-120 / BVL-REC-123), or, for an ``actor_output`` source (T2-001), from
its producer's committed output in the call's round.  Only a transformed observation digest and the
rendering digest are attested, not recomputed: the package holds no source
contents (``OBSERVATION_DIGESTS_ATTESTED_NOT_RECOMPUTED``).

``dataset_units`` (``boomvalley-lab-l1-dataset-1``), one per sealed L1
package: the run's analysis dataset as four unit tables derived from the
verified evidence only - calls, proposals, decisions and eligibility (one
row per decision unit).  A unit is eligible exactly when every criterion of
``ELIGIBILITY_CRITERIA`` holds; the reasons name the failing criteria.  The
builder writes it, and the product verifier and the FULLMT reader re-derive it
independently; it must be byte-identical.

Nothing here knows a study: rows are keyed by IR node ids and plan actors.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from boomvalley_lab.core.canonical import canonical_json
from boomvalley_lab.kernel.actors import ActorBindingV1
from boomvalley_lab.kernel.identity import CallIdentity
from boomvalley_lab.kernel.information import (
    ActorOutputDescriptorV1,
    InformationAccessSetV1,
    SourceDescriptorV1,
)
from boomvalley_lab.kernel.memory import memory_request_problems
from boomvalley_lab.kernel.pipeline import PIPELINE_TRACE_SCHEMA, PipelineTraceV1
from boomvalley_lab.kernel.request import CorroborationGrade, RequestV2
from boomvalley_lab.kernel.seed import SeedDerivation

CALL_BINDING_SCHEMA = "boomvalley-lab-call-binding-1"
CALL_BINDING_FIELDS = frozenset(
    {
        "schema",
        "episode",
        "step",
        "round",
        "node",
        "call",
        "request",
        "provider",
        "actor",
        "role",
        "profile",
        "seed",
        "access",
    }
)
TRACE_FIELDS = frozenset(
    {
        "schema",
        "actor_id",
        "considered",
        "granted",
        "denied",
        "transforms",
        "observation",
        "renderer",
        "rendering_sha256",
        "codec",
        "corroboration_grade",
        "request_identity",
    }
)
DATASET_SCHEMA = "boomvalley-lab-l1-dataset-1"
L1_ROLES = frozenset({"call_binding", "dataset_units"})
# attestation check added for a run whose calls carry L1 call bindings
L1_CALL_CHECK = "l1_call_bindings_recompute"
L1_LIMITATION = "OBSERVATION_DIGESTS_ATTESTED_NOT_RECOMPUTED"

# A decision unit is eligible only when every criterion holds (closed list).
ELIGIBILITY_CRITERIA = (
    "lineage_bound",  # every candidate proposal parses from an L1-bound call
    "decided",  # the decision outcome is not NO_ACTION
    "coverage_complete",  # the run's P09-ERF coverage attestation is COMPLETE
    "comparisons_run",  # the run's bound comparison result set is RUN
)
NOT_ATTESTED = "NOT_ATTESTED"
NOT_BOUND = "NOT_BOUND"


def _hex(digest: str) -> str:
    return digest.removeprefix("sha256:")


def call_binding_document(
    *,
    call: CallIdentity,
    episode: Mapping[str, Any],
    step: Mapping[str, Any],
    round_index: int,
    node_id: str,
    request: RequestV2,
    binding: ActorBindingV1,
    trace: PipelineTraceV1,
) -> dict[str, Any]:
    """The L1 evidence of one planned call, written before its intent."""

    return {
        "schema": CALL_BINDING_SCHEMA,
        "episode": dict(episode),
        "step": dict(step),
        "round": round_index,
        "node": node_id,
        "call": call.document(),
        "request": request.identity().document(),
        "provider": binding.profile.provider,
        "actor": {"actor_id": binding.actor_id, "identity": binding.identity.document()},
        "role": {"role_id": binding.role, "identity": binding.role_identity.document()},
        "profile": binding.profile_identity.document(),
        "seed": request.resolved_seed,
        "access": trace.document(),
    }


def _expected_access(
    access: InformationAccessSetV1 | None, actor_id: str
) -> tuple[list[str], list[str], list[str], dict[str, Any]]:
    if access is None:
        return [], [], [], {}
    specs = access.transforms_of(actor_id)
    return (
        sorted(access.sources),
        list(access.granted(actor_id)),
        list(access.denied(actor_id)),
        {source: json_of(specs[source].document()) for source in sorted(specs)},
    )


def json_of(value: Any) -> Any:
    """The at-rest (canonical-json-1) form of *value*: absent members dropped."""

    return json.loads(canonical_json(value))


def call_binding_problems(
    document: Any,
    *,
    call: str,
    intent_request: Mapping[str, Any],
    episode: Mapping[str, Any],
    step: Mapping[str, Any],
    round_index: int,
    node_id: str,
    binding: ActorBindingV1,
    request: Mapping[str, Any],
    access: InformationAccessSetV1 | None,
    seeds: SeedDerivation | None = None,
    produced: Mapping[str, str | None] | None = None,
    lineage: Mapping[str, Mapping[str, Any] | None] | None = None,
    memory: Mapping[str, Mapping[str, Any] | None] | None = None,
) -> list[str]:
    """Recompute one stored call binding; ``[]`` means it is this call's.

    *memory* maps each memory_artifact source of the plan to the request-2
    lineage its committed artifacts valid in this call's round derive (T4-003);
    *produced* then also holds the digest of the bytes that source carried.

    *seeds* is the plan's bound seed tree (plan-7, T1-012): the bound seed must
    re-derive from it, the actor's identity and the call's position.
    *produced* maps each actor_output source to the sha256 of its producer's
    committed output in this call's round (T2-001); *lineage* maps it to that
    producer's committed identity (``producer_kind`` / ``identity`` /
    ``content_sha256``), which request-2 must bind as ``upstream`` (T2-003).
    """

    if not isinstance(document, Mapping) or set(document) != CALL_BINDING_FIELDS:
        return ["call binding has the wrong closed shape"]
    if document["schema"] != CALL_BINDING_SCHEMA:
        return [f"call binding is not {CALL_BINDING_SCHEMA}"]
    problems: list[str] = []
    profile = binding.profile
    if (
        document["episode"] != dict(episode)
        or document["step"] != dict(step)
        or document["round"] != round_index
        or document["node"] != node_id
    ):
        problems.append("call binding names another step")
    if f"{document['call'].get('kind')}:{document['call'].get('digest')}" != call:
        problems.append("call binding names another call")
    if document["request"] != intent_request:
        problems.append("call binding names another request-2 than the call intent")
    recomputed = CallIdentity.of_payload(
        {
            "episode": dict(episode),
            "step": dict(step),
            "round": round_index,
            "request": dict(intent_request),
            "adapter": profile.provider,
        }
    )
    if str(recomputed) != call or document["provider"] != profile.provider:
        problems.append("CallIdentity does not recompute from the plan actor's provider")
    if document["actor"] != {
        "actor_id": binding.actor_id,
        "identity": binding.identity.document(),
    }:
        problems.append("call binding actor is not the IR node's plan actor")
    if document["role"] != {"role_id": binding.role, "identity": binding.role_identity.document()}:
        problems.append("call binding role is not the plan actor's role")
    if document["profile"] != binding.profile_identity.document():
        problems.append("call binding ExecutionProfileIdentity is not the plan actor's")
    if (
        request.get("model_identity") != profile.model
        or request.get("renderer_identity") != profile.renderer
        or canonical_json(dict(request.get("options") or {}))
        != canonical_json(dict(profile.options))
        or request.get("resolved_seed") != document["seed"]
    ):
        problems.append("request-2 is not the bound profile's model / renderer / options / seed")
    problems.extend(upstream_lineage_problems(request, binding.actor_id, access, lineage))
    # T4-003: request-2 names the exact Memory Artifacts it observed
    problems.extend(
        memory_request_problems(
            request,
            access.grants.get(binding.actor_id, ()) if access is not None else (),
            memory or {},
        )
    )
    if seeds is not None and document["seed"] != profile.resolve_seed(
        seeds,
        actor=binding.identity,
        episode_key=f"{episode.get('kind')}:{episode.get('digest')}",
        round_index=round_index,
        step_id=node_id,
    ):
        problems.append("call binding seed does not re-derive from the plan's seed tree")

    trace = document["access"]
    if not isinstance(trace, Mapping) or set(trace) != TRACE_FIELDS:
        return [*problems, "call binding access trace has the wrong closed shape"]
    considered, granted, denied, transforms = _expected_access(access, binding.actor_id)
    if (
        trace["schema"] != PIPELINE_TRACE_SCHEMA
        or trace["actor_id"] != binding.actor_id
        or trace["request_identity"] != f"request:{intent_request.get('digest')}"
        or trace["renderer"] != profile.renderer
    ):
        problems.append("access trace is not this call's actor / request / renderer")
    if (
        trace["considered"] != considered
        or trace["granted"] != granted
        or trace["denied"] != denied
        or trace["transforms"] != transforms
    ):
        problems.append("access trace is not the plan's default-deny access for the actor")
    observation = trace["observation"]
    if not isinstance(observation, Mapping) or sorted(observation) != granted:
        problems.append("access trace observes other than exactly the granted sources")
    elif access is not None:
        for source in granted:
            descriptor = access.sources[source]
            planned = (
                descriptor.content_sha256
                if isinstance(descriptor, SourceDescriptorV1)
                else (produced or {}).get(source)  # actor output / memory of the round
            )
            if source not in transforms and observation[source] != planned:
                problems.append(f"observation of {source!r} is not its planned content")
    if (
        trace["codec"] != request.get("codec_identity")
        or trace["corroboration_grade"] != request.get("corroboration_grade")
        or trace["corroboration_grade"] not in {grade.value for grade in CorroborationGrade}
    ):
        problems.append("access trace codec / grade is not request-2's")
    rendering = trace["rendering_sha256"]
    if not isinstance(rendering, str) or len(rendering) != 64:
        problems.append("access trace rendering digest is malformed")
    return problems


def upstream_lineage_problems(
    request: Mapping[str, Any],
    actor_id: str,
    access: InformationAccessSetV1 | None,
    lineage: Mapping[str, Mapping[str, Any] | None] | None,
) -> list[str]:
    """request-2 ``upstream`` is exactly the committed identity of every granted
    actor_output source (T2-003); a request without one has no ``upstream``."""

    granted = sorted(
        source
        for source in (access.grants.get(actor_id, ()) if access is not None else ())
        if isinstance(access.sources[source], ActorOutputDescriptorV1)
    )
    if not granted:
        if "upstream" in request:
            return ["request-2 binds upstream lineage but observes no actor_output source"]
        return []
    expected = []
    for source in granted:
        committed = (lineage or {}).get(source)
        if committed is None:
            return [f"actor_output {source!r} has no committed producer identity in the round"]
        expected.append({
            "source_id": source,
            "producer": access.sources[source].producer,
            "producer_kind": committed["producer_kind"],
            "identity": dict(committed["identity"]),
            "content_sha256": committed["content_sha256"],
        })
    if request.get("upstream") != expected:
        return ["request-2 upstream is not the exact committed upstream proposal / call identity"]
    return []


# ---------------------------------------------------------------- dataset units
def eligibility_row(
    decision: Mapping[str, Any],
    *,
    lineage_bound: bool,
    coverage: str,
    comparisons: str,
) -> dict[str, Any]:
    """One decision unit's eligibility over the closed criteria."""

    criteria = {
        "lineage_bound": lineage_bound,
        "decided": decision["outcome"] != "NO_ACTION",
        "coverage_complete": coverage == "COMPLETE",
        "comparisons_run": comparisons == "RUN",
    }
    return {
        "unit": decision["unit"],
        "episode_key": decision["episode_key"],
        "round": decision["round"],
        "node": decision["node"],
        "criteria": criteria,
        "eligible": all(criteria.values()),
        "reasons": [name for name in ELIGIBILITY_CRITERIA if not criteria[name]],
    }


def unit_order(row: Mapping[str, Any]) -> tuple[str, int, str]:
    """Rows are ordered by episode key, round and IR node id."""

    return (row["episode_key"], row["round"], row["node"])


def dataset_document(
    *,
    run: str,
    experiment_id: str,
    plan: Mapping[str, Any],
    authorization: Mapping[str, Any],
    attestation: Mapping[str, Any],
    conditions: Mapping[str, Any],
    calls: list[dict[str, Any]],
    proposals: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    eligibility: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema": DATASET_SCHEMA,
        "run": run,
        "experiment_id": experiment_id,
        "plan": dict(plan),
        "authorization": dict(authorization),
        "attestation": dict(attestation),
        "conditions": dict(conditions),
        "limitations": [L1_LIMITATION],
        "calls": sorted(calls, key=unit_order),
        "proposals": sorted(proposals, key=unit_order),
        "decisions": sorted(decisions, key=unit_order),
        "eligibility": sorted(eligibility, key=unit_order),
        "counts": {
            "calls": len(calls),
            "proposals": len(proposals),
            "decisions": len(decisions),
            "eligible": sum(1 for row in eligibility if row["eligible"]),
        },
    }


__all__ = [
    "CALL_BINDING_SCHEMA",
    "DATASET_SCHEMA",
    "ELIGIBILITY_CRITERIA",
    "L1_CALL_CHECK",
    "L1_LIMITATION",
    "L1_ROLES",
    "NOT_ATTESTED",
    "NOT_BOUND",
    "call_binding_document",
    "call_binding_problems",
    "dataset_document",
    "eligibility_row",
    "json_of",
    "unit_order",
]
