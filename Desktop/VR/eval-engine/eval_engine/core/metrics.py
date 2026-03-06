"""
Slice metrics and QA throughput for run_summary.
"""
from typing import Any, Dict, List, Optional


def _pass_rate_dict(n: int, pass_count: int) -> Dict[str, Any]:
    return {
        "n": n,
        "pass": pass_count,
        "pass_rate": round(pass_count / n, 4) if n else 0.0,
    }


def _percentile(sorted_values: List[int], p: float) -> int:
    """p in [0, 100]. Returns percentile value."""
    if not sorted_values:
        return 0
    k = (len(sorted_values) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    return int(sorted_values[f] + (k - f) * (sorted_values[c] - sorted_values[f]))


def compute_slice_metrics(
    items: List[Dict[str, Any]],
    oracles: List[Dict[str, Any]],
    eval_results: List[Dict[str, Any]],
    attempted_total: int,
    item_abort_total: int,
    latency_ms_list: Optional[List[Optional[int]]] = None,
) -> Dict[str, Any]:
    """
    Compute pass_rate by task_type, domain_tags, difficulty, eval_method;
    P50/P90 latency when available; QA throughput (attempted vs evaluated vs abort).
    """
    item_by_id = {it["item_id"]: it for it in items}
    oracle_by_id = {oc["item_id"]: oc for oc in oracles}

    by_task_type: Dict[str, Dict[str, int]] = {}
    by_domain_tag: Dict[str, Dict[str, int]] = {}
    by_difficulty: Dict[str, Dict[str, int]] = {}
    by_eval_method: Dict[str, Dict[str, int]] = {}

    latency_values: List[int] = []
    if latency_ms_list is not None:
        for i, er in enumerate(eval_results):
            if i < len(latency_ms_list) and latency_ms_list[i] is not None:
                latency_values.append(latency_ms_list[i])

    for er in eval_results:
        item_id = er["item_id"]
        item = item_by_id.get(item_id)
        oracle = oracle_by_id.get(item_id)
        if item is None or oracle is None:
            continue
        passed = 1 if er.get("verdict") == "pass" else 0

        # by task_type
        tt = item.get("task_type", "unknown")
        if tt not in by_task_type:
            by_task_type[tt] = {"n": 0, "pass": 0}
        by_task_type[tt]["n"] += 1
        by_task_type[tt]["pass"] += passed

        # by domain_tags (each tag gets this item counted)
        for tag in item.get("domain_tags") or []:
            if tag not in by_domain_tag:
                by_domain_tag[tag] = {"n": 0, "pass": 0}
            by_domain_tag[tag]["n"] += 1
            by_domain_tag[tag]["pass"] += passed

        # by difficulty
        diff = item.get("difficulty", "unknown")
        if diff not in by_difficulty:
            by_difficulty[diff] = {"n": 0, "pass": 0}
        by_difficulty[diff]["n"] += 1
        by_difficulty[diff]["pass"] += passed

        # by eval_method
        em = oracle.get("eval_method", "unknown")
        if em not in by_eval_method:
            by_eval_method[em] = {"n": 0, "pass": 0}
        by_eval_method[em]["n"] += 1
        by_eval_method[em]["pass"] += passed

    def to_pass_rate(d: Dict[str, Dict[str, int]]) -> Dict[str, Dict[str, Any]]:
        return {k: _pass_rate_dict(v["n"], v["pass"]) for k, v in d.items()}

    evaluated = len(eval_results)
    latency_ms: Optional[Dict[str, int]] = None
    if latency_values:
        sorted_lat = sorted(latency_values)
        latency_ms = {
            "p50": _percentile(sorted_lat, 50),
            "p90": _percentile(sorted_lat, 90),
        }

    return {
        "slice_metrics": {
            "by_task_type": to_pass_rate(by_task_type),
            "by_domain_tags": to_pass_rate(by_domain_tag),
            "by_difficulty": to_pass_rate(by_difficulty),
            "by_eval_method": to_pass_rate(by_eval_method),
            "latency_ms": latency_ms,
            "qa_throughput": {
                "attempted": attempted_total,
                "evaluated": evaluated,
                "aborted": item_abort_total,
            },
        }
    }
