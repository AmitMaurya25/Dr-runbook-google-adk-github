"""SQLiteStateStore (versioned state, tokens, hash-chained audit, chat) + deterministic operator tools."""
from __future__ import annotations
import copy, hashlib, json, secrets, sqlite3, time
from contextlib import contextmanager
from pathlib import Path
from .constants import (ALLOWED_DIAGNOSTICS, ALLOWED_STEPS, CONFIG_HASH, MUTATING_STEPS, ROLLBACKABLE_STEPS, ROLLBACK_DEFAULT,
                        S1, S2, S3, S4, S5, S6)
from .guardrails import redact
from .interfaces import ApprovalError, ConcurrencyError, TokenExpiredError
SCHEMA = """
CREATE TABLE IF NOT EXISTS drill_states(drill_id TEXT PRIMARY KEY, session_id TEXT, version INTEGER, scenario TEXT,
  outcome TEXT, state_json TEXT, created_at REAL, updated_at REAL);
CREATE TABLE IF NOT EXISTS approval_tokens(approval_id TEXT PRIMARY KEY, session_id TEXT, drill_id TEXT, step_id TEXT,
  purpose TEXT, status TEXT, created_at REAL, expires_at REAL, resolved_at REAL);
CREATE TABLE IF NOT EXISTS audit_events(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, session_id TEXT, drill_id TEXT,
  actor TEXT, action TEXT, step TEXT, status TEXT, details TEXT, model_version TEXT, config_hash TEXT, prev_hash TEXT, row_hash TEXT);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_events BEGIN SELECT RAISE(ABORT,'audit log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_events BEGIN SELECT RAISE(ABORT,'audit log is append-only'); END;
CREATE TABLE IF NOT EXISTS chat_turns(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, session_id TEXT, drill_id TEXT, role TEXT, text TEXT);
"""
def load_scenarios(path: str | Path | None = None) -> dict:
    p = Path(path or Path(__file__).resolve().parent.parent / "data" / "scenario_table.json")
    return json.loads(p.read_text(encoding="utf-8"))["scenarios"]
def _hash(*parts) -> str:
    return hashlib.sha256(json.dumps(list(parts)).encode()).hexdigest()
class SQLiteStateStore:
    def __init__(self, path="dr_orchestrator.db", clock=time.time):
        self.path, self.clock = str(path), clock
        with self._c() as c:
            c.execute("PRAGMA journal_mode=WAL"); c.executescript(SCHEMA)
    @contextmanager
    def _c(self):
        c = sqlite3.connect(self.path, timeout=10); c.row_factory = sqlite3.Row
        try:
            yield c; c.commit()
        finally:
            c.close()
    # ---- drill state (optimistic lock + session ownership)
    def create_drill(self, sid, did, state) -> dict:
        now = self.clock(); state = {k: v for k, v in state.items() if k != "_version"}
        with self._c() as c:
            c.execute("INSERT INTO drill_states VALUES(?,?,?,?,?,?,?,?)", (did, sid, 1, state["scenario"], None, json.dumps(state), now, now))
        return {**state, "_version": 1}
    def load(self, sid, did) -> dict:
        with self._c() as c:
            r = c.execute("SELECT * FROM drill_states WHERE drill_id=?", (did,)).fetchone()
        if r is None: raise KeyError(f"unknown drill {did}")
        if r["session_id"] != sid: raise PermissionError("drill belongs to another session")
        return {**json.loads(r["state_json"]), "_version": r["version"]}
    def save(self, sid, did, state) -> int:
        ver = state["_version"]; body = {k: v for k, v in state.items() if k != "_version"}
        with self._c() as c:
            n = c.execute("UPDATE drill_states SET version=?,outcome=?,state_json=?,updated_at=? WHERE drill_id=? AND session_id=? AND version=?",
                          (ver + 1, body.get("outcome"), json.dumps(body), self.clock(), did, sid, ver)).rowcount
        if n != 1:
            self.load(sid, did)  # raises PermissionError / KeyError when applicable
            raise ConcurrencyError("state changed since it was loaded; reload")
        return ver + 1
    def list_drills(self, sid) -> list[dict]:
        with self._c() as c:
            rows = c.execute("SELECT drill_id,scenario,outcome,updated_at FROM drill_states WHERE session_id=? ORDER BY updated_at DESC, rowid DESC", (sid,)).fetchall()
        return [{"id": r["drill_id"], "scenario": r["scenario"], "outcome": r["outcome"], "updated_at": r["updated_at"]} for r in rows]
    # ---- approval tokens
    def issue_token(self, sid, did, step, purpose, ttl) -> tuple[str, float]:
        aid = f"{'APR' if purpose == 'EXECUTE' else 'RBK'}-{secrets.token_hex(4).upper()}"; now = self.clock()
        with self._c() as c:
            c.execute("INSERT INTO approval_tokens VALUES(?,?,?,?,?,?,?,?,NULL)", (aid, sid, did, step, purpose, "ISSUED", now, now + ttl))
        return aid, now + ttl
    def token_status(self, aid) -> str | None:
        with self._c() as c:
            r = c.execute("SELECT status,expires_at FROM approval_tokens WHERE approval_id=?", (aid,)).fetchone()
            if r is None: return None
            if r["status"] == "ISSUED" and r["expires_at"] <= self.clock():
                c.execute("UPDATE approval_tokens SET status='EXPIRED',resolved_at=? WHERE approval_id=? AND status='ISSUED'", (self.clock(), aid))
                return "EXPIRED"
            return r["status"]
    def revoke_token(self, aid):
        with self._c() as c:
            c.execute("UPDATE approval_tokens SET status='REVOKED',resolved_at=? WHERE approval_id=? AND status IN ('ISSUED','EXPIRED')", (self.clock(), aid))
    def verify_and_consume(self, aid, sid, did, step, purpose) -> bool:
        now = self.clock()
        with self._c() as c:
            n = c.execute("UPDATE approval_tokens SET status='CONSUMED',resolved_at=? WHERE approval_id=? AND session_id=? AND drill_id=? "
                          "AND step_id=? AND purpose=? AND status='ISSUED' AND expires_at>?", (now, aid, sid, did, step, purpose, now)).rowcount
            if n == 1: return True
            r = c.execute("SELECT * FROM approval_tokens WHERE approval_id=?", (aid,)).fetchone()
        if r is None: raise ApprovalError("unknown approval token")
        if (r["session_id"], r["drill_id"], r["step_id"]) != (sid, did, step): raise ApprovalError("token is not bound to this action")
        if r["purpose"] != purpose: raise ApprovalError("token purpose mismatch")
        if self.token_status(aid) == "EXPIRED": raise TokenExpiredError("approval token expired")
        raise ApprovalError(f"token already {r['status'].lower()}")
    # ---- audit chain
    def audit(self, sid, did, actor, action, step="", status="", details="", model_version=""):
        with self._c() as c:
            p = c.execute("SELECT row_hash FROM audit_events WHERE session_id=? AND drill_id=? ORDER BY id DESC LIMIT 1", (sid, did)).fetchone()
            prev = p["row_hash"] if p else "GENESIS"; ts = self.clock(); details = redact(details)
            h = _hash(prev, ts, sid, did, actor, action, step, status, details, model_version, CONFIG_HASH)
            c.execute("INSERT INTO audit_events(ts,session_id,drill_id,actor,action,step,status,details,model_version,config_hash,prev_hash,row_hash) "
                      "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (ts, sid, did, actor, action, step, status, details, model_version, CONFIG_HASH, prev, h))
    def events(self, sid, did) -> list[dict]:
        with self._c() as c:
            return [dict(r) for r in c.execute("SELECT * FROM audit_events WHERE session_id=? AND drill_id=? ORDER BY id", (sid, did))]
    def verify_chain(self, sid, did) -> bool:
        prev = "GENESIS"
        for e in self.events(sid, did):
            if e["prev_hash"] != prev or e["row_hash"] != _hash(prev, e["ts"], e["session_id"], e["drill_id"], e["actor"], e["action"],
                                                              e["step"], e["status"], e["details"], e["model_version"], e["config_hash"]):
                return False
            prev = e["row_hash"]
        return True
    def export_audit_head(self, sid, did) -> dict:
        ev = self.events(sid, did)
        return {"head_hash": ev[-1]["row_hash"] if ev else "GENESIS", "count": len(ev)}
    def verify_against_anchor(self, sid, did, head_hash) -> bool:
        return self.verify_chain(sid, did) and any(e["row_hash"] == head_hash.strip() for e in self.events(sid, did))
    # ---- persistent console chat
    def add_chat_turn(self, sid, did, role, text):
        with self._c() as c:
            c.execute("INSERT INTO chat_turns(ts,session_id,drill_id,role,text) VALUES(?,?,?,?,?)", (self.clock(), sid, did, role, redact(text)))
    def get_chat(self, sid, did) -> list[dict]:
        with self._c() as c:
            return [dict(r) for r in c.execute("SELECT role,text FROM chat_turns WHERE session_id=? AND drill_id=? ORDER BY id", (sid, did))]
class OperatorTools:
    """Deterministic simulated tools. Mutating ones consume the approval token before doing anything."""
    def __init__(self, store: SQLiteStateStore, scenarios: dict):
        self.store, self.scenarios = store, scenarios
    def _entry(self, scenario, step, attempt=0) -> dict:
        if scenario not in self.scenarios: raise ValueError("unknown scenario")
        if step not in ALLOWED_STEPS: raise ValueError("step not allowed")
        e = self.scenarios[scenario]["steps"][step]
        return copy.deepcopy(e[min(attempt, len(e) - 1)] if isinstance(e, list) else e)
    def _out(self, step, e, approval_id=None, progress=0.0) -> dict:
        return {"action_id": f"ACT-{secrets.token_hex(4).upper()}", "step": step, "result": e["result"], "details": e["details"],
                "duration": int(e["duration"]), "approval_id": approval_id, "progress_pct": progress}
    def get_scenario_telemetry(self, scenario, step=S1, attempt=0) -> dict:
        return self._entry(scenario, step, attempt).get("telemetry") or {"lag_seconds": None, "wal_state": "UNKNOWN"}
    def check_replication(self, sid, did, scenario, attempt=0, progress=0.0) -> dict:
        r = self._out(S1, self._entry(scenario, S1, attempt), None, progress)
        self.store.audit(sid, did, "tool", "TOOL_CHECK_REPLICATION", S1, r["result"], r["details"]); return r
    def check_health(self, sid, did, scenario, attempt=0, progress=0.0) -> dict:
        r = self._out(S5, self._entry(scenario, S5, attempt), None, progress)
        self.store.audit(sid, did, "tool", "TOOL_CHECK_HEALTH", S5, r["result"], r["details"]); return r
    def run_readonly_diagnostic(self, kind, sid, did, scenario, attempt=0) -> dict:
        if kind not in ALLOWED_DIAGNOSTICS: raise ValueError("diagnostic not allowed")
        return (self.check_replication if kind == "replication" else self.check_health)(sid, did, scenario, attempt)
    def _mutate(self, step, name, sid, did, scenario, attempt, approval_id, progress) -> dict:
        if step not in MUTATING_STEPS: raise ValueError("not a mutating step")
        self.store.verify_and_consume(approval_id, sid, did, step, "EXECUTE")
        r = self._out(step, self._entry(scenario, step, attempt), approval_id, progress)
        self.store.audit(sid, did, "tool", name, step, r["result"], r["details"]); return r
    def failover_database(self, sid, did, scenario, attempt, approval_id, progress=0.0): return self._mutate(S2, "TOOL_FAILOVER_DATABASE", sid, did, scenario, attempt, approval_id, progress)
    def repoint_application(self, sid, did, scenario, attempt, approval_id, progress=0.0): return self._mutate(S3, "TOOL_REPOINT_APPLICATION", sid, did, scenario, attempt, approval_id, progress)
    def update_dns(self, sid, did, scenario, attempt, approval_id, progress=0.0): return self._mutate(S4, "TOOL_UPDATE_DNS", sid, did, scenario, attempt, approval_id, progress)
    def send_stakeholder_notice(self, sid, did, scenario, attempt, approval_id, progress=0.0): return self._mutate(S6, "TOOL_SEND_STAKEHOLDER_NOTICE", sid, did, scenario, attempt, approval_id, progress)
    def execute_step(self, step, sid, did, scenario, attempt, approval_id, progress=0.0) -> dict:
        fn = {S2: self.failover_database, S3: self.repoint_application, S4: self.update_dns, S6: self.send_stakeholder_notice}.get(step)
        if fn is None: raise ValueError("step has no mutating tool")
        return fn(sid, did, scenario, attempt, approval_id, progress)
    def rollback_step(self, sid, did, scenario, step, approval_id, progress=0.0) -> dict:
        if step not in ROLLBACKABLE_STEPS: raise ValueError("step cannot be rolled back")
        self.store.verify_and_consume(approval_id, sid, did, step, "ROLLBACK")
        if scenario not in self.scenarios: raise ValueError("unknown scenario")
        e = copy.deepcopy(self.scenarios[scenario].get("rollback", {}).get(step) or ROLLBACK_DEFAULT)
        r = self._out(step, e, approval_id, progress)
        self.store.audit(sid, did, "tool", "TOOL_ROLLBACK_STEP", step, r["result"], r["details"]); return r
