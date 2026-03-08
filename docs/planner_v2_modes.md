# Planner v2: Deterministic vs LLM vs Hybrid

The intent planning layer supports three **planner modes**. All outputs remain schema-validated and catalog/whitelist-constrained; the compiler boundary is never bypassed.

## Modes

### Deterministic (default)

- **Behavior**: No LLM calls. Eval families are resolved from the **family catalog** using `capability_focus`; prompt blueprints and judge specs are built by rule.
- **When to use**: Reproducible runs, CI, or when no Gemini API key is configured.
- **Env**: No `GEMINI_API_KEY` required. `PLANNER_MODE=deterministic` (default).

### LLM

- **Behavior**: Gemini proposes schema-typed artifacts (eval_families, prompt_blueprints, judge_specs). Proposals are validated against JSON schemas and the eval-method whitelist. No catalog overlay.
- **When to use**: More semantic freedom in decomposing goals, prompt scenarios, and judge rationale; still fully auditable.
- **Env**: `GEMINI_API_KEY` required. `PLANNER_MODE=llm`. If the key is missing, the backend returns `LLM_PROVIDER_NOT_CONFIGURED`.

### Hybrid

- **Behavior**: Gemini proposes artifacts; then **deterministic normalization** runs: catalog mapping, whitelist enforcement, evidence requirements for rubric_judge, and alignment of observables. Combines LLM creativity with catalog governance.
- **When to use**: You want LLM-generated families/blueprints/judges but need them anchored to supported task types and eval methods.
- **Env**: `GEMINI_API_KEY` required. `PLANNER_MODE=hybrid`.

## Backend configuration (server-side only)

Set these in the **backend** environment only. Never expose API keys to the frontend.

| Variable | Default | Description |
|----------|---------|-------------|
| `GEMINI_API_KEY` | (empty) | Google AI Studio / Gemini API key. Required for `llm` and `hybrid`. |
| `PLANNER_MODE` | `deterministic` | One of `deterministic`, `llm`, `hybrid`. |
| `PLANNER_MODEL` | `gemini-2.0-flash` | Model name for planner calls. |
| `PLANNER_TEMPERATURE` | `0.2` | Temperature for generation (0–2). |
| `PLANNER_MAX_RETRIES` | `3` | Retries for invalid JSON or schema mismatch. |
| `PLANNER_ALLOW_EXPERIMENTAL_FAMILIES` | `false` | Allow experimental catalog families when resolving. |

## Why LLM freedom is constrained by compiler contracts

- **Schema**: Every planner output (eval_family, prompt_blueprint, judge_spec) is validated against the corresponding JSON schema. Invalid structure is rejected or retried.
- **Whitelist**: Only supported eval methods (`programmatic_check`, `exact_match`, `trajectory_check`, `schema_check`, `rubric_judge`) and catalog task types are allowed. The compiler does not accept arbitrary checker implementations or eval methods.
- **Catalog**: In deterministic and hybrid modes, family and task types are anchored to the family catalog. In hybrid, LLM proposals are mapped/normalized to catalog families where possible; unsupported proposals fail explicitly unless experimental is allowed and schema/whitelist are satisfied.
- **No silent repair**: The system does not silently change evaluation goal, target domain, or intended difficulty. Repair is explicit (e.g. hybrid normalization) and reported in metadata (e.g. `repaired_fields`, `warnings`).

## Recommended deployment pattern

- Run the API server (and any compile/run services) on the **backend** with `GEMINI_API_KEY` set in the environment.
- Do **not** send API keys to the frontend. The web UI calls `GET /planner-status` to see whether Gemini is configured (`gemini_configured: true/false`) and shows a clear message when the user selects LLM/hybrid but the backend has no key.
- For production, keep `PLANNER_MODE=deterministic` unless you explicitly enable LLM/hybrid and have configured the key.

## Artifacts (run_dir / artifacts_dir)

When using llm/hybrid and/or `save_raw_planner_outputs`:

- `planner_metadata.json` – planner_mode, planner_model, planner_temperature, fallback_used, llm_round_trips, warnings
- `raw_llm_eval_families.json` – raw LLM proposal for eval_families (if saved)
- `raw_llm_prompt_blueprints.json` – raw LLM proposal for prompt_blueprints (if saved)
- `raw_llm_judge_specs.json` – raw LLM proposal for judge_specs (if saved)
- `planner_critic_report.json` – critic issues/summary/passed (if run)

Compile metadata in `compiled_plan.compile_metadata` includes `planner_mode`, `planner_model`, `planner_temperature`, `fallback_used`, `llm_round_trips`, and `warnings` for auditability.
