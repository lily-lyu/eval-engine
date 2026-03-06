"""
QA gate: evaluability checks. Ensures task_type is in spec, eval_method is machine-checkable,
oracle doesn't leak, output schema is scoreable; rubric_judge requires evidence_requirements.
Optional: subjective keyword scan only on instruction header (not embedded input).
"""
from typing import Any, Dict, Set

from ..core.failure_codes import (
    DISALLOWED_DOMAIN_TAG,
    DUPLICATE_ITEM,
    ORACLE_LEAK,
    PROMPT_TOO_LONG,
    SCHEMA_INVALID,
    SUBJECTIVE_TASK,
)
from ..core.hashing import normalize_prompt, sha256_json
from ..core.timeutil import now_iso
from ..core.schema import validate_or_raise

# Machine-checkable eval methods (no human judgement required for scoring)
MACHINE_CHECKABLE_METHODS = frozenset({
    "schema_check",
    "exact_match",
    "programmatic_check",
    "trajectory_check",
})

# Optional: only scan instruction header for these (not embedded input content)
SUBJECTIVE_KEYWORDS_INSTRUCTION_ONLY = [
    "prefer the prettier", "which looks better", "how do you feel about",
    "vibe check", "in your opinion which", "more aesthetically pleasing",
]


def _allowed_task_types(spec: Dict[str, Any]) -> Set[str]:
    return {t["task_type"] for t in spec.get("capability_targets", [])}


def _instruction_header(prompt: str, max_chars: int = 500) -> str:
    """Prefix of prompt before embedded input payload, to avoid flagging input content."""
    for sep in ("Input JSON:", "input json:", "\nInput ", "\ninput "):
        idx = prompt.find(sep)
        if idx != -1:
            return prompt[:idx].strip()
    return prompt[:max_chars].strip()


def qa_check(
    spec: Dict[str, Any],
    item: Dict[str, Any],
    oracle: Dict[str, Any],
    seen_prompt_hashes: Set[str],
) -> Dict[str, Any]:
    # Gate 1: Schema
    try:
        validate_or_raise("item.schema.json", item)
        validate_or_raise("oracle.schema.json", oracle)
    except Exception as e:
        return {
            "item_id": item.get("item_id", ""),
            "passed": False,
            "stage": "QA_GATE/SCHEMA",
            "failure_code": SCHEMA_INVALID,
            "explanation": str(e),
            "patch_instructions": "Fix the JSON to match schema exactly. Do not add extra fields.",
            "created_at": now_iso(),
        }

    # Gate 2: Evaluability
    allowed_tags = set(spec["allowed_domain_tags"])
    for t in item["domain_tags"]:
        if t not in allowed_tags:
            return {
                "item_id": item["item_id"],
                "passed": False,
                "stage": "QA_GATE/EVALUABILITY",
                "failure_code": DISALLOWED_DOMAIN_TAG,
                "explanation": f"domain_tag '{t}' not in allowed_domain_tags",
                "patch_instructions": "Change domain_tags to an allowed tag WITHOUT changing task intent.",
                "created_at": now_iso(),
            }

    allowed_tasks = _allowed_task_types(spec)
    task_type = item.get("task_type", "")
    if task_type not in allowed_tasks:
        return {
            "item_id": item["item_id"],
            "passed": False,
            "stage": "QA_GATE/EVALUABILITY",
            "failure_code": SCHEMA_INVALID,
            "explanation": f"task_type '{task_type}' not in spec capability_targets",
            "patch_instructions": "Use a task_type from spec.capability_targets.",
            "created_at": now_iso(),
        }

    eval_method = oracle.get("eval_method", "")
    if eval_method not in MACHINE_CHECKABLE_METHODS and eval_method != "rubric_judge":
        return {
            "item_id": item["item_id"],
            "passed": False,
            "stage": "QA_GATE/EVALUABILITY",
            "failure_code": SCHEMA_INVALID,
            "explanation": f"eval_method '{eval_method}' not allowed or not machine-checkable",
            "patch_instructions": "Use programmatic_check, exact_match, trajectory_check, schema_check, or rubric_judge with evidence_requirements.",
            "created_at": now_iso(),
        }

    if eval_method == "rubric_judge":
        if not oracle.get("evidence_requirements"):
            return {
                "item_id": item["item_id"],
                "passed": False,
                "stage": "QA_GATE/EVALUABILITY",
                "failure_code": SCHEMA_INVALID,
                "explanation": "rubric_judge requires evidence_requirements to be set",
                "patch_instructions": "Set oracle.evidence_requirements so the judge is verifiable.",
                "created_at": now_iso(),
            }

    output_schema = item.get("output_schema")
    if not isinstance(output_schema, dict) or not (output_schema.get("type") or output_schema.get("properties")):
        return {
            "item_id": item["item_id"],
            "passed": False,
            "stage": "QA_GATE/EVALUABILITY",
            "failure_code": SCHEMA_INVALID,
            "explanation": "output_schema must be closed/scoreable (type or properties)",
            "patch_instructions": "Define output_schema with type and/or properties.",
            "created_at": now_iso(),
        }

    max_len = spec["defaults"]["max_prompt_length"]
    if len(item["prompt"]) > max_len:
        return {
            "item_id": item["item_id"],
            "passed": False,
            "stage": "QA_GATE/EVALUABILITY",
            "failure_code": PROMPT_TOO_LONG,
            "explanation": f"prompt length {len(item['prompt'])} exceeds max_prompt_length {max_len}",
            "patch_instructions": "Shorten prompt while preserving objective scoring.",
            "created_at": now_iso(),
        }

    if oracle.get("leak_check", {}).get("passed") is False:
        return {
            "item_id": item["item_id"],
            "passed": False,
            "stage": "QA_GATE/EVALUABILITY",
            "failure_code": ORACLE_LEAK,
            "explanation": f"oracle leak_check failed: {oracle['leak_check']['notes']}",
            "patch_instructions": "Regenerate item/oracle so expected answer isn't exposed in prompt.",
            "created_at": now_iso(),
        }

    # Optional: subjective keywords only in instruction header (not input payload)
    header = _instruction_header(item["prompt"]).lower()
    if any(k in header for k in SUBJECTIVE_KEYWORDS_INSTRUCTION_ONLY):
        return {
            "item_id": item["item_id"],
            "passed": False,
            "stage": "QA_GATE/EVALUABILITY",
            "failure_code": SUBJECTIVE_TASK,
            "explanation": "instruction header includes subjective/taste phrasing => not objectively scorable",
            "patch_instructions": "Rewrite instructions to be objectively scorable; keep subjective content only in input payload if needed.",
            "created_at": now_iso(),
        }

    # Gate 3: Stat (dedup)
    norm = normalize_prompt(item["prompt"])
    h = sha256_json({"prompt": norm, "task_type": item["task_type"], "difficulty": item["difficulty"]})
    if h in seen_prompt_hashes:
        return {
            "item_id": item["item_id"],
            "passed": False,
            "stage": "QA_GATE/STAT",
            "failure_code": DUPLICATE_ITEM,
            "explanation": "duplicate prompt skeleton detected",
            "patch_instructions": "Regenerate item with different input parameters or different surface form.",
            "created_at": now_iso(),
        }

    seen_prompt_hashes.add(h)

    return {
        "item_id": item["item_id"],
        "passed": True,
        "stage": "QA_GATE",
        "failure_code": "",
        "explanation": "PASS",
        "patch_instructions": "",
        "created_at": now_iso(),
    }
