"""Check that the frozen inputs of the BCP demo are the outputs of the sealed phase P and E runs.

    python check_frozen_inputs.py <sample folder> <frozen_inputs folder>

<sample folder> holds study.json and sources/ (the copy you run). <frozen_inputs folder> is
results/bcp_demo/frozen_inputs_2026-10-18 of this edition (phase_p/ and phase_e/, two sealed
packages). Reads only members listed in each package's MANIFEST-4.json and writes nothing.
Exit code 0 when every check matches, 1 otherwise.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

EVALUATIONS = {"e_it_parse": "eval_it", "e_fin_parse": "eval_finance",
               "e_ops_parse": "eval_operations", "e_pro_parse": "eval_procurement"}


def members(package: Path, role: str):
    manifest = json.loads((package / "MANIFEST-4.json").read_text("utf-8"))
    for member in manifest["members"]:
        if member.get("role") == role:
            data = (package / member["path"]).read_bytes()
            if "sha256:" + hashlib.sha256(data).hexdigest() != member["digest"]:
                raise SystemExit(f"{package.name}: {member['path']} does not match MANIFEST-4.json")
            yield member["path"], json.loads(data)


def main() -> int:
    sample, frozen = Path(sys.argv[1]), Path(sys.argv[2])
    checks = []

    transitions = [doc["transition"] for _, doc in members(frozen / "phase_p", "world_transition")]
    if len(transitions) != 1:
        raise SystemExit(f"phase_p: expected 1 World transition, found {len(transitions)}")
    post_state = transitions[0]["post_state"]
    study = json.loads((sample / "study.json").read_text("utf-8"))
    offer = json.loads((sample / "sources" / "supplier_offer.json").read_text("utf-8"))
    checks.append(("study.json initial_world_state", "phase_p World post_state",
                   study["initial_world_state"] == post_state))
    checks.append(("sources\\supplier_offer.json list_offer_usd", "phase_p offers.seller",
                   offer["list_offer_usd"] == post_state["offers"]["seller"]))

    proposals = {doc["contract"]["node_id"]: doc for _, doc in members(frozen / "phase_e", "proposal")}
    for node, name in EVALUATIONS.items():
        frozen_value = json.loads((sample / "sources" / f"{name}.json").read_text("utf-8"))
        doc = proposals.get(node)
        checks.append((f"sources\\{name}.json", f"phase_e proposal {node}",
                       doc is not None and doc["verdict"] == "VALID" and doc["value"] == frozen_value))

    for left, right, ok in checks:
        print(f"{'MATCH   ' if ok else 'MISMATCH'} {left} == {right}")
    print(f"supplier first offer {post_state['offers']['seller']}; evaluations in favor: "
          + ", ".join(f"{name}={proposals[node]['value']['favor']}" for node, name in EVALUATIONS.items()
                      if node in proposals))
    return 0 if all(ok for _, _, ok in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
