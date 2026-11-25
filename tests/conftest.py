import copy, os, pytest
os.environ["DEMO_OFFLINE_FALLBACK"] = "true"
from backend.adk_controller import ADKDrillController
from backend.constants import CONFIRM_PHRASES, ROLLBACK_CONFIRM, S1, S5, S6, STEP_OWNERS
from backend.tools import load_scenarios
SID = "a" * 32
class Clock:
    def __init__(self): self.t = 1_000_000.0
    def __call__(self): return self.t
    def advance(self, s): self.t += s
def _fail(e): return {"result": "FAILED", "details": e, "duration": 20}
def test_scenarios():
    base = load_scenarios(); out = copy.deepcopy(base)
    n = base["normal_drill"]
    x = copy.deepcopy(n); x["steps"][S1] = [{"result": "RETRY", "details": "lag high", "duration": 40, "telemetry": {"lag_seconds": 22.0, "wal_state": "STREAMING"}}]; out["retry_exhaust"] = x
    x = copy.deepcopy(n); x["steps"][S5] = {"result": "FAILED", "details": "canary 503", "duration": 95}; out["canary_fail"] = x
    x = copy.deepcopy(n); x["steps"][S6] = [_fail("smtp down"), _fail("smtp down"), n["steps"][S6]]; out["notice_fail_then_ok"] = x
    x = copy.deepcopy(n); x["steps"][S6] = [_fail("smtp down")]; out["notice_fail"] = x
    return out
@pytest.fixture
def clock(): return Clock()
@pytest.fixture
def db(tmp_path): return str(tmp_path / "t.db")
@pytest.fixture
def ctl(db, clock): return ADKDrillController(db, clock=clock, scenarios=test_scenarios())
def approve(c, s, name="Asha", role=None, decision="APPROVE", confirm=None):
    step = s["pending_action"]
    conf = confirm if confirm is not None else (ROLLBACK_CONFIRM if s["gate_purpose"] == "ROLLBACK" else CONFIRM_PHRASES.get(step, ""))
    return c.submit_decision(SID, s["drill_id"], decision, s["approval_id"], name, role or STEP_OWNERS[step], conf)
def drive(c, s, stop=None):
    """Run to each gate and approve it, until DONE or stop(state) is true at a gate."""
    while s["phase"] != "DONE":
        s = c.run_to_gate(SID, s["drill_id"])
        if s["phase"] == "WAITING_APPROVAL":
            if stop and stop(s): return s
            s = approve(c, s)
    return s
