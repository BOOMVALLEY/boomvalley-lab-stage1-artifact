"""Rendering: two views of one result, never two results.

`--json` prints the domain result as canonical JSON; the default prints a
short human reading of the SAME dictionary. Nothing is recomputed, re-decided
or summarised differently between the two — every line below reads a value
that is already in the JSON.

The human reading is locale-aware (`core.i18n`: message_key + params); the
JSON is not: its members and codes are English and identical in every locale.

This module owns the process's output streams: `emit` is the only writer of
stdout (the machine or human result) and `emit_error` of the error report on
stderr. Diagnostics go to `core.log`, never here; product code never calls
`print` (tests/lab/test_lab_c1_foundation.py).
"""

from __future__ import annotations

import sys
from collections.abc import Mapping

from boomvalley_lab.core.canonical import canonical_json, wire_json
from boomvalley_lab.core.i18n import DEFAULT_LOCALE, translate


def emit(text: str) -> None:
    """Write one result to stdout: the only stdout writer of the product."""
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


def emit_error(text: str) -> None:
    """Write the error report to stderr. An unwritable stderr changes nothing."""
    try:
        sys.stderr.write(text + "\n")
        sys.stderr.flush()
    except Exception:  # never a verdict, never an exit code
        pass


def render(result: Mapping, *, as_json: bool, locale: str = DEFAULT_LOCALE) -> str:
    if as_json:
        return wire_json(dict(result))

    def t(key: str, **params) -> str:
        return translate(key, params, locale)

    return "\n".join([*_lines(result, t), *_input_lines(result, t), *_gate_lines(result, t)])


def _gate_reason_lines(gate: Mapping, t) -> list[str]:
    lines = []
    for entry in gate.get("reasons") or ():
        lines.append(t("render.gate_reason", rule_id=entry["rule_id"],
                       reason_code=entry["reason_code"],
                       message=t(entry["message_key"], **entry["params"])))
        if entry.get("evidence_ref"):
            lines.append(t("render.gate_evidence",
                           evidence=canonical_json(entry["evidence_ref"])))
    return lines


def _gate_lines(result: Mapping, t) -> list[str]:
    """The execution gate decision and why (#81): status, rule, reason, evidence."""
    gate = result.get("execution_gate")
    if not isinstance(gate, Mapping) or result.get("command") == "verify":
        return []
    status = gate.get("execution_gate_status")
    lines = [t("render.gate", status=status, message=t(f"gate.status.{status}")),
             *_gate_reason_lines(gate, t)]
    if result.get("execution_status"):
        lines.append(t("render.execution_status", status=result["execution_status"]))
    if result.get("gate_record"):
        lines.append(t("render.gate_record",
                       path=f"{result.get('directory')}/{result['gate_record']}"))
    return lines


def _request_lines(result: Mapping, t) -> list[str]:
    """The request content status and why (#84): codes and message keys, never content."""
    reading = result.get("request_content")
    if not isinstance(reading, Mapping) or not reading.get("message_key"):
        return []
    status = reading["request_content_status"]
    lines = [t("render.request_content", status=status,
               message=t(reading["message_key"], **reading["params"]))]
    reason = reading.get("reason")
    if isinstance(reason, Mapping):
        lines.append(t("render.request_content_reason", reason_code=reason["reason_code"],
                       message=t(reason["message_key"], **reason["params"])))
    return lines


def _provenance_lines(result: Mapping, t) -> list[str]:
    """Verified and self-reported provenance on separate lines (#87): field names only."""
    reading = result.get("provenance")
    if not isinstance(reading, Mapping):
        return []
    if not reading.get("trust_classified"):
        return [t("render.provenance_unclassified", schema=reading.get("producer_schema"))]
    return [t("render.provenance_verified",
              fields=", ".join(reading["verified_provenance"]) or "-"),
            t("render.provenance_self_reported",
              fields=", ".join(reading["self_reported_provenance"]) or "-")]


def _input_lines(result: Mapping, t) -> list[str]:
    """The experiment-input facts `bvl` adds, read off the same result."""
    lines = []
    if result.get("contract_identity"):
        lines.append(t("render.contract_identity", value=result["contract_identity"]))
    if result.get("experiment_input_identity"):
        lines.append(t("render.eii", value=result["experiment_input_identity"]))
    if result.get("input_digest"):
        lines.append(t("render.input_digest", value=result["input_digest"]))
    preflight = result.get("preflight")
    if preflight:
        lines.append(f"  {preflight['wording']}")
        lines.append(t("render.preflight_tool", version=preflight["tool"]["version"],
                       manifest=canonical_json(preflight["manifest"]),
                       result=canonical_json(preflight["result"])))
        lines.append(t("render.limitations_indented",
                       limitations=", ".join(preflight["limitations"])))
    scheduled = result.get("schedule_preflight")
    if isinstance(scheduled, Mapping):
        lines.append(t("render.schedule_preflight",
                       status=scheduled["schedule_preflight_status"],
                       message=t(scheduled["message_key"], **scheduled["params"])))
    gated = result.get("experiment_input_preflight")
    if isinstance(gated, Mapping):
        lines.append(t("render.experiment_input_preflight",
                       status=gated["experiment_input_preflight_status"],
                       message=t(gated["message_key"], **gated["params"])))
    found = result.get("input_lock")
    if isinstance(found, Mapping):
        verification = f" {found['verification']}" if found.get("verification") else ""
        code = f" {found['code']}: {found.get('detail')}" if found.get("code") else ""
        lines.append(t("render.input_lock", classification=found.get("classification"),
                       verification=verification, code=code))
    return lines


def _reasons(reasons) -> str:
    return "".join(f"\n      - {reason}" for reason in reasons)


def _gated_lines(result: Mapping, t) -> list[str]:
    """A gated (`lifecycle: k0-gate-2`) result: the gate decision, run state, package."""
    command = result.get("command")
    lines = []
    if command == "validate":
        lines.append(t("render.gated_valid", experiment=result["experiment"],
                       cells=len(result["cells"])))
        lines += [t("render.gated_cell", cell=cell, plan=plan["digest"])
                  for cell, plan in result["cells"].items()]
    gate = result.get("gate_decision")
    if isinstance(gate, Mapping):
        lines.append(t("render.gated_gate", decision=gate["decision"],
                       cell=gate.get("cell", "-"), plan=gate["plan"]["digest"]))
        lines += [t("render.blocking", reason=reason) for reason in gate["reasons"]]
    if result.get("state"):
        lines.append(t("render.gated_run", run=result.get("run"), state=result["state"]))
        calls = result.get("calls") or {}
        lines.append(t("render.gated_calls", accepted=calls.get("accepted", 0),
                       pending=len(calls.get("pending", ()))))
        if result.get("package_problem"):  # SV-09: a manifest-4 that does not seal the run
            lines.append(t("render.blocking", reason=result["package_problem"]))
    if result.get("execution_status"):
        lines.append(t("render.execution_status", status=result["execution_status"]))
        if result.get("failure_journaled") is False:  # SV-09: refused, not a FAILED run
            lines.append(t("render.blocking", reason=(
                f"{result.get('failure')}: not journaled as EPISODE_FAILED; the run is "
                f"{result.get('state')}, not FAILED")))
    lines += [t("render.human_waiting", actor=item["actor"], participant=item["participant"],
                intent=item["intent"]["digest"], desk=item["desk"])
              for item in result.get("waiting") or ()]
    if result.get("resume_action"):
        lines.append(t("render.gated_resume", action=result["resume_action"]))
    if command == "package":
        lines.append(t("render.gated_package", package_class=result["package_class"],
                       members=result["members"],
                       manifest=result["manifest_identity"]["digest"]))
    if command == "verify":
        lines.append(t("render.verified" if result["verified"] else "render.refused"))
        lines += [t("render.blocking", reason=problem) for problem in result["problems"]]
        claim = result.get("l1_conformance")
        if isinstance(claim, Mapping):
            lines.append(t("render.gated_l1", level=claim["level"],
                           hidden=claim.get("hidden_calls", "-")))
            lines += [t("render.blocking", reason=f"{item['id']} {problem}")
                      for item in claim["criteria"] for problem in item["problems"]]
        claim = result.get("l2_conformance")
        if isinstance(claim, Mapping):
            lines.append(t("render.gated_l2", level=claim["level"],
                           edges=claim["lineage"].get("verified_edges", "-")))
            lines += [t("render.blocking", reason=f"{item['id']} {problem}")
                      for item in claim["criteria"] for problem in item["problems"]]
        replay = result.get("world_replay")
        if isinstance(replay, Mapping):
            lines.append(t("render.gated_world_replay", verdict=replay["verdict"],
                           transitions=replay["transitions"]))
            lines += [t("render.blocking", reason=problem) for problem in replay["problems"]]
            # the L3 claim needs the replay (its W5): stated only when one was made
            claim = result.get("l3_conformance")
            if isinstance(claim, Mapping):
                lines.append(t("render.gated_l3", level=claim["level"],
                               transitions=claim["transitions"].get("decision_bound", "-")))
                lines += [t("render.blocking", reason=f"{item['id']} {problem}")
                          for item in claim["criteria"] for problem in item["problems"]]
            # the L4 claim is over the L3 claim (its X1), so over the same replay
            claim = result.get("l4_conformance")
            if isinstance(claim, Mapping):
                lines.append(t("render.gated_l4", level=claim["level"],
                               rounds=claim.get("rounds", {}).get("rounds_closed", "-"),
                               memory=claim.get("memory", {}).get("counts", {}).get(
                                   "recorded", "-")))
                lines += [t("render.blocking", reason=f"{item['id']} {problem}")
                          for item in claim["criteria"] for problem in item["problems"]]
        claim = result.get("call_provenance")
        if isinstance(claim, Mapping):
            lines.append(t("render.gated_call_provenance", verdict=claim["verdict"],
                           hidden=claim.get("hidden_calls", "-"),
                           **{kind.lower(): claim["callers"].get(kind, "-")
                              for kind in ("MODEL", "HUMAN", "TOOL")}))
            lines += [t("render.blocking", reason=f"{item['id']} {problem}")
                      for item in claim["criteria"] for problem in item["problems"]]
        # the L5 claim is over the L1 claim and the call provenance: it needs no replay
        claim = result.get("l5_conformance")
        if isinstance(claim, Mapping):
            lines.append(t("render.gated_l5", level=claim["level"],
                           humans=claim.get("human", {}).get("counts", {}).get(
                               "received", "-"),
                           tools=claim.get("tool", {}).get("counts", {}).get("steps", "-")))
            lines += [t("render.blocking", reason=f"{item['id']} {problem}")
                      for item in claim["criteria"] for problem in item["problems"]]
            arguments = claim.get("tool", {}).get("arguments", {})
            if claim.get("limitations"):
                lines.append(t("render.gated_l5_arguments",
                               rederived=arguments.get("rederived", "-"),
                               declared=arguments.get("declared", "-")))
    if command == "analyse":
        analysis = result["analysis"]
        lines.append(t("render.gated_analysis", analysis=analysis["contract"]["analysis_id"],
                       status=analysis["status"]))
        lines += [f"  {metric['metric_id']}: {canonical_json(metric['groups'])}"
                  for metric in analysis["metrics"]]
    return lines


def _human_lines(result: Mapping, t) -> list[str]:
    """A human desk (`lifecycle: human-desk-1`) result: enrollment, deliveries, answers."""
    action = result.get("action")
    if action == "enroll":
        return [t("render.human_enrolled", participant=result["participant"],
                  actor=result["actor"], consent=result["consent"]["digest"])]
    if action == "answer":
        return [t("render.human_answered", intent=result["intent"]["digest"],
                  actor=result["actor"], participant=result["participant"])]
    lines = [t("render.human_pending", desk=result["desk"], pending=len(result["pending"]),
               delivered=result["delivered"])]
    for item in result["pending"]:
        lines.append(t("render.human_request", actor=item["actor"],
                       participant=item["participant"], intent=item["intent"]["digest"]))
        lines += [t("render.human_message", role=message.get("role"),
                    content=message.get("content")) for message in item["messages"]]
    return lines


def _lines(result: Mapping, t) -> list[str]:
    command = result.get("command")
    if result.get("lifecycle") == "k0-gate-2":
        return _gated_lines(result, t)
    if result.get("lifecycle") == "human-desk-1":
        return _human_lines(result, t)
    if command in ("validate", "check"):
        return [t("render.validated" if command == "validate" else "render.checked",
                  experiment=result["experiment"], records=result["records"])]
    if command == "lock":
        lines = [f"{kind}: {value}" for kind, value in sorted(result["identities"].items())]
        if result.get("output"):
            lines.append(t("render.written", output=result["output"]))
        return lines
    if command in ("run", "resume"):
        lines = []
        if result.get("released"):
            lines.append(t("render.released", released=result["released"]))
        if result.get("recovered"):
            lines.append(t("render.recovered", record=result["recovered"],
                           origin=result["origin"]))
        if "executed" in result:
            lines.append(t("render.progress", executed=result["executed"],
                           skipped=result["skipped"], remaining=result["remaining"]))
        lines.extend(_run_lines(result, t))
        return lines
    if command == "status":
        return _run_lines(result, t)
    if command == "audit":
        lines = [t("render.audit_head", eligibility=result["eligibility"], run=result["run"])]
        lines += [f"  {finding['verdict']:9} {finding['step']}" + _reasons(finding["reasons"])
                  for finding in result["findings"]]
        if result.get("dataset"):
            lines.append(t("render.dataset", identity=result["dataset"]["identity"],
                           records=result["dataset"]["records"]))
        return lines
    if command == "analyse":
        return [t("render.analysed", records=result["records"], dataset=result["dataset"]),
                t("render.analysis", plugin=result["analysis"]["plugin"],
                  version=result["analysis"]["version"]),
                t("render.analysis_result", result=canonical_json(result["result"]))]
    if command == "package" and "package_identity" in result:
        return [t("render.epc_package", run=result["run"]["run_id"], members=result["members"],
                  input_lock=result["input_lock"]),
                t("render.package_identity", value=result["package_identity"]),
                t("render.evidence_root", value=result["evidence_root"]),
                *(t("render.identity", kind=kind, digest=digest)
                  for kind, digest in result["identities"].items()),
                t("render.self_check", value=result["producer_self_check"]),
                *_request_lines(result, t),
                t("render.limitations", limitations=", ".join(result["limitation_codes"]))]
    if command == "verify" and "gate_record" in result:
        lines = [t("render.gate_record_verified",
                   verification=t("render.verified" if result["verified"] else "render.refused"),
                   record=result["gate_record"], status=result["execution_gate_status"],
                   execution=result["execution_status"])]
        lines += [f"  {rule['verdict']:9} {rule['rule_id']}" + _reasons(rule["reasons"])
                  for rule in result["rules"]]
        return lines + _gate_reason_lines(result.get("execution_gate") or {}, t)
    if command == "verify" and "package_identity" in result:
        lines = [t("render.verified" if result["verified"] else "render.refused")
                 + f"  {result['manifest']} {result['package_identity']}"]
        lines += [f"  {rule['verdict']:9} {rule['rule_id']}" + _reasons(rule["reasons"])
                  for rule in result["rules"]]
        return lines + _request_lines(result, t) + _provenance_lines(result, t)
    if command == "package":
        dataset = (result.get("dataset") or {}).get("identity")
        return [t("render.package", run=result["run"], members=result["members"]),
                t("render.package_dataset", identity=dataset),
                t("render.self_check", value=result["producer_self_check"]),
                t("render.analysis_outputs", count=len(result["analysis"]))]
    if command == "verify":
        lines = [t("render.verified" if result["verified"] else "render.refused")]
        lines += [f"  {finding['verdict']:9} {finding['step']}" + _reasons(finding["reasons"])
                  for finding in result["findings"]]
        lines.append(t("render.recomputed_dataset", value=result["recomputed"].get("dataset")))
        lines.append(t("render.recomputed_eligibility",
                       value=result["recomputed"].get("eligibility")))
        return lines
    return [canonical_json(dict(result))]


def _run_lines(result: Mapping, t) -> list[str]:
    if "state" not in result:
        return []
    lines = []
    if "run" in result:
        lines.append(t("render.run_state", run=result["run"], state=result["state"]))
    if "active_session" in result:
        lines.append(t("render.active_session",
                       session=result["active_session"] or t("render.none"),
                       sessions=result.get("sessions")))
    if "states" in result:
        counts = ", ".join(f"{state} {count}" for state, count in result["states"].items()
                           if count)
        decisions = ", ".join(f"{decision} {count}"
                              for decision, count in result["decisions"].items() if count)
        lines.append(t("render.scheduled", scheduled=result["scheduled"], counts=counts))
        lines.append(t("render.decisions", decisions=decisions))
    if "custody" in result:
        custody = result["custody"]
        lines.append(t("render.custody", entries=custody["entries"], fresh=custody["FRESH"],
                       recovered=custody["RECOVERED"]))
    if "resume_permitted" in result:
        lines.append(t("render.resume_permitted", permitted=result["resume_permitted"]))
        for reason in result.get("blocking") or []:
            lines.append(t("render.blocking", reason=reason))
        for record in result.get("operator_decision_required") or []:
            lines.append(t("render.operator_decision", record=record))
    return lines
