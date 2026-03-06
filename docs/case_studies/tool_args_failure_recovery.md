# Case Study: Tool-Argument Failure Detection and Recovery

## Overview

This demo shows how the evaluation engine handles a real agent/tool-use failure as a **structured, closed-loop workflow** rather than a vague error log.

In this case, I injected a tool-call bug into a trajectory-style task:
- the agent used `text`
- but the tool contract required `query`

The engine detected the failure, classified it with a typed evidence code, clustered it into a root-cause hypothesis, generated a concrete remediation request, and then verified recovery through the release gate after the bug was removed.

---

## Scenario

**Task type:** `trajectory_email_then_answer`  
**Injected failure:** wrong tool-argument schema  

**Expected contract:** tool `search_email_db` must receive:

```json
{"query": "<string>"}
```

**Injected behavior:** tool call used:

```json
{"text": "<string>"}
```

### Before / After Summary

| Phase        | Verdict | Error Type               | Evidence Code            | Gate Status |
| ------------ | ------- | ------------------------ | ------------------------ | ----------- |
| Bug injected | fail    | TRAJECTORY_CHECK_FAILED  | TOOL_ARGS_SCHEMA_FAILED  | fail        |
| Bug removed  | pass    | none                     | none                     | pass        |

---

## Failure Detection

When the injected bug was evaluated, the engine produced:

- **Item ID:** `break_traj_args`
- **Task Type:** `trajectory_email_then_answer`
- **Verdict:** fail
- **Error Type:** TRAJECTORY_CHECK_FAILED
- **Evidence Code:** TOOL_ARGS_SCHEMA_FAILED

This is important because the engine did not stop at "trajectory failed." It identified the specific failure mode: the tool was called with arguments that violated the declared schema.

---

## Diagnosis

The diagnoser grouped the failure into the following cluster:

- **Cluster ID:** `TRAJECTORY_CHECK_FAILED/TOOL_ARGS_SCHEMA_FAILED|trajectory_email_then_answer|trajectory_check`

It then produced a structured root-cause analysis:

- **Root cause hypothesis:** tool-call arguments fail schema; model behavior and tool contract are misaligned
- **Recommended owner:** tooling
- **Priority:** 1
- **Next action:** align arg schema with actual usage and add examples demonstrating correct query formulation

This turns a raw failure into a clear operational hypothesis rather than leaving the issue at the level of logs.

---

## Closed-Loop Action

A6 converted the failure into a structured remediation request:

- **Issue type:** TOOL_ARGS_BAD
- **Owner type:** data
- **What to collect:** more tool-call examples with correct query formulation, plus negative examples of malformed arguments
- **Verification eval:** trajectory arg-schema failure rate should decrease on rerun

This is the key product value of the engine: it does not just detect errors, it translates them into actionable backlog items for model/data/tooling improvement.

---

## Recovery

After removing the injected bug and returning the server to normal behavior:

- the full release gate was rerun
- `make gate` passed successfully

This verified that recovery was not anecdotal. It was measured through the same evaluation and release mechanism used to detect the failure in the first place.

---

## What This Demonstrates

This case shows that the engine can:

- detect failures with typed evidence, not vague logs
- separate failure detection from root-cause diagnosis
- generate actionable remediation requests
- verify recovery through the release gate

In other words, the system functions not just as an evaluator, but as a closed-loop evaluation and improvement engine.

---

## Why This Matters

In practice, model and agent failures are only useful if they can be turned into:

- a precise failure category
- a credible root-cause hypothesis
- a concrete next action
- a measurable recovery path

This demo shows that the engine supports that full loop.
