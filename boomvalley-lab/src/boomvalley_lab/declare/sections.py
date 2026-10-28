"""What an absent declaration section means — the one authoritative table.

Every optional section of an experiment declaration has exactly one meaning
when it is absent, of two kinds (frozen: MVP_REQUIREMENTS_FREEZE §7):

    NO_CLAIM        the design asserts nothing about this; nothing is checked,
                    and nothing is reported as verified
    OLD_BEHAVIOUR   a written default applies (the behaviour designs had before
                    the section existed) — used by clean-native declarations as
                    their default and by import paths as their mapping

Absence is never inferred into a claim from names, directories or order, and
is never read as "verified". Evidence-side absences (an entry with no binding,
no derivation record, no origin) follow the same table so there is one place
to look. This replaces the research instrument's twelve scattered LEGACY_*
constants (REIMPLEMENT FROM SPEC).

Canonical form: an absent section is omitted from every canonical document
(core.canonical's single omission rule), for contract and design identity
alike.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from boomvalley_lab.core.errors import DeclarationError


class AbsentMeaning(StrEnum):
    NO_CLAIM = "NO_CLAIM"
    OLD_BEHAVIOUR = "OLD_BEHAVIOUR"


@dataclass(frozen=True)
class SectionRule:
    section: str
    meaning: AbsentMeaning
    when_absent: str
    requirement: str


_RULES = (
    # declaration — structure
    SectionRule("cells", AbsentMeaning.OLD_BEHAVIOUR,
                "the full product of the declared factor levels", "R20"),
    SectionRule("replication", AbsentMeaning.OLD_BEHAVIOUR,
                "one uniform replicate count for every cell", "R21"),
    SectionRule("denominator_policy", AbsentMeaning.OLD_BEHAVIOUR,
                "the full declared factor set", "R26"),
    SectionRule("denominator_basis", AbsentMeaning.OLD_BEHAVIOUR,
                "the execution cell is the counted unit", "R23"),
    SectionRule("analysis_views", AbsentMeaning.OLD_BEHAVIOUR,
                "one default view whose unit is the execution cell", "R23/R31"),
    SectionRule("relation_view", AbsentMeaning.OLD_BEHAVIOUR,
                "the relation targets the default view", "R32"),
    SectionRule("schedule", AbsentMeaning.OLD_BEHAVIOUR,
                "the canonical order: by cell key, then replicate", "R7/R9"),
    SectionRule("failure_policy", AbsentMeaning.OLD_BEHAVIOUR,
                "the one MVP policy (one attempt per cell, ambiguity aborts, "
                "operator-confirmed recovery, one active session per run)", "R7/R8"),
    # declaration — claims
    SectionRule("relation", AbsentMeaning.NO_CLAIM,
                "no claim about what a unit's records are to each other", "R29"),
    SectionRule("relation_invariant", AbsentMeaning.NO_CLAIM,
                "no claim about a unit's role composition", "R30"),
    SectionRule("assignment", AbsentMeaning.NO_CLAIM,
                "no claim about what was assigned to which entity (import form)", "R33"),
    SectionRule("assignment_mechanisms", AbsentMeaning.NO_CLAIM,
                "no claim about what was assigned to which entity", "R33/R35"),
    SectionRule("upstream_stages", AbsentMeaning.NO_CLAIM,
                "no upstream artifact population is declared", "R43"),
    SectionRule("analysis_binding", AbsentMeaning.NO_CLAIM,
                "no analysis is pre-bound to the design", "R12/R14"),
    SectionRule("execution_expectations", AbsentMeaning.NO_CLAIM,
                "no declared-vs-actual execution claim", "R39"),
    SectionRule("artifact_provenance_rules", AbsentMeaning.NO_CLAIM,
                "no per-cell artifact provenance claim", "R40"),
    SectionRule("derivation_expectations", AbsentMeaning.NO_CLAIM,
                "no derivation-design claim", "R43"),
    # evidence
    SectionRule("actual_execution", AbsentMeaning.NO_CLAIM,
                "what answered was not recorded; never inferred from the intent", "R37"),
    SectionRule("execution_binding", AbsentMeaning.NO_CLAIM,
                "the custody entry is unbound; never reported as verified", "R38"),
    SectionRule("derivation_record", AbsentMeaning.NO_CLAIM,
                "no claim that the artifact was derived from another", "R41"),
    SectionRule("session_ledger", AbsentMeaning.OLD_BEHAVIOUR,
                "a run written without a ledger had one implicit session", "R15"),
    SectionRule("custody_origin", AbsentMeaning.OLD_BEHAVIOUR,
                "the entry was written at execution time (FRESH)", "R16"),
)

ABSENT_SECTIONS: dict[str, SectionRule] = {rule.section: rule for rule in _RULES}


def when_absent(section: str) -> SectionRule:
    """The written meaning of `section` being absent. Unknown sections raise:
    a section without a written absent-meaning is not a section."""
    try:
        return ABSENT_SECTIONS[section]
    except KeyError:
        raise DeclarationError(f"no absent-meaning is written for section {section!r}") from None
