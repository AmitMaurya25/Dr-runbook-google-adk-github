"""Read-only monitoring view-model. Pure functions over a drill-state dict; no store, no tools."""
from __future__ import annotations
import time
from .constants import LABELS, STEP_ORDER, STEP_TIERS, TARGET_DURATIONS, TARGET_RTO_SECONDS
STATUS_META = {"PENDING": ("circle", "Pending"), "IN_PROGRESS": ("play", "Next"), "AWAITING_APPROVAL": ("hourglass", "Awaiting approval"),
               "ROLLBACK_AWAITING": ("hourglass", "Rollback awaiting approval"), "TOKEN_EXPIRED": ("clock", "Token expired"),
               "COMPLETED": ("circle-check", "Completed"), "FAILED": ("circle-x", "Failed"), "ROLLED_BACK": ("rotate-ccw", "Rolled back"),
               "BLOCKED": ("ban", "Blocked")}
def display_status(s: dict, step: str) -> str:
    if s["phase"] == "WAITING_APPROVAL" and s["pending_action"] == step:
        if s["gate_status"] == "EXPIRED": return "TOKEN_EXPIRED"
        return "ROLLBACK_AWAITING" if s["gate_purpose"] == "ROLLBACK" else "AWAITING_APPROVAL"
    st = s["steps_status"][step]
    if st == "PENDING" and s["phase"] == "FORWARD" and s["current_step_index"] < len(STEP_ORDER) and STEP_ORDER[s["current_step_index"]] == step:
        return "IN_PROGRESS"
    return st
def format_mmss(seconds: float) -> str:
    seconds = max(0, int(seconds)); return f"{seconds // 60:02d}:{seconds % 60:02d}"
def token_ttl_remaining(s: dict, now: float | None = None) -> float | None:
    if s["phase"] != "WAITING_APPROVAL" or s["expires_at"] is None: return None
    return max(0.0, s["expires_at"] - (time.time() if now is None else now))
def human_wait(s: dict, now: float | None = None) -> float:
    """Real wall-clock human wait. Never feeds simulated RTO."""
    live = max(0.0, (time.time() if now is None else now) - s["gate_opened_at"]) if s["gate_opened_at"] is not None else 0.0
    return s["gate_wait_seconds"] + live
def step_row_detail(s: dict, step: str) -> str:
    st = display_status(s, step)
    if st in ("AWAITING_APPROVAL", "ROLLBACK_AWAITING", "TOKEN_EXPIRED"): return STATUS_META[st][1]
    if st == "COMPLETED": return f"{s['step_durations'].get(step, 0)}s"
    if st == "FAILED": return f"Failed · {s['step_durations'].get(step, 0)}s"
    if st == "ROLLED_BACK": return f"Rolled back · {s['rollback_durations'].get(step, 0)}s"
    if st == "BLOCKED": return "Blocked"
    return "Next" if st == "IN_PROGRESS" else ""
def nodes(s: dict) -> list[dict]:
    out = []
    for i, step in enumerate(STEP_ORDER, 1):
        st = display_status(s, step); ic, label = STATUS_META[st]
        out.append({"index": i, "step": step, "label": LABELS[step], "status": st, "status_label": label, "icon": ic})
    return out
def snapshot(s: dict, now: float | None = None) -> dict:
    tel = s["telemetry"]
    return {"forward_progress_pct": s["forward_progress_pct"], "rollback_progress_pct": s["rollback_progress_pct"],
            "elapsed_rto": s["elapsed_rto"], "rto_target": TARGET_RTO_SECONDS, "rto_pct": s["rto_pct"], "human_wait_seconds": round(human_wait(s, now), 1),
            "tool_calls": s["tool_call_count"], "retry_count": s["retry_count"], "lag_seconds": tel.get("lag_seconds"),
            "wal_state": tel.get("wal_state", "UNKNOWN"), "token_ttl": token_ttl_remaining(s, now)}
def target_vs_actual(s: dict) -> list[dict]:
    return [{"step": LABELS[x], "target": TARGET_DURATIONS[x], "actual": s["step_durations"].get(x, 0)} for x in STEP_ORDER]
def tier_totals(s: dict) -> dict:
    t: dict = {}
    for x in STEP_ORDER:
        t[STEP_TIERS[x]] = t.get(STEP_TIERS[x], 0) + s["step_durations"].get(x, 0) + s["rollback_durations"].get(x, 0)
    return t
