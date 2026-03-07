"""
Diagnoser: cluster failures and emit operational action plans with root-cause hypotheses,
recommended owners, blast radius, top examples, and next actions.

Heuristics (recommended_owner):
  TOOL_ARGS_* → tooling (or data)
  TOOL_BINDING_* → model (or data)
  EXACT_MATCH_FAILED → model
  UNKNOWN_CHECKER / UNSUPPORTED_EVAL_METHOD → eval
  SCHEMA / NOT_JSON → product
  Other TRAJECTORY + code → data
  Future: high QA rejection rate in one slice → data / dataset spec (needs QA stats input).
"""
from collections import defaultdict
from typing import Any, Dict, List, Tuple

# Evidence code prefixes / values for heuristic routing
TOOL_ARGS_PREFIX = "TOOL_ARGS_"
TOOL_BINDING_PREFIX = "TOOL_BINDING_"
EXACT_MATCH_FAILED = "EXACT_MATCH_FAILED"
UNKNOWN_CHECKER = "UNKNOWN_CHECKER"
UNSUPPORTED_EVAL_METHOD = "UNSUPPORTED_EVAL_METHOD"


def _evidence_code(record: Dict[str, Any]) -> str:
    """First evidence entry with a code, or empty string."""
    for e in record.get("evidence", []) or []:
        if e.get("code"):
            return e["code"]
    return ""


def _cluster_key(record: Dict[str, Any]) -> Tuple[str, str, str, str]:
    """Cluster by (error_type, evidence.code, task_type, eval_method)."""
    error_type = record.get("error_type") or "PASS"
    code = _evidence_code(record)
    task_type = record.get("task_type") or ""
    eval_method = record.get("eval_method") or ""
    return (error_type, code, task_type, eval_method)


def _blast_radius_tier(count: int, total: int) -> str:
    """Classify blast radius from cluster count and total evaluated."""
    if total <= 0:
        return "unknown"
    pct = count / total
    if pct >= 0.3 or count >= 10:
        return "high"
    if pct >= 0.1 or count >= 3:
        return "medium"
    return "low"


def _root_cause_and_owner(
    error_type: str,
    code: str,
    count: int,
    total: int,
    task_type: str = "",
) -> Tuple[str, str, str]:
    """
    Heuristics: return (root_cause_hypothesis, recommended_owner, next_action).
    recommended_owner one of: data, model, tooling, product, eval.
    """
    # Structured-extraction-specific logic by evidence_code
    if task_type == "json_extract_structured" and "PROGRAMMATIC" in error_type:
        if code == "STRUCTURED_FIELD_VALUE_MISMATCH":
            return (
                "Extractor is brittle to layout variation or distractor spans; field value chosen incorrectly.",
                "data",
                "Add extraction supervision for paraphrased layouts, reordered fields, and distractor-heavy examples.",
            )
        if code == "STRUCTURED_FIELD_MISSING":
            return (
                "Model is omitting required slots under multi-field extraction.",
                "data",
                "Add examples emphasizing full-slot coverage and missing-field penalties.",
            )
        if code == "STRUCTURED_EXTRA_FIELD_PRESENT":
            return (
                "Model over-extracts unsupported fields or fails to obey the output contract.",
                "model",
                "Add constrained-output examples and checker-enforced negative cases.",
            )

    # Eval infra: wrong checker or unsupported method
    if code == UNKNOWN_CHECKER or code == UNSUPPORTED_EVAL_METHOD:
        return (
            "Eval configuration or registry mismatch; checker_name or eval_method not supported.",
            "eval",
            "Fix oracle checker_name / eval_method or add the checker to the registry; re-run suite.",
        )

    # Schema / JSON validity → product
    if "SCHEMA" in error_type or "NOT_JSON" in error_type:
        return (
            "Model output fails schema or is not valid JSON; formatting or instruction adherence issue.",
            "product",
            "Improve output formatting instructions; add stricter JSON schema and examples; add schema_check-heavy items.",
        )

    # Tool args (arg_schema failures) → data or tooling
    if code.startswith(TOOL_ARGS_PREFIX):
        return (
            "Tool-call arguments fail schema (e.g. query format, length); model or tool contract mismatch.",
            "tooling",
            "Align tool arg_schema with actual usage; add data/examples for correct query formulation; consider data if many variants fail.",
        )

    # Tool binding (result not reflected in output) → model or data
    if code.startswith(TOOL_BINDING_PREFIX):
        return (
            "Tool result not correctly reflected in final answer; grounding or copy/transform failure.",
            "model",
            "Add trajectory data where output must copy/transform tool result; tune for tool-use grounding; track binding mismatch rate.",
        )

    # Exact-match with high consistency (most failures in cluster) → model
    if EXACT_MATCH_FAILED in error_type:
        return (
            "Deterministic exact-match failures; model output differs from expected (format or value).",
            "model",
            "Add SFT data for deterministic transforms; ensure canonical label/format handling; add exact_match items with varied surface forms.",
        )

    # Other trajectory (sequence, max_calls, etc.) → data
    if "TRAJECTORY" in error_type and code:
        return (
            "Tool-use sequence or usage constraints violated; wrong tools or order.",
            "data",
            "Add trajectory data for this failure code; train agent to call required tools in order; add targeted trajectory items.",
        )

    # Programmatic / rubric / generic
    if "RUBRIC" in error_type:
        return (
            "Rubric or judge-based check failed; subjective or criteria mismatch.",
            "model",
            "Review rubric criteria and model outputs; add calibration data or adjust evidence_requirements.",
        )
    if "PROGRAMMATIC" in error_type:
        return (
            "Programmatic checker failed; logic or format mismatch.",
            "model",
            "Review checker logic and model output distribution; add targeted items or adjust checker.",
        )

    # Default: eval / infra
    return (
        "Unclassified failure cluster; review oracle and eval_method routing.",
        "eval",
        "Review oracle + eval_method; ensure deterministic method when possible; add targeted items for this failure type.",
    )


def diagnose(eval_results: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Cluster failures by (error_type, evidence_code, task_type, eval_method).
    Returns (clusters, action_plans):
    - clusters: analytical failure_cluster objects (cluster_id, error_type, item_ids, count, hypothesis, owner, recommended_actions).
    - action_plans: operational follow-up (summary, priority, top_examples, next_action, etc.).
    """
    key_to_group: Dict[Tuple[str, str, str, str], List[Dict[str, Any]]] = defaultdict(list)
    for r in eval_results:
        key = _cluster_key(r)
        key_to_group[key].append(r)

    total_evaluated = len(eval_results)
    cluster_list: List[Dict[str, Any]] = []
    plans: List[Dict[str, Any]] = []

    failure_items = sorted(
        [(k, v) for k, v in key_to_group.items() if (k[0] or "PASS") != "PASS"],
        key=lambda kv: len(kv[1]),
        reverse=True,
    )
    for (error_type, code, task_type, eval_method), group in failure_items[:10]:
        count = len(group)
        cluster_id = error_type
        if code:
            cluster_id = f"{error_type}/{code}"
        if task_type or eval_method:
            cluster_id = f"{cluster_id}|{task_type}|{eval_method}"

        root_cause, recommended_owner, next_action = _root_cause_and_owner(
            error_type, code, count, total_evaluated, task_type
        )
        blast_tier = _blast_radius_tier(count, total_evaluated)
        estimated_blast_radius = f"{blast_tier} ({count} items in run)"
        top_examples = [
            {
                "item_id": x["item_id"],
                "error_type": x.get("error_type", ""),
                "evidence_code": _evidence_code(x),
            }
            for x in group[:5]
        ]
        priority = 1 if blast_tier == "high" else (2 if blast_tier == "medium" else 3)
        item_ids = [x["item_id"] for x in group]

        # Analytical cluster object (failure_cluster.schema.json)
        cluster_list.append({
            "cluster_id": cluster_id,
            "error_type": error_type,
            "item_ids": item_ids,
            "count": count,
            "hypothesis": root_cause,
            "owner": recommended_owner,
            "recommended_actions": [next_action],
            "task_type": task_type or "",
            "evidence_code": code or "",
            "eval_method": eval_method or "",
        })

        # Operational action plan (action_plan.schema.json)
        plans.append({
            "cluster_id": cluster_id,
            "summary": f"Cluster '{cluster_id}' with {count} failures (sample item_ids: {[e['item_id'] for e in top_examples]})",
            "root_cause_hypothesis": root_cause,
            "recommended_owner": recommended_owner,
            "priority": priority,
            "estimated_blast_radius": estimated_blast_radius,
            "top_examples": top_examples,
            "next_action": next_action,
            "count": count,
        })

    if not cluster_list and not plans:
        cluster_list.append({
            "cluster_id": "PASS",
            "error_type": "",
            "item_ids": [],
            "count": 0,
            "hypothesis": "No failures in this run.",
            "owner": "eval",
            "recommended_actions": [
                "Add harder targets, more domains, and trajectory_check tasks; run larger batch and track metrics.",
            ],
            "task_type": "",
            "evidence_code": "",
            "eval_method": "",
        })
        plans.append({
            "cluster_id": "PASS",
            "summary": "All items passed in this run; expand coverage and difficulty gradually.",
            "root_cause_hypothesis": "No failures in this run.",
            "recommended_owner": "eval",
            "priority": 4,
            "estimated_blast_radius": "none",
            "top_examples": [],
            "next_action": "Add harder targets, more domains, and trajectory_check tasks; run larger batch and track metrics.",
            "count": 0,
        })

    return cluster_list, plans
