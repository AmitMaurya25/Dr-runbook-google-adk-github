"""ADK Runner adapter, worker-thread runner, Operator -> Coordinator handoff, fallback chain (plan 9.2)."""
from __future__ import annotations
import asyncio, json, os
from concurrent.futures import ThreadPoolExecutor
from . import llm
from .constants import LABELS
from .guardrails import numbers_consistent
from .adk_agents import build_agents
def _model() -> str: return os.getenv("FAST_MODEL", "gemini-2.5-flash")
def is_offline() -> bool:
    if os.getenv("DEMO_OFFLINE_FALLBACK", "true").lower() == "true": return True
    key = os.getenv("GOOGLE_API_KEY", "").strip()
    return not key or "replace" in key.lower()
def mode_label() -> str:
    return "Offline (deterministic text)" if is_offline() else f"Online (Google ADK + {_model()})"
def run_blocking(coro, timeout: float = 20):
    """Run a coroutine on a dedicated worker thread with its own event loop, so Streamlit's loop is never touched."""
    ex = ThreadPoolExecutor(max_workers=1)
    try:
        return ex.submit(asyncio.run, coro).result(timeout=timeout)
    finally:
        ex.shutdown(wait=False)
async def _run_agent(agent, prompt: str, session_id: str) -> str:
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types
    svc, app = InMemorySessionService(), "dr_runbook_agent"
    await svc.create_session(app_name=app, user_id="drill", session_id=session_id)
    runner = Runner(agent=agent, app_name=app, session_service=svc)
    msg, text = types.Content(role="user", parts=[types.Part(text=prompt)]), ""
    async for ev in runner.run_async(user_id="drill", session_id=session_id, new_message=msg):
        if ev.is_final_response() and ev.content and ev.content.parts:
            text = "".join(p.text or "" for p in ev.content.parts)
    return text.strip()
def _ask_agent(agent, prompt: str, session_id: str) -> str:
    return run_blocking(_run_agent(agent, prompt, session_id))
def narrate_step(agent, prompt: str, session_id: str, fallback: str, facts: str = "") -> tuple[str, str]:
    """(text, model_version). Offline -> deterministic; ADK error -> llm wrapper; final failure -> cached deterministic."""
    model = _model()
    if is_offline(): return fallback, f"{model}-adk-offline"
    try:
        text = _ask_agent(agent, prompt, session_id)
        if not text: raise RuntimeError("empty ADK response")
    except Exception:
        try: text = llm.invoke_llm_with_backoff(prompt)
        except Exception: return fallback, f"{model}-fallback-cached"
    if not numbers_consistent(text, facts): return fallback, f"{model}-numeric-guard"
    return text, model
def deterministic_handoff(result: dict, runbook_step: str) -> dict:
    label = LABELS.get(result["step"], result["step"])
    return {"operator_message": f"Operator: {label} returned {result['result']} in {result['duration']} s. {result['details']}",
            "coordinator_message": f"Coordinator: {result['step']} outcome {result['result']}. Runbook: {runbook_step.split('. ')[0]}."}
def agent_handoff(verified_result: dict, runbook_step: str, ctx: dict | None = None, live: bool = True) -> dict:
    """Operator interprets the verified JSON, then hands its explanation to the Coordinator."""
    det = deterministic_handoff(verified_result, runbook_step)
    if not live or ctx is None: return {**det, "model_version": "deterministic"}
    if is_offline(): return {**det, "model_version": f"{_model()}-adk-offline"}
    facts, sid = json.dumps(verified_result) + runbook_step, f"{ctx['session_id']}-{ctx['drill_id']}"
    try: agents = build_agents(ctx)
    except Exception: return {**det, "model_version": f"{_model()}-fallback-cached"}
    op, t1 = narrate_step(agents.operator, f"Verified tool result (JSON): {json.dumps(verified_result)}\nInterpret it for the coordinator.",
                          sid + "-op", det["operator_message"], facts)
    co, t2 = narrate_step(agents.coordinator, f"Operator says: {op}\nRunbook: {runbook_step}\nExplain the outcome and next step to the human.",
                          sid + "-co", det["coordinator_message"], facts + op)
    return {"operator_message": op, "coordinator_message": co, "model_version": t2 if t1 == t2 else f"{t1}|{t2}"}
