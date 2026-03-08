# Example Run Artifact Tree (Intent-Driven Batch)

After a run started with `intent_json` (Mode 2), the run directory contains the same structure as a direct-spec run, plus compile artifacts under `artifacts/`.

```
runs/
  run_1.0.0_42_20250308T120000Z_abc123/
    run_record.json
    run_summary.json
    events.jsonl
    released_items.jsonl
    released_oracles.jsonl
    eval_results.jsonl
    action_plans.jsonl
    data_requests.jsonl
    agent_handoffs.jsonl
    artifacts/
      intent_spec.json
      eval_families.json
      prompt_blueprints.json
      judge_specs.json
      compiled_plan.json
      compiled_dataset_spec.json
      batch_plan.json
      item_xxx_a1_item.json
      item_xxx_a1b_oracle.json
      item_xxx_qa_report.json
      item_xxx_a2_eval_result.json
      ...
      batch_a3_clusters.json
      batch_a3_action_plans.json
      batch_a6_data_requests.json
      batch_a5_run_summary.json
```

- **intent_spec.json** – user-provided intent (evaluation_goal, capability_focus, etc.).
- **eval_families.json** – families selected from the catalog by the intent planner.
- **prompt_blueprints.json** – blueprints produced by the prompt program compiler.
- **judge_specs.json** – judge specs produced by the judge planner.
- **compiled_plan.json** – full compiled artifact (intent_spec + eval_families + prompt_blueprints + judge_specs + compiled_dataset_spec + compile_metadata).
- **compiled_dataset_spec.json** – the dataset_spec actually executed by the engine (same shape as direct-spec).

All other artifacts match the existing run layout; the execution path (A1 → A1b → QA → run SUT → verify → diagnose → package) is unchanged.
