"""Frozen break suite data: one row per scenario. Used to generate examples/break_suite.jsonl."""

from typing import Any, Dict, List

# Base item/oracle fields reused across scenarios
_COMMON_ITEM = {
    "dataset_spec_version": "1.0.0",
    "domain_tags": ["math"],
    "difficulty": "easy",
    "task_type": "json_math_add",
    "input": {"a": 1, "b": 2},
    "input_schema": {"type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}}, "required": ["a", "b"]},
    "output_schema": {"type": "object", "additionalProperties": False, "required": ["answer"], "properties": {"answer": {"type": "integer"}}},
    "constraints": {"no_subjective_judgement": True, "safety_notes": "", "locked_fields": ["dataset_spec_version", "domain_tags", "difficulty", "task_type"]},
    "provenance": {"created_at": "2026-03-06T00:00:00+00:00", "created_by": "break_suite", "source": "synthetic"},
}
_COMMON_ORACLE = {
    "method_justification": "Break suite.",
    "evidence_requirements": None,
    "created_at": "2026-03-06T00:00:00+00:00",
}


def _item(item_id: str, **overrides) -> Dict[str, Any]:
    out = {**_COMMON_ITEM, "item_id": item_id, "prompt": "Add the two numbers.", **overrides}
    return out


def _oracle(item_id: str, eval_method: str, expected: Any, **overrides) -> Dict[str, Any]:
    leak = overrides.pop("leak_check", {"passed": True, "notes": ""})
    out = {**_COMMON_ORACLE, "item_id": item_id, "eval_method": eval_method, "expected": expected, "leak_check": leak, **overrides}
    return out


def build_break_suite_rows() -> List[Dict[str, Any]]:
    return [
        {
            "scenario_id": "wrong_checker_name",
            "item": _item("break_wrong_checker", prompt="Add a and b.", task_type="json_math_add"),
            "oracle": _oracle("break_wrong_checker", "programmatic_check", {"answer": 3}, checker_name="nonexistent_checker_xyz"),
            "raw_output": '{"answer": 3}',
            "expected_error_type": "EVAL_METHOD_UNSUPPORTED",
            "expected_evidence_code": "UNKNOWN_CHECKER",
        },
        {
            "scenario_id": "unsupported_eval_method",
            "item": _item("break_unsupported_method", prompt="Add a and b.", task_type="json_math_add"),
            "oracle": _oracle("break_unsupported_method", "unit_test", {"answer": 3}),
            "raw_output": '{"answer": 3}',
            "expected_error_type": "EVAL_METHOD_UNSUPPORTED",
            "expected_evidence_code": "UNSUPPORTED_EVAL_METHOD",
        },
        {
            "scenario_id": "schema_invalid_output",
            "item": _item(
                "break_schema_invalid",
                task_type="json_extract_email",
                domain_tags=["extraction"],
                prompt="Extract email from: contact bob@example.com",
                input={"text": "contact bob@example.com"},
                input_schema={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
                output_schema={"type": "object", "additionalProperties": False, "required": ["email"], "properties": {"email": {"type": "string"}}},
            ),
            "oracle": _oracle("break_schema_invalid", "exact_match", {"email": "bob@example.com"}),
            "raw_output": "not valid json at all",
            "expected_error_type": "MODEL_OUTPUT_NOT_JSON",
        },
        {
            "scenario_id": "exact_match_wrong_answer",
            "item": _item(
                "break_exact_match",
                task_type="json_extract_email",
                domain_tags=["extraction"],
                prompt="Extract email.",
                input={"text": "Email: ok@example.com"},
                input_schema={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
                output_schema={"type": "object", "additionalProperties": False, "required": ["email"], "properties": {"email": {"type": "string"}}},
            ),
            "oracle": _oracle("break_exact_match", "exact_match", {"email": "ok@example.com"}),
            "raw_output": '{"email": "wrong@example.com"}',
            "expected_error_type": "EXACT_MATCH_FAILED",
            "expected_evidence_code": "EXACT_MATCH_FAILED",
        },
        {
            "scenario_id": "trajectory_missing_first_tool",
            "item": _item(
                "break_traj_first",
                task_type="trajectory_email_then_answer",
                domain_tags=["trajectory"],
                prompt="Use search_contacts then return email.",
                input={"query": "find alice"},
                input_schema={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
                output_schema={"type": "object", "additionalProperties": False, "required": ["email"], "properties": {"email": {"type": "string"}}},
            ),
            "oracle": _oracle(
                "break_traj_first",
                "trajectory_check",
                {"required_first": ["search_contacts"], "bindings": []},
            ),
            "raw_output": '{"email": "a@b.co"}',
            "tool_trace": [],
            "expected_error_type": "TRAJECTORY_CHECK_FAILED",
            "expected_evidence_code": "TOOL_SEQUENCE_MISSING",
        },
        {
            "scenario_id": "trajectory_wrong_tool_args",
            "item": _item(
                "break_traj_args",
                task_type="trajectory_email_then_answer",
                domain_tags=["trajectory"],
                prompt="Use search_email_db with query.",
                input={"query": "find bob"},
                input_schema={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
                output_schema={"type": "object", "additionalProperties": False, "required": ["email"], "properties": {"email": {"type": "string"}}},
            ),
            "oracle": _oracle(
                "break_traj_args",
                "trajectory_check",
                {
                    "required_first": ["search_email_db"],
                    "arg_schema": {
                        "tool": "search_email_db",
                        "schema": {"type": "object", "additionalProperties": False, "required": ["query"], "properties": {"query": {"type": "string", "minLength": 3, "maxLength": 200}}},
                    },
                    "bindings": [],
                },
            ),
            "raw_output": '{"email": "bob@example.com"}',
            "tool_trace": [{"name": "search_email_db", "args": {"query": "x"}, "result": {"email": "bob@example.com"}}],
            "expected_error_type": "TRAJECTORY_CHECK_FAILED",
            "expected_evidence_code": "TOOL_ARGS_SCHEMA_FAILED",
        },
        {
            "scenario_id": "tool_binding_mismatch",
            "item": _item(
                "break_traj_binding",
                task_type="trajectory_email_then_answer",
                domain_tags=["trajectory"],
                prompt="Call tool then put result in output.",
                input={"q": "x"},
                input_schema={"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]},
                output_schema={"type": "object", "additionalProperties": False, "required": ["email"], "properties": {"email": {"type": "string"}}},
            ),
            "oracle": _oracle(
                "break_traj_binding",
                "trajectory_check",
                {
                    "required_first": ["search_email_db"],
                    "bindings": [{"tool": "search_email_db", "tool_path": "$.email", "output_path": "$.email"}],
                },
            ),
            "raw_output": '{"email": "hallucinated@wrong.com"}',
            "tool_trace": [{"name": "search_email_db", "args": {"query": "alice"}, "result": {"email": "alice@tool.com"}}],
            "expected_error_type": "TRAJECTORY_CHECK_FAILED",
            "expected_evidence_code": "TOOL_BINDING_MISMATCH",
        },
        {
            "scenario_id": "rubric_missing_evidence_requirements",
            "item": _item(
                "break_rubric_no_ev",
                task_type="json_classify_sentiment",
                domain_tags=["classification"],
                prompt="Classify sentiment.",
                input={"text": "It is okay."},
                input_schema={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
                output_schema={"type": "object", "additionalProperties": False, "required": ["label"], "properties": {"label": {"type": "string", "enum": ["positive", "neutral", "negative"]}}},
            ),
            "oracle": _oracle("break_rubric_no_ev", "rubric_judge", {"label": "neutral"}, evidence_requirements=None),
            "expected_qa_failure_code": "RUBRIC_INCOMPLETE",
        },
        {
            "scenario_id": "answer_leakage_into_prompt",
            "item": _item(
                "break_leak",
                prompt="The answer is 42. What is a+b?",
                input={"a": 1, "b": 2},
            ),
            "oracle": _oracle("break_leak", "exact_match", {"answer": 42}, leak_check={"passed": False, "notes": "canonical expected JSON appears in prompt"}),
            "expected_qa_failure_code": "ORACLE_LEAK",
        },
        # ---- structured extraction (programmatic_check structured_extraction_v1) ----
        {
            "scenario_id": "structured_extraction_pass",
            "item": _item(
                "break_structured_pass",
                task_type="json_extract_structured",
                domain_tags=["extraction"],
                prompt="Extract fields from text.",
                input={"text": "Name: Alice; Email: alice@example.com; Company: Acme"},
                input_schema={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
                output_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["name", "email", "company"],
                    "properties": {
                        "name": {"type": "string"},
                        "email": {"type": "string"},
                        "company": {"type": "string"},
                    },
                },
            ),
            "oracle": _oracle(
                "break_structured_pass",
                "programmatic_check",
                {"name": "Alice", "email": "alice@example.com", "company": "Acme"},
                checker_name="structured_extraction_v1",
                checker_config={"field_normalize": {"email": "strip_lower", "name": "strip", "company": "strip"}},
            ),
            "raw_output": '{"name":"Alice","email":"alice@example.com","company":"Acme"}',
            "expected_verdict": "pass",
        },
        {
            "scenario_id": "structured_extraction_fail",
            "item": _item(
                "break_structured_fail",
                task_type="json_extract_structured",
                domain_tags=["extraction"],
                prompt="Extract fields from text.",
                input={"text": "Name: Alice; Email: alice@example.com; Company: Acme"},
                input_schema={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
                output_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["name", "email", "company"],
                    "properties": {
                        "name": {"type": "string"},
                        "email": {"type": "string"},
                        "company": {"type": "string"},
                    },
                },
            ),
            "oracle": _oracle(
                "break_structured_fail",
                "programmatic_check",
                {"name": "Alice", "email": "alice@example.com", "company": "Acme"},
                checker_name="structured_extraction_v1",
            ),
            "raw_output": '{"name":"Alice","email":"wrong@example.com","company":"Acme"}',
            "expected_verdict": "fail",
            "expected_error_type": "PROGRAMMATIC_CHECK_FAILED",
        },
        # ---- canonical classification (programmatic_check classification_canonical_v1) ----
        {
            "scenario_id": "canonical_classification_pass",
            "item": _item(
                "break_canonical_pass",
                task_type="json_classify_canonical",
                domain_tags=["classification"],
                prompt="Classify into canonical label.",
                input={"text": "I loved it."},
                input_schema={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
                output_schema={"type": "object", "additionalProperties": False, "required": ["label"], "properties": {"label": {"type": "string"}}},
            ),
            "oracle": _oracle(
                "break_canonical_pass",
                "programmatic_check",
                {"label": "positive"},
                checker_name="classification_canonical_v1",
                checker_config={"allowed_labels": ["positive", "neutral", "negative"]},
                canonicalization_rules=[{"from": "Positive", "to": "positive"}, {"from": "Neutral", "to": "neutral"}, {"from": "Negative", "to": "negative"}],
            ),
            "raw_output": '{"label":"Positive"}',
            "expected_verdict": "pass",
        },
        {
            "scenario_id": "canonical_classification_fail",
            "item": _item(
                "break_canonical_fail",
                task_type="json_classify_canonical",
                domain_tags=["classification"],
                prompt="Classify into canonical label.",
                input={"text": "Mixed feelings."},
                input_schema={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
                output_schema={"type": "object", "additionalProperties": False, "required": ["label"], "properties": {"label": {"type": "string"}}},
            ),
            "oracle": _oracle(
                "break_canonical_fail",
                "programmatic_check",
                {"label": "neutral"},
                checker_name="classification_canonical_v1",
                checker_config={"allowed_labels": ["positive", "neutral", "negative"]},
            ),
            "raw_output": '{"label":"mixed"}',
            "expected_verdict": "fail",
            "expected_error_type": "PROGRAMMATIC_CHECK_FAILED",
        },
    ]
