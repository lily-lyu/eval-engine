# eval-engine

Evaluation engine for agent and model outputs, built around **typed failure detection**, **root-cause diagnosis**, and **actionable data requests**.

Instead of vague failure logs, it produces structured outputs that support debugging, dataset improvement, and release gating.

## What it does

Supported evaluation modes:

- programmatic checks  
- trajectory checks  
- exact match  
- schema checks  
- rubric judge  

The engine answers not only *did this fail?* but:

- **what** failed  
- **why** it likely failed  
- **who** should own the fix  
- **what** data or product action should happen next  

## Core workflow

1. **Evaluate** — deterministic checks first; rubric/judge when needed  
2. **Emit typed evidence** — not generic pass/fail logs  
3. **Cluster** — root-cause hypotheses per failure mode  
4. **Generate** — actionable data requests / remediation tasks  
5. **Verify** — recovery through the release gate  

## Release gate

Run before regression and before shipping any engine change:

```bash
make gate
```

This runs:

- **Break suite** — invariant pathways must pass  
- **Regression suite** — golden suite against your SUT  

See the `Makefile` for defaults (`--sut_url`, `--golden_suite`, `--min_pass_rate`).

## CLI

| Command | Description |
| ------- | ----------- |
| `gate` | Break-suite first, then regression. **Use this as the main release check.** |
| `break-suite` | Run the frozen break suite only (validate invariant failure pathways). |
| `regression` | Run the golden suite against an HTTP SUT. |
| `run` | Run a batch from a dataset spec (mock or HTTP SUT). |
| `generate-golden` | Generate or refresh the frozen golden suite JSONL. |
| `generate-break-suite` | Generate or refresh the frozen break suite JSONL. |

## Why the break suite matters

The break suite is a frozen set of failure-pathway tests. It ensures the engine still correctly detects and classifies known failure modes, including:

- unsupported eval methods  
- wrong checker names  
- schema-invalid outputs  
- exact-match failures  
- trajectory tool-call failures  
- structured extraction failures  

## Case studies

- **[Tool-argument failure recovery](docs/case_studies/tool_args_failure_recovery.md)** — trajectory tool-argument schema failure → typed evidence → diagnosis → data request → recovery via the gate.  
- **[Structured extraction failure](docs/case_studies/structured_extraction_failure.md)** — programmatic structured-extraction with typed evidence and evidence-specific diagnosis / A6 remediation.  

## Repository structure

- `eval_engine/` — core engine  
- `examples/` — frozen suites and example inputs  
- `schemas/` — JSON schemas  
- `tests/` — test coverage  
- `docs/case_studies/` — demo case studies  

## Development

1. Run `make gate`.  
2. After changing engine logic, run `make gate` again; break-suite and regression must both pass.  
3. Update frozen suites only when you intentionally change the evaluation contract.  

## Goal

Make evaluation more like an engineering system and less like manual spot-checking: **deterministic** where possible, **structured** when failures happen, **actionable** for the next iteration.
