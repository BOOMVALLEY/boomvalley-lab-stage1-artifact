"""Where a run keeps its evidence — names only, never identity or provenance.

One place, because two readers must agree on it without depending on each
other: the runtime writes a run, `verify` audits one it did not write.
Changing a name here changes only where bytes live; every identity in the
package is computed from content.
"""

from __future__ import annotations

LOCK_FILE = "lock.json"
RUN_FILE = "run.json"
JOURNAL_FILE = "journal.jsonl"
ARTIFACT_DIR = "artifacts"
SESSIONS_DIR = "sessions"
ACTIVE_MARKER = "ACTIVE"
CUSTODY_DIR = "custody"
ENTRIES_FILE = "entries.jsonl"
HEAD_FILE = "head.json"

# INPUT_LOCKED runs only (Input Contract §10.2). A run whose journal carries no
# INPUT_LOCK_BOUND must hold none of these.
INPUT_FILE = "input.json"
PREFLIGHT_DIR = "preflight"
GNDCRW_MANIFEST_FILE = "gndcrw-manifest.json"
GNDCRW_RESULT_FILE = "gndcrw-result.json"
#: the five GNDCRW subjects' fixed file names, relative to the manifest
GNDCRW_SUBJECT_FILES = {
    "declaration": "subjects/declaration.json",
    "target_catalog": "subjects/catalog.json",
    "base_surface": "subjects/base.json",
    "candidate_surface": "subjects/candidate.json",
    "pair_context": "subjects/pair.json",
}

# The evidence package (EPC-v1, in place and additive). EVIDENCE.json is the
# EPC manifest and, like PACKAGE.json, is not a member of itself.
EVIDENCE_FILE = "EVIDENCE.json"
PACKAGE_FILE = "PACKAGE.json"
DECLARATION_MEMBER = "design/declaration.json"
DESIGN_MEMBER = "design/design.json"
SCHEDULE_MEMBER = "design/schedule.json"
DATASET_MEMBER = "dataset/dataset.json"
ELIGIBILITY_MEMBER = "reports/eligibility.json"
PRODUCER_MEMBER = "provenance/producer.json"
ENVIRONMENT_MEMBER = "provenance/environment.json"
REQUESTS_DIR = "requests"
