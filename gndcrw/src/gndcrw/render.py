"""Renderers over one `gndcrw-result/v0.1` object.

Renderers may change presentation; they may not recompute truth
(RESULT §1). Every value printed here is read from the result document.
TEXT output is ASCII so it survives a cp949 Windows console.
"""

from __future__ import annotations

from gndcrw.jsonio import canonical_json


def render_json(result: dict) -> str:
    """The normative serialization: canonical JSON, one object, newline-terminated."""
    return canonical_json(result) + "\n"


def _ascii(value: object) -> str:
    return str(value).encode("ascii", "backslashreplace").decode("ascii")


def _row(label: str, value: object) -> str:
    return f"{label:<32}{_ascii(value)}"


def _facts(observed: dict) -> list[str]:
    lines = []
    if "scoped_entities" in observed and "satisfied_entities" in observed:
        lines.append(_row("  satisfied entities",
                          f"{observed['satisfied_entities']} / {observed['scoped_entities']}"))
    if "base_count" in observed:
        lines.append(_row("  entity count",
                          f"{observed['base_count']} -> {observed['candidate_count']} "
                          f"(+{observed['added_count']} / -{observed['removed_count']})"))
    if "differing_entities" in observed:
        lines.append(_row("  differing entities", observed["differing_entities"]))
    if "missing" in observed:
        lines.append(_row("  missing", ", ".join(observed["missing"])))
    return lines


def render_text(result: dict) -> str:
    subject = result["subject"]
    lines = [
        "GNDCRW Preflight",
        "",
        _row("Tool", f"{result['tool']['name']} {result['tool']['version']}"),
        _row("Policy", result["policy_id"]),
        _row("Outcome", result["outcome"]),
        _row("Comparison", result["comparison_mode"]),
        _row("Declaration", subject["declaration"]["id"]),
        _row("Intent digest", subject["declaration"]["intent_digest"]),
        _row("Catalog", f"{subject['catalog']['id']} / {subject['catalog']['profile_id']}"),
        _row("Base surface", subject["base_surface"]["id"]),
        _row("Candidate surface", subject["candidate_surface"]["id"]),
    ]
    binding = result.get("binding")
    if binding is not None:  # gndcrw-result/v0.2 (manifest mode)
        manifest = binding["manifest"]
        lines += ["", _row("Result version", result["result_version"]),
                  _row("Manifest sha256", manifest["sha256"]),
                  _row("Manifest size", manifest["size"])]
        for role, raw in sorted(binding["subjects"].items()):
            lines.append(_row(f"  {role}", f"{raw['sha256']}  {raw['size']}"))
        external = binding["external_subject"]
        lines.append(_row("External subject",
                          f"{external['scheme']} {external['digest']}" if external else "(none)"))
        lines.append(_row("Binding limitations", ", ".join(binding["limitations"])))
    lines += ["", "Findings"]
    for finding in result["findings"]:
        target = finding["target"]
        label = finding["finding_id"]
        if target and target["id"] not in label:
            label += f"  {target['id']}"
        lines.append("")
        lines.append(_ascii(label))
        lines.append(_row("  status", finding["status"]))
        lines.append(_row("  policy", finding["policy_class"]))
        lines.append(_row("  reason", finding["reason_code"]))
        lines.extend(_facts(finding["observed"]))
    if not result["findings"]:
        lines.append("  (none)")

    lines += ["", "Premises"]
    for premise in result["premises"]:
        authority = premise["authority"]
        lines.append(_ascii(f"  {premise['premise_id']}  [{authority['kind']}:{authority['id']}]"
                            f"  {premise['statement']}"))
    if not result["premises"]:
        lines.append("  (none)")

    lines += ["", "Limitations"]
    for limitation in result["limitations"]:
        lines.append(_ascii(f"  {limitation['limitation_id']}  scope="
                            f"{','.join(limitation['scope'])}"))
    if not result["limitations"]:
        lines.append("  (none)")

    summary = result["summary"]
    by_status = summary["by_status"]
    lines += [
        "",
        "Summary",
        _row("  findings", summary["finding_count"]),
        _row("  by status", "  ".join(f"{k}={by_status[k]}" for k in by_status)),
        "",
        _row("Outcome", result["outcome"]),
        "",
    ]
    return "\n".join(lines)
