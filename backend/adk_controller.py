"""Deterministic drill controller: the only component that runs tools. LLM output is never authorization (plan 6, 7)."""
from __future__ import annotations
import copy, os, threading, time, uuid
from . import adk_runtime
from .constants import *  # noqa: F401,F403
from .constants import (ACTION_PHRASES, APPROVER_ROLES, CONFIRM_PHRASES, DEFAULT_TOKEN_TTL_SECONDS, LABELS, MAX_RETRIES, MAX_TOKEN_REISSUES,
    MAX_TOOL_CALLS, MUTATING_STEPS, OUTCOME_ABORTED_NO_MUTATION, OUTCOME_HALTED, OUTCOME_NOTICE_FAILED, OUTCOME_OK, OUTCOME_ROLLED_BACK,
    PREREQUISITE, READ_ONLY_STEPS, REQUIRE_FOUR_EYES_ROLLBACK, RETRY_WAIT_SECONDS, ROLLBACK_CONFIRM, ROLLBACKABLE_STEPS, STEP_ORDER, STEP_OWNERS,
    TARGET_RTO_SECONDS, S1, S5, S6)
from .interfaces import ApprovalError, ConcurrencyError, ControllerError, TokenExpiredError
from .retriever import LocalMarkdownRetriever
from .tools import OperatorTools, SQLiteStateStore, load_scenarios
class _Safe(dict):
    def __missing__(self, k): return "{" + k + "}"
class ADKDrillController:
    def __init__(self, db_path=None, clock=time.time, scenarios=None, token_ttl=None, four_eyes=None, auto_narrate=True, retriever=None):
        self.clock = clock
        self.scenarios = scenarios or load_scenarios()
        self.store = SQLiteStateStore(db_path or os.getenv("DR_DB_PATH", "dr_orchestrator.db"), clock)
        self.tools = OperatorTools(self.store, self.scenarios)
        self.retriever = retriever or LocalMarkdownRetriever()
        self.ttl = int(token_ttl or os.getenv("TOKEN_TTL_SECONDS", DEFAULT_TOKEN_TTL_SECONDS))
        self.four_eyes = REQUIRE_FOUR_EYES_ROLLBACK if four_eyes is None else four_eyes
        self.auto_narrate = auto_narrate
        self._lock = threading.RLock()
    # ------------------------------------------------------------------ public API (plan 7.1)
    def start_drill(self, session_id, scenario="normal_drill") -> dict:
        if scenario not in self.scenarios: raise ControllerError("unknown scenario")
        did = uuid.uuid4().hex[:12]
        s = {"session_id": session_id, "drill_id": did, "scenario": scenario, "current_step_index": 0,
             "steps_status": {x: "PENDING" for x in STEP_ORDER}, "elapsed_rto": 0, "pending_action": None, "approval_id": None,
             "gate_purpose": None, "gate_status": None, "gate_opened_at": None, "gate_wait_seconds": 0.0, "expires_at": None,
             "reissue_count": 0, "pending_second": [], "phase": "FORWARD", "outcome": None, "retry_count": 0, "attempts": {},
             "rollback_queue": [], "rollback_total": 0, "step_durations": {}, "rollback_durations": {}, "tool_call_count": 0,
             "step_results": {}, "last_result": None, "approvals": [], "telemetry": {"lag_seconds": None, "wal_state": "UNKNOWN"},
             "forward_progress_pct": 0.0, "rollback_progress_pct": 0.0, "rto_pct": 0.0, "operator_message": "", "coordinator_message": "",
             "model_version": "", "comms_draft": "", "notice_text": "", "notice_attempts": 0, "correction": False, "notice_corrected": False}
        with self._lock:
            s = self.store.create_drill(session_id, did, s)
            s["comms_draft"] = self._tpl("A", s, S1)
            self.store.audit(session_id, did, "controller", "DRILL_STARTED", "", "OK", f"scenario={scenario}")
            return self._commit(s)
    def advance_drill(self, session_id, drill_id) -> dict:
        with self._lock:
            return self._commit(self._advance(self.store.load(session_id, drill_id)))
    def run_to_gate(self, session_id, drill_id) -> dict:
        with self._lock:
            s = self.store.load(session_id, drill_id)
            for _ in range(MAX_TOOL_CALLS + 4):
                if s["phase"] in ("WAITING_APPROVAL", "DONE"): break
                s = self._advance(s)
            return self._commit(s)
    def submit_decision(self, session_id, drill_id, decision, approval_id, approver, approver_role, confirm_text="") -> dict:
        decision = str(decision).upper()
        if decision not in ("APPROVE", "REJECT"): raise ControllerError("decision must be APPROVE or REJECT")
        with self._lock:
            s = self.store.load(session_id, drill_id)
            if self._refresh_expiry(s): s = self._commit(s)
            if s["phase"] != "WAITING_APPROVAL" or not s["pending_action"]: raise ControllerError("no approval is pending")
            if approval_id != s["approval_id"]: raise ApprovalError("approval id does not match the open gate")
            step, purpose = s["pending_action"], s["gate_purpose"]
            self._check_approver(step, approver, approver_role)
            if decision == "REJECT": return self._commit(self._reject(s, approver, approver_role))
            if s["gate_status"] == "EXPIRED": raise TokenExpiredError("approval token expired; re-issue it")
            need = ROLLBACK_CONFIRM if purpose == "ROLLBACK" else CONFIRM_PHRASES.get(step)
            if need and confirm_text.strip().upper() != need: raise ApprovalError(f"type {need} to confirm")
            if purpose == "ROLLBACK" and self.four_eyes:
                names = s["pending_second"]
                if approver.strip() not in names: names.append(approver.strip())
                if len(set(names)) < 2:
                    self.store.audit(session_id, drill_id, f"approver:{approver}", "FOUR_EYES_FIRST_APPROVAL", step, "WAITING", "second approver needed")
                    return self._commit(s)
            wait = max(0.0, self.clock() - (s["gate_opened_at"] or self.clock()))
            try:
                res = self._run_approved(s, step, purpose)
            except TokenExpiredError:
                s["gate_status"] = "EXPIRED"; self._commit(s); raise
            s["gate_wait_seconds"] += wait
            s["approvals"].append({"step": step, "purpose": purpose, "approver": approver, "role": approver_role, "decision": "APPROVE", "at": self.clock()})
            s["tool_call_count"] += 1; s["attempts"][step] = s["attempts"].get(step, 0) + 1
            self.store.audit(session_id, drill_id, f"approver:{approver}", "APPROVED", step, purpose, f"role={approver_role}")
            was_correction = s["correction"]
            self._clear_gate(s)
            if purpose == "ROLLBACK": self._apply_rollback(s, step, res)
            elif was_correction and step == S6: self._apply_correction(s, res)
            else: s["phase"] = "FORWARD"; self._apply_forward(s, step, res)
            self._narrate(s, res, live=False)
            return self._commit(s)
    def reissue_token(self, session_id, drill_id, approver, approver_role) -> dict:
        with self._lock:
            s = self.store.load(session_id, drill_id)
            if s["phase"] != "WAITING_APPROVAL": raise ControllerError("no approval is pending")
            self._refresh_expiry(s)
            if s["gate_status"] != "EXPIRED": raise ApprovalError("the current token is still valid")
            step = s["pending_action"]; self._check_approver(step, approver, approver_role)
            if s["reissue_count"] >= MAX_TOKEN_REISSUES:
                self.store.audit(session_id, drill_id, "controller", "REISSUE_CAP_REACHED", step, "ABORT", "aborting through the reject path")
                return self._commit(self._reject(s, "system", approver_role))
            self.store.revoke_token(s["approval_id"])
            aid, exp = self.store.issue_token(session_id, drill_id, step, s["gate_purpose"], self.ttl)
            s.update(approval_id=aid, expires_at=exp, gate_status="ISSUED", reissue_count=s["reissue_count"] + 1)
            self.store.audit(session_id, drill_id, f"approver:{approver}", "REISSUE_APPROVAL_TOKEN", step, "ISSUED", f"reissue {s['reissue_count']} of {MAX_TOKEN_REISSUES}")
            return self._commit(s)
    def request_correction_notice(self, session_id, drill_id) -> dict:
        with self._lock:
            s = self.store.load(session_id, drill_id)
            if s["outcome"] != OUTCOME_NOTICE_FAILED or s["phase"] != "DONE": raise ControllerError("no failed notice to correct")
            s.update(outcome=None, correction=True); self._open_gate(s, S6, "EXECUTE")
            self.store.audit(session_id, drill_id, "controller", "CORRECTION_NOTICE_REQUESTED", S6, "WAITING", "new approval required")
            return self._commit(s)
    def explain_last(self, session_id, drill_id) -> dict:
        """Live Operator -> Coordinator ADK handoff (falls back deterministically). Triggered by the UI button."""
        with self._lock:
            s = self.store.load(session_id, drill_id)
            if not s["last_result"]: raise ControllerError("nothing to explain yet")
            self._narrate(s, s["last_result"], live=True); return self._commit(s)
    def get_state(self, session_id, drill_id) -> dict:
        with self._lock:
            s = self.store.load(session_id, drill_id)
            if self._refresh_expiry(s): s = self._commit(s)
            return copy.deepcopy(s)
    def restart_drill(self, session_id, drill_id) -> dict:
        return self.start_drill(session_id, self.store.load(session_id, drill_id)["scenario"])
    start, decide, state = start_drill, submit_decision, get_state   # starter-zip aliases (C-02)
    # ------------------------------------------------------------------ internals
    def _commit(self, s):
        done = list(s["steps_status"].values()).count("COMPLETED")
        s["forward_progress_pct"] = round(100 * done / len(STEP_ORDER), 1)
        t = s["rollback_total"]
        s["rollback_progress_pct"] = round(100 * (t - len(s["rollback_queue"])) / t, 1) if t and s["phase"] != "FORWARD" else 0.0
        s["rto_pct"] = round(100 * s["elapsed_rto"] / TARGET_RTO_SECONDS, 1)
        s["_version"] = self.store.save(s["session_id"], s["drill_id"], s); return s
    def _tpl(self, letter, s, step):
        return self.retriever.get_template(letter).format_map(_Safe(drill_id=s["drill_id"][:4], scenario=s["scenario"], step=f"{step[:7]} {LABELS[step]}",
                                                                   owner=STEP_OWNERS[step], rto=s["elapsed_rto"], outcome=s["outcome"] or ""))
    def _refresh_expiry(self, s) -> bool:
        if s["phase"] == "WAITING_APPROVAL" and s["approval_id"] and s["gate_status"] != "EXPIRED":
            if self.store.token_status(s["approval_id"]) == "EXPIRED":
                s["gate_status"] = "EXPIRED"; self.store.audit(s["session_id"], s["drill_id"], "controller", "TOKEN_EXPIRED", s["pending_action"], "EXPIRED", "")
                return True
        return False
    def _check_approver(self, step, name, role):
        if not str(name or "").strip(): raise ApprovalError("approver name is required")
        if role not in APPROVER_ROLES: raise ApprovalError("unknown approver role")
        if role != STEP_OWNERS[step] and role != "Incident Commander": raise ApprovalError(f"only the {STEP_OWNERS[step]} (or Incident Commander) may decide this step")
    def _clear_gate(self, s):
        s.update(pending_action=None, approval_id=None, gate_purpose=None, gate_status=None, expires_at=None, gate_opened_at=None, pending_second=[])
    def _open_gate(self, s, step, purpose):
        aid, exp = self.store.issue_token(s["session_id"], s["drill_id"], step, purpose, self.ttl)
        s.update(pending_action=step, approval_id=aid, gate_purpose=purpose, gate_opened_at=self.clock(), gate_status="ISSUED", expires_at=exp,
                 reissue_count=0, phase="WAITING_APPROVAL", pending_second=[])
        s["comms_draft"] = self._tpl("C" if purpose == "ROLLBACK" else "B", s, step)
        self.store.audit(s["session_id"], s["drill_id"], "controller", "ISSUE_APPROVAL_TOKEN", step, purpose, f"ttl={self.ttl}s")
    def _finish(self, s, outcome):
        s["outcome"] = outcome; s["phase"] = "DONE"; self._clear_gate(s)
        self.store.audit(s["session_id"], s["drill_id"], "controller", "DRILL_FINISHED", "", outcome, f"simulated_rto={s['elapsed_rto']}s")
    def _advance(self, s):
        if s["phase"] in ("DONE", "WAITING_APPROVAL"): return s
        if s["phase"] == "ROLLBACK":
            if not s["rollback_queue"]: self._finish(s, OUTCOME_ROLLED_BACK)
            else: self._open_gate(s, s["rollback_queue"][0], "ROLLBACK")
            return s
        step = STEP_ORDER[s["current_step_index"]]
        pre = PREREQUISITE.get(step)
        if pre and s["steps_status"][pre] != "COMPLETED": raise ControllerError(f"prerequisite {pre} is not completed")
        if step in MUTATING_STEPS: self._open_gate(s, step, "EXECUTE"); return s
        if s["tool_call_count"] >= MAX_TOOL_CALLS:
            res = {"step": step, "result": "FAILED", "details": "tool-call budget exhausted", "duration": 0, "approval_id": None, "action_id": "BUDGET", "progress_pct": s["forward_progress_pct"]}
        else:
            attempt = s["attempts"].get(step, 0)
            fn = self.tools.check_replication if step == S1 else self.tools.check_health
            res = fn(s["session_id"], s["drill_id"], s["scenario"], attempt, s["forward_progress_pct"])
            s["attempts"][step] = attempt + 1; s["tool_call_count"] += 1
            if step == S1: s["telemetry"] = self.tools.get_scenario_telemetry(s["scenario"], S1, attempt)
        self._apply_forward(s, step, res); self._narrate(s, res, live=False); return s
    def _run_approved(self, s, step, purpose):
        sid, did = s["session_id"], s["drill_id"]
        if s["tool_call_count"] >= MAX_TOOL_CALLS:
            self.store.revoke_token(s["approval_id"]); raise ControllerError("tool-call budget exhausted")
        if purpose == "ROLLBACK":
            return self.tools.rollback_step(sid, did, s["scenario"], step, s["approval_id"], s["forward_progress_pct"])
        return self.tools.execute_step(step, sid, did, s["scenario"], s["attempts"].get(step, 0), s["approval_id"], s["forward_progress_pct"])
    def _apply_forward(self, s, step, res):
        s["last_result"] = res; s["step_results"][step] = res; d = res["duration"]
        s["elapsed_rto"] += d; s["step_durations"][step] = s["step_durations"].get(step, 0) + d
        r = res["result"]
        self.store.audit(s["session_id"], s["drill_id"], "controller", "STEP_RESULT", step, r, res["details"])
        if r == "SUCCESS":
            s["steps_status"][step] = "COMPLETED"; s["retry_count"] = 0; s["current_step_index"] += 1
            if step == S6:
                s["outcome"] = OUTCOME_OK; s["notice_text"] = self._tpl("D", s, step); self._finish(s, OUTCOME_OK)
        elif r == "RETRY" and step == S1 and s["retry_count"] < MAX_RETRIES:
            s["retry_count"] += 1; s["elapsed_rto"] += RETRY_WAIT_SECONDS
            s["step_durations"][step] += RETRY_WAIT_SECONDS
            self.store.audit(s["session_id"], s["drill_id"], "controller", "RETRY_WAIT", step, "RETRY", f"{RETRY_WAIT_SECONDS}s wait, retry {s['retry_count']} of {MAX_RETRIES}")
        else:
            self._fail_step(s, step)
    def _fail_step(self, s, step):
        s["steps_status"][step] = "FAILED"
        self.store.audit(s["session_id"], s["drill_id"], "controller", "STEP_FAILED", step, "FAILED", "")
        if step == S6:
            if s["notice_attempts"] < 1:
                s["notice_attempts"] += 1; s["steps_status"][step] = "PENDING"; self._open_gate(s, S6, "EXECUTE")
            else:
                self._finish(s, OUTCOME_NOTICE_FAILED)
            return
        for x in STEP_ORDER:
            if s["steps_status"][x] == "PENDING": s["steps_status"][x] = "BLOCKED"
        done = [x for x in reversed(STEP_ORDER) if s["steps_status"][x] == "COMPLETED" and x in ROLLBACKABLE_STEPS]
        self._start_rollback(s, ([step] if step in ROLLBACKABLE_STEPS else []) + done)
    def _start_rollback(self, s, queue):
        if not queue: self._finish(s, OUTCOME_ABORTED_NO_MUTATION); return
        s.update(rollback_queue=list(queue), rollback_total=len(queue), phase="ROLLBACK")
        self._open_gate(s, queue[0], "ROLLBACK")
    def _apply_rollback(self, s, step, res):
        s["last_result"] = res; s["elapsed_rto"] += res["duration"]; s["rollback_durations"][step] = res["duration"]
        s["steps_status"][step] = "ROLLED_BACK"; s["rollback_queue"].remove(step); s["phase"] = "ROLLBACK"
        self.store.audit(s["session_id"], s["drill_id"], "controller", "ROLLBACK_RESULT", step, res["result"], res["details"])
        if res["result"] != "ROLLED_BACK": self._finish(s, OUTCOME_HALTED)
        elif s["rollback_queue"]: self._open_gate(s, s["rollback_queue"][0], "ROLLBACK")
        else: self._finish(s, OUTCOME_ROLLED_BACK)
    def _apply_correction(self, s, res):
        s["last_result"] = res; s["correction"] = False; s["elapsed_rto"] += res["duration"]
        s["step_durations"][S6] = s["step_durations"].get(S6, 0) + res["duration"]
        self.store.audit(s["session_id"], s["drill_id"], "controller", "CORRECTION_RESULT", S6, res["result"], res["details"])
        if res["result"] == "SUCCESS":
            s["steps_status"][S6] = "COMPLETED"; s["notice_corrected"] = True; s["outcome"] = OUTCOME_OK
            s["notice_text"] = self._tpl("D", s, S6); self._finish(s, OUTCOME_OK)
        else:
            self._finish(s, OUTCOME_NOTICE_FAILED)
    def _reject(self, s, approver, role):
        step, purpose = s["pending_action"], s["gate_purpose"]
        self.store.revoke_token(s["approval_id"])
        s["gate_wait_seconds"] += max(0.0, self.clock() - (s["gate_opened_at"] or self.clock()))
        s["approvals"].append({"step": step, "purpose": purpose, "approver": approver, "role": role, "decision": "REJECT", "at": self.clock()})
        self.store.audit(s["session_id"], s["drill_id"], f"approver:{approver}", "REJECTED", step, purpose, f"role={role}")
        was_correction = s["correction"]; s["correction"] = False; self._clear_gate(s)
        if was_correction or (purpose == "EXECUTE" and step == S6): self._finish(s, OUTCOME_NOTICE_FAILED)
        elif purpose == "ROLLBACK": self._finish(s, OUTCOME_HALTED)
        else:
            for x in STEP_ORDER:
                if s["steps_status"][x] == "PENDING": s["steps_status"][x] = "BLOCKED"
            self._start_rollback(s, [x for x in reversed(STEP_ORDER) if s["steps_status"][x] == "COMPLETED" and x in ROLLBACKABLE_STEPS])
        return s
    def _narrate(self, s, res, live):
        if not self.auto_narrate and not live: return
        ctx = {"store": self.store, "retriever": self.retriever, "tools": self.tools, "session_id": s["session_id"], "drill_id": s["drill_id"], "scenario": s["scenario"]}
        try: out = adk_runtime.agent_handoff(res, self.retriever.get_step(res["step"]), ctx=ctx, live=live)
        except Exception: out = {**adk_runtime.deterministic_handoff(res, self.retriever.get_step(res["step"])), "model_version": "deterministic"}
        s["operator_message"], s["coordinator_message"], s["model_version"] = out["operator_message"], out["coordinator_message"], out["model_version"]
        self.store.audit(s["session_id"], s["drill_id"], "coordinator", "NARRATION", res["step"], "OK", "", out["model_version"])
