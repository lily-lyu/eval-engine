# Hard intent local verification report

**Intent:** `hard_failure_seeking_reliability` (from `examples/hard_intent_test.json`)  
**Run:** Local batch with mock SUT, deterministic planner, batch_size=12.  
**Script:** `scripts/verify_hard_batch.py` (run via `.venv/bin/python scripts/verify_hard_batch.py`).

---

## 1) Batch size

| Metric | Value |
|--------|--------|
| Requested `batch_size` | 12 |
| Batch plan `total_slots` | 12 |
| Realized items (released) | 12 |

**Result:** Batch size is correct. No over-allocation to 13.

---

## 2) Per-item summary (realized run)

Each item had:
- **item_id**, **task_type**, **family_id**, **blueprint_id**, **difficulty**
- **scenario_subtype** from blueprint `materializer_config`
- **Prompt preview** (first 120 chars)

Observed distribution:
- **extraction.structured:** 3 items (bp v1=distractor, v2=noisy, v3=multi_record)
- **grounded.qa.factual:** 3 items (v1=distractor_context, v2=near_match, v3=multi_hopish)
- **trajectory.email_lookup:** 6 items (v1=tool_order_trap x2, v2=missing_tool_arg_risk x2, v3=distractor_email x2)

**Note:** This run had **no math.add** and **no classification** items. With failure_seeking, the compiler sets `min_count` on hard-family targets only; the batch planner then allocates the full quota (12) across those targets. With three hard families and multiple blueprints each, all 12 slots went to trajectory / grounded_qa / extraction.structured.

---

## 3) Blueprint scenario_subtype reflected in prompts/inputs

| Family | Blueprint subtype | Reflected in content |
|--------|-------------------|----------------------|
| extraction.structured | distractor, noisy, multi_record | Yes (input text: "Do not use", "[Ticket", "second record") |
| grounded.qa.factual | distractor_context, near_match, multi_hopish | Yes (context: "Unrelated", "exact name", "Step 1"/"Step 2") |
| trajectory.email_lookup | tool_order_trap, missing_tool_arg_risk, distractor_email | Yes (prompt/input: "Order matters", "document", "Primary") |

**Result:** Execution layer is honoring blueprint diversity. Hard scenario_subtypes (tool_order_trap, missing_tool_arg_risk, distractor_context, near_match, multi_record, distractor, noisy, multi_hopish) are reflected in generated prompt structure and/or input content.

One item was initially flagged (multi_hopish) because the keyword list did not include "Step 1" for that subtype; after adding it, no false positives.

---

## 4) Hard blueprint but easy-looking prompt

**Result:** None. All hard blueprints produced prompts/inputs that match the intended subtype (distractor, noisy, multi_record, tool_order_trap, etc.). No family had a hard blueprint but a generic “easy” prompt.

---

## 5) Batch size accounting

- **Sum(plan counts)** = 12 (matches quota).
- **Source of truth:** `eval_engine/agents/batch_planner.py` — `compile_batch_plan(spec, quota, rng)` returns a plan with `sum(count) == quota`. The orchestrator uses `plan_to_target_list(batch_plan)` so `len(targets) == quota`.
- **No over-allocation:** Remainder allocation in `compile_batch_plan` assigns exactly `remaining` extra slots; total never exceeds quota.

**Result:** Batch size normalization is consistent. No mismatch in compile vs planning vs allocation.

---

## Summary table

| Check | Status | Notes |
|-------|--------|--------|
| Compile layer (hard families + blueprints) | **OK** | Failure-seeking produces hard families, risk_tier, and failure-prone scenario_subtypes. |
| Execution (blueprint diversity in prompts) | **OK** | scenario_subtype is reflected in prompt/input (distractor, tool_order_trap, near_match, etc.). |
| batch_size accounting | **OK** | Realized count = 12; plan sum = 12; no over-allocation. |
---

## Files/functions involved (for any future patches)

- **Compile layer:**  
  - `eval_engine/agents/intent_planner.py` — `_plan_intent_deterministic` (slot_weight, difficulty, risk_tier for failure_seeking).  
  - `eval_engine/agents/prompt_program_compiler.py` — `_compile_blueprints_deterministic`, `_scenario_subtypes_for_family`, `HARD_SCENARIO_SUBTYPES_BY_FAMILY`.  
  - `eval_engine/agents/compiler.py` — `compile_to_plan` (min_count for hard targets, hard_min_fraction).

- **Execution layer:**  
  - `eval_engine/agents/a1_item_generator.py` — `_scenario_subtype()`, and each `_make_*_item` uses `materializer_config.scenario_subtype` to vary content.  
  - `eval_engine/agents/a0_orchestrator.py` — `materialize_target_to_item` passes blueprint (including materializer_config) into the generator.

- **Batch size:**  
  - `eval_engine/agents/batch_planner.py` — `compile_batch_plan(spec, quota, rng)` guarantees `sum(count) == quota`.  
  - `eval_engine/agents/a0_orchestrator.py` — uses `compile_batch_plan(spec, quota, rng)` with `quota` from the run request (e.g. intent `batch_size`).

