# LLM Workers Execution Plan (Schema-First, Deterministic-First)

## Scope

Expand LLM usage as **constrained schema-first workers** only. Do **not** modify A0 (Orchestrator). Reuse `eval_engine/llm/gemini_client.py` and `eval_engine/llm/structured.py`. All LLM outputs must be **Pydantic-validated**; on validation failure after `max_llm_retries_per_stage`, fallback to deterministic logic or drop the item safely (fail closed).

---

## Phase 1: Config & Schemas (shared)

### 1.1 Run-level config knobs

- **Location**: Config is supplied at run time and merged into `spec` so A1/A2/A3 can read it **without changing A0**. A0 already passes `spec` to all agents.
- **Flags** (literal): `item_generation_mode`, `judge_mode`, `diagnoser_mode` each one of: `deterministic` | `hybrid` | `llm_materialized`.
- **Default**: All `deterministic` for smoke runs.
- **Retries**: `max_llm_retries_per_stage` (int, default e.g. 2) — used for LLM validation retries; after exhaustion, fallback or drop.

**Files to modify:**

| File | Change |
|------|--------|
| `schemas/dataset_spec.schema.json` | Add optional top-level `run_config` object with optional properties: `item_generation_mode`, `judge_mode`, `diagnoser_mode` (each enum `["deterministic","hybrid","llm_materialized"]`), `max_llm_retries_per_stage` (integer, default 2). |
| `eval_engine/services/run_service.py` | Extend `RunBatchRequest` with optional `item_generation_mode`, `judge_mode`, `diagnoser_mode`, `max_llm_retries_per_stage`. In `run_batch_service`, before calling `run_batch()`, merge these into `spec["run_config"]` (create if missing) so agents read `spec.get("run_config", {})`. |
| `eval_engine/api/app.py` | Extend `RunBatchRequestSchema` with optional `item_generation_mode`, `judge_mode`, `diagnoser_mode`, `max_llm_retries_per_stage`; pass through to `RunBatchRequest`. |
| `eval_engine/config.py` | (Optional) Add `Literal` type alias for mode flags and env override for `max_llm_retries_per_stage` if desired; otherwise defaults only in run_config. |

### 1.2 Pydantic output/input schemas for workers

- **Location**: New module for worker schemas used by LLM paths and validation.

**New file:**

| File | Purpose |
|------|--------|
| `eval_engine/llm/worker_schemas.py` | Pydantic models for A1, A2, A3. |

**Models to add:**

- **A1 Materializer**
  - **Input (job spec)**: `A1JobSpec` — structured JSON job: `prompt_blueprint` (dict), `capability_target` (dict), `dataset_spec_version` (str), optional `repetition_index` (int). Mirrors what A0 would pass to materialize (blueprint + target).
  - **Output (eval_item shape)**: `A1EvalItemOutput` — Pydantic model that mirrors `item.schema.json` required fields: `item_id`, `dataset_spec_version`, `domain_tags`, `difficulty`, `task_type`, `prompt`, `input`, `input_schema`, `output_schema`, `constraints`, `provenance`; optional `judge_spec_id`. Use strict types and constraints so that `model_validate(llm_dict)` enforces eval_item shape; on failure, fallback to deterministic.

- **A2 Judge** (Phase 2)
  - **Output**: `A2JudgeOutput` — `score` (float 0–1), `verdict` (Literal["pass","fail"]), `error_type` (str), `evidence` (list of dicts with at least `kind`/`code`/`message`), `confidence` (float 0–1, optional). Used when `eval_method == 'rubric_judge'` and judge_mode allows LLM.

- **A3 Analyst** (Phase 3)
  - **Output**: `A3ClusterSummary` — `cluster_id`, `title`, `affected_share` (float), `likely_root_cause` (str), `owner` (str), `recommended_actions` (list[str]), `evidence_examples` (list of short evidence dicts). A3 must **not** mutate `dataset_spec`; this is analytical output only, merged with or replacing heuristic fields in existing failure_cluster/action_plan.

---

## Phase 2: A1 Materializer Worker (Step 3 implementation)

### 2.1 Behavior

- **When**: `run_config.item_generation_mode` is `hybrid` or `llm_materialized` **and** the slot has a `prompt_blueprint` + `capability_target` (same as current blueprint path in A0).
- **Input**: Strict JSON job spec: `A1JobSpec` (prompt_blueprint + capability_target + dataset_spec_version + optional repetition_index).
- **Flow**: Call LLM with job spec; parse JSON; validate with `A1EvalItemOutput` (Pydantic). If validation fails, retry up to `max_llm_retries_per_stage`; then **fallback to existing deterministic** `generate_item_from_target` / `materialize_target_to_item` (no A0 change: A1 chooses internally).
- **Preserve**: Current deterministic generators remain first-class; they are the fallback and the only path when mode is `deterministic`.

### 2.2 Files to modify (A1 only)

| File | Change |
|------|--------|
| `eval_engine/llm/worker_schemas.py` | Implement `A1JobSpec`, `A1EvalItemOutput` (and stubs for A2/A3 for later). |
| `eval_engine/agents/a1_item_generator.py` | Add `materialize_target_to_item_llm(spec, target, dataset_spec_version, rng, blueprint, run_config)` (or equivalent). Inside: build `A1JobSpec`, call `gemini_client.generate` (or structured layer) with a prompt that requests a single eval_item JSON; parse; validate with `A1EvalItemOutput`; on success return dict conforming to item.schema; on failure after retries call existing `materialize_target_to_item(..., blueprint=blueprint)` (deterministic). Integrate **only** where `materialize_target_to_item` is currently used: **caller remains A0** — A0 still calls `materialize_target_to_item(spec, target, ...)`. So the change is **inside** `materialize_target_to_item`: if `spec.get("run_config", {}).get("item_generation_mode") in ("hybrid", "llm_materialized")` and blueprint is present, try LLM materializer first; on validation failure after retries, fall back to current deterministic branch. A0 is **not** modified. |
| `eval_engine/llm/prompts/a1_materializer.md` (new) | Prompt template: input = JSON job spec (A1JobSpec); output = single JSON object conforming to eval_item; instruct model to output only the item JSON. |

### 2.3 Helper for validation + retries

- Reuse `eval_engine/llm/structured.py` pattern: either add a small helper that uses `generate()` from `gemini_client`, then parses JSON and runs Pydantic `A1EvalItemOutput.model_validate(...)`; on `ValidationError` retry up to `max_llm_retries_per_stage`; then return `None` so A1 falls back to deterministic. Or extend `structured.py` with a `generate_and_validate_pydantic(prompt, model_class, max_retries)` that returns validated model or raises; A1 catches and falls back.

---

## Phase 3: A2 Judge Router (later; not implemented in Step 3)

- **Deterministic first**: Keep current rubric_judge path (stub or existing judge_fn) as default.
- **LLM/VLM only when**: `eval_method == 'rubric_judge'` and `run_config.judge_mode` in `hybrid` | `llm_materialized`.
- **Input**: `rubric_schema` + `evidence_requirements` (from oracle); item + parsed output.
- **Output**: Strict schema: `score`, `verdict`, `error_type`, `evidence[]`, `confidence` — validate with `A2JudgeOutput`; on failure after retries, fallback to deterministic rubric path or safe fail (e.g. fail verdict with error_type).
- **Optional prep**: Logic or types for dual-judge arbitration (existing `rubric_judge` already has dual-judge + arbiter; A2 change would be to feed real LLM into judge_fn/arbiter_fn and validate outputs with `A2JudgeOutput`).

**Files (for later):** `eval_engine/agents/a2_verifier.py`, `eval_engine/eval_methods/rubric_judge.py`, `eval_engine/llm/worker_schemas.py` (A2JudgeOutput), `eval_engine/llm/prompts/a2_judge.md`.

---

## Phase 4: A3 Analyst Worker (later; not implemented in Step 3)

- **Deterministic pre-clustering first**: Keep current `diagnose()` clustering by (error_type, evidence_code, task_type, eval_method).
- **Add**: LLM analyst that reads structured failures (and optionally existing cluster list) and outputs **cluster summaries**: `cluster_id`, `title`, `affected_share`, `likely_root_cause`, `owner`, `recommended_actions[]`, `evidence_examples[]`. Validate with `A3ClusterSummary` (or list of). A3 must **not** mutate `dataset_spec`; only enrich cluster/action_plan artifacts.
- **Integration**: After deterministic `diagnose()` produces clusters/plans, optionally call LLM analyst to add titles/summaries/evidence_examples per cluster; merge into existing failure_cluster/action_plan or append as separate artifact.

**Files (for later):** `eval_engine/agents/a3_diagnoser.py`, `eval_engine/llm/worker_schemas.py` (A3ClusterSummary), `eval_engine/llm/prompts/a3_analyst.md`.

---

## Summary: Files Touched in Step 3 (Config + A1 only)

| Action | File |
|--------|------|
| Modify | `schemas/dataset_spec.schema.json` — optional `run_config` |
| Modify | `eval_engine/services/run_service.py` — request fields + merge into `spec["run_config"]` |
| Modify | `eval_engine/api/app.py` — request schema + pass-through |
| Modify | `eval_engine/config.py` — optional Literal types / env for retries |
| **New** | `eval_engine/llm/worker_schemas.py` — Pydantic: `A1JobSpec`, `A1EvalItemOutput`; stubs for A2, A3 |
| Modify | `eval_engine/agents/a1_item_generator.py` — LLM materializer branch inside `materialize_target_to_item`, fallback to deterministic |
| **New** | `eval_engine/llm/prompts/a1_materializer.md` — prompt for A1 LLM |

**Not modified:** `eval_engine/agents/a0_orchestrator.py`.

---

## New functions / symbols

- **`eval_engine/llm/worker_schemas.py`**: `A1JobSpec`, `A1EvalItemOutput`; (later) `A2JudgeOutput`, `A3ClusterSummary`.
- **`eval_engine/agents/a1_item_generator.py`**: `_materialize_via_llm(spec, target, dataset_spec_version, rng, blueprint, run_config) -> Dict[str, Any] | None` (returns None on validation failure after retries); `materialize_target_to_item` gains internal branch: if run_config allows and blueprint present, try `_materialize_via_llm`; if result is not None use it, else existing deterministic path.
- **Optional**: `eval_engine/llm/structured.py` — `generate_and_validate_pydantic(prompt, model_class, max_retries, model=..., temperature=...)` for reuse in A1/A2/A3.

---

## Appendix: Gemini SDK migration (google-genai)

The LLM client has been migrated from `google-generativeai` to the official **google-genai** SDK to resolve `FutureWarning` and use the supported API.

- **Package**: `pip install google-genai` (see `requirements.txt`: `google-genai>=1.0.0`). Remove `google-generativeai` if present.
- **Usage**: `eval_engine/llm/gemini_client.py` uses `from google import genai`, `genai.Client(api_key=...)`, and `client.models.generate_content(model=..., contents=..., config=types.GenerateContentConfig(temperature=...))`; response text via `response.text`.
- **Behaviour**: Same public API: `get_client()`, `generate(prompt, model=..., temperature=...)`. All planner and A1/A2/A3 LLM calls go through `generate()`.
