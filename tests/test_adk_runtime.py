import asyncio, inspect
from types import SimpleNamespace
import pytest
from backend import adk_runtime as rt, llm
from backend.adk_agents import build_session_tools
RES = {"step": "STEP_02_FAILOVER_DB", "result": "SUCCESS", "details": "Standby promoted.", "duration": 165, "approval_id": None, "action_id": "A", "progress_pct": 0}
CTX = {"session_id": "s", "drill_id": "d"}
def _online(monkeypatch):
    monkeypatch.setenv("DEMO_OFFLINE_FALLBACK", "false"); monkeypatch.setenv("GOOGLE_API_KEY", "AIza" + "B" * 35)
    monkeypatch.setattr(rt, "build_agents", lambda ctx: SimpleNamespace(operator=None, coordinator=None))
def test_20_adk_fallbacks_and_thread_runner(monkeypatch):
    out = rt.agent_handoff(RES, "Promote the standby. Next.", CTX); assert out["model_version"].endswith("-adk-offline") and "165" in out["operator_message"]
    _online(monkeypatch)
    def boom(*a, **k): raise RuntimeError("adk down")
    monkeypatch.setattr(rt, "_ask_agent", boom); monkeypatch.setattr(llm, "invoke_llm_with_backoff", boom)
    assert rt.agent_handoff(RES, "Promote the standby.", CTX)["model_version"].endswith("-fallback-cached")
    monkeypatch.setattr(llm, "invoke_llm_with_backoff", lambda p, **k: "The failover took 165 seconds.")      # ADK fails, llm wrapper works
    assert rt.agent_handoff(RES, "Promote the standby.", CTX)["operator_message"] == "The failover took 165 seconds."
    monkeypatch.setattr(llm, "invoke_llm_with_backoff", lambda p, **k: "It took 999 seconds.")                # invented number is discarded
    assert "numeric-guard" in rt.agent_handoff(RES, "Promote the standby.", CTX)["model_version"]
    monkeypatch.setattr(rt, "_ask_agent", lambda a, p, s: "Standby promoted in 165 s.")
    assert rt.agent_handoff(RES, "Promote the standby.", CTX)["coordinator_message"].startswith("Standby")
    async def main():
        async def work(): await asyncio.sleep(0); return 42
        return rt.run_blocking(work())                      # runs inside an already-running loop
    assert asyncio.run(main()) == 42
def test_21_tool_closures_expose_no_identity_params(ctl):
    s = ctl.start_drill("a" * 32, "normal_drill")
    t = build_session_tools(ctl.store, ctl.retriever, ctl.tools, "a" * 32, s["drill_id"], "normal_drill")
    banned = {"session_id", "drill_id", "scenario", "attempt", "approval_id", "approval", "token"}
    names = set()
    for group in t.values():
        for fn in group:
            names.add(fn.__name__); assert not banned & set(inspect.signature(fn).parameters), fn.__name__
    assert not any(n in names for n in ("failover_database", "repoint_application", "update_dns", "send_stakeholder_notice", "rollback_step"))
    assert t["operator"][0]("not-a-group") == {"error": "group not allowed"} and t["operator"][0]("pg-payments-dr")["result"] == "SUCCESS"
def test_agents_build_with_real_adk(ctl):
    from backend.adk_agents import build_agents
    s = ctl.start_drill("a" * 32, "normal_drill")
    a = build_agents({"store": ctl.store, "retriever": ctl.retriever, "tools": ctl.tools, "session_id": "a" * 32, "drill_id": s["drill_id"], "scenario": "normal_drill"})
    assert (a.coordinator.name, a.operator.name) == ("drill_coordinator", "simulated_failover_operator")
    assert not any(n in {x.__name__ for x in a.operator.tools} for n in ("failover_database", "rollback_step"))
