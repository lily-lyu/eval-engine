# Demo Report — Injected Wrong Tool Args

- Item ID: **break_traj_args**
- Task Type: **trajectory_email_then_answer**
- Verdict: **fail**
- Error Type: **TRAJECTORY_CHECK_FAILED**
- Evidence Codes: **['TOOL_ARGS_SCHEMA_FAILED']**

## Diagnoser Output
- `TRAJECTORY_CHECK_FAILED/TOOL_ARGS_SCHEMA_FAILED|trajectory_email_then_answer|trajectory_check` — Cluster 'TRAJECTORY_CHECK_FAILED/TOOL_ARGS_SCHEMA_FAILED|trajectory_email_then_answer|trajectory_check' with 1 failures (sample item_ids: ['break_traj_args'])

## A6 Data Requests
- `TOOL_ARGS_BAD` — Collect tool-call examples with correct query formulation; include negative examples of malformed args.
