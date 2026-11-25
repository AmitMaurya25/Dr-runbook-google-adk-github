# DR Runbook Agent (use case 22): Google ADK, simulation only
Two ADK agents (`drill_coordinator`, `simulated_failover_operator`) around a deterministic controller with single-use approval tokens,
a hash-chained audit log, a read-only status console and a Streamlit workbench. **No real infrastructure is touched.**

```bash
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                               # offline by default (deterministic text)
python -m pytest                                   # 30 tests, no API key needed
streamlit run app.py
```
Live agents: in `.env` set `DEMO_OFFLINE_FALLBACK=false` and a real `GOOGLE_API_KEY`, then press **Explain with Google ADK agents**.
Auto-narration after each action is deterministic by design (fast, free); the button runs the live Operator -> Coordinator handoff.

Demo path: start `app_repoint_failure_drill`, set approver name + the owning role in the sidebar, approve, then approve the two rollbacks.
Simulated identity is recorded in the audit log; it is **not** authentication. Anchor the audit head hash outside the database for strong tamper evidence.
Layout: `backend/` (controller, tools/store, ADK agents + runtime, guardrails, monitoring, report), `app.py`, `data/`, `tests/`, `docs/`.
