"""
Tests for duplicate-generation bottleneck fixes: blueprint diversity, materializer variation,
dedup fingerprint design, and QA duplicate report metadata.
"""
import random

import pytest

from eval_engine.agents.prompt_program_compiler import compile_prompt_blueprints, _blueprint_diversity_target
from eval_engine.agents.a1_item_generator import generate_item_from_blueprint, generate_item_from_target
from eval_engine.agents.a4_qa_gate import qa_check
from eval_engine.core.hashing import (
    compute_dedup_fingerprint,
    compute_dedup_fingerprint_inputs,
    normalize_prompt,
)
from eval_engine.agents.compile_pipeline import compile_intent_to_plan
from eval_engine.agents.compiler import compile_to_plan


# ---- A) Broad hard intent produces more blueprint diversity ----

def test_broad_intent_produces_multiple_families():
    """Compile a broad intent; assert multiple families appear."""
    intent = {
        "intent_name": "broad",
        "intent_spec_version": "1.0.0",
        "evaluation_goal": "Extraction, classification, trajectory.",
        "capability_focus": ["extraction", "classification", "trajectory"],
        "batch_size": 12,
        "defaults": {"seed": 42, "max_prompt_length": 20000, "max_retries_per_stage": 2},
    }
    plan = compile_intent_to_plan(intent, planner_mode="deterministic")
    families = plan["eval_families"]
    assert len(families) >= 2
    family_ids = {f["family_id"] for f in families}
    assert len(family_ids) == len(families)


def test_blueprint_diversity_target_increases_with_slot_weight():
    """When family slot_weight >= 2 we get >= 2 blueprints; when >= 4 we get >= 3."""
    intent = {"difficulty_mix": {}}
    assert _blueprint_diversity_target(1, intent) == 1
    assert _blueprint_diversity_target(2, intent) == 2
    assert _blueprint_diversity_target(4, intent) == 3
    intent_hard = {"difficulty_mix": {"hard": 5}}
    assert _blueprint_diversity_target(2, intent_hard) == 3


def test_deterministic_compiler_produces_multiple_blueprints_per_family_when_slots_allow():
    """With slot_weight >= 2, deterministic compiler produces >= 2 blueprints for that family."""
    families = [
        {
            "family_id": "extraction.email",
            "family_label": "Email",
            "objective": "Extract email.",
            "observable_targets": ["email"],
            "allowed_eval_methods": ["exact_match"],
            "difficulty": "easy",
            "slot_weight": 4,
            "materializer_type": "json_extract_email",
            "materializer_config": {},
            "dedup_group": "extraction.email",
            "failure_taxonomy": [],
        }
    ]
    intent_spec = {
        "intent_name": "x",
        "intent_spec_version": "1.0.0",
        "evaluation_goal": "G",
        "batch_size": 8,
        "difficulty_mix": {},
    }
    blueprints = compile_prompt_blueprints(families, intent_spec, mode="deterministic")
    assert len(blueprints) >= 2
    family_bps = [b for b in blueprints if b["family_id"] == "extraction.email"]
    assert len(family_bps) >= 2
    blueprint_ids = {b["blueprint_id"] for b in family_bps}
    assert len(blueprint_ids) == len(family_bps)


# ---- B) Materializer uses blueprint variation ----

def test_same_family_two_blueprints_different_structural_fingerprints():
    """Same family, two distinct blueprints; generated items have different structural fingerprints."""
    spec = {
        "dataset_name": "t",
        "dataset_spec_version": "1.0.0",
        "allowed_domain_tags": ["general"],
        "capability_targets": [],
        "defaults": {"max_prompt_length": 20000, "max_retries_per_stage": 2, "seed": 999},
    }
    bp1 = {
        "blueprint_id": "bp_email_v1",
        "family_id": "extraction.email",
        "blueprint_type": "json_extract_email",
        "materializer_type": "json_extract_email",
        "grounding_recipe": {"mode": "synthetic"},
    }
    bp2 = {
        "blueprint_id": "bp_email_v2",
        "family_id": "extraction.email",
        "blueprint_type": "json_extract_email",
        "materializer_type": "json_extract_email",
        "grounding_recipe": {"mode": "synthetic"},
    }
    rng1 = random.Random(42)
    rng2 = random.Random(43)
    item1 = generate_item_from_blueprint(spec, bp1, spec["dataset_spec_version"], rng1)
    item2 = generate_item_from_blueprint(spec, bp2, spec["dataset_spec_version"], rng2)
    item1["provenance"] = item1.get("provenance") or {}
    item1["provenance"]["blueprint_id"] = "bp_email_v1"
    item1["provenance"]["family_id"] = "extraction.email"
    item2["provenance"] = item2.get("provenance") or {}
    item2["provenance"]["blueprint_id"] = "bp_email_v2"
    item2["provenance"]["family_id"] = "extraction.email"
    h1, _ = compute_dedup_fingerprint(item1, include_structural=True)
    h2, _ = compute_dedup_fingerprint(item2, include_structural=True)
    assert h1 != h2


# ---- C) Dedup fingerprint: true duplicates vs distinct variants ----

def test_dedup_fingerprint_collapses_identical_skeleton():
    """Two items with same normalized prompt and same task_type/difficulty (no structural ids) collapse."""
    item = {
        "prompt": "You MUST output valid JSON.\nTask: Extract the email.\nInput JSON: {\"text\": \"Contact alex at a@b.com\"}\nReturn JSON: {\"email\": \"...\"}\n",
        "task_type": "json_extract_email",
        "difficulty": "easy",
        "provenance": {},
    }
    item2 = {**item, "prompt": item["prompt"].upper()}
    h1, inp1 = compute_dedup_fingerprint(item, include_structural=True)
    h2, inp2 = compute_dedup_fingerprint(item2, include_structural=True)
    assert normalize_prompt(item["prompt"]) == normalize_prompt(item2["prompt"])
    assert h1 == h2


def test_dedup_fingerprint_distinct_blueprints_do_not_collapse():
    """Same prompt text but different blueprint_id -> different fingerprint (structural uniqueness)."""
    base = {
        "prompt": "You MUST output valid JSON.\nTask: Extract the email.\nInput JSON: {\"text\": \"x\"}\nReturn JSON: {\"email\": \"...\"}\n",
        "task_type": "json_extract_email",
        "difficulty": "easy",
    }
    item1 = {**base, "provenance": {"blueprint_id": "bp_v1", "family_id": "extraction.email"}}
    item2 = {**base, "provenance": {"blueprint_id": "bp_v2", "family_id": "extraction.email"}}
    h1, _ = compute_dedup_fingerprint(item1, include_structural=True)
    h2, _ = compute_dedup_fingerprint(item2, include_structural=True)
    assert h1 != h2


# ---- D) Hard batch: capability_targets spread across blueprints ----

def test_compiled_plan_has_multiple_targets_per_family_when_multiple_blueprints():
    """Compiler produces one capability_target per blueprint, so slots spread across blueprints."""
    families = [
        {
            "family_id": "extraction.email",
            "family_label": "Email",
            "objective": "Extract email.",
            "observable_targets": ["email"],
            "allowed_eval_methods": ["exact_match"],
            "difficulty": "easy",
            "slot_weight": 4,
            "materializer_type": "json_extract_email",
            "materializer_config": {},
            "dedup_group": "extraction.email",
            "failure_taxonomy": [],
        }
    ]
    blueprints = compile_prompt_blueprints(
        families,
        {"intent_name": "x", "intent_spec_version": "1.0.0", "evaluation_goal": "G", "batch_size": 8},
        mode="deterministic",
    )
    judge_specs = [{"family_id": "extraction.email", "judge_spec_id": "judge_email", "eval_method": "exact_match", "method_justification": "J"}]
    intent_spec = {"intent_name": "x", "intent_spec_version": "1.0.0", "target_domain": ["general"]}
    plan = compile_to_plan(intent_spec, families, blueprints, judge_specs)
    targets = plan["compiled_dataset_spec"]["capability_targets"]
    email_targets = [t for t in targets if t.get("family_id") == "extraction.email"]
    assert len(email_targets) >= 2
    blueprint_ids = {t["blueprint_id"] for t in email_targets}
    assert len(blueprint_ids) == len(email_targets)


# ---- E) QA duplicate reports include explanatory metadata ----

def test_qa_duplicate_report_includes_duplicate_metadata():
    """When QA emits DUPLICATE_ITEM, report includes family_id, blueprint_id, materializer_type, fingerprint."""
    from eval_engine.core.timeutil import now_iso

    spec = {
        "dataset_name": "t",
        "dataset_spec_version": "1.0.0",
        "allowed_domain_tags": ["general"],
        "capability_targets": [{"target_id": "t1", "task_type": "json_extract_email", "difficulty": "easy", "quota_weight": 1}],
        "defaults": {"max_prompt_length": 20000, "max_retries_per_stage": 2, "seed": 42},
    }
    prompt_text = "You MUST output valid JSON.\nTask: Extract the email.\nInput JSON: {\"text\": \"contact a@b.com\"}\nReturn JSON: {\"email\": \"...\"}\n"
    base_item = {
        "item_id": "item_xxxx_01",
        "dataset_spec_version": "1.0.0",
        "domain_tags": ["general"],
        "difficulty": "easy",
        "task_type": "json_extract_email",
        "prompt": prompt_text,
        "input": {"text": "contact a@b.com"},
        "input_schema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
        "output_schema": {"type": "object", "properties": {"email": {"type": "string"}}, "required": ["email"]},
        "constraints": {"no_subjective_judgement": True, "safety_notes": "", "locked_fields": ["dataset_spec_version", "domain_tags", "difficulty", "task_type"]},
        "provenance": {
            "created_at": now_iso(),
            "created_by": "A1",
            "source": "synthetic",
            "blueprint_id": "bp_1",
            "family_id": "extraction.email",
            "materializer_type": "json_extract_email",
        },
    }
    oracle = {
        "item_id": "item_xxxx_01",
        "eval_method": "exact_match",
        "expected": {"email": "a@b.com"},
        "method_justification": "Exact match.",
        "evidence_requirements": None,
        "leak_check": {"passed": True, "notes": ""},
        "created_at": now_iso(),
    }
    seen_hashes = set()
    report1 = qa_check(spec, base_item, oracle, seen_hashes)
    assert report1["passed"] is True
    h, _ = compute_dedup_fingerprint(base_item, include_structural=True)
    seen_hashes.add(h)

    item2 = {**base_item, "item_id": "item_xxxx_02"}
    item2["provenance"] = {**base_item["provenance"]}
    oracle2 = {**oracle, "item_id": "item_xxxx_02"}
    report2 = qa_check(spec, item2, oracle2, seen_hashes)
    assert report2["passed"] is False
    assert report2["failure_code"] == "DUPLICATE_ITEM"
    assert "duplicate_metadata" in report2
    meta = report2["duplicate_metadata"]
    assert meta.get("family_id") == "extraction.email"
    assert meta.get("blueprint_id") == "bp_1"
    assert meta.get("materializer_type") == "json_extract_email"
    assert "dedup_fingerprint" in meta
    assert "fingerprint_inputs" in meta
