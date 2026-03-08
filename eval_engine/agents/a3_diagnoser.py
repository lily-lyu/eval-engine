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
from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..config import MAX_LLM_RETRIES_PER_STAGE
from ..llm.structured import generate_and_validate_pydantic
from ..llm.worker_schemas import A3AnalystReport

logger = logging.getLogger(__name__)
_PROMPT_DIR = Path(__file__).resolve().parents[1] / "llm" / "prompts"

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


def _run_llm_analyst(
    cluster_list: List[Dict[str, Any]],
    plans: List[Dict[str, Any]],
    total_evaluated: int,
    run_config: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Run LLM analyst on deterministic clusters. Enriches clusters with title, root cause,
    owner, recommended_actions, evidence_examples. Read-only: does not mutate dataset_spec.
    On validation failure after retries, returns (cluster_list, plans) unmodified.
    """
    if total_evaluated <= 0 or not cluster_list:
        return cluster_list, plans
    payload = {
        "total_evaluated": total_evaluated,
        "clusters": [
            {
                "cluster_id": c["cluster_id"],
                "error_type": c.get("error_type", ""),
                "count": c["count"],
                "hypothesis": c.get("hypothesis", ""),
                "owner": c.get("owner", ""),
                "task_type": c.get("task_type", ""),
                "evidence_code": c.get("evidence_code", ""),
                "eval_method": c.get("eval_method", ""),
            }
            for c in cluster_list
        ],
    }
    template = (_PROMPT_DIR / "a3_analyst.md").read_text(encoding="utf-8")
    prompt = template + "\n\n## Input\n\n```json\n" + json.dumps(payload, indent=2) + "\n```\n\nOutput only the JSON object with key `clusters`."
    max_retries = int(run_config.get("max_llm_retries_per_stage", MAX_LLM_RETRIES_PER_STAGE))
    try:
        report = generate_and_validate_pydantic(prompt, A3AnalystReport, max_retries=max_retries)
    except Exception as e:
        logger.warning("A3 LLM analyst failed after retries, returning deterministic clusters unmodified: %s", e)
        return cluster_list, plans
    _ALLOWED_OWNERS = frozenset({"data", "model", "tooling", "product", "eval"})

    def _normalize_owner(llm_owner: str, fallback: str) -> str:
        o = (llm_owner or "").strip().lower()
        if o in _ALLOWED_OWNERS:
            return o
        if "model" in o or "training" in o:
            return "model"
        if "data" in o:
            return "data"
        if "product" in o or "ux" in o:
            return "product"
        if "tool" in o:
            return "tooling"
        return fallback

    by_id = {s.cluster_id: s for s in report.clusters}
    enriched_clusters: List[Dict[str, Any]] = []
    for c in cluster_list:
        cluster_id = c["cluster_id"]
        out = dict(c)
        summary = by_id.get(cluster_id)
        if summary is not None:
            out["title"] = summary.title
            out["hypothesis"] = summary.likely_root_cause
            out["owner"] = _normalize_owner(summary.owner, c.get("owner", "eval"))
            out["recommended_actions"] = summary.recommended_actions
            out["evidence_examples"] = summary.evidence_examples
        enriched_clusters.append(out)
    enriched_plans: List[Dict[str, Any]] = []
    for p in plans:
        cluster_id = p["cluster_id"]
        out = dict(p)
        summary = by_id.get(cluster_id)
        if summary is not None:
            out["summary"] = summary.title
            out["root_cause_hypothesis"] = summary.likely_root_cause
            out["recommended_owner"] = _normalize_owner(summary.owner, p.get("recommended_owner", "eval"))
            out["next_action"] = summary.recommended_actions[0] if summary.recommended_actions else (out.get("next_action") or "Review cluster and update action plan.")
            out["evidence_examples"] = summary.evidence_examples
        enriched_plans.append(out)
    return enriched_clusters, enriched_plans


def diagnose(
    eval_results: List[Dict[str, Any]],
    run_config: Optional[Dict[str, Any]] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Cluster failures by (error_type, evidence_code, task_type, eval_method).
    Returns (clusters, action_plans). When run_config.diagnoser_mode is hybrid or llm_materialized,
    runs LLM analyst to enrich clusters with title, root cause, recommendations; on LLM failure
    returns deterministic clusters unmodified. Does not mutate dataset_spec.
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

    diagnoser_mode = (run_config or {}).get("diagnoser_mode") or "deterministic"
    diagnoser_mode = diagnoser_mode.strip().lower() if isinstance(diagnoser_mode, str) else "deterministic"
    if diagnoser_mode in ("hybrid", "llm_materialized") and run_config:
        cluster_list, plans = _run_llm_analyst(cluster_list, plans, total_evaluated, run_config)

    return cluster_list, plans
