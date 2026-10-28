"""What an analysis of THIS evidence must say — rebuilt, never read off it.

A recorded analysis document says which run it analysed, which dataset, under
which lock, with which plugin, at which version, with which parameters, and
that the gate had said ELIGIBLE. Checking those claims against each other
establishes only that whoever wrote the document was consistent:

    self-consistent evidence  !=  authoritatively bound evidence

Rewrite the fields together and a document describing a different run, a
different dataset or different analysis parameters passes every internal
check, recomputes its own evidence identity, and verifies.

So the verifier reconstructs what the answer HAS to be, from sources the
document cannot influence, and then compares:

    authority                   comes from
    ------------------------------------------------------------------
    run                         the run the evidence is being read as
    contract/design/schedule    the experiment lock, re-verified
    DatasetIdentity             the admitted dataset the gate recomputed
    admitted row count          the same dataset
    plugin, version, parameters the lock's `analysis_binding`
    eligibility verdict         the verifier's OWN audit
    eligibility report          the digest of that audit document

`reconstruct` takes an audit the caller performed and returns exactly that.
It reads no analysis document, takes no argument derived from one, and has
no way to be steered by one — which is the only property that matters here.

    R12  analysis exists only where the gate said ELIGIBLE
    R14  an output names the dataset and the lock identities it belongs to

Scope: whether ONE analysis document is bound to the experiment context it
claims. Whether a package may carry an analysis belonging to another run at
all is #11, and the package's normative-member authority is #12.
"""

from __future__ import annotations

from collections.abc import Mapping

from boomvalley_lab.core.digest import sha256_document
from boomvalley_lab.dataset.manifest import dataset_identity


def _same(recorded: object, authoritative: object) -> bool:
    """Canonical comparison, not dict equality.

    A recorded document has been through `canonical-json-1`, which omits None
    entries, so a binding that declares no version comes back without the key
    while the lock's live document still carries `version: None`. Those are
    the same binding, and only a canonical comparison says so. Comparing the
    dicts directly would refuse every honest analysis of a design that binds
    no version - which is exactly what it did before this was fixed.
    """
    return sha256_document(recorded) == sha256_document(authoritative)


def reconstruct(report) -> dict:
    """The binding an honest analysis of this evidence must carry.

    `report` is an `Audit` the caller computed from the run directory. Every
    value below comes from it or from the lock it verified.
    """
    dataset = None if report.dataset is None else dataset_identity(report.dataset)
    return {
        "run": report.run,
        "identities": dict(report.identities),
        "dataset": None if dataset is None else str(dataset.digest),
        "records": None if report.dataset is None else report.dataset["records"],
        "binding": None if report.binding is None else dict(report.binding),
        "eligibility": {
            "verdict": report.document()["eligibility"],
            "report": str(sha256_document(report.document())),
        },
    }


def problems(recorded: Mapping, authority: Mapping, *, where: str = "the analysis") -> list[str]:
    """Where a recorded analysis disagrees with the reconstructed authority.

    Each comparison names the authoritative side, so a reader of the failure
    can see what was trusted and what was merely claimed.
    """
    found: list[str] = []

    if recorded.get("run") != authority["run"]:
        found.append(f"{where}: recorded for run {recorded.get('run')!r}, which is not "
                     f"{authority['run']!r} (R14)")

    if not _same(recorded.get("identities"), authority["identities"]):
        found.append(f"{where}: bound to another contract, design or schedule than the "
                     "lock this evidence verifies against (R14)")

    if authority["dataset"] is None:
        found.append(f"{where}: this evidence admits no dataset, so no analysis of it "
                     "can be bound to one (R12)")
    elif recorded.get("dataset") != authority["dataset"]:
        found.append(f"{where}: bound to dataset {str(recorded.get('dataset'))[:23]}…, "
                     f"which is not the dataset this evidence admits (R14)")

    if recorded.get("records") != authority["records"]:
        found.append(f"{where}: says it analysed {recorded.get('records')!r} record(s); the "
                     f"admitted dataset has {authority['records']!r}")

    if authority["binding"] is None:
        found.append(f"{where}: the design pre-binds no analysis, so none may be recorded")
    else:
        # the lock's binding, compared whole: plugin, version and parameters
        # together, so a parameter cannot be changed by renaming the plugin.
        declared = recorded.get("declared")
        if not _same(declared, authority["binding"]):
            found.append(f"{where}: declares the analysis binding {_binding(declared)}, "
                         f"which is not the locked {_binding(authority['binding'])}")
        # and what actually ran is still compared with what was bound
        actual = recorded.get("actual") or {}
        locked = authority["binding"]
        if actual.get("plugin") != locked.get("plugin"):
            found.append(f"{where}: {actual.get('plugin')!r} ran where the lock binds "
                         f"{locked.get('plugin')!r}")
        if locked.get("version") is not None and actual.get("version") != locked["version"]:
            found.append(f"{where}: version {actual.get('version')!r} ran where the lock "
                         f"binds {locked['version']!r}")

    eligibility = recorded.get("eligibility")
    if not isinstance(eligibility, Mapping):
        found.append(f"{where}: records no eligibility evidence (R12)")
    else:
        if eligibility.get("verdict") != authority["eligibility"]["verdict"]:
            found.append(f"{where}: claims the gate said {eligibility.get('verdict')!r}; "
                         f"this evidence recomputes to "
                         f"{authority['eligibility']['verdict']!r} (R12)")
        if eligibility.get("report") != authority["eligibility"]["report"]:
            found.append(f"{where}: names an eligibility report this evidence does not "
                         "produce (R12)")
    return found


def _binding(binding: object) -> str:
    if not isinstance(binding, Mapping):
        return repr(binding)
    parameters = binding.get("parameters") or {}
    return (f"{binding.get('plugin')!r}/{binding.get('version')!r} with "
            f"{dict(sorted(parameters.items()))!r}")
