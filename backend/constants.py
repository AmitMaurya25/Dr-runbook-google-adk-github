"""Step order, allow-lists, owners, budgets (plan section 5.4)."""
from __future__ import annotations
import hashlib, os
STEP_ORDER = ["STEP_01_VERIFY_REPLICATION", "STEP_02_FAILOVER_DB", "STEP_03_REPOINT_APP",
              "STEP_04_UPDATE_DNS", "STEP_05_VALIDATE_E2E", "STEP_06_COMMUNICATE_COMPLETE"]
S1, S2, S3, S4, S5, S6 = STEP_ORDER
READ_ONLY_STEPS = {S1, S5}
MUTATING_STEPS = {S2, S3, S4, S6}
ROLLBACKABLE_STEPS = {S2, S3, S4}
PREREQUISITE = {S2: S1, S3: S2, S4: S3, S5: S4, S6: S5}
LABELS = {S1: "Verify replication", S2: "Failover DB", S3: "Repoint app", S4: "Update DNS",
          S5: "Validate end to end", S6: "Communicate completion"}
ACTION_PHRASES = {S1: "verifying replication", S2: "failing over the database", S3: "repointing the application",
                  S4: "updating DNS", S5: "validating end to end", S6: "sending the completion notice"}
STEP_TIERS = {S1: "Database", S2: "Database", S3: "Application", S4: "Network", S5: "Validation", S6: "Communication"}
DBA, PLAT, NET, COORD = ("Database Reliability Lead", "Platform Engineering Lead",
                         "Network & Edge Operations Lead", "DR Drill Coordinator")
STEP_OWNERS = {S1: DBA, S2: DBA, S3: PLAT, S4: NET, S5: COORD, S6: COORD}
TARGET_DURATIONS = {S1: 60, S2: 180, S3: 240, S4: 180, S5: 120, S6: 30}
TARGET_RESOURCES = {S1: "pg-payments-dr", S2: "pg-payments-dr", S3: "payments-api (DR region)",
                    S4: "payments.example.com", S5: "payments-canary", S6: "stakeholder distribution list"}
ROLLBACK_PLANS = {S2: "Demote standby and unfence the old primary", S3: "Restore previous application configuration",
                  S4: "Restore previous DNS records", S6: "No rollback; a correction notice needs a new approval"}
ALLOWED_SCENARIOS = ["normal_drill", "replication_lag_retry_drill", "app_repoint_failure_drill"]
ALLOWED_STEPS = set(STEP_ORDER)
ALLOWED_REPL_GROUPS = {"pg-payments-dr"}
ALLOWED_HEALTH_TARGETS = {"payments-canary"}
ALLOWED_DIAGNOSTICS = {"replication", "health"}
APPROVER_ROLES = [DBA, PLAT, NET, COORD, "Incident Commander"]
CONFIRM_PHRASES = {S2: "FAILOVER", S3: "REPOINT", S4: "DNS", S6: "NOTIFY"}
ROLLBACK_CONFIRM = "ROLLBACK"
MAX_TOOL_CALLS, MAX_RETRIES, RETRY_WAIT_SECONDS = 15, 3, 30
TARGET_RTO_SECONDS, LAG_LIMIT_SECONDS = 900, 15
DEFAULT_TOKEN_TTL_SECONDS, MAX_TOKEN_REISSUES = 600, 3
REQUIRE_FOUR_EYES_ROLLBACK = os.getenv("REQUIRE_FOUR_EYES_ROLLBACK", "false").lower() == "true"
OUTCOME_OK = "COMPLETED_SUCCESSFULLY"
OUTCOME_ROLLED_BACK = "ROLLED_BACK_ABORTED"
OUTCOME_ABORTED_NO_MUTATION = "ABORTED_NO_MUTATION"
OUTCOME_HALTED = "HALTED_ROLLBACK_DECLINED"
OUTCOME_NOTICE_FAILED = "COMPLETED_NOTICE_FAILED"
ROLLBACK_DEFAULT = {"result": "ROLLED_BACK", "details": "Step reversed.", "duration": 135}
CONFIG_HASH = hashlib.sha256(repr((STEP_ORDER, TARGET_DURATIONS, MAX_RETRIES, TARGET_RTO_SECONDS)).encode()).hexdigest()[:16]
def short_id(step: str) -> str: return step[:7]
def step_number(step: str) -> int: return STEP_ORDER.index(step) + 1
