"""Which role a package member has — one grammar for both manifests.

`PACKAGE.json` (boomvalley-lab-package-1) and `EVIDENCE.json`
(boomvalley-epc-manifest-1) describe the same directory, so they must agree on
what each file IS. A path has a role because of where the product writes it,
and a file whose path has no role here is not a member of any package: a
reader refuses it rather than guessing.

    fixed      one path, one role (the run's own evidence, the Input Lock
               members, the materialised EPC documents)
    by place   artifacts/*, analysis/*, requests/*

The Input Lock members (IR-07) exist only in an INPUT_LOCKED run; whether a
run may hold them is the gate's `input_lock` step, never this table's.
"""

from __future__ import annotations

from boomvalley_lab.core.layout import (
    ARTIFACT_DIR,
    CUSTODY_DIR,
    DATASET_MEMBER,
    DECLARATION_MEMBER,
    DESIGN_MEMBER,
    ELIGIBILITY_MEMBER,
    ENTRIES_FILE,
    ENVIRONMENT_MEMBER,
    GNDCRW_MANIFEST_FILE,
    GNDCRW_RESULT_FILE,
    GNDCRW_SUBJECT_FILES,
    HEAD_FILE,
    INPUT_FILE,
    JOURNAL_FILE,
    LOCK_FILE,
    PACKAGE_FILE,
    PREFLIGHT_DIR,
    PRODUCER_MEMBER,
    REQUESTS_DIR,
    RUN_FILE,
    SCHEDULE_MEMBER,
)

ANALYSIS_DIR = "analysis"  # analysis.run.ANALYSIS_DIR, restated to avoid an import cycle

#: role -> path, the members every package must have.
REQUIRED = {
    "lock": LOCK_FILE,
    "run": RUN_FILE,
    "journal": JOURNAL_FILE,
    "custody_entries": f"{CUSTODY_DIR}/{ENTRIES_FILE}",
    "custody_head": f"{CUSTODY_DIR}/{HEAD_FILE}",
}

#: role -> path, the Input Lock members of an INPUT_LOCKED run (IR-07).
INPUT_LOCK = {
    "experiment_input": INPUT_FILE,
    "gndcrw_manifest": f"{PREFLIGHT_DIR}/{GNDCRW_MANIFEST_FILE}",
    "gndcrw_result": f"{PREFLIGHT_DIR}/{GNDCRW_RESULT_FILE}",
    **{f"gndcrw_subject_{role}": f"{PREFLIGHT_DIR}/{name}"
       for role, name in GNDCRW_SUBJECT_FILES.items()},
}

#: role -> path, the documents the EPC packager materialises.
MATERIALISED = {
    "declaration": DECLARATION_MEMBER,
    "design": DESIGN_MEMBER,
    "schedule": SCHEDULE_MEMBER,
    "dataset": DATASET_MEMBER,
    "eligibility_report": ELIGIBILITY_MEMBER,
    "producer_provenance": PRODUCER_MEMBER,
    "environment": ENVIRONMENT_MEMBER,
}

#: role -> path for every member that has exactly one path.
FIXED = {**REQUIRED, **INPUT_LOCK, **MATERIALISED}
_BY_PATH = {path: role for role, path in FIXED.items()}

#: directory -> role for the members that have a role by where they live
BY_PLACE = {ARTIFACT_DIR: "artifact", ANALYSIS_DIR: "analysis", REQUESTS_DIR: "request"}

#: the EPC manifest also lists the legacy manifest, as an informational member
PACKAGE_MANIFEST_ROLE = "legacy_package_manifest"


def role_for(path: str, *, epc: bool = False) -> str | None:
    """The role `path` has, or None: then it is not a member of any package."""
    if path in _BY_PATH:
        return _BY_PATH[path]
    if epc and path == PACKAGE_FILE:
        return PACKAGE_MANIFEST_ROLE
    head, _, rest = path.partition("/")
    if rest and head in BY_PLACE:
        return BY_PLACE[head]
    return None
