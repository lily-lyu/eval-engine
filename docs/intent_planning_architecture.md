# Intent Planning Layer – Architecture

## Overview

The eval-engine supports two ways to launch a batch:

1. **Direct dataset_spec (existing)** – user supplies low-level `dataset_spec` JSON with `capability_targets` (task_type, quota_weight, etc.). The execution layer runs unchanged.
2. **Intent-based (new)** – user supplies high-level `intent_spec` (evaluation_goal, capability_focus, batch_size, etc.). A **compile front-end** turns this into typed intermediate artifacts and then into a **compiled_dataset_spec** that the same execution engine runs.

The execution engine (A0 → validate → plan batch → A1 → A1b → QA → run model → verify → diagnose → package) is **not replaced**. Intent mode adds a **compiled** path in front of it.

---

## Old Flow (Direct Spec)

```
User → dataset_spec JSON → validate spec → batch_planner (slot counts)
     → A1 generate_item_from_target → A1b build_oracle → QA → run SUT → verify → diagnose → package
```

- Single source of truth: `dataset_spec` with `capability_targets`.
- Task registry: `task_type` → generator, oracle builder, mock_sut.

---

## New Compiled Flow

```
User → intent_spec JSON
     → intent_planner     → eval_families (from family catalog only)
     → prompt_program_compiler → prompt_blueprints
     → judge_planner     → judge_specs
     → compiler          → compiled_plan (includes compiled_dataset_spec)
     → save artifacts (intent_spec.json, eval_families.json, prompt_blueprints.json, judge_specs.json, compiled_plan.json, compiled_dataset_spec.json)
     → run_batch(compiled_dataset_spec)  [same execution path as above]
```

- **Family catalog**: controlled ontology (e.g. `extraction.email`, `trajectory.email_lookup`). No freeform invention.
- **Typed intermediates**: all planner outputs are JSON validated by schema (intent_spec, eval_family, prompt_blueprint, judge_spec, compiled_plan).
- **Compile only**: LLMs may propose structured artifacts in the future, but only after schema validation; no agent emits final prompts or judge standards without going through the compiler.

---

## Why This Preserves Auditability

- **Schema-validated artifacts**: intent_spec, eval_families, prompt_blueprints, judge_specs, and compiled_plan are all validated. Invalid planner output is rejected with explicit failure codes (e.g. `INTENT_SCHEMA_INVALID`, `FAMILY_CATALOG_MISS`).
- **No silent repair**: the compiler does not “fix” or drift user intent; underspecified or unsupported intent fails with a clear code.
- **Traceability**: intent-driven runs save full compile artifacts in `run_dir/artifacts/`, so every run can be traced back to intent_spec and the compiled dataset_spec that was executed.
- **Versioning**: compile_metadata in compiled_plan records intent_spec_version, family_catalog_version, planner_version, compiler_version, compiled_at.

---

## Entry Points

- **API**
  - `POST /runs` with `spec_json`: Mode 1 (direct dataset_spec).
  - `POST /runs` with `intent_json`: Mode 2 (compile then run).
  - `POST /compile` with `intent_json`: compile only (returns compiled_plan, no run).
- **Web UI**: Advanced → “Custom JSON” vs “Intent”. Intent mode includes a default intent template and “Preview compile”.
- **Service**: `RunBatchRequest(..., intent_spec=...)` triggers compile then `run_batch(compiled_dataset_spec)`.

---

## Backward Compatibility

- Existing smoke / email / trajectory presets and custom dataset_spec JSON continue to work.
- `dataset_spec.schema.json` is extended with optional `family_id`, `blueprint_id`, `judge_spec_id`, `materializer_config`, `family_config`; required fields and existing capability_targets shape are unchanged.
- A1 still uses `generate_item_from_target`; `generate_item_from_blueprint` and `materialize_target_to_item` are available for blueprint-driven flows.
- A1b still uses task-registry oracles; `build_oracle_from_judge_spec` and optional `judge_specs_by_id` support judge-spec-driven oracles when provided.
