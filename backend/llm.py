"""Resilient Gemini wrapper: the fallback path used when the ADK Runner call fails (plan 9.2)."""
from __future__ import annotations
import os, time
def invoke_llm_with_backoff(prompt: str, model: str | None = None, retries: int = 3, sleeper=time.sleep) -> str:
    from google import genai
    client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
    delay, last = 1.0, None
    for _ in range(retries):
        try:
            return (client.models.generate_content(model=model or os.getenv("FAST_MODEL", "gemini-2.5-flash"), contents=prompt).text or "").strip()
        except Exception as e:  # retry only on rate-limit / overload
            last = e
            if not any(c in str(e) for c in ("429", "503")): raise
            sleeper(delay); delay *= 2
    raise last
