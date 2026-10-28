"""GNDCRW comparison-set binding (T1-007, P08 strict gate input).

The P09-ERF attestation (T1-006) derives the *required* comparison set of a
design: every adjacent-isolation edge with its five GNDCRW subject documents.
This module binds the GNDCRW results of that whole set into one
``GNDCRWResultSetIdentity``:

    CoverageAttestationV1
        -> run_comparison_set(engine): every required edge's five subjects,
           in edge order, through one injected GNDCRW engine (the kernel never
           imports GNDCRW; the engine is a callable over the subject documents)
        -> GNDCRWResultSetV1 (coverage identity, required edges, one result
           document per edge) -> GNDCRWResultSetIdentity
        -> result_set_refusals: what gate-2 refuses before any actor call

A result binds its edge only when its ``subject`` equals the subject the
kernel recomputes from the edge's own documents (declaration id / intent /
content digest, catalog digest, surface ids and content digests, pair
digest), so a result of another edge, another cell plan or another
attestation never counts.  Anything short of one valid ``RUN`` result per
required edge refuses:

    BVL-COV-009   a required edge has no result (partial comparison set)
    BVL-GATE-002  a result does not bind its edge's subjects / is not required
    BVL-GATE-003  an edge's GNDCRW outcome is not RUN (e.g. BLOCK)
    BVL-GATE-004  a result is malformed / not GNDCRW strict / the engine failed
    BVL-GATE-005  the result set binds another coverage attestation
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from boomvalley_lab.core.digest import Digest, sha256_bytes
from boomvalley_lab.kernel.coverage import (
    COMPARISON_SET_INCOMPLETE,
    CoverageAttestationV1,
    attested_edge_documents,
)
from boomvalley_lab.kernel.identity import CoverageAttestationIdentity, GNDCRWResultSetIdentity

# P08 strict gate reason-code family (the gate-2 refusals this module owns)
GATE_RESULT_SET_INVALID = "BVL-GATE-001"
GATE_SUBJECT_UNBOUND = "BVL-GATE-002"
GATE_EDGE_NOT_RUN = "BVL-GATE-003"
GATE_RESULT_INVALID = "BVL-GATE-004"
GATE_FOREIGN_RESULT_SET = "BVL-GATE-005"

RESULT_SET_SCHEMA = "bvl-gndcrw-result-set-1"
RESULT_VERSION = "gndcrw-result/v0.1"
STRICT_POLICY = "GNDCRW-STRICT-0.1"
CONTROL = "CONTROL"
RUN = "RUN"
SUBJECTS = ("declaration", "target_catalog", "base_surface", "candidate_surface", "pair_context")

#: one GNDCRW engine: the five subject documents -> one gndcrw-result document
GNDCRWEngineV1 = Callable[[Mapping[str, Any]], Mapping[str, Any]]


def gndcrw_digest(document: Any) -> str:
    """The GNDCRW content digest: SHA-256 over sorted, compact, null-preserving JSON."""

    data = json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    return str(sha256_bytes(data))


def expected_subject(documents: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """The ``subject`` a GNDCRW result over these five documents must carry."""

    declaration = documents["declaration"]
    catalog = documents["target_catalog"]
    base, candidate = documents["base_surface"], documents["candidate_surface"]
    return {
        "declaration": {
            "id": declaration["declaration_id"],
            "intent_digest": declaration["intent"]["intent_digest"],
            "content_digest": gndcrw_digest(declaration),
        },
        "catalog": {
            "id": catalog["catalog_id"],
            "profile_id": catalog["profile_id"],
            "catalog_digest": catalog["catalog_digest"],
        },
        "base_surface": {"id": base["surface_id"], "content_digest": gndcrw_digest(base)},
        "candidate_surface": {
            "id": candidate["surface_id"],
            "content_digest": gndcrw_digest(candidate),
        },
        "pair": {"content_digest": gndcrw_digest(documents["pair_context"])},
    }


@dataclass(frozen=True)
class GNDCRWResultSetV1:
    """The GNDCRW results of one attestation's required comparison set."""

    coverage: CoverageAttestationIdentity
    method: str
    required: tuple[str, ...]
    results: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "required", tuple(sorted(self.required)))
        object.__setattr__(
            self, "results", MappingProxyType(dict(sorted(dict(self.results).items())))
        )

    def document(self) -> dict[str, Any]:
        return {
            "schema": RESULT_SET_SCHEMA,
            "coverage": self.coverage.document(),
            "method": self.method,
            "required_edges": list(self.required),
            "results": [
                {"edge_id": edge, "result": result} for edge, result in self.results.items()
            ],
        }

    def identity(self) -> GNDCRWResultSetIdentity:
        return GNDCRWResultSetIdentity.of_payload(self.document())

    def bound_edges(self) -> list[str]:
        """The required edges whose result is present (bound, not judged)."""

        return [edge for edge in self.required if edge in self.results]

    def without(self, *edges: str) -> GNDCRWResultSetV1:
        """The same set with *edges*' results dropped (a partial set)."""

        kept = {edge: result for edge, result in self.results.items() if edge not in edges}
        return GNDCRWResultSetV1(self.coverage, self.method, self.required, kept)


def run_comparison_set(
    attestation: CoverageAttestationV1, engine: GNDCRWEngineV1
) -> GNDCRWResultSetV1:
    """Run *engine* over every required edge of *attestation*, in edge order.

    An engine failure is bound as an error result (refused BVL-GATE-004), so
    a set is never silently short of an edge.
    """

    results: dict[str, Any] = {}
    for edge in attestation.edges():
        documents = attestation.gndcrw_edge(edge.edge_id)
        try:
            results[edge.edge_id] = dict(engine(copy.deepcopy(documents)))
        except Exception as error:  # noqa: BLE001 - an engine failure is evidence
            results[edge.edge_id] = {"engine_error": f"{type(error).__name__}: {error}"}
    return GNDCRWResultSetV1(
        attestation.identity(),
        attestation.design.comparison,
        tuple(edge.edge_id for edge in attestation.edges()),
        results,
    )


def result_set_from_document(document: Any) -> GNDCRWResultSetV1 | None:
    """Read a stored ``bvl-gndcrw-result-set-1`` back (``None``: malformed)."""

    keys = {"schema", "coverage", "method", "required_edges", "results"}
    if not isinstance(document, Mapping) or set(document) != keys or (
        document["schema"] != RESULT_SET_SCHEMA
    ):
        return None
    coverage = document["coverage"]
    entries = document["results"]
    if (
        not isinstance(coverage, Mapping)
        or coverage.get("kind") != CoverageAttestationIdentity.KIND
        or not isinstance(document["required_edges"], list)
        or not isinstance(entries, list)
        or not all(isinstance(e, Mapping) and set(e) == {"edge_id", "result"} for e in entries)
    ):
        return None
    edges = [entry["edge_id"] for entry in entries]
    if len(set(edges)) != len(edges):
        return None
    try:
        identity = CoverageAttestationIdentity(Digest.parse(coverage["digest"]))
    except (KeyError, TypeError, ValueError):
        return None
    return GNDCRWResultSetV1(
        identity,
        document["method"],
        tuple(document["required_edges"]),
        {entry["edge_id"]: entry["result"] for entry in entries},
    )


def result_set_refusals(
    subjects: Mapping[str, Mapping[str, Mapping[str, Any]]],
    coverage: CoverageAttestationIdentity,
    result_set: GNDCRWResultSetV1 | None,
) -> list[str]:
    """gate-2 refusal reasons of one result set (``[]``: the comparison set is bound).

    *subjects* maps every required edge to its five GNDCRW subject documents;
    *coverage* is the attestation the gate decides on.
    """

    if result_set is None:
        return [f"{GATE_RESULT_SET_INVALID}:set:not a {RESULT_SET_SCHEMA} document"]
    reasons: list[str] = []
    if result_set.coverage != coverage:
        reasons.append(f"{GATE_FOREIGN_RESULT_SET}:set:binds {result_set.coverage}")
    if list(result_set.required) != sorted(subjects):
        reasons.append(
            f"{GATE_RESULT_SET_INVALID}:set:required edges are not the attested comparison set"
        )
    for edge in sorted(subjects):
        if edge not in result_set.results:
            reasons.append(f"{COMPARISON_SET_INCOMPLETE}:{edge}")
            continue
        reasons.extend(_result_refusals(edge, subjects[edge], result_set.results[edge]))
    reasons.extend(
        f"{GATE_SUBJECT_UNBOUND}:{edge}:not a required comparison"
        for edge in sorted(set(result_set.results) - set(subjects))
    )
    return reasons


def _result_refusals(
    edge: str, documents: Mapping[str, Mapping[str, Any]], result: Any
) -> list[str]:
    if not isinstance(result, Mapping):
        return [f"{GATE_RESULT_INVALID}:{edge}:not a result document"]
    if "engine_error" in result:
        return [f"{GATE_RESULT_INVALID}:{edge}:engine failed"]
    if (
        result.get("result_version") != RESULT_VERSION
        or result.get("policy_id") != STRICT_POLICY
        or result.get("comparison_mode") != CONTROL
    ):
        return [f"{GATE_RESULT_INVALID}:{edge}:not a {STRICT_POLICY} {CONTROL} result"]
    if result.get("subject") != expected_subject(documents):
        return [f"{GATE_SUBJECT_UNBOUND}:{edge}:result subject is not the edge's subjects"]
    if result.get("outcome") != RUN:
        return [f"{GATE_EDGE_NOT_RUN}:{edge}:{result.get('outcome')}"]
    return []


def attestation_subjects(
    attestation: CoverageAttestationV1,
) -> dict[str, dict[str, dict[str, Any]]]:
    return {edge.edge_id: attestation.gndcrw_edge(edge.edge_id) for edge in attestation.edges()}


def stored_result_set_problems(
    coverage_document: Mapping[str, Any], result_document: Any
) -> list[str]:
    """Package verifier: a stored result set re-binds against the stored attestation."""

    try:
        subjects = attested_edge_documents(coverage_document)
    except Exception as error:  # noqa: BLE001 - reported as a verification problem
        return [f"the attested comparison set does not rebuild: {error}"]
    return result_set_refusals(
        subjects,
        CoverageAttestationIdentity.of_payload(coverage_document),
        result_set_from_document(result_document),
    )
