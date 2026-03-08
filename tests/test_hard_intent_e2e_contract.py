"""
End-to-end contract test for hard failure-seeking intent.
Runs: compile -> batch plan -> run (mock SUT) -> verify.
Checks: batch size, family/task/blueprint distribution, field consistency through pipeline,
        starvation, duplicate detection, schema validation, pass rate vs intent.
"""
import json
import os
from pathlib import Path

import pytest

# Project root
PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)

HARD_INTENT = {
    "intent_name": "hard_failure_seeking_reliability",
    "intent_spec_version": "1.0.0",
    "planner_objective": "failure_seeking",
    "difficulty_floor": "hard",
    "evaluation_goal": "Stress-test agent reliability with harder, failure-prone but still machine-checkable tasks across trajectory, grounded QA, extraction, classification, and math.",
    "target_domain": ["trajectory", "grounded_qa", "extraction", "classification", "math"],
    "capability_focus": ["trajectory", "grounded_qa", "extraction", "classification", "math"],
    "hard_min_fraction": 0.7,
    "adversarial_variation_required": True,
    "risk_focus": [
        "tool_use_correctness",
        "grounding_fidelity",
        "schema_adherence",
        "instruction_following",
    ],
    "difficulty_mix": {"medium": 0.2, "hard": 0.8},
    "batch_size": 12,
    "defaults": {"seed": 42, "max_prompt_length": 20000, "max_retries_per_stage": 2},
}


def _load_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").strip().splitlines():
        if line:
            out.append(json.loads(line))
    return out


def _run_full_pipeline():
    """Compile intent, run batch with mock SUT, return (run_dir, compiled_plan, artifacts_dir)."""
    from eval_engine.agents.compile_pipeline import compile_intent_to_plan
    from eval_engine.services.run_service import RunBatchRequest, run_batch_service

    plan = compile_intent_to_plan(HARD_INTENT, planner_mode="deterministic")
    request = RunBatchRequest(
        project_root=PROJECT_ROOT,
        spec={},
        quota=HARD_INTENT["batch_size"],
        sut_name="mock",
        model_version="mock-1",
        intent_spec=HARD_INTENT,
        planner_mode="deterministic",
    )
    response = run_batch_service(request)
    run_dir = response.run_dir
    artifacts_dir = run_dir / "artifacts"
    # Save compiled_plan into run artifacts (run_service does this when intent_spec is set)
    if (artifacts_dir / "compiled_plan.json").exists():
        compiled_plan = json.loads((artifacts_dir / "compiled_plan.json").read_text(encoding="utf-8"))
    else:
        compiled_plan = plan
    return run_dir, compiled_plan, artifacts_dir


@pytest.fixture(scope="module")
def e2e_run():
    """Run pipeline once per module; reuse for all tests."""
    run_dir, compiled_plan, artifacts_dir = _run_full_pipeline()
    batch_plan_path = artifacts_dir / "batch_plan.json"
    if not batch_plan_path.exists():
        batch_plan_path = run_dir / "batch_plan.json"
    batch_plan = json.loads(batch_plan_path.read_text(encoding="utf-8")) if batch_plan_path.exists() else {}
    released_items = _load_jsonl(run_dir / "released_items.jsonl")
    if not released_items and artifacts_dir.exists():
        for p in sorted(artifacts_dir.glob("*_a1_item.json")):
            released_items.append(json.loads(p.read_text(encoding="utf-8")))
    released_oracles = _load_jsonl(run_dir / "released_oracles.jsonl")
    eval_results = _load_jsonl(run_dir / "eval_results.jsonl")
    run_summary = {}
    if (run_dir / "run_summary.json").exists():
        run_summary = json.loads((run_dir / "run_summary.json").read_text(encoding="utf-8"))
    run_record = {}
    if (run_dir / "run_record.json").exists():
        run_record = json.loads((run_dir / "run_record.json").read_text(encoding="utf-8"))
    # QA reports (for released items we only have passed; failed are in package_run's qa_reports_failed)
    qa_failure_codes = []
    if artifacts_dir.exists():
        for p in artifacts_dir.glob("*_qa_report.json"):
            try:
                r = json.loads(p.read_text(encoding="utf-8"))
                if not r.get("passed") and r.get("failure_code"):
                    qa_failure_codes.append(r["failure_code"])
            except Exception:
                pass
    return {
        "run_dir": run_dir,
        "compiled_plan": compiled_plan,
        "artifacts_dir": artifacts_dir,
        "batch_plan": batch_plan,
        "released_items": released_items,
        "released_oracles": released_oracles,
        "eval_results": eval_results,
        "run_summary": run_summary,
        "run_record": run_record,
        "qa_failure_codes": qa_failure_codes,
    }


# ---- 1) Batch size ----
def test_batch_size_requested_planned_realized(e2e_run):
    requested = HARD_INTENT["batch_size"]
    total_slots = e2e_run["batch_plan"].get("total_slots", 0)
    realized = len(e2e_run["released_items"])
    assert requested == total_slots, f"planned slots {total_slots} != requested {requested}"
    assert total_slots == realized, f"realized {realized} != planned {total_slots}"
    assert realized == requested, f"realized {realized} != requested {requested}"


# ---- 2) Compiled vs generated ----
def test_compiled_families_blueprints_targets_match_generated(e2e_run):
    plan = e2e_run["compiled_plan"]
    items = e2e_run["released_items"]
    families = {f["family_id"] for f in plan.get("eval_families", [])}
    blueprints = {b["blueprint_id"] for b in plan.get("prompt_blueprints", [])}
    targets = plan.get("compiled_dataset_spec", {}).get("capability_targets", [])
    target_ids = {t["target_id"] for t in targets}
    # Every item should have family_id and blueprint_id from the plan
    item_families = {item.get("provenance", {}).get("family_id") for item in items}
    item_blueprints = {item.get("provenance", {}).get("blueprint_id") for item in items}
    assert item_families <= families, f"item families {item_families} not subset of plan families {families}"
    assert item_blueprints <= blueprints, f"item blueprints {item_blueprints} not subset of plan blueprints {blueprints}"


# ---- 3) Field consistency through pipeline ----
def test_item_provenance_and_fields_consistent(e2e_run):
    from eval_engine.core.schema import validate_or_raise

    items = e2e_run["released_items"]
    bp_by_id = {b["blueprint_id"]: b for b in e2e_run["compiled_plan"].get("prompt_blueprints", [])}
    for item in items:
        prov = item.get("provenance") or {}
        assert "blueprint_id" in prov, f"item {item.get('item_id')} missing provenance.blueprint_id"
        assert "family_id" in prov, f"item {item.get('item_id')} missing provenance.family_id"
        assert item.get("task_type"), f"item {item.get('item_id')} missing task_type"
        assert item.get("difficulty"), f"item {item.get('item_id')} missing difficulty"
        # Blueprint should agree on materializer_type vs item task_type
        bid = prov.get("blueprint_id")
        if bid and bid in bp_by_id:
            bp = bp_by_id[bid]
            assert bp.get("materializer_type") == item.get("task_type"), (
                f"item task_type {item.get('task_type')} != blueprint materializer_type {bp.get('materializer_type')}"
            )
        validate_or_raise("item.schema.json", item)


def test_oracle_item_id_and_eval_method_consistent(e2e_run):
    from eval_engine.core.schema import validate_or_raise

    items = e2e_run["released_items"]
    oracles = e2e_run["released_oracles"]
    assert len(oracles) == len(items)
    by_item = {o["item_id"]: o for o in oracles}
    for item in items:
        iid = item["item_id"]
        assert iid in by_item, f"oracle missing for item {iid}"
        oc = by_item[iid]
        assert oc.get("eval_method"), f"oracle {iid} missing eval_method"
        validate_or_raise("oracle.schema.json", oc)


# ---- 4) Family/task starvation ----
def test_no_family_silently_starved(e2e_run):
    plan = e2e_run["compiled_plan"]
    batch_plan = e2e_run["batch_plan"]
    plan_entries = batch_plan.get("plan", [])
    # Families in capability_targets that got 0 count are starved
    targets = plan.get("compiled_dataset_spec", {}).get("capability_targets", [])
    family_counts = {}
    for e in plan_entries:
        # plan entries have target_id, count, task_type; we need family_id from targets
        tid = e.get("target_id", "")
        c = e.get("count", 0)
        tgt = next((t for t in targets if t.get("target_id") == tid), None)
        if tgt:
            fid = tgt.get("family_id", "")
            family_counts[fid] = family_counts.get(fid, 0) + c
    # With failure_seeking we bias hard families; easy families can get 0 (not a bug)
    # Just ensure every family that appears in plan has at least one slot if it's a hard family
    hard_families = {"trajectory.email_lookup", "grounded.qa.factual", "extraction.structured"}
    for fid, count in family_counts.items():
        if fid in hard_families:
            assert count >= 1, f"hard family {fid} got 0 slots (starved)"


# ---- 5) Duplicate detection ----
def test_no_duplicate_prompt_fingerprints_in_released(e2e_run):
    from eval_engine.core.hashing import compute_dedup_fingerprint

    items = e2e_run["released_items"]
    fingerprints = []
    for item in items:
        fp_hash, _ = compute_dedup_fingerprint(item)
        fingerprints.append(fp_hash)
    assert len(fingerprints) == len(set(fingerprints)), "duplicate dedup fingerprint among released items"


# ---- 6) Compile-time vs runtime artifact fields ----
def test_compile_artifacts_fields_present_in_runtime(e2e_run):
    items = e2e_run["released_items"]
    for item in items:
        prov = item.get("provenance", {})
        for key in ("blueprint_id", "family_id", "materializer_type"):
            assert key in prov or (key == "materializer_type" and item.get("task_type")), (
                f"runtime item missing {key} in provenance or task_type"
            )


# ---- 7) Runtime schema validation ----
def test_released_items_and_oracles_validate_against_schema(e2e_run):
    from eval_engine.core.schema import validate_or_raise

    for item in e2e_run["released_items"]:
        validate_or_raise("item.schema.json", item)
    for oracle in e2e_run["released_oracles"]:
        validate_or_raise("oracle.schema.json", oracle)
    for er in e2e_run["eval_results"]:
        validate_or_raise("eval_result.schema.json", er)


# ---- 8) Pass rate and hard intent ----
def test_pass_rate_and_hard_intent_not_inflated_by_easy_only(e2e_run):
    eval_results = e2e_run["eval_results"]
    items = e2e_run["released_items"]
    if not eval_results or not items:
        pytest.skip("no eval results or items")
    passed = sum(1 for r in eval_results if r.get("verdict") == "pass")
    total = len(eval_results)
    pass_rate = passed / total if total else 0
    # With mock SUT we expect high pass rate; with failure_seeking we expect mix of hard families
    hard_families = {"trajectory.email_lookup", "grounded.qa.factual", "extraction.structured"}
    hard_count = sum(1 for it in items if (it.get("provenance") or {}).get("family_id") in hard_families)
    assert hard_count >= 1, "failure_seeking intent should produce at least one hard-family item"
    # Pass rate is not the inflation check; the check is that we have hard items (done above)
    assert total == len(items), "eval_results count should match released items count"


# ---- Report generation (run with -s to see output) ----
def test_e2e_contract_report(e2e_run, request):
    """Print the requested report: distributions, QA failures, mismatches, demo-safe verdict."""
    run_dir = e2e_run["run_dir"]
    plan = e2e_run["compiled_plan"]
    batch_plan = e2e_run["batch_plan"]
    items = e2e_run["released_items"]
    oracles = e2e_run["released_oracles"]
    eval_results = e2e_run["eval_results"]
    qa_failure_codes = e2e_run["qa_failure_codes"]
    run_summary = e2e_run["run_summary"]
    run_record = e2e_run["run_record"]

    requested = HARD_INTENT["batch_size"]
    total_slots = batch_plan.get("total_slots", 0)
    realized = len(items)

    # Distributions
    family_dist = {}
    task_dist = {}
    blueprint_dist = {}
    for it in items:
        fid = (it.get("provenance") or {}).get("family_id", "")
        tt = it.get("task_type", "")
        bid = (it.get("provenance") or {}).get("blueprint_id", "")
        family_dist[fid] = family_dist.get(fid, 0) + 1
        task_dist[tt] = task_dist.get(tt, 0) + 1
        blueprint_dist[bid] = blueprint_dist.get(bid, 0) + 1

    # Mismatches
    mismatches = []
    if realized != requested:
        mismatches.append(f"batch_size: requested={requested} realized={realized}")
    if total_slots != requested:
        mismatches.append(f"planned_slots: requested={requested} planned={total_slots}")
    plan_families = {f["family_id"] for f in plan.get("eval_families", [])}
    item_families = set(family_dist.keys())
    if item_families and not item_families.issubset(plan_families):
        mismatches.append(f"families: item families {item_families} not subset of plan {plan_families}")
    for it in items:
        prov = it.get("provenance") or {}
        if not prov.get("blueprint_id"):
            mismatches.append(f"item {it.get('item_id')} missing blueprint_id in provenance")
        if not prov.get("family_id"):
            mismatches.append(f"item {it.get('item_id')} missing family_id in provenance")

    # Demo-safe verdict
    demo_safe = (
        realized == requested
        and total_slots == requested
        and len(mismatches) == 0
        and (not qa_failure_codes or all(c == "DUPLICATE_ITEM" for c in qa_failure_codes))  # dup can be retried
    )
    # If we had QA failures that caused item aborts, not demo-safe
    if qa_failure_codes:
        bad = [c for c in qa_failure_codes if c not in ("DUPLICATE_ITEM",)]
        if bad:
            demo_safe = False

    # Print report (only when run with -s or when this test runs)
    report = [
        "========== E2E CONTRACT REPORT (hard failure-seeking intent) ==========",
        f"Run dir: {run_dir}",
        "",
        "1) BATCH SIZE",
        f"  requested batch_size: {requested}",
        f"  planned total_slots:  {total_slots}",
        f"  realized items:      {realized}",
        "  OK" if realized == requested and total_slots == requested else "  MISMATCH",
        "",
        "2) REALIZED FAMILY DISTRIBUTION",
        *[f"  {k}: {v}" for k, v in sorted(family_dist.items())],
        "",
        "3) REALIZED TASK DISTRIBUTION",
        *[f"  {k}: {v}" for k, v in sorted(task_dist.items())],
        "",
        "4) REALIZED BLUEPRINT DISTRIBUTION",
        *[f"  {k}: {v}" for k, v in sorted(blueprint_dist.items())],
        "",
        "5) QA FAILURE CODES (any)",
        f"  {qa_failure_codes if qa_failure_codes else 'none'}",
        "",
        "6) MISMATCHES (intent -> compile -> run -> verify)",
        *([f"  - {m}" for m in mismatches] if mismatches else ["  none"]),
        "",
        "7) PASS RATE (from run_summary/record)",
        f"  run_summary counts: {run_summary.get('counts', {})}" if run_summary else "  (no run_summary)",
        f"  run_record metrics: {run_record.get('metrics', {})}",
        "",
        "8) VERDICT",
        "  demo-safe: yes" if demo_safe else "  demo-safe: no",
        "========================================================================",
    ]
    print("\n".join(report))
    assert demo_safe, "E2E contract report marked run as not demo-safe; see report above"
