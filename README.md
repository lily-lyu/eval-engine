# eval-engine

Evaluation engine for agent/model outputs: typed failure detection, root-cause diagnosis, and actionable data requests. Supports programmatic checks, trajectory checks, exact match, schema checks, and rubric judge.

## Gate (release check)

Run before regression and before shipping any engine change:

```bash
make gate
```

This runs the **break suite** (invariant pathways must pass), then **regression** against your SUT (`--sut_url`, `--golden_suite`, `--min_pass_rate`). See `Makefile` for defaults.

## CLI

- `gate` — break-suite then regression (use this for release).
- `break-suite` — run frozen break suite only.
- `regression` — run golden suite against HTTP SUT.
- `run` — run a batch from a dataset spec (mock or HTTP SUT).
- `generate-golden` / `generate-break-suite` — (re)generate suite JSONL.

## Case studies

- [Tool-argument failure recovery](docs/case_studies/tool_args_failure_recovery.md) — trajectory tool args schema failure → diagnosis → data request → recovery.
- [Structured extraction failure](docs/case_studies/structured_extraction_failure.md) — programmatic structured-extraction with typed evidence and evidence-specific diagnosis/A6.
