"""DR Runbook Agent: Streamlit workbench (use case 22, Google ADK, SIMULATION ONLY).
The UI never executes anything itself: it calls the controller, the only component that runs tools."""
from __future__ import annotations
import json
from pathlib import Path
import streamlit as st
from dotenv import load_dotenv
load_dotenv()
from backend import ui_html as ui
from backend.adk_controller import ADKDrillController
from backend.adk_runtime import mode_label
from backend.constants import (ALLOWED_SCENARIOS, APPROVER_ROLES, CONFIRM_PHRASES, MAX_TOKEN_REISSUES, OUTCOME_NOTICE_FAILED, ROLLBACK_CONFIRM,
                               STEP_OWNERS, STEP_ORDER, TARGET_RTO_SECONDS)
from backend.guardrails import BLOCK_MESSAGE
from backend.interfaces import ApprovalError, ConcurrencyError, ControllerError, TokenExpiredError
from backend.monitoring import format_mmss, nodes, snapshot, target_vs_actual, tier_totals, token_ttl_remaining
from backend.pipeline_svg import pipeline_svg, pipeline_text
from backend.report import build_report, markdown
from backend.session import is_valid_code, new_session_id, normalise_code, resume
from backend.status_console import SUGGESTIONS, answer
NAV = ["Runbook", "Monitoring", "Audit", "Console", "Report"]
st.set_page_config(page_title="DR Runbook Agent", page_icon="🛡️", layout="centered", initial_sidebar_state="collapsed")
st.html(f"<style>{(Path(__file__).parent / 'assets' / 'style.css').read_text(encoding='utf-8')}</style>")
@st.cache_resource
def get_controller() -> ADKDrillController: return ADKDrillController()
ctl, ss = get_controller(), st.session_state
if "sid" not in ss:
    code = st.query_params.get("session")
    ss.sid = normalise_code(code) if code and is_valid_code(code) and ctl.store.list_drills(normalise_code(code)) else new_session_id()
    d = ctl.store.list_drills(ss.sid); ss.did = d[0]["id"] if d else None
sid = ss.sid
def act(fn, *a, **k) -> bool:
    try:
        r = fn(*a, **k)
        if fn.__name__ in ("start_drill", "restart_drill"): ss.did = r["drill_id"]
    except (ApprovalError, TokenExpiredError, ControllerError, ConcurrencyError, PermissionError, KeyError, ValueError) as e:
        ss["flash"] = ("error", str(e) or e.__class__.__name__); return False
    return True
def state(): return ctl.get_state(sid, ss.did) if ss.get("did") else None
# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.subheader("Drill")
    scen = st.selectbox("Scenario", ALLOWED_SCENARIOS, key="scenario")
    info = ctl.scenarios[scen]; st.caption(f"{info['description']} Expected simulated RTO {info['expected_rto']} s.")
    if st.button("Start drill", type="primary", width="stretch"): act(ctl.start_drill, sid, scen); st.rerun()
    drills = ctl.store.list_drills(sid)
    if drills:
        ids = [d["id"] for d in drills]
        pick = st.selectbox("Drill history", ids, index=ids.index(ss.did) if ss.get("did") in ids else 0,
                            format_func=lambda i: next(f"{i[:4]} · {d['scenario']} · {d['outcome'] or 'in progress'}" for d in drills if d["id"] == i))
        if pick != ss.get("did"): ss.did = pick; st.rerun()
        if st.button("Restart same scenario", width="stretch") and ss.get("did"): act(ctl.restart_drill, sid, ss.did); st.rerun()
    st.subheader("Approver (simulated identity)")
    ss.approver = st.text_input("Name", value=ss.get("approver", ""), placeholder="e.g. Asha Rao")
    ss.role = st.selectbox("Role", APPROVER_ROLES, key="role_pick")
    st.caption("Not authentication: the name and role are recorded in the audit log only.")
    st.subheader("Session")
    st.code(sid, language=None); code = st.text_input("Resume session code")
    if st.button("Resume session", width="stretch"):
        try: ss.sid, dr = resume(ctl.store, code); ss.did = dr[0]["id"]; st.rerun()
        except ValueError as e: st.error(str(e))
    st.caption(f"ADK mode: {mode_label()} · token TTL {ctl.ttl}s · four-eyes rollback: {'on' if ctl.four_eyes else 'off'}")
s = state()
if f := ss.pop("flash", None): st.html(f'<div class="dr-flash-{"error" if f[0] == "error" else "ok"}">{ui.esc(f[1])}</div>')
nav = st.session_state.get("nav") or "Runbook"
# ---------------------------------------------------------------- header
with st.container(key="panel"):
    st.html(ui.title_row("DR Runbook Agent", "Simulation only") + ui.caption(s["scenario"] if s else scen, s["drill_id"] if s else None))
    st.html(ui.metrics(s["forward_progress_pct"] if s else 0, s["elapsed_rto"] if s else 0))
    if s is None:
        with st.container(key="card_pipeline"): st.html(ui.pipeline_rows(None, STEP_ORDER))
        st.info("Pick a scenario in the sidebar and click Start drill.")
    elif nav == "Runbook":
        with st.container(key="card_pipeline"): st.html(ui.pipeline_rows(s, STEP_ORDER))
        if s["phase"] == "DONE":
            tone = st.success if s["outcome"] == "COMPLETED_SUCCESSFULLY" else st.warning
            tone(f"Drill finished: {s['outcome']} · simulated RTO {s['elapsed_rto']} s of {TARGET_RTO_SECONDS} s")
            if s["outcome"] == OUTCOME_NOTICE_FAILED and st.button("Send correction notice (needs new approval)", width="stretch"):
                act(ctl.request_correction_notice, sid, s["drill_id"]); st.rerun()
        elif s["phase"] != "WAITING_APPROVAL":
            c1, c2 = st.columns(2)
            if c1.button("Run to next gate", type="primary", width="stretch"): act(ctl.run_to_gate, sid, s["drill_id"]); st.rerun()
            if c2.button("Advance one step", width="stretch"): act(ctl.advance_drill, sid, s["drill_id"]); st.rerun()
        if s["phase"] == "WAITING_APPROVAL":
            expired, step = s["gate_status"] == "EXPIRED", s["pending_action"]
            with st.container(key="card_expired" if expired else "card_approval"):
                st.html(ui.approval_card(s))
                @st.fragment(run_every=1)
                def ttl():
                    cur = ctl.get_state(sid, s["drill_id"]); t = token_ttl_remaining(cur)
                    st.html(f'<div class="dr-ttl">{"Token expired" if cur["gate_status"] == "EXPIRED" else "Expires in " + format_mmss(t or 0)}</div>')
                ttl()
                with st.expander("Communication draft"): st.text_area("Editable preview (not sent anywhere)", s["comms_draft"], height=110, key=f"comms_{s['approval_id']}")
                need = ROLLBACK_CONFIRM if s["gate_purpose"] == "ROLLBACK" else CONFIRM_PHRASES.get(step, "")
                typed = st.text_input(f"Type {need} to confirm", key=f"conf_{s['approval_id']}") if need else ""
                ok = bool(ss.approver.strip()) and (not need or typed.strip().upper() == need)
                if not ss.approver.strip(): st.caption("Enter the approver name in the sidebar.")
                if STEP_OWNERS[step] != ss.role and ss.role != "Incident Commander": st.caption(f"This step is owned by the {STEP_OWNERS[step]}; select that role in the sidebar.")
                b1, b2 = st.columns(2)
                if expired:
                    left = MAX_TOKEN_REISSUES - s["reissue_count"]
                    if b1.button(f"Re-issue token ({left} left)", type="primary", width="stretch", disabled=not ss.approver.strip()):
                        act(ctl.reissue_token, sid, s["drill_id"], ss.approver, ss.role); st.rerun()
                elif b1.button("Approve", type="primary", width="stretch", disabled=not ok):
                    if act(ctl.submit_decision, sid, s["drill_id"], "APPROVE", s["approval_id"], ss.approver, ss.role, typed): ss["flash"] = ("ok", "Decision recorded.")
                    st.rerun()
                if b2.button("Reject", width="stretch", disabled=not ss.approver.strip()):
                    act(ctl.submit_decision, sid, s["drill_id"], "REJECT", s["approval_id"], ss.approver, ss.role); st.rerun()
        with st.container(key="card_agents"):
            st.html('<div class="dr-card-title">Google ADK agents</div>')
            if s["operator_message"]:
                st.html(f'<div class="dr-msg">{ui.esc(s["operator_message"])}</div><div class="dr-msg">{ui.esc(s["coordinator_message"])}</div>'
                        f'<div class="dr-caption">model: {ui.esc(s["model_version"])}</div>')
            else: st.caption("Agent explanations appear after the first action.")
            if s["last_result"] and st.button("Explain with Google ADK agents", width="stretch"): act(ctl.explain_last, sid, s["drill_id"]); st.rerun()
    elif nav == "Monitoring":
        m = snapshot(s); a, b = st.columns(2)
        a.metric("Forward progress", f"{m['forward_progress_pct']:.0f}%"); b.metric("Rollback progress", f"{m['rollback_progress_pct']:.0f}%")
        a.metric("Simulated RTO", f"{m['elapsed_rto']} / {m['rto_target']} s"); b.metric("Human wait (real time)", f"{m['human_wait_seconds']:.0f} s")
        a.metric("Tool calls", m["tool_calls"]); b.metric("Retries", m["retry_count"])
        a.metric("Replication lag", "n/a" if m["lag_seconds"] is None else f"{m['lag_seconds']} s"); b.metric("WAL state", m["wal_state"])
        st.html(pipeline_svg(s, ctl.store.export_audit_head(sid, s["drill_id"])["count"]))
        with st.expander("Text version of the pipeline"): st.write("\n".join(f"- {x}" for x in pipeline_text(s)))
        st.bar_chart({"Target (s)": {r["step"]: r["target"] for r in target_vs_actual(s)}, "Actual (s)": {r["step"]: r["actual"] for r in target_vs_actual(s)}})
        st.table([{"Tier": k, "Seconds": v} for k, v in tier_totals(s).items()])
    elif nav == "Audit":
        ev = ctl.store.events(sid, s["drill_id"]); head = ctl.store.export_audit_head(sid, s["drill_id"])
        actors = sorted({e["actor"] for e in ev}); sel = st.multiselect("Filter by actor", actors)
        rows = [{"time": e["ts"], "actor": e["actor"], "action": e["action"], "step": e["step"], "status": e["status"], "details": e["details"]} for e in ev if not sel or e["actor"] in sel]
        st.dataframe(rows, hide_index=True)
        ok = ctl.store.verify_chain(sid, s["drill_id"]); (st.success if ok else st.error)("Audit chain verified" if ok else "Audit chain BROKEN")
        st.text_input("Chain head (copy to a separate system)", head["head_hash"], disabled=True); st.caption(f"{head['count']} events. Tamper evidence needs an external anchor.")
        anchor = st.text_input("Verify against a stored head hash")
        if anchor: (st.success if ctl.store.verify_against_anchor(sid, s["drill_id"], anchor) else st.error)("Anchor matches" if ctl.store.verify_against_anchor(sid, s["drill_id"], anchor) else "Anchor does not match")
        st.download_button("Download audit JSON", json.dumps(ev, indent=1), f"audit_{s['drill_id'][:4]}.json", "application/json")
    elif nav == "Console":
        for t in ctl.store.get_chat(sid, s["drill_id"]): st.chat_message(t["role"]).write(t["text"])
        chip = st.pills("Suggested", SUGGESTIONS, label_visibility="collapsed", key="chip")
        q = st.chat_input("Ask about RTO, replication, progress, approvals, next step") or (chip if chip and chip != ss.get("last_chip") else None)
        ss["last_chip"] = chip
        if q:
            try: reply = answer(q, ctl.get_state(sid, s["drill_id"]))
            except ValueError: reply = BLOCK_MESSAGE
            ctl.store.add_chat_turn(sid, s["drill_id"], "user", q); ctl.store.add_chat_turn(sid, s["drill_id"], "assistant", reply); st.rerun()
    elif nav == "Report":
        r = build_report(s, ctl.store); st.markdown(markdown(r))
        c1, c2 = st.columns(2)
        c1.download_button("Markdown", markdown(r), f"report_{s['drill_id'][:4]}.md", width="stretch")
        c2.download_button("JSON", json.dumps(r, indent=1), f"report_{s['drill_id'][:4]}.json", width="stretch")
    st.pills("Navigate", NAV, default="Runbook", key="nav", label_visibility="collapsed")
