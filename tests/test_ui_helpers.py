import os, pytest
from backend import ui_html as ui
from backend.pipeline_svg import pipeline_svg, pipeline_text
from backend.session import is_valid_code, new_session_id, resume
from backend.monitoring import format_mmss, nodes, target_vs_actual
from tests.conftest import SID, drive
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOSTILE = '<script>alert(1)</script>"\'><img src=x onerror=1>'
def test_19_hostile_strings_are_escaped(ctl):
    s = ctl.run_to_gate(SID, ctl.start_drill(SID)["drill_id"])
    s["last_result"] = {"step": HOSTILE}; s["scenario"] = HOSTILE
    html = pipeline_svg(s, audit_count=HOSTILE) + ui.caption(HOSTILE, HOSTILE) + ui.title_row(HOSTILE, HOSTILE)
    assert "<script" not in html and "<img" not in html and "onerror=1>" not in html and "&lt;script&gt;" in html
def test_pipeline_text_and_icons_not_colour_only(ctl):
    s = ctl.run_to_gate(SID, ctl.start_drill(SID)["drill_id"]); txt = pipeline_text(s)
    assert txt[0].endswith("Completed") and txt[1].endswith("Awaiting approval") and len(txt) == 6
    assert "Awaiting approval" in ui.pipeline_rows(s, [n["step"] for n in nodes(s)]) and "<svg" in ui.approval_card(s)
def test_session_recovery_and_formatting(ctl):
    sid = new_session_id(); assert is_valid_code(sid) and is_valid_code(" " + sid.upper() + " ") and not is_valid_code("abc")
    with pytest.raises(ValueError): resume(ctl.store, sid)
    ctl.start_drill(sid); assert resume(ctl.store, sid.upper())[0] == sid and format_mmss(125) == "02:05"
def test_chat_persists_and_redacts(ctl):
    did = ctl.start_drill(SID)["drill_id"]
    ctl.store.add_chat_turn(SID, did, "user", "my key AIza" + "C" * 35); ctl.store.add_chat_turn(SID, did, "assistant", "ok")
    c = ctl.store.get_chat(SID, did); assert [t["role"] for t in c] == ["user", "assistant"] and "AIza" not in c[0]["text"]
def test_target_vs_actual_and_history(ctl):
    s = drive(ctl, ctl.start_drill(SID, "replication_lag_retry_drill")); rows = target_vs_actual(s)
    assert rows[0] == {"step": "Verify replication", "target": 60, "actual": 125} and ctl.store.list_drills(SID)[0]["outcome"] == "COMPLETED_SUCCESSFULLY"
def test_app_runs_end_to_end(tmp_path, monkeypatch):
    pytest.importorskip("streamlit.testing.v1")
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("DR_DB_PATH", str(tmp_path / "ui.db")); monkeypatch.chdir(ROOT)
    at = AppTest.from_file(os.path.join(ROOT, "app.py"), default_timeout=30).run(); assert not at.exception
    at.sidebar.button[0].click().run(); assert not at.exception           # Start drill
    next(b for b in at.button if "next gate" in b.label.lower()).click().run(); assert not at.exception
    assert any("Approve" in (m.label if hasattr(m, "label") else "") for m in at.button)
