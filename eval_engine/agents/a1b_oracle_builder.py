import json
import re
from typing import Any, Dict, List, Optional

from ..core.timeutil import now_iso

# Deterministic methods first; schema_check before rubric_judge. unit_test omitted until implemented end-to-end.
METHOD_ORDER = [
    "programmatic_check",
    "exact_match",
    "trajectory_check",
    "schema_check",
    "rubric_judge",
]

# Must match SENTIMENT_TEMPLATES in a1_item_generator and tasks.mock_suts.SENTIMENT_MAPPING
SENTIMENT_MAPPING = {
    "I love this product. It works perfectly!": "positive",
    "This is amazing. Best purchase ever.": "positive",
    "Really happy with it. Exceeds expectations.": "positive",
    "Fantastic quality. Would buy again.": "positive",
    "Excellent service and product. Very pleased.": "positive",
    "Could not be happier. Highly recommend.": "positive",
    "Outstanding. Exactly what I needed.": "positive",
    "Great value. Delivered as described.": "positive",
    "Wonderful experience from start to finish.": "positive",
    "Top notch. No complaints at all.": "positive",
    "Superb. Will definitely order again.": "positive",
    "Impressive. Lives up to the hype.": "positive",
    "It is okay. Nothing special.": "neutral",
    "Average. Does the job.": "neutral",
    "Neither good nor bad. As expected.": "neutral",
    "Acceptable. No strong feelings either way.": "neutral",
    "Decent. Could be better could be worse.": "neutral",
    "Mediocre. Met basic expectations.": "neutral",
    "Fair. Nothing to write home about.": "neutral",
    "So-so. Standard quality.": "neutral",
    "Adequate. Serves its purpose.": "neutral",
    "Unremarkable. Middle of the road.": "neutral",
    "Run of the mill. Fine.": "neutral",
    "Moderate. Mixed experience.": "neutral",
    "This is terrible. Completely broken.": "negative",
    "Waste of money. Do not buy.": "negative",
    "Very disappointed. Poor quality.": "negative",
    "Broken on arrival. Useless.": "negative",
    "Awful. Returned immediately.": "negative",
    "Horrible experience. Regret buying.": "negative",
    "Worst purchase I have ever made.": "negative",
    "Defective. Customer service was no help.": "negative",
    "Cheap and flimsy. Fell apart.": "negative",
    "Not worth a penny. Avoid.": "negative",
    "Extremely poor. Total letdown.": "negative",
    "Rubbish. Would give zero stars if possible.": "negative",
    "Failed to work. Complete junk.": "negative",
}


def _can_programmatically_check(item: Dict[str, Any]) -> bool:
    from ..tasks.registry import get_task_registry

    task_type = item.get("task_type", "")
    registry = get_task_registry()
    return task_type in registry and registry[task_type].verifier_plan == "programmatic_check"


def _can_schema_check(item: Dict[str, Any]) -> bool:
    return True


def _can_exact_match(item: Dict[str, Any]) -> bool:
    from ..tasks.registry import get_task_registry

    task_type = item.get("task_type", "")
    registry = get_task_registry()
    return task_type in registry and registry[task_type].verifier_plan == "exact_match"


def _can_trajectory_check(item: Dict[str, Any]) -> bool:
    from ..tasks.registry import get_task_registry

    task_type = item.get("task_type", "")
    registry = get_task_registry()
    return task_type in registry and registry[task_type].verifier_plan == "trajectory_check"


def _explain_choice(item: Dict[str, Any], selected: str) -> str:
    """Short rationale for selecting this eval method."""
    reasons = {
        "programmatic_check": "Deterministic programmatic checker available; preferred over exact_match.",
        "schema_check": "No deterministic checker; validate output schema only.",
        "exact_match": "Deterministic expected value; exact_match suffices.",
        "trajectory_check": "Task requires tool-use trajectory; trajectory_check enforces sequence and bindings.",
        "rubric_judge": "No deterministic method applicable; fallback to rubric_judge with evidence_requirements.",
    }
    return reasons.get(selected, f"Selected {selected}.")


def _explain_rejections(
    item: Dict[str, Any], candidates: List[str], selected: str
) -> List[Dict[str, Any]]:
    """For each candidate we did not select, why we preferred the selected method."""
    rejected = [m for m in candidates if m != selected]
    return [
        {"method": m, "reason": f"Prefer {selected} (higher priority in method order)."}
        for m in rejected
    ]


def select_eval_method(item: Dict[str, Any]) -> Dict[str, Any]:
    """Select eval method from item capabilities; deterministic first, rubric_judge last."""
    candidates: List[str] = []
    if _can_programmatically_check(item):
        candidates.append("programmatic_check")
    if _can_schema_check(item):
        candidates.append("schema_check")
    if _can_exact_match(item):
        candidates.append("exact_match")
    if _can_trajectory_check(item):
        candidates.append("trajectory_check")
    candidates.append("rubric_judge")

    # Dedupe and order by METHOD_ORDER; select first
    seen: set = set()
    ordered: List[str] = []
    for m in METHOD_ORDER:
        if m in candidates and m not in seen:
            seen.add(m)
            ordered.append(m)
    selected = ordered[0] if ordered else "rubric_judge"

    return {
        "candidate_methods": ordered,
        "selected_method": selected,
        "selection_rationale": _explain_choice(item, selected),
        "rejected_methods": _explain_rejections(item, ordered, selected),
    }


def _leak_check(prompt: str, expected: Any) -> Dict[str, Any]:
    """
    Leak = the prompt contains the expected answer in a *completed* form.
    """
    s = prompt.lower()
    canon = json.dumps(expected, sort_keys=True, ensure_ascii=False, separators=(",", ":")).lower()
    notes = []
    if canon and canon in s:
        notes.append("canonical expected JSON appears in prompt")
    if isinstance(expected, dict):
        for k, v in expected.items():
            k_s = json.dumps(k, ensure_ascii=False).lower()
            v_s = json.dumps(v, ensure_ascii=False).lower()
            pair1 = f"{k_s}:{v_s}"
            pair2 = f"{k_s} : {v_s}"
            if pair1 in s or pair2 in s:
                notes.append(f"completed key/value pair leaked for key={k}")
    passed = len(notes) == 0
    return {"passed": passed, "notes": "; ".join(notes)[:2000]}


def _oracle_common(
    item: Dict[str, Any],
    expected: Any,
    eval_method: str,
    justification: str,
    evidence_requirements: Any = None,
    checker_name: Optional[str] = None,
    checker_config: Optional[Dict[str, Any]] = None,
    failure_taxonomy: Optional[List[str]] = None,
    canonicalization_rules: Optional[List[Any]] = None,
) -> Dict[str, Any]:
    leak = _leak_check(item["prompt"], expected)
    out = {
        "item_id": item["item_id"],
        "eval_method": eval_method,
        "expected": expected,
        "method_justification": justification,
        "evidence_requirements": evidence_requirements,
        "leak_check": leak,
        "created_at": now_iso(),
    }
    if checker_name is not None:
        out["checker_name"] = checker_name
    if checker_config is not None:
        out["checker_config"] = checker_config
    if failure_taxonomy is not None:
        out["failure_taxonomy"] = failure_taxonomy
    if canonicalization_rules is not None:
        out["canonicalization_rules"] = canonicalization_rules
    return out


def build_add_oracle(item: Dict[str, Any]) -> Dict[str, Any]:
    inp = item["input"]
    expected = {"answer": int(inp["a"]) + int(inp["b"])}
    return _oracle_common(
        item,
        expected,
        "programmatic_check",
        "Deterministic numeric relation; prefer programmatic_check over exact_match.",
        None,
        checker_name="math_add_v1",
        checker_config={"input_keys": ["a", "b"], "output_key": "answer"},
        failure_taxonomy=["PROGRAMMATIC_CHECK_FAILED"],
    )


def build_email_oracle(item: Dict[str, Any]) -> Dict[str, Any]:
    inp = item["input"]
    m = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", inp["text"])
    expected = {"email": m.group(0) if m else ""}
    return _oracle_common(
        item,
        expected,
        "exact_match",
        "Deterministic extraction from input text; exact_match against extracted email.",
        None,
        failure_taxonomy=["EXACT_MATCH_FAILED"],
    )


def build_sentiment_oracle(item: Dict[str, Any]) -> Dict[str, Any]:
    inp = item["input"]
    expected = {"label": SENTIMENT_MAPPING.get(inp["text"], "neutral")}
    return _oracle_common(
        item,
        expected,
        "exact_match",
        "Closed-set classification with deterministic label mapping for curated texts.",
        None,
        failure_taxonomy=["EXACT_MATCH_FAILED"],
    )


def build_structured_extraction_oracle(item: Dict[str, Any]) -> Dict[str, Any]:
    """Oracle for json_extract_structured: expected email + name, checker_config field_normalize."""
    inp = item["input"]
    text = inp["text"]
    email_m = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
    email = email_m.group(0) if email_m else ""
    # "Contact Name at email" -> capture name (word before " at ")
    name_m = re.search(r"Contact\s+(\w+)\s+at\s+", text, re.IGNORECASE)
    name = name_m.group(1).capitalize() if name_m else ""
    expected = {"email": email, "name": name}
    return _oracle_common(
        item,
        expected,
        "programmatic_check",
        "Structured extraction: schema + field correctness with optional normalization.",
        None,
        checker_name="structured_extraction_v1",
        checker_config={"field_normalize": {"email": "strip_lower", "name": "strip"}},
        failure_taxonomy=["PROGRAMMATIC_CHECK_FAILED"],
    )


def build_classify_canonical_oracle(item: Dict[str, Any]) -> Dict[str, Any]:
    """Oracle for json_classify_canonical: label set + canonicalization rules."""
    inp = item["input"]
    expected = {"label": SENTIMENT_MAPPING.get(inp["text"], "neutral")}
    return _oracle_common(
        item,
        expected,
        "programmatic_check",
        "Classification with label set enforcement and canonicalization (e.g. Positive -> positive).",
        None,
        checker_name="classification_canonical_v1",
        checker_config={"allowed_labels": ["positive", "neutral", "negative"]},
        failure_taxonomy=["PROGRAMMATIC_CHECK_FAILED"],
        canonicalization_rules=[
            {"from": "Positive", "to": "positive"},
            {"from": "Neutral", "to": "neutral"},
            {"from": "Negative", "to": "negative"},
        ],
    )


def build_trajectory_oracle(item: Dict[str, Any]) -> Dict[str, Any]:
    expected = {
        "required_first": ["search_email_db"],
        "required_sequence": ["search_email_db"],
        "must_include": ["search_email_db"],
        "max_calls": {"search_email_db": 1},
        "arg_schema": {
            "tool": "search_email_db",
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["query"],
                "properties": {"query": {"type": "string", "minLength": 3, "maxLength": 200}},
            },
        },
        "bindings": [
            {"tool": "search_email_db", "tool_path": "$.email", "output_path": "$.email"},
        ],
    }
    return _oracle_common(
        item,
        expected,
        "trajectory_check",
        "Tool-use trajectory required: search_email_db exactly once, then final answer; arg_schema + bindings enforce correctness and groundedness.",
        None,
        failure_taxonomy=["TRAJECTORY_CHECK_FAILED"],
    )


def build_oracle(item: Dict[str, Any]) -> Dict[str, Any]:
    from ..tasks.registry import get_task_registry

    sel = select_eval_method(item)
    task_type = item.get("task_type", "")
    registry = get_task_registry()

    if task_type in registry:
        task_def = registry[task_type]
        oracle = task_def.oracle_builder(item)
        if getattr(task_def, "checker_name", None) and "checker_name" not in oracle:
            oracle["checker_name"] = task_def.checker_name
    else:
        oracle = _oracle_common(
            item,
            None,
            "schema_check",
            "Fallback to schema_check.",
            None,
        )

    oracle["eval_method"] = sel["selected_method"]
    oracle["candidate_methods"] = sel["candidate_methods"]
    oracle["selection_rationale"] = sel["selection_rationale"]
    oracle["rejected_methods"] = sel["rejected_methods"]
    return oracle


def build_factual_grounded_qa_oracle(item: Dict[str, Any]) -> Dict[str, Any]:
    """Oracle for web_grounded (answer) or image_grounded (description) factual QA."""
    inp = item["input"]
    if "context" in inp:
        expected = {"answer": inp.get("context", "")}
    elif "image_description" in inp:
        expected = {"description": inp.get("image_description", "")}
    else:
        expected = {"answer": ""}
    return _oracle_common(
        item,
        expected,
        "exact_match",
        "Factual grounded QA: exact_match on answer or description from grounding.",
        None,
        failure_taxonomy=["EXACT_MATCH_FAILED"],
    )
