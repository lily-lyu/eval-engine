"""
Batch planner: compile exact target counts from spec + quota for reproducible runs.
Guarantees minimum coverage, respects max_count, distributes remainder by quota_weight.
"""
import random
from typing import Any, Dict, List


def compile_batch_plan(
    spec: Dict[str, Any],
    quota: int,
    rng: random.Random,
) -> List[Dict[str, Any]]:
    """
    Compute exact per-target counts. Plan is deterministic for given (spec, quota, seed).
    Returns list of {"target": target_dict, "count": int}; sum(count) == quota.
    """
    targets = list(spec.get("capability_targets", []))
    if not targets:
        return []

    n = len(targets)
    weights = [max(1, t.get("quota_weight", 1)) for t in targets]
    min_counts = [t.get("min_count", 0) for t in targets]
    max_counts = [t.get("max_count", quota) for t in targets]

    total_min = sum(min_counts)
    if total_min > quota:
        raise ValueError(
            f"Sum of min_count ({total_min}) exceeds quota ({quota}). "
            "Adjust spec min_count/max_count or increase quota."
        )

    counts = list(min_counts)
    remaining = quota - total_min

    if remaining > 0:
        total_weight = sum(weights)
        capacity = [max(0, max_counts[i] - counts[i]) for i in range(n)]
        if sum(capacity) == 0:
            raise ValueError(
                f"No headroom to allocate remaining {remaining} items: all targets at max_count."
            )
        # Deterministic proportional allocation: ideal share, then floor, then assign remainder
        ideal = [remaining * (weights[i] / total_weight) for i in range(n)]
        floor_part = [min(int(ideal[i]), capacity[i]) for i in range(n)]
        counts = [counts[i] + floor_part[i] for i in range(n)]
        allocated = sum(floor_part)
        remainder = remaining - allocated
        # Assign remainder one-by-one: target with largest fractional part and room left
        frac = [ideal[i] - floor_part[i] for i in range(n)]
        for _ in range(remainder):
            best = -1
            best_frac = -1.0
            for i in range(n):
                if counts[i] < max_counts[i] and frac[i] > best_frac:
                    best_frac = frac[i]
                    best = i
            if best >= 0:
                counts[best] += 1
                frac[best] = -1.0  # don't pick again
            else:
                # All at max; give to first with room (shouldn't happen if capacity was correct)
                for i in range(n):
                    if counts[i] < max_counts[i]:
                        counts[i] += 1
                        break

    ordered = sorted(zip(targets, counts), key=lambda x: (x[0]["target_id"], x[0].get("difficulty", "")))
    plan = [{"target": t, "count": c} for t, c in ordered if c > 0]

    return plan


def plan_to_target_list(plan: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Flatten plan into a list of targets (each repeated count times). Order stable for same plan."""
    out: List[Dict[str, Any]] = []
    for entry in plan:
        t, c = entry["target"], entry["count"]
        for _ in range(c):
            out.append(t)
    return out
