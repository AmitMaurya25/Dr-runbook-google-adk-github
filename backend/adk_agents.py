"""Two Google ADK LlmAgents with session-bound, READ-ONLY tools. No mutating tool is registered on any agent."""
from __future__ import annotations
from types import SimpleNamespace
from .constants import ALLOWED_HEALTH_TARGETS, ALLOWED_REPL_GROUPS, ALLOWED_STEPS, S1, S5
COORDINATOR_INSTRUCTION = ("You are drill_coordinator for a SIMULATED disaster-recovery drill. Explain runbook-grounded next steps and outcomes in "
    "2-3 plain sentences, citing the step id. You can read the runbook and status only. Never claim that you approved, executed or changed anything; "
    "only a human approver and the deterministic controller can. Use only numbers present in the verified facts you are given.")
OPERATOR_INSTRUCTION = ("You are simulated_failover_operator for a SIMULATED drill. You have NO infrastructure access. Interpret the verified tool "
    "result you are given in 2 sentences for the coordinator. You may call the read-only diagnostics. Never state numbers that are not in the facts.")
def build_session_tools(store, retriever, tools, session_id, drill_id, scenario) -> dict:
    """Closures: identity, scenario and attempt are bound here, never supplied by the model."""
    def _attempt(step):
        return store.load(session_id, drill_id)["attempts"].get(step, 0)
    def get_runbook_step(step_id: str) -> dict:
        """Return the runbook text for one step id such as STEP_02_FAILOVER_DB."""
        return {"step_id": step_id, "text": retriever.get_step(step_id)} if step_id in ALLOWED_STEPS else {"error": "unknown step id"}
    def get_drill_status() -> dict:
        """Return the current drill phase, outcome, progress and simulated RTO."""
        s = store.load(session_id, drill_id)
        return {k: s[k] for k in ("phase", "outcome", "pending_action", "forward_progress_pct", "elapsed_rto")}
    def get_recent_events(limit: int = 5) -> list:
        """Return the most recent audit events (action, step, status)."""
        ev = store.events(session_id, drill_id)[-max(1, min(int(limit), 10)):]
        return [{k: e[k] for k in ("action", "step", "status")} for e in ev]
    def adk_check_replication(group: str) -> dict:
        """Read-only replication diagnostic for an allow-listed replication group."""
        if group not in ALLOWED_REPL_GROUPS: return {"error": "group not allowed"}
        return tools._out(S1, tools._entry(scenario, S1, _attempt(S1)))
    def adk_check_health(target: str) -> dict:
        """Read-only health diagnostic for an allow-listed target."""
        if target not in ALLOWED_HEALTH_TARGETS: return {"error": "target not allowed"}
        return tools._out(S5, tools._entry(scenario, S5, _attempt(S5)))
    return {"coordinator": [get_runbook_step, get_drill_status, get_recent_events],
            "operator": [adk_check_replication, adk_check_health]}
def build_agents(ctx: dict, model: str | None = None) -> SimpleNamespace:
    import os
    from google.adk.agents import LlmAgent
    model = model or os.getenv("FAST_MODEL", "gemini-2.5-flash")
    t = build_session_tools(ctx["store"], ctx["retriever"], ctx["tools"], ctx["session_id"], ctx["drill_id"], ctx["scenario"])
    return SimpleNamespace(
        coordinator=LlmAgent(name="drill_coordinator", model=model, description="Explains runbook next steps and outcomes.",
                             instruction=COORDINATOR_INSTRUCTION, tools=t["coordinator"]),
        operator=LlmAgent(name="simulated_failover_operator", model=model, description="Interprets verified tool results.",
                          instruction=OPERATOR_INSTRUCTION, tools=t["operator"]))
