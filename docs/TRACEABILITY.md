# Requirement -> test
| Requirement | Tests (file::function) |
|---|---|
| Deterministic control, step order | test_controller::test_01, test_02, test_03, test_11 |
| HITL token security | test_security::test_06, test_07, test_08, test_09; test_controller::test_23 |
| Approver identity, four-eyes | test_controller::test_22 |
| Durability, concurrency, isolation | test_controller::test_10; test_security::test_13, test_14 |
| Audit integrity | test_security::test_15 |
| Input / secret hygiene | test_security::test_16, test_17 |
| Read-only console | test_security::test_18 |
| UI safety, accessibility | test_ui_helpers::test_19, test_pipeline_text_and_icons_not_colour_only |
| ADK integration | test_adk_runtime::test_20, test_21, test_agents_build_with_real_adk |
| RTO / progress accounting | test_controller::test_01, test_04, test_24 |
| Retry bounds, STEP_06 handling | test_controller::test_05, test_12 |
| Persistence extras, UI end to end | test_ui_helpers::test_chat_persists_and_redacts, test_session_recovery_and_formatting, test_app_runs_end_to_end |
