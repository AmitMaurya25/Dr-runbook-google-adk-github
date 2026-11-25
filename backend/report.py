"""Deterministic drill report. Simulated RTO and human wait are reported separately and never mixed."""
from __future__ import annotations
from .constants import LABELS, OUTCOME_NOTICE_FAILED, OUTCOME_ROLLED_BACK, STEP_ORDER, TARGET_DURATIONS, TARGET_RTO_SECONDS, short_id
from .monitoring import tier_totals
_RULES = [("TLS certificate", "Validate the DR application TLS certificate (CN/SAN) before the drill and add it to the STEP_03 prerequisites."),
          ("lag", "Alert on replication lag before the drill window and keep the DR standby caught up.")]
def _deviations(s):
    out = []
    for x in STEP_ORDER:
        if s["steps_status"][x] in ("FAILED", "ROLLED_BACK", "BLOCKED"): out.append(f"{short_id(x)} {LABELS[x]}: {s['steps_status'][x]}")
        if s["step_durations"].get(x, 0) > TARGET_DURATIONS[x]: out.append(f"{short_id(x)} {LABELS[x]}: {s['step_durations'][x]} s exceeded the {TARGET_DURATIONS[x]} s target")
    if s["attempts"].get(STEP_ORDER[0], 0) > 1: out.append(f"STEP_01 needed {s['attempts'][STEP_ORDER[0]]} attempts because replication lag was high")
    if s["outcome"] == OUTCOME_NOTICE_FAILED: out.append("STEP_06 stakeholder notice failed; a correction notice is required")
    if s["notice_corrected"]: out.append("STEP_06 first notice failed; a correction notice was sent under a new approval")
    return out
def _improvements(s):
    txt = " ".join(r["details"] for r in s["step_results"].values() if r).lower()
    items = [m for k, m in _RULES if k.lower() in txt or (k == "lag" and s["attempts"].get(STEP_ORDER[0], 0) > 1)]
    if s["outcome"] == OUTCOME_ROLLED_BACK: items.append("Rehearse compensation: each rollback step needs its own approval, so staff the approver roles in advance.")
    if s["elapsed_rto"] > TARGET_RTO_SECONDS: items.append("Simulated RTO exceeded the 900 s target: review step targets.")
    items.append("Copy the audit chain head to a separate trusted system (tamper evidence needs an external anchor).")
    return items
def build_report(s: dict, store) -> dict:
    head = store.export_audit_head(s["session_id"], s["drill_id"])
    return {"drill_id": s["drill_id"], "scenario": s["scenario"], "outcome": s["outcome"] or "IN_PROGRESS", "simulated_rto_seconds": s["elapsed_rto"],
            "target_rto_seconds": TARGET_RTO_SECONDS, "rto_within_target": s["elapsed_rto"] <= TARGET_RTO_SECONDS, "human_wait_seconds": round(s["gate_wait_seconds"], 1),
            "rto_by_tier": tier_totals(s), "step_durations": s["step_durations"], "rollback_durations": s["rollback_durations"],
            "deviations": _deviations(s), "improvements": _improvements(s),
            "approvers": [{k: a[k] for k in ("step", "purpose", "approver", "role", "decision")} for a in s["approvals"]], "notice_text": s.get("notice_text", ""),
            "audit": {"head_hash": head["head_hash"], "events": head["count"], "chain_valid": store.verify_chain(s["session_id"], s["drill_id"])},
            "notes": "Simulated RTO comes from the scenario table. Human wait is real wall-clock time and is not part of simulated RTO."}
def markdown(r: dict) -> str:
    L = [f"# DR drill report {r['drill_id'][:4]}", f"- Scenario: {r['scenario']}", f"- Outcome: **{r['outcome']}**",
         f"- Simulated RTO: {r['simulated_rto_seconds']} s of {r['target_rto_seconds']} s ({'within' if r['rto_within_target'] else 'over'} target)",
         f"- Human wait (real time, separate): {r['human_wait_seconds']} s", "", "## RTO by tier"] + [f"- {k}: {v} s" for k, v in r["rto_by_tier"].items()]
    L += ["", "## Deviations"] + ([f"- {d}" for d in r["deviations"]] or ["- none"]) + ["", "## Improvements"] + [f"- {i}" for i in r["improvements"]]
    L += ["", "## Approvers"] + ([f"- {a['step'][:7]} {a['purpose']} {a['decision']}: {a['approver']} ({a['role']}) [simulated identity]" for a in r["approvers"]] or ["- none"])
    L += ["", "## Audit", f"- Head hash: `{r['audit']['head_hash']}`", f"- Events: {r['audit']['events']}; chain valid: {r['audit']['chain_valid']}",
          "- Copy the head hash to a separate system to make tampering detectable.", "", f"_{r['notes']}_"]
    return "\n".join(L)
