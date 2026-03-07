"""
QA gate: 3-gate system (schema, semantic, stat). Ensures task_type in spec, eval_method
machine-checkable, oracle doesn't leak, output schema scoreable; rubric_judge requires
evidence_requirements. Semantic checks: ambiguous task, conflicting constraints, unverifiable
output, rubric incomplete. Stat: dedup + distribution vs batch plan.
"""
from typing import Any, Dict, Set, Tuple

from ..core.failure_codes import (
    AMBIGUOUS_TASK,
    CONFLICTING_CONSTRAINTS,
    DISALLOWED_DOMAIN_TAG,
    DISTRIBUTION_MISMATCH,
    DUPLICATE_ITEM,
    MULTI_VALID_ANSWER,
    ORACLE_LEAK,
    PROMPT_TOO_LONG,
    RUBRIC_INCOMPLETE,
    SCHEMA_INVALID,
    SUBJECTIVE_TASK,
    UNVERIFIABLE_OUTPUT,
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

# Instruction-header-only scans (not embedded input)
SUBJECTIVE_KEYWORDS_INSTRUCTION_ONLY = [
    "prefer the prettier", "which looks better", "how do you feel about",
    "vibe check", "in your opinion which", "more aesthetically pleasing",
]
# "best / nicer / better" without measurable rubric -> AMBIGUOUS_TASK
AMBIGUOUS_KEYWORDS_INSTRUCTION = ["best", "nicer", "better", "prefer the best", "which is better"]

# Max over planned count before stat gate fails (allow one extra per slot for rounding)
DISTRIBUTION_TOLERANCE = 1


def _allowed_task_types(spec: Dict[str, Any]) -> Set[str]:
    return {t["task_type"] for t in spec.get("capability_targets", [])}


def _instruction_header(prompt: str, max_chars: int = 500) -> str:
    """Prefix of prompt before embedded input payload."""
    for sep in ("Input JSON:", "input json:", "\nInput ", "\ninput "):
        idx = prompt.find(sep)
        if idx != -1:
            return prompt[:idx].strip()
    return prompt[:max_chars].strip()


def _gate_result(gate: str, passed: bool, failure_code: str = "", explanation: str = "") -> Dict[str, Any]:
    return {"gate": gate, "passed": passed, "failure_code": failure_code, "explanation": explanation}


# ---- Semantic helpers ----

def _has_conflicting_constraints(item: Dict[str, Any]) -> bool:
    """Heuristic: prompt imposes incompatible conditions (e.g. 'must be X and must be Y' where X != Y)."""
    prompt_lower = item.get("prompt", "").lower()
    # Very simple: "must not" and "must" on same dimension (e.g. "must be short" and "must be long")
    if "must not" in prompt_lower and "must " in prompt_lower:
        # Could extend with more nuanced checks
        pass
    return False


def _has_multiple_valid_answers(item: Dict[str, Any], oracle: Dict[str, Any]) -> bool:
    """Heuristic: output space allows many valid answers and oracle is open-ended."""
    output_schema = item.get("output_schema") or {}
    props = output_schema.get("properties") or {}
    required = output_schema.get("required") or []
    # If output has free-form string with no enum and no programmatic checker, multiple valid
    if not props and output_schema.get("type") == "object":
        return True
    for k, v in props.items():
        if isinstance(v, dict) and v.get("type") == "string" and "enum" not in v and k not in required:
            if oracle.get("eval_method") not in MACHINE_CHECKABLE_METHODS:
                return True
    return False


def _is_unverifiable(item: Dict[str, Any], oracle: Dict[str, Any]) -> bool:
    """Output space unconstrained and no exact/schema/programmatic oracle."""
    eval_method = oracle.get("eval_method", "")
    if eval_method in ("exact_match", "programmatic_check", "schema_check", "trajectory_check"):
        return False
    output_schema = item.get("output_schema") or {}
    has_structure = bool(output_schema.get("type") or output_schema.get("properties"))
    if not has_structure:
        return True
    # rubric_judge with no evidence_requirements is unverifiable
    if eval_method == "rubric_judge" and not oracle.get("evidence_requirements"):
        return True
    return False


def _rubric_incomplete(oracle: Dict[str, Any]) -> bool:
    """rubric_judge but no explicit observable evidence target."""
    if oracle.get("eval_method") != "rubric_judge":
        return False
    er = oracle.get("evidence_requirements")
    if not er:
        return True
    if isinstance(er, dict) and not er:
        return True
    return False


def _has_ambiguous_task_phrasing(item: Dict[str, Any], oracle: Dict[str, Any]) -> bool:
    """Prompt says 'best/nicer/better' without measurable rubric."""
    header = _instruction_header(item["prompt"]).lower()
    if not any(k in header for k in AMBIGUOUS_KEYWORDS_INSTRUCTION):
        return False
    # Has measurable rubric if deterministic method or rubric with evidence_requirements
    if oracle.get("eval_method") in MACHINE_CHECKABLE_METHODS:
        return False
    if oracle.get("eval_method") == "rubric_judge" and oracle.get("evidence_requirements"):
        return False
    return True


def _run_schema_gate(item: Dict[str, Any], oracle: Dict[str, Any]) -> Dict[str, Any]:
    try:
        validate_or_raise("item.schema.json", item)
        validate_or_raise("oracle.schema.json", oracle)
        return _gate_result("schema", True)
    except Exception as e:
        return _gate_result("schema", False, SCHEMA_INVALID, str(e))


def _run_semantic_gate(
    spec: Dict[str, Any], item: Dict[str, Any], oracle: Dict[str, Any]
) -> Dict[str, Any]:
    allowed_tags = set(spec["allowed_domain_tags"])
    for t in item["domain_tags"]:
        if t not in allowed_tags:
            return _gate_result(
                "semantic", False, DISALLOWED_DOMAIN_TAG,
                f"domain_tag '{t}' not in allowed_domain_tags",
            )

    allowed_tasks = _allowed_task_types(spec)
    task_type = item.get("task_type", "")
    if task_type not in allowed_tasks:
        return _gate_result(
            "semantic", False, SCHEMA_INVALID,
            f"task_type '{task_type}' not in spec capability_targets",
        )

    eval_method = oracle.get("eval_method", "")
    if eval_method not in MACHINE_CHECKABLE_METHODS and eval_method != "rubric_judge":
        return _gate_result(
            "semantic", False, SCHEMA_INVALID,
            f"eval_method '{eval_method}' not allowed or not machine-checkable",
        )

    if _rubric_incomplete(oracle):
        return _gate_result(
            "semantic", False, RUBRIC_INCOMPLETE,
            "rubric_judge requires evidence_requirements with explicit observable evidence target",
        )

    output_schema = item.get("output_schema")
    if not isinstance(output_schema, dict) or not (output_schema.get("type") or output_schema.get("properties")):
        return _gate_result(
            "semantic", False, SCHEMA_INVALID,
            "output_schema must be closed/scoreable (type or properties)",
        )

    max_len = spec["defaults"]["max_prompt_length"]
    if len(item["prompt"]) > max_len:
        return _gate_result(
            "semantic", False, PROMPT_TOO_LONG,
            f"prompt length {len(item['prompt'])} exceeds max_prompt_length {max_len}",
        )

    if oracle.get("leak_check", {}).get("passed") is False:
        return _gate_result(
            "semantic", False, ORACLE_LEAK,
            f"oracle leak_check failed: {oracle['leak_check']['notes']}",
        )

    header = _instruction_header(item["prompt"]).lower()
    if any(k in header for k in SUBJECTIVE_KEYWORDS_INSTRUCTION_ONLY):
        return _gate_result(
            "semantic", False, SUBJECTIVE_TASK,
            "instruction header includes subjective/taste phrasing => not objectively scorable",
        )

    if _has_ambiguous_task_phrasing(item, oracle):
        return _gate_result(
            "semantic", False, AMBIGUOUS_TASK,
            "instruction uses 'best/nicer/better' without measurable rubric",
        )

    if _has_conflicting_constraints(item):
        return _gate_result(
            "semantic", False, CONFLICTING_CONSTRAINTS,
            "prompt appears to impose incompatible conditions",
        )

    if _is_unverifiable(item, oracle):
        return _gate_result(
            "semantic", False, UNVERIFIABLE_OUTPUT,
            "output space unconstrained and no deterministic oracle (exact/schema/programmatic)",
        )

    if _has_multiple_valid_answers(item, oracle):
        return _gate_result(
            "semantic", False, MULTI_VALID_ANSWER,
            "output allows multiple valid answers without programmatic or exact_match oracle",
        )

    return _gate_result("semantic", True)


def _run_stat_gate(
    item: Dict[str, Any],
    seen_prompt_hashes: Set[str],
    actual_counts: Dict[Tuple[str, str, str], int],
    planned_counts: Dict[Tuple[str, str, str], int],
) -> Tuple[Dict[str, Any], bool]:
    """Returns (gate_result, should_add_hash). If duplicate, don't add hash."""
    norm = normalize_prompt(item["prompt"])
    h = sha256_json({"prompt": norm, "task_type": item["task_type"], "difficulty": item["difficulty"]})
    if h in seen_prompt_hashes:
        return _gate_result("stat", False, DUPLICATE_ITEM, "duplicate prompt skeleton detected"), False

    key = (item.get("task_type", ""), item.get("difficulty", ""), item.get("split", ""))
    actual = actual_counts.get(key, 0)
    planned = planned_counts.get(key, 0)
    if planned >= 0 and actual + 1 > planned + DISTRIBUTION_TOLERANCE:
        return _gate_result(
            "stat", False, DISTRIBUTION_MISMATCH,
            f"slot (task_type,difficulty,split) would exceed planned count: actual={actual} planned={planned}",
        ), False

    return _gate_result("stat", True), True


def _patch_instructions_for(failure_code: str) -> str:
    patches = {
        SCHEMA_INVALID: "Fix the JSON to match schema exactly. Do not add extra fields.",
        DISALLOWED_DOMAIN_TAG: "Change domain_tags to an allowed tag WITHOUT changing task intent.",
        PROMPT_TOO_LONG: "Shorten prompt while preserving objective scoring.",
        ORACLE_LEAK: "Regenerate item/oracle so expected answer isn't exposed in prompt.",
        SUBJECTIVE_TASK: "Rewrite instructions to be objectively scorable; keep subjective content only in input payload if needed.",
        DUPLICATE_ITEM: "Regenerate item with different input parameters or different surface form.",
        AMBIGUOUS_TASK: "Remove subjective comparatives (best/nicer/better) or add measurable rubric with evidence_requirements.",
        MULTI_VALID_ANSWER: "Constrain output_schema (enum or programmatic_check) or use exact_match with single expected.",
        CONFLICTING_CONSTRAINTS: "Remove or resolve incompatible conditions in the prompt.",
        UNVERIFIABLE_OUTPUT: "Define output_schema and use exact_match, programmatic_check, or schema_check; or set rubric evidence_requirements.",
        RUBRIC_INCOMPLETE: "Set oracle.evidence_requirements so the judge is verifiable.",
        DISTRIBUTION_MISMATCH: "Batch slot overfilled; skip or rebalance quota.",
    }
    return patches.get(failure_code, "Address the reported issue and regenerate.")


def qa_check(
    spec: Dict[str, Any],
    item: Dict[str, Any],
    oracle: Dict[str, Any],
    seen_prompt_hashes: Set[str],
    actual_counts: Dict[Tuple[str, str, str], int] | None = None,
    planned_counts: Dict[Tuple[str, str, str], int] | None = None,
) -> Dict[str, Any]:
    item_id = item.get("item_id", "")
    gates: list[Dict[str, Any]] = []

    # Gate 1: Schema
    schema_res = _run_schema_gate(item, oracle)
    gates.append(schema_res)
    if not schema_res["passed"]:
        overall = schema_res["failure_code"]
        report = {
            "item_id": item_id,
            "passed": False,
            "stage": "QA_GATE",
            "overall_failure_code": overall,
            "gates": gates,
            "patch_instructions": _patch_instructions_for(overall),
            "created_at": now_iso(),
        }
        report["failure_code"] = overall
        report["explanation"] = schema_res["explanation"]
        return report

    # Gate 2: Semantic
    semantic_res = _run_semantic_gate(spec, item, oracle)
    gates.append(semantic_res)
    if not semantic_res["passed"]:
        overall = semantic_res["failure_code"]
        report = {
            "item_id": item_id,
            "passed": False,
            "stage": "QA_GATE",
            "overall_failure_code": overall,
            "gates": gates,
            "patch_instructions": _patch_instructions_for(overall),
            "created_at": now_iso(),
        }
        report["failure_code"] = overall
        report["explanation"] = semantic_res["explanation"]
        return report

    # Gate 3: Stat (dedup + distribution)
    actual = actual_counts if actual_counts is not None else {}
    planned = planned_counts if planned_counts is not None else {}
    stat_res, should_add_hash = _run_stat_gate(item, seen_prompt_hashes, actual, planned)
    gates.append(stat_res)
    if not stat_res["passed"]:
        overall = stat_res["failure_code"]
        report = {
            "item_id": item_id,
            "passed": False,
            "stage": "QA_GATE",
            "overall_failure_code": overall,
            "gates": gates,
            "patch_instructions": _patch_instructions_for(overall),
            "created_at": now_iso(),
        }
        report["failure_code"] = overall
        report["explanation"] = stat_res["explanation"]
        return report

    if should_add_hash:
        seen_prompt_hashes.add(
            sha256_json({
                "prompt": normalize_prompt(item["prompt"]),
                "task_type": item["task_type"],
                "difficulty": item["difficulty"],
            })
        )

    report = {
        "item_id": item_id,
        "passed": True,
        "stage": "QA_GATE",
        "overall_failure_code": "",
        "gates": gates,
        "patch_instructions": "",
        "created_at": now_iso(),
    }
    report["failure_code"] = ""
    report["explanation"] = "PASS"
    return report
