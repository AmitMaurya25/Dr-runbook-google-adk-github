import pytest
from backend.constants import *
from backend.interfaces import ApprovalError
from tests.conftest import SID, approve, drive
def test_01_normal_flow_685_and_100(ctl):
    s = drive(ctl, ctl.start_drill(SID, "normal_drill"))
    assert s["outcome"] == OUTCOME_OK and s["elapsed_rto"] == 685 and s["forward_progress_pct"] == 100
    assert all(v == "COMPLETED" for v in s["steps_status"].values()) and "finished" in s["notice_text"]
def test_02_83_percent_before_step_06(ctl):
    s = drive(ctl, ctl.start_drill(SID), stop=lambda s: s["pending_action"] == S6)
    assert s["forward_progress_pct"] == pytest.approx(83.3, abs=0.1)
def test_03_rollback_separate_approvals_reverse_order(ctl):
    s = drive(ctl, ctl.start_drill(SID, "app_repoint_failure_drill"), stop=lambda s: s["gate_purpose"] == "ROLLBACK")
    assert s["pending_action"] == S3 and s["approval_id"].startswith("RBK-") and s["rollback_queue"] == [S3, S2]
    t1 = s["approval_id"]; s = approve(ctl, s)
    assert s["pending_action"] == S2 and s["approval_id"] != t1
    s = approve(ctl, s)
    assert s["outcome"] == OUTCOME_ROLLED_BACK and s["elapsed_rto"] == 695 and s["forward_progress_pct"] < 100
    assert [a["step"] for a in s["approvals"] if a["purpose"] == "ROLLBACK"] == [S3, S2]
def test_04_retry_scenario_755(ctl):
    s = drive(ctl, ctl.start_drill(SID, "replication_lag_retry_drill"))
    assert s["elapsed_rto"] == 755 and s["retry_count"] == 0 and s["attempts"][S1] == 2 and s["outcome"] == OUTCOME_OK
def test_05_retry_exhaustion_aborts(ctl):
    s = ctl.run_to_gate(SID, ctl.start_drill(SID, "retry_exhaust")["drill_id"])
    assert s["outcome"] == OUTCOME_ABORTED_NO_MUTATION and s["steps_status"][S1] == "FAILED" and s["tool_call_count"] == MAX_RETRIES + 1
def test_10_reject_then_resume_in_new_controller(ctl, db, clock):
    from backend.adk_controller import ADKDrillController
    from tests.conftest import test_scenarios
    s = drive(ctl, ctl.start_drill(SID), stop=lambda s: s["pending_action"] == S4)
    s = approve(ctl, s, decision="REJECT")
    assert s["gate_purpose"] == "ROLLBACK" and s["rollback_queue"] == [S3, S2]
    c2 = ADKDrillController(db, clock=clock, scenarios=test_scenarios())
    s = c2.get_state(SID, s["drill_id"]); assert s["phase"] == "WAITING_APPROVAL"
    s = approve(c2, s); s = approve(c2, s)
    assert s["outcome"] == OUTCOME_ROLLED_BACK
def test_11_canary_failure_rolls_back_04_03_02(ctl):
    s = drive(ctl, ctl.start_drill(SID, "canary_fail"), stop=lambda s: s["gate_purpose"] == "ROLLBACK")
    assert s["rollback_queue"] == [S4, S3, S2] and s["steps_status"][S5] == "FAILED" and s["steps_status"][S6] == "BLOCKED"
    s = drive(ctl, s); assert s["outcome"] == OUTCOME_ROLLED_BACK
def test_12_step06_failure_retry_then_notice_failed_then_correction(ctl):
    s = drive(ctl, ctl.start_drill(SID, "notice_fail_then_ok"), stop=lambda s: s["pending_action"] == S6)
    s = approve(ctl, s)
    assert s["phase"] == "WAITING_APPROVAL" and s["pending_action"] == S6          # one retry under a fresh token
    s = approve(ctl, s)
    assert s["outcome"] == OUTCOME_NOTICE_FAILED and s["steps_status"][S2] == "COMPLETED"   # infra not rolled back
    s = ctl.request_correction_notice(SID, s["drill_id"]); assert s["phase"] == "WAITING_APPROVAL"
    s = approve(ctl, s)
    assert s["outcome"] == OUTCOME_OK and s["notice_corrected"]
def test_22_role_mismatch_and_four_eyes(ctl, db, clock):
    s = drive(ctl, ctl.start_drill(SID), stop=lambda s: s["pending_action"] == S2)
    with pytest.raises(ApprovalError): approve(ctl, s, role=PLAT)
    with pytest.raises(ApprovalError): approve(ctl, s, name=" ")
    assert approve(ctl, s, role="Incident Commander")["steps_status"][S2] == "COMPLETED"
    from backend.adk_controller import ADKDrillController
    from tests.conftest import test_scenarios
    c = ADKDrillController(db + "2", clock=clock, scenarios=test_scenarios(), four_eyes=True)
    s = drive(c, c.start_drill(SID, "app_repoint_failure_drill"), stop=lambda s: s["gate_purpose"] == "ROLLBACK")
    s = approve(c, s, name="Asha"); assert s["pending_action"] == S3 and s["steps_status"][S3] == "FAILED"
    s = approve(c, s, name="Asha"); assert s["steps_status"][S3] == "FAILED"          # same person cannot be both
    s = approve(c, s, name="Ben"); assert s["steps_status"][S3] == "ROLLED_BACK"
def test_23_reissue_cap_then_abort(ctl, clock):
    s = drive(ctl, ctl.start_drill(SID), stop=lambda s: s["pending_action"] == S2)
    for i in range(MAX_TOKEN_REISSUES):
        clock.advance(TARGET_RTO_SECONDS)
        s = ctl.reissue_token(SID, s["drill_id"], "Asha", DBA); assert s["reissue_count"] == i + 1
    clock.advance(TARGET_RTO_SECONDS)
    s = ctl.reissue_token(SID, s["drill_id"], "Asha", DBA)
    assert s["phase"] == "DONE" and s["outcome"] == OUTCOME_ABORTED_NO_MUTATION
def test_24_simulated_rto_and_human_wait_are_separate(ctl, clock):
    from backend.report import build_report
    s = drive(ctl, ctl.start_drill(SID), stop=lambda s: s["pending_action"] == S2)
    clock.advance(45); s = drive(ctl, s)
    r = build_report(s, ctl.store)
    assert s["elapsed_rto"] == 685 and r["human_wait_seconds"] >= 45 and r["simulated_rto_seconds"] == 685
    assert "human_wait_seconds" in r and sum(r["rto_by_tier"].values()) == 685
