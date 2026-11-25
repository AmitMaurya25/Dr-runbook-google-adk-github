"""Read-only status console. Imports NOTHING that can mutate a drill; takes a loaded state dict, returns text."""
from __future__ import annotations
import re, time
from .constants import ACTION_PHRASES, LABELS, LAG_LIMIT_SECONDS, STEP_ORDER, STEP_OWNERS, TARGET_RTO_SECONDS
from .guardrails import CONSOLE_HELP, validate_input
from .monitoring import format_mmss, human_wait, token_ttl_remaining
SUGGESTIONS = ["RTO", "Replication", "Progress", "Approvals", "Next step"]
REFUSAL = "This console is read-only. Use the approval workflow on the Runbook tab to run or change anything."
_MUT = re.compile(r"\b(approve|reject|execute|rollback now|roll ?back it|fail ?over now|repoint now|run (the |next |step)|start (a |the )?drill|restart|"
                  r"re-?issue|trigger|perform|go ahead|delete|remove|override|skip|update dns|switch dns|send (the )?(notice|email)|force)\b", re.I)
def _rto(s, now): return (f"Simulated RTO is {s['elapsed_rto']} s of the {TARGET_RTO_SECONDS} s target ({s['rto_pct']:.0f}%). "
                          f"Human wait is {human_wait(s, now):.0f} s of real time, tracked separately.")
def _repl(s):
    t = s["telemetry"]
    return ("Replication has not been verified yet. STEP_01 is read-only and runs without approval." if t.get("lag_seconds") is None
            else f"Replication lag {t['lag_seconds']} s (limit {LAG_LIMIT_SECONDS} s), WAL {t['wal_state']}.")
def _progress(s):
    done = list(s["steps_status"].values()).count("COMPLETED")
    txt = f"Forward progress {s['forward_progress_pct']:.0f}% ({done} of {len(STEP_ORDER)} steps completed)."
    if s["rollback_total"]: txt += f" Rollback {s['rollback_progress_pct']:.0f}% ({s['rollback_total'] - len(s['rollback_queue'])} of {s['rollback_total']})."
    return txt
def _approvals(s, now):
    if s["phase"] == "WAITING_APPROVAL" and s["pending_action"]:
        step = s["pending_action"]; kind = "Rollback of" if s["gate_purpose"] == "ROLLBACK" else "Approval needed for"
        tail = "The token has expired and must be re-issued." if s["gate_status"] == "EXPIRED" else f"Token expires in {format_mmss(token_ttl_remaining(s, now) or 0)}."
        return f"{kind} {step[:7]} {LABELS[step]} from the {STEP_OWNERS[step]}. {tail}"
    return f"No approval is pending. {len(s['approvals'])} decision(s) recorded; phase {s['phase']}."
def _next(s):
    if s["phase"] == "DONE": return f"The drill is finished: {s['outcome']}."
    if s["phase"] == "WAITING_APPROVAL": return f"Next is {ACTION_PHRASES[s['pending_action']]}; it needs approval from the {STEP_OWNERS[s['pending_action']]}."
    if s["phase"] == "ROLLBACK": return "A rollback is in progress; each reversal needs its own approval."
    return f"Next is {ACTION_PHRASES[STEP_ORDER[s['current_step_index']]]}; it is read-only and runs without approval."
def answer(question: str, state: dict, now: float | None = None) -> str:
    """Raises ValueError (policy block) for hostile input; otherwise a deterministic answer."""
    q = validate_input(question).lower(); now = time.time() if now is None else now
    if _MUT.search(q): return REFUSAL
    for keys, fn in ((("rto", "time", "long", "wait"), lambda: _rto(state, now)), (("replic", "lag", "wal"), lambda: _repl(state)),
                     (("progress", "percent", "done", "complete"), lambda: _progress(state)), (("approv", "token", "gate", "pending"), lambda: _approvals(state, now)),
                     (("next", "what now"), lambda: _next(state))):
        if any(k in q for k in keys): return fn()
    return CONSOLE_HELP
