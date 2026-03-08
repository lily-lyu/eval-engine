"""
Item schema validation: ensure item.schema.json accepts judge_spec_id and remains
backward compatible with items that do not have it. Regression tests for A4 SCHEMA_INVALID
when generated items include top-level judge_spec_id.
"""
import pytest

from eval_engine.core.schema import validate_or_raise
from eval_engine.core.timeutil import now_iso


def _minimal_valid_item(*, with_judge_spec_id: bool = False) -> dict:
    """Minimal item that satisfies item.schema.json required fields."""
    item = {
        "item_id": "item_test_01",
        "dataset_spec_version": "1.0.0",
        "domain_tags": ["general"],
        "difficulty": "easy",
        "task_type": "json_extract_email",
        "prompt": "You MUST output valid JSON.\nTask: Extract the email.\nInput JSON: {\"text\": \"x\"}\nReturn JSON: {\"email\": \"...\"}\n",
        "input": {"text": "contact a@b.com"},
        "input_schema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
        "output_schema": {"type": "object", "properties": {"email": {"type": "string"}}, "required": ["email"]},
        "constraints": {
            "no_subjective_judgement": True,
            "safety_notes": "",
            "locked_fields": ["dataset_spec_version", "domain_tags", "difficulty", "task_type"],
        },
        "provenance": {
            "created_at": now_iso(),
            "created_by": "A1",
            "source": "synthetic",
        },
    }
    if with_judge_spec_id:
        item["judge_spec_id"] = "judge_extraction_email"
    return item


# ---- A) Item schema accepts judge_spec_id ----

def test_item_schema_accepts_judge_spec_id():
    """Minimal valid item with judge_spec_id validates against item.schema.json."""
    item = _minimal_valid_item(with_judge_spec_id=True)
    validate_or_raise("item.schema.json", item)


# ---- B) Item schema still accepts old items without judge_spec_id ----

def test_item_schema_accepts_item_without_judge_spec_id():
    """Minimal valid item without judge_spec_id still validates (backward compatibility)."""
    item = _minimal_valid_item(with_judge_spec_id=False)
    assert "judge_spec_id" not in item
    validate_or_raise("item.schema.json", item)


# ---- C) QA gate does not reject valid item solely because of judge_spec_id ----

def test_qa_gate_accepts_item_with_judge_spec_id():
    """QA schema gate passes for an otherwise-valid item that includes judge_spec_id."""
    from eval_engine.agents.a4_qa_gate import qa_check

    spec = {
        "dataset_name": "t",
        "dataset_spec_version": "1.0.0",
        "allowed_domain_tags": ["general"],
        "capability_targets": [],
        "defaults": {"max_prompt_length": 20000, "max_retries_per_stage": 2, "seed": 42},
    }
    item = _minimal_valid_item(with_judge_spec_id=True)
    oracle = {
        "item_id": item["item_id"],
        "eval_method": "exact_match",
        "expected": {"email": "a@b.com"},
        "method_justification": "Exact match.",
        "evidence_requirements": None,
        "leak_check": {"passed": True, "notes": ""},
        "created_at": now_iso(),
    }
    report = qa_check(spec, item, oracle, set())
    # Must not fail at schema gate with SCHEMA_INVALID due to judge_spec_id
    schema_gate = next(g for g in report["gates"] if g["gate"] == "schema")
    assert schema_gate["passed"] is True, f"Schema gate failed: {schema_gate.get('explanation')}"
