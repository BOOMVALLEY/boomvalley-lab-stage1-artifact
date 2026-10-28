"""P06 proposal schema / parser registry (T1-004).

A raw actor response is not a decision.  P06 turns it, through one registered
parser bound in the frozen plan, into a typed proposal:

    raw actor response (custody-accepted artifact)
        -> registered parser (plugin identity + frozen config)
        -> proposal schema validation (kernel-owned)
        -> typed proposal artifact (VALID | NO_ACTION) or PARSE_FAILURE

Declaration: ``ProposalRegistryV1`` holds the declared proposal schemas and
one ``ProposalContractDeclV1`` per ``proposal_parse`` node (schema reference,
parser plugin identity, parser config, failure policy).  It resolves into a
``ProposalContractSetV1`` that enters the frozen plan (``semantic-plan-4``);
the parser identity and config therefore contribute to PlanIdentity, the
parsed proposals never do.

Ownership (P06 §13.2): P06 owns *syntax* only - the response decodes and the
parser output is exactly the schema's closed, typed shape.  Whether a
syntactically valid requested action is admissible in the domain is the
World's verdict (P15: ADMISSIBLE / CLIPPED / INADMISSIBLE ...); a schema
therefore declares field types, never domain ranges or option lists, and a
domain-inadmissible action is never a parse failure.

Parser contract: ``parse(content, config)`` is pure and deterministic with
respect to (raw bytes, frozen config, parser identity).  Malformed input is
signalled by raising ``ProposalSyntaxError`` and nothing else; every other
exception is a parser defect (or a containment refusal such as a hidden
provider call, BVL-PROP-009) and is never relabelled as a parse failure.
The kernel never repairs: no coercion, no fallback, no re-prompt.  Repair
policies are refused at declaration (BVL-PROP-008).
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Protocol

from boomvalley_lab.core.canonical import canonical_json
from boomvalley_lab.core.errors import CanonicalisationError, DeclarationError
from boomvalley_lab.kernel.protocol import NodeKind, ProtocolIR

SCHEMA_SCHEMA = "bvl-proposal-schema-1"
CONTRACT_SCHEMA = "bvl-proposal-contract-1"
CONTRACT_SET_SCHEMA = "bvl-proposal-contract-set-1"
# proposal evidence: -1 is the historical unschematized T0 proposal, -2 binds
# the plan contract, the parse verdict and the failure reason (T1-004)
EVIDENCE_SCHEMA_V1 = "boomvalley-lab-proposal-1"
EVIDENCE_SCHEMA_V2 = "boomvalley-lab-proposal-2"
EVIDENCE_FIELDS_V1 = ("episode", "step", "round", "call", "response_artifact", "parser", "value")
EVIDENCE_FIELDS_V2 = (*EVIDENCE_FIELDS_V1, "contract", "verdict", "reason")

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]*")

# P06 §8 stable reason-code family
PARSER_NOT_REGISTERED = "BVL-PROP-001"
PARSER_IDENTITY_MISMATCH = "BVL-PROP-002"
PROPOSAL_SCHEMA_UNKNOWN = "BVL-PROP-003"
PARSE_FAILED = "BVL-PROP-004"
PROPOSAL_SCHEMA_INVALID = "BVL-PROP-005"
FAILURE_POLICY_UNKNOWN = "BVL-PROP-006"
NO_ACTION_NOT_ALLOWED = "BVL-PROP-007"
HIDDEN_REPAIR_FORBIDDEN = "BVL-PROP-008"
PARSER_EXTERNAL_CALL_FORBIDDEN = "BVL-PROP-009"
PROPOSAL_LINEAGE_MISMATCH = "BVL-PROP-010"

PROPOSAL_CODES = frozenset(
    {
        PARSER_NOT_REGISTERED,
        PARSER_IDENTITY_MISMATCH,
        PROPOSAL_SCHEMA_UNKNOWN,
        PARSE_FAILED,
        PROPOSAL_SCHEMA_INVALID,
        FAILURE_POLICY_UNKNOWN,
        NO_ACTION_NOT_ALLOWED,
        HIDDEN_REPAIR_FORBIDDEN,
        PARSER_EXTERNAL_CALL_FORBIDDEN,
        PROPOSAL_LINEAGE_MISMATCH,
    }
)

#: closed field types; syntax only - domain ranges/options belong to the World
FIELD_TYPES = frozenset({"integer", "number", "string", "boolean"})

#: policies that would repair or re-ask; never a parser behavior (P06 §13.4)
_REPAIR_POLICIES = frozenset(
    {"REPAIR", "RETRY", "REPROMPT", "RE_PROMPT", "FALLBACK", "HEURISTIC_REPAIR", "COERCE"}
)


class ProposalError(DeclarationError):
    """A P06 refusal carrying one stable ``BVL-PROP-*`` code."""

    def __init__(self, code: str, detail: str) -> None:
        if code not in PROPOSAL_CODES:
            raise ValueError(f"unknown proposal reason code {code!r}")
        super().__init__(f"{code}: {detail}")
        self.code = code


class ProposalSyntaxError(Exception):
    """Raised by a parser, and only by a parser, for malformed response bytes."""


class FailurePolicy(StrEnum):
    # the actor call succeeded; the run/episode consequence is K0's (§13.3)
    PARSE_FAILURE = "PARSE_FAILURE"
    # an explicit NO_ACTION proposal, only where the schema permits it
    NO_ACTION = "NO_ACTION"


class ParseVerdict(StrEnum):
    VALID = "VALID"
    NO_ACTION = "NO_ACTION"
    INVALID = "INVALID"


class ProposalParserV1(Protocol):
    """A registered P06 parser: raw response bytes + frozen config -> mapping."""

    plugin_identity: str

    def parse(self, content: bytes, config: Mapping[str, Any]) -> Mapping[str, Any]: ...


def _frozen(value: Any, code: str, what: str) -> Any:
    try:
        return json.loads(canonical_json(value))
    except (CanonicalisationError, TypeError, ValueError) as error:
        raise ProposalError(code, f"{what} is not canonical data: {error}") from error


def _require_id(value: Any, what: str, code: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ProposalError(code, f"{what} is not a valid identifier: {value!r}")
    return value


def _type_ok(kind: str, value: Any) -> bool:
    if kind == "boolean":
        return isinstance(value, bool)
    if isinstance(value, bool):
        return False  # a bool is never silently an integer/number
    if kind == "integer":
        return isinstance(value, int)
    if kind == "number":
        return isinstance(value, (int, float))
    return isinstance(value, str)


@dataclass(frozen=True)
class ProposalSchemaV1:
    """A closed typed proposal shape: every field required, no other keys."""

    schema_id: str
    version: int
    fields: Mapping[str, str]
    allow_no_action: bool = False

    def __post_init__(self) -> None:
        _require_id(self.schema_id, "proposal schema id", PROPOSAL_SCHEMA_UNKNOWN)
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise ProposalError(PROPOSAL_SCHEMA_UNKNOWN, "proposal schema version is >= 1")
        if not isinstance(self.fields, Mapping) or not self.fields:
            raise ProposalError(PROPOSAL_SCHEMA_UNKNOWN, "proposal schema declares no fields")
        for name, kind in self.fields.items():
            if not isinstance(name, str) or not name or kind not in FIELD_TYPES:
                raise ProposalError(
                    PROPOSAL_SCHEMA_UNKNOWN,
                    f"field {name!r} type {kind!r} is not one of {sorted(FIELD_TYPES)}",
                )
        if not isinstance(self.allow_no_action, bool):
            raise ProposalError(PROPOSAL_SCHEMA_UNKNOWN, "allow_no_action is a boolean")
        object.__setattr__(self, "fields", MappingProxyType(dict(sorted(self.fields.items()))))

    @property
    def ref(self) -> str:
        return f"{self.schema_id}:{self.version}"

    def document(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_SCHEMA,
            "schema_id": self.schema_id,
            "version": self.version,
            "fields": dict(self.fields),
            "allow_no_action": self.allow_no_action,
        }

    @classmethod
    def from_document(cls, document: Any) -> ProposalSchemaV1:
        keys = {"schema", "schema_id", "version", "fields", "allow_no_action"}
        if (
            not isinstance(document, Mapping)
            or set(document) != keys
            or document["schema"] != SCHEMA_SCHEMA
        ):
            raise ProposalError(PROPOSAL_SCHEMA_UNKNOWN, f"not a {SCHEMA_SCHEMA}")
        return cls(
            document["schema_id"],
            document["version"],
            document["fields"],
            document["allow_no_action"],
        )

    def problems(self, value: Any) -> list[str]:
        """Syntax-only validation; never coerces (P06 §5, no silent repair)."""

        if not isinstance(value, Mapping):
            return [f"proposal is a {type(value).__name__}, not an object"]
        problems = [f"missing field {name!r}" for name in self.fields if name not in value]
        problems += [f"undeclared field {name!r}" for name in sorted(set(value) - set(self.fields))]
        problems += [
            f"field {name!r} is not {kind}"
            for name, kind in self.fields.items()
            if name in value and not _type_ok(kind, value[name])
        ]
        return problems


@dataclass(frozen=True)
class ProposalContractV1:
    """One proposal_parse node's frozen P06 binding (enters PlanIdentity)."""

    node_id: str
    schema: ProposalSchemaV1
    parser: str  # the parser's registered plugin identity
    config: Mapping[str, Any]
    on_invalid: FailurePolicy

    def document(self) -> dict[str, Any]:
        return {
            "schema": CONTRACT_SCHEMA,
            "node_id": self.node_id,
            "proposal_schema": self.schema.document(),
            "parser": self.parser,
            "config": _frozen(dict(self.config), PARSER_IDENTITY_MISMATCH, "parser config"),
            "on_invalid": self.on_invalid.value,
        }


def _policy(value: Any, schema: ProposalSchemaV1, node_id: str) -> FailurePolicy:
    if isinstance(value, str) and value.upper() in _REPAIR_POLICIES:
        raise ProposalError(
            HIDDEN_REPAIR_FORBIDDEN,
            f"{node_id!r}: {value!r} would repair or re-ask; P06 parsers never repair",
        )
    try:
        policy = FailurePolicy(value)
    except ValueError as error:
        raise ProposalError(
            FAILURE_POLICY_UNKNOWN, f"{node_id!r}: unknown failure policy {value!r}"
        ) from error
    if policy is FailurePolicy.NO_ACTION and not schema.allow_no_action:
        raise ProposalError(
            NO_ACTION_NOT_ALLOWED,
            f"{node_id!r}: schema {schema.ref} does not permit NO_ACTION",
        )
    return policy


@dataclass(frozen=True)
class ProposalContractDeclV1:
    """Declared binding of one proposal_parse node (by schema reference)."""

    node_id: str
    schema: str  # "<schema_id>:<version>"
    parser: str
    config: Mapping[str, Any] = field(default_factory=dict)
    on_invalid: str = FailurePolicy.PARSE_FAILURE.value


@dataclass(frozen=True)
class ProposalRegistryV1:
    """Declared proposal schemas + per-node parser contracts (P01 declaration)."""

    schemas: Sequence[ProposalSchemaV1]
    contracts: Sequence[ProposalContractDeclV1]

    def resolve(self) -> ProposalContractSetV1:
        known: dict[str, ProposalSchemaV1] = {}
        for schema in self.schemas:
            if schema.ref in known and known[schema.ref] != schema:
                raise ProposalError(
                    PROPOSAL_SCHEMA_UNKNOWN, f"schema {schema.ref} is declared twice, differently"
                )
            known[schema.ref] = schema
        contracts: dict[str, ProposalContractV1] = {}
        for decl in self.contracts:
            node_id = _require_id(decl.node_id, "proposal node id", PARSER_NOT_REGISTERED)
            if node_id in contracts:
                raise ProposalError(PARSER_NOT_REGISTERED, f"{node_id!r} is bound twice")
            if decl.schema not in known:
                raise ProposalError(
                    PROPOSAL_SCHEMA_UNKNOWN, f"{node_id!r} names undeclared schema {decl.schema!r}"
                )
            schema = known[decl.schema]
            contracts[node_id] = ProposalContractV1(
                node_id,
                schema,
                _require_id(decl.parser, "parser plugin identity", PARSER_NOT_REGISTERED),
                MappingProxyType(
                    _frozen(dict(decl.config), PARSER_IDENTITY_MISMATCH, "parser config")
                ),
                _policy(decl.on_invalid, schema, node_id),
            )
        return ProposalContractSetV1(contracts)


@dataclass(frozen=True)
class ProposalContractSetV1:
    """The resolved P06 contracts of one plan, keyed by proposal_parse node."""

    contracts: Mapping[str, ProposalContractV1]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "contracts", MappingProxyType(dict(sorted(self.contracts.items())))
        )

    def contract(self, node_id: Any) -> ProposalContractV1:
        if not isinstance(node_id, str) or node_id not in self.contracts:
            raise ProposalError(
                PARSER_NOT_REGISTERED, f"proposal_parse {node_id!r} has no plan parser contract"
            )
        return self.contracts[node_id]

    def require_protocol(self, protocol: ProtocolIR) -> None:
        """Exactly the IR's proposal_parse nodes are bound, before anything runs."""

        parse_nodes = {n.node_id for n in protocol.nodes if n.kind is NodeKind.PROPOSAL_PARSE}
        for node_id in sorted(parse_nodes - set(self.contracts)):
            raise ProposalError(
                PARSER_NOT_REGISTERED, f"proposal_parse {node_id!r} has no parser contract"
            )
        for node_id in sorted(set(self.contracts) - parse_nodes):
            raise ProposalError(
                PARSER_NOT_REGISTERED, f"contract {node_id!r} binds no proposal_parse node"
            )

    def document(self) -> dict[str, Any]:
        return {
            "schema": CONTRACT_SET_SCHEMA,
            "contracts": [contract.document() for contract in self.contracts.values()],
        }

    @classmethod
    def from_document(cls, document: Any) -> ProposalContractSetV1:
        """Read one ``bvl-proposal-contract-set-1`` back (closed, canonical shape)."""

        if (
            not isinstance(document, Mapping)
            or set(document) != {"schema", "contracts"}
            or document["schema"] != CONTRACT_SET_SCHEMA
            or not isinstance(document["contracts"], list)
        ):
            raise ProposalError(PROPOSAL_LINEAGE_MISMATCH, f"not a {CONTRACT_SET_SCHEMA}")
        schemas: list[ProposalSchemaV1] = []
        decls: list[ProposalContractDeclV1] = []
        keys = {"schema", "node_id", "proposal_schema", "parser", "config", "on_invalid"}
        for item in document["contracts"]:
            if (
                not isinstance(item, Mapping)
                or set(item) != keys
                or item["schema"] != CONTRACT_SCHEMA
                or not isinstance(item["config"], Mapping)
            ):
                raise ProposalError(PROPOSAL_LINEAGE_MISMATCH, "a contract has the wrong shape")
            schema = ProposalSchemaV1.from_document(item["proposal_schema"])
            schemas.append(schema)
            decls.append(
                ProposalContractDeclV1(
                    item["node_id"], schema.ref, item["parser"], item["config"], item["on_invalid"]
                )
            )
        parsed = ProposalRegistryV1(schemas, decls).resolve()
        if parsed.document() != _frozen(dict(document), PROPOSAL_LINEAGE_MISMATCH, "contracts"):
            raise ProposalError(PROPOSAL_LINEAGE_MISMATCH, "contract set is not canonical")
        return parsed


@dataclass(frozen=True)
class ParseOutcomeV1:
    """The kernel's verdict on one raw response under one contract."""

    verdict: ParseVerdict
    value: Mapping[str, Any]
    reason: Mapping[str, str] | None  # {"code", "detail"} when the parse was invalid

    def document(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "value": dict(self.value),
            "reason": dict(self.reason) if self.reason is not None else None,
        }


def attempt_parse(
    parser: ProposalParserV1, content: bytes, config: Mapping[str, Any]
) -> tuple[str, Any]:
    """One parser invocation: ("OK", output) or ("SYNTAX", reason).

    Only ``ProposalSyntaxError`` is a syntax verdict; any other exception
    propagates (parser defect / containment refusal, never a parse failure).
    """

    try:
        return "OK", parser.parse(content, config)
    except ProposalSyntaxError as error:
        return "SYNTAX", str(error)


def judge(contract: ProposalContractV1, attempt: tuple[str, Any]) -> ParseOutcomeV1:
    """Kernel-owned schema validation + failure-policy application."""

    status, output = attempt
    if status == "SYNTAX":
        reason = {"code": PARSE_FAILED, "detail": str(output)}
    else:
        try:
            value = json.loads(canonical_json(output))
        except (CanonicalisationError, TypeError, ValueError) as error:
            value, problems = None, [f"parser output is not canonical data: {error}"]
        else:
            # SV-11: a member stated null is one the canonical form drops; judged on
            # what is left, an answer naming an undeclared member would be VALID
            stated_null = sorted(
                str(name) for name, item in output.items() if item is None
            ) if isinstance(output, Mapping) else []
            problems = [
                f"member {name!r} is null: a proposal states every member it names"
                for name in stated_null
            ] + contract.schema.problems(value)
        if not problems:
            return ParseOutcomeV1(ParseVerdict.VALID, value, None)
        reason = {"code": PROPOSAL_SCHEMA_INVALID, "detail": "; ".join(problems)}
    if contract.on_invalid is FailurePolicy.NO_ACTION:
        return ParseOutcomeV1(ParseVerdict.NO_ACTION, {}, reason)
    return ParseOutcomeV1(ParseVerdict.INVALID, {}, reason)


def committed_proposal_problems(
    document: Mapping[str, Any], contract: ProposalContractV1
) -> list[str]:
    """Verifier check of one committed proposal-2 against its plan contract."""

    if document.get("contract") != contract.document():
        return [f"{PROPOSAL_LINEAGE_MISMATCH}: proposal contract is not the plan's"]
    if document.get("parser") != contract.parser:
        return [f"{PARSER_IDENTITY_MISMATCH}: proposal parser is not the plan's"]
    verdict, value, reason = document.get("verdict"), document.get("value"), document.get("reason")
    if verdict == ParseVerdict.VALID.value:
        problems = contract.schema.problems(value)
        if problems or reason is not None:
            return [f"{PROPOSAL_SCHEMA_INVALID}: committed VALID proposal: {problems}"]
        return []
    if verdict == ParseVerdict.NO_ACTION.value:
        if contract.on_invalid is not FailurePolicy.NO_ACTION or value != {} or not reason:
            return [f"{NO_ACTION_NOT_ALLOWED}: NO_ACTION proposal outside its policy"]
        return []
    return [f"{PARSE_FAILED}: a {verdict!r} proposal was committed"]
