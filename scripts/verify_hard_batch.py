#!/usr/bin/env python3
"""
Local verification: run a batch with hard_failure_seeking_reliability intent,
then inspect realized items for batch size, blueprint reflection, and scenario_subtype in prompts.
"""
import json
import sys
from pathlib import Path

# Project root = parent of scripts/
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from eval_engine.agents.compile_pipeline import compile_intent_to_plan
from eval_engine.services.run_service import RunBatchRequest, run_batch_service


INTENT_PATH = PROJECT_ROOT / "examples" / "hard_intent_test.json"
PREVIEW_LEN = 120


def main() -> None:
    intent = json.loads(INTENT_PATH.read_text(encoding="utf-8"))
    batch_size_requested = intent.get("batch_size", 12)
    print(f"Intent: {intent['intent_name']}")
    print(f"Requested batch_size: {batch_size_requested}")
    print()

    # Compile
    print("Compiling intent...")
    plan = compile_intent_to_plan(intent, planner_mode="deterministic")
    spec = plan["compiled_dataset_spec"]
    blueprints = plan["prompt_blueprints"]
    bp_by_id = {b["blueprint_id"]: b for b in blueprints}

    # Run batch (mock SUT)
    print("Running batch (mock SUT)...")
    request = RunBatchRequest(
        project_root=PROJECT_ROOT,
        spec={},
        quota=batch_size_requested,
        sut_name="mock",
        model_version="mock-1",
        intent_spec=intent,
        planner_mode="deterministic",
    )
    response = run_batch_service(request)
    run_dir = response.run_dir
    artifacts_dir = run_dir / "artifacts"
    print(f"Run dir: {run_dir}")
    print()

    # Load batch_plan (saved in artifacts_dir by a0_orchestrator)
    batch_plan_path = artifacts_dir / "batch_plan.json"
    if not batch_plan_path.exists():
        batch_plan_path = run_dir / "batch_plan.json"
    batch_plan_data = json.loads(batch_plan_path.read_text(encoding="utf-8")) if batch_plan_path.exists() else {}
    total_slots_planned = batch_plan_data.get("total_slots", 0)
    plan_entries = batch_plan_data.get("plan", [])

    # Released items: run_dir/released_items.jsonl (one JSON object per line)
    released_items = []
    released_path = run_dir / "released_items.jsonl"
    if released_path.exists():
        for line in released_path.read_text(encoding="utf-8").strip().splitlines():
            if line:
                released_items.append(json.loads(line))
    # Fallback: collect from artifacts *_a1_item.json (items are saved there per slot)
    if not released_items and artifacts_dir.exists():
        item_files = sorted(artifacts_dir.glob("*_a1_item.json"))
        for p in item_files:
            released_items.append(json.loads(p.read_text(encoding="utf-8")))

    realized_count = len(released_items)
    print("=" * 60)
    print("1) BATCH SIZE")
    print("=" * 60)
    print(f"  Requested batch_size: {batch_size_requested}")
    print(f"  Batch plan total_slots: {total_slots_planned}")
    print(f"  Realized items (released): {realized_count}")
    if realized_count != batch_size_requested:
        print(f"  >>> MISMATCH: realized={realized_count} vs requested={batch_size_requested}")
    else:
        print("  OK: realized == requested")
    print()

    print("=" * 60)
    print("2) PER-ITEM: item_id, task_type, family_id, blueprint_id, difficulty, prompt preview")
    print("=" * 60)
    hard_subtype_keywords = {
        "tool_order_trap": "order",
        "missing_tool_arg_risk": "document",
        "distractor_context": "Unrelated",
        "near_match": "exact name",
        "multi_record": "second record",
        "carry_chain": "carry",
        "distractor": "Do not use",
        "multi_step": "then add",
        "distractor_email": "Primary",
        "multi_step_dependency": "Step 1",
        "multi_hopish": "Step 1",
        "boundary_case": "Not bad",
        "negation": "don't dislike",
        "label_confusion": "Mediocre",
        "noisy": "[Ticket",
        "conflicting_fields": "primary",
        "citation_conflict": "Source A",
    }
    easy_looking = []
    for i, item in enumerate(released_items):
        prov = item.get("provenance") or {}
        bid = prov.get("blueprint_id", "")
        fid = prov.get("family_id", "")
        bp = bp_by_id.get(bid, {})
        mcfg = bp.get("materializer_config") or {}
        subtype = mcfg.get("scenario_subtype", "default")
        difficulty = item.get("difficulty", "")
        prompt = (item.get("prompt") or "")[:PREVIEW_LEN]
        prompt_preview = prompt + ("..." if len(item.get("prompt") or "") > PREVIEW_LEN else "")

        print(f"  [{i+1}] {item.get('item_id', '')}")
        print(f"      task_type={item.get('task_type')} family_id={fid} blueprint_id={bid} difficulty={difficulty}")
        print(f"      scenario_subtype={subtype}")
        print(f"      prompt: {prompt_preview!r}")
        # Check if subtype is reflected
        reflected = False
        for kw in hard_subtype_keywords.values():
            if kw.lower() in (item.get("prompt") or "").lower() or kw.lower() in str(item.get("input") or "").lower():
                reflected = True
                break
        if difficulty == "hard" and subtype != "default" and not reflected:
            # Could still be hard via structure (e.g. multi_step has "c" in input)
            if item.get("task_type") == "json_math_add" and "c" in (item.get("input") or {}):
                reflected = True
            if not reflected:
                easy_looking.append({"item_id": item.get("item_id"), "task_type": item.get("task_type"), "subtype": subtype})
        print()
    print()

    print("=" * 60)
    print("3) SCENARIO_SUBTYPE REFLECTION")
    print("=" * 60)
    for bp in blueprints[:20]:
        mcfg = bp.get("materializer_config") or {}
        st = mcfg.get("scenario_subtype", "default")
        print(f"  {bp['family_id']} / {bp['blueprint_id']} -> scenario_subtype={st}")
    print()

    print("=" * 60)
    print("4) HARD BLUEPRINT BUT EASY-LOOKING PROMPT (flagged)")
    print("=" * 60)
    if easy_looking:
        for x in easy_looking:
            print(f"  - {x['item_id']} task_type={x['task_type']} subtype={x['subtype']}")
    else:
        print("  None flagged.")
    print()

    print("=" * 60)
    print("5) BATCH PLAN (min_count / quota accounting)")
    print("=" * 60)
    for e in plan_entries:
        t = e.get("target_id", "")
        c = e.get("count", 0)
        tt = e.get("task_type", "")
        print(f"  {t} task_type={tt} count={c}")
    total_from_plan = sum(e.get("count", 0) for e in plan_entries)
    print(f"  Sum(plan counts) = {total_from_plan}")
    if total_from_plan != batch_size_requested:
        print(f"  >>> Plan sum {total_from_plan} != requested {batch_size_requested}")
    print()

    # Summary
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    compile_ok = len(plan["eval_families"]) >= 1 and any(f.get("risk_tier") == "failure_seeking" for f in plan["eval_families"])
    execution_ok = realized_count == batch_size_requested and (not easy_looking or len(easy_looking) < 3)
    batch_ok = total_from_plan == batch_size_requested and total_slots_planned == batch_size_requested
    print(f"  Compile layer (hard families + blueprints): {'OK' if compile_ok else 'CHECK'}")
    print(f"  Execution (count + blueprint diversity in prompts): {'OK' if execution_ok else 'CHECK'}")
    print(f"  batch_size accounting: {'OK' if batch_ok else 'MISMATCH'}")
    if not batch_ok:
        print("  -> Check: batch_planner.compile_batch_plan(spec, quota, rng) and compiler min_count logic.")


if __name__ == "__main__":
    main()
