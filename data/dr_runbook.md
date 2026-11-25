# RB-PAY-DR-042 Payments platform disaster-recovery runbook (RTO 900 s, RPO 15 s)

## STEP_01_VERIFY_REPLICATION
Verify replication on pg-payments-dr. Read-only. Owner: Database Reliability Lead. Target 60 s. Lag must be below 15 s and WAL STREAMING; otherwise wait 30 s and retry (max 3 retries), then abort. Rollback: abort, no mutation.

## STEP_02_FAILOVER_DB
Promote the DR standby pg-payments-dr and fence the old primary. Mutating. Owner: Database Reliability Lead. Target 180 s. Prerequisite: STEP_01 completed. Rollback: demote standby and unfence primary.

## STEP_03_REPOINT_APP
Repoint payments-api (DR region) to the promoted database. Mutating. Owner: Platform Engineering Lead. Target 240 s. Prerequisite: STEP_02 completed. Rollback: restore previous application configuration.

## STEP_04_UPDATE_DNS
Switch payments.example.com to the DR endpoint. Mutating. Owner: Network & Edge Operations Lead. Target 180 s. Prerequisite: STEP_03 completed. Rollback: restore previous DNS records.

## STEP_05_VALIDATE_E2E
Run the end-to-end canary against payments-canary (HTTP 200, p99 under 500 ms). Read-only. Owner: DR Drill Coordinator. Target 120 s. Prerequisite: STEP_04 completed. A failure triggers rollback starting at STEP_04.

## STEP_06_COMMUNICATE_COMPLETE
Send the completion notice to stakeholders. Mutating. Owner: DR Drill Coordinator. Target 30 s. Prerequisite: STEP_05 completed. Not rolled back; a correction notice is sent under a new approval.
