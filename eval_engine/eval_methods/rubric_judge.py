"""
Rubric judge: last-resort evaluation via independent judge calls and arbitration.
MVP: stub judge; later: LLM endpoint with judge_prompt_version, judge_model_version, artifacts.
"""
import json
from typing import Any, Callable, Dict, List, Optional, Tuple

JUDGE_PROMPT_VERSION = "v1"
JUDGE_MODEL_VERSION_STUB = "stub"


def _stub_judge(prompt: str, item: Dict[str, Any], output: Any) -> Dict[str, Any]:
    """MVP stub: no LLM call; returns pass with fixed reason."""
    return {
        "verdict": "pass",
        "reason": "MVP rubric_judge stub: deterministic checks preferred.",
        "model_version": JUDGE_MODEL_VERSION_STUB,
    }


def run_rubric_judge(
    oracle: Dict[str, Any],
    parsed_output: Dict[str, Any],
    item: Dict[str, Any],
    raw_prompt: str,
    judge_fn: Optional[Callable[[str, Dict, Any], Dict[str, Any]]] = None,
) -> Tuple[bool, float, List[Dict[str, str]], List[Dict[str, Any]]]:
    """
    Two independent judge calls (double-blind), then arbitration.
    Returns (passed, score, evidence, judge_outputs).
    judge_fn(prompt, item, output) -> {verdict, reason, model_version}.
    """
    judge_fn = judge_fn or _stub_judge
    judge_outputs: List[Dict[str, Any]] = []

    # Normalized verbosity: same prompt for both (could vary for double-blind)
    prompt = f"Item task_type: {item.get('task_type')}. Output to judge: {json.dumps(parsed_output)}"

    for i in range(2):
        out = judge_fn(prompt, item, parsed_output)
        out["judge_index"] = i + 1
        out["judge_prompt_version"] = JUDGE_PROMPT_VERSION
        judge_outputs.append(out)

    v1 = judge_outputs[0].get("verdict", "fail") == "pass"
    v2 = judge_outputs[1].get("verdict", "fail") == "pass"

    # Arbitration: both must pass for pass
    passed = v1 and v2
    score = 1.0 if passed else 0.0

    evidence: List[Dict[str, str]] = [
        {"kind": "rubric_judge", "message": f"judge_prompt_version={JUDGE_PROMPT_VERSION} judge_model_version={judge_outputs[0].get('model_version', '')}"},
        {"kind": "rubric_judge", "message": f"judge_1={judge_outputs[0].get('verdict')} judge_2={judge_outputs[1].get('verdict')} arbitration={'pass' if passed else 'fail'}"},
    ]
    if not passed:
        evidence.append({"kind": "rubric_judge", "message": f"judge_1_reason={judge_outputs[0].get('reason', '')[:200]}"})
        evidence.append({"kind": "rubric_judge", "message": f"judge_2_reason={judge_outputs[1].get('reason', '')[:200]}"})

    return passed, score, evidence, judge_outputs
