"""
Rubric judge: dual independent judge calls (double-blind) then arbitration.
Structured output only: rubric_schema_version, evidence_requirements, and
rule-by-rule evidence are required; judge free text is not the final truth.
"""
import json
from typing import Any, Callable, Dict, List, Optional, Tuple

JUDGE_PROMPT_VERSION = "v1"
RUBRIC_SCHEMA_VERSION = "v1"
JUDGE_MODEL_VERSION_STUB = "stub"
ARBITER_MODEL_VERSION_STUB = "stub"
SCORE_DELTA_THRESHOLD = 0.15

# Target judge/arbiter output shape (structured; evidence required)
JudgeOutput = Dict[str, Any]  # verdict, score, reason, evidence[], model_version


def build_judge_prompt(
    oracle: Dict[str, Any],
    parsed_output: Dict[str, Any],
    item: Dict[str, Any],
    raw_prompt: str,
) -> str:
    """Build the prompt for a single judge: task context, rubric, evidence requirements, and output to judge."""
    schema_version = oracle.get("rubric_schema_version") or RUBRIC_SCHEMA_VERSION
    ev_req = oracle.get("evidence_requirements") or {}
    parts = [
        f"# Rubric judge (prompt_version={JUDGE_PROMPT_VERSION}, rubric_schema_version={schema_version})",
        "",
        "## Task",
        f"- task_type: {item.get('task_type', '')}",
        f"- raw_prompt: {raw_prompt!r}",
        "",
        "## Evidence requirements (you must cite these rule-by-rule)",
        json.dumps(ev_req, indent=2),
        "",
        "## Model output to evaluate (parsed)",
        json.dumps(parsed_output, indent=2),
        "",
        "## Instructions",
        "Return a JSON object with: verdict (pass|fail), score (0-1), reason (short), evidence (array of {rule, observation} for each evidence requirement). Do not rely on free text alone; every conclusion must be backed by structured evidence.",
    ]
    return "\n".join(parts)


def _normalize_judge_output(raw: Dict[str, Any]) -> JudgeOutput:
    """Ensure judge output has required fields and structured evidence."""
    evidence = raw.get("evidence")
    if not isinstance(evidence, list):
        evidence = []
    evidence = [
        {"rule": e.get("rule", "unknown"), "observation": e.get("observation", "")}
        for e in evidence
        if isinstance(e, dict)
    ]
    score = raw.get("score")
    if score is None:
        try:
            score = 1.0 if raw.get("verdict") == "pass" else 0.0
        except Exception:
            score = 0.0
    else:
        score = max(0.0, min(1.0, float(score)))
    return {
        "verdict": "pass" if str(raw.get("verdict", "fail")).lower() == "pass" else "fail",
        "score": score,
        "reason": str(raw.get("reason", ""))[:2000],
        "evidence": evidence,
        "model_version": str(raw.get("model_version", JUDGE_MODEL_VERSION_STUB)),
    }


def call_judge(
    model_name: str,
    prompt: str,
    judge_fn: Optional[Callable[[str, str], Dict[str, Any]]] = None,
) -> JudgeOutput:
    """
    Call a single judge. Returns normalized JudgeOutput.
    judge_fn(model_name, prompt) -> raw dict if provided; otherwise uses stub.
    """
    if judge_fn is not None:
        raw = judge_fn(model_name, prompt)
    else:
        raw = _stub_judge(model_name, prompt)
    return _normalize_judge_output(raw)


def _stub_judge(model_name: str, prompt: str) -> Dict[str, Any]:
    """Default stub when no judge_fn: returns pass with structured evidence."""
    return {
        "verdict": "pass",
        "score": 0.85,
        "reason": "MVP rubric_judge stub: deterministic checks preferred; structured evidence required in production.",
        "evidence": [
            {"rule": "rubric_stub", "observation": "stub judge; no LLM call"},
        ],
        "model_version": model_name or JUDGE_MODEL_VERSION_STUB,
    }


def compare_judgements(j1: JudgeOutput, j2: JudgeOutput) -> Dict[str, Any]:
    """
    Compare two judge outputs. Returns:
    - verdicts_match: bool
    - score_delta: float (>= 0)
    - accept_mean: True iff verdicts match and score_delta < SCORE_DELTA_THRESHOLD
    """
    v1 = j1.get("verdict", "fail") == "pass"
    v2 = j2.get("verdict", "fail") == "pass"
    verdicts_match = v1 == v2
    score_delta = abs(float(j1.get("score", 0)) - float(j2.get("score", 0)))
    accept_mean = verdicts_match and score_delta < SCORE_DELTA_THRESHOLD
    return {
        "verdicts_match": verdicts_match,
        "score_delta": score_delta,
        "accept_mean": accept_mean,
    }


def build_arbiter_prompt(
    j1: JudgeOutput,
    j2: JudgeOutput,
    oracle: Dict[str, Any],
    item: Dict[str, Any],
    parsed_output: Dict[str, Any],
) -> str:
    """Build prompt for arbiter: two judge outputs + context; arbiter must return cited rule-by-rule evidence."""
    schema_version = oracle.get("rubric_schema_version") or RUBRIC_SCHEMA_VERSION
    ev_req = oracle.get("evidence_requirements") or {}
    parts = [
        f"# Arbiter (rubric_schema_version={schema_version})",
        "",
        "## Task",
        f"- task_type: {item.get('task_type', '')}",
        "- You are resolving disagreement between two judges. Your output must cite rule-by-rule evidence.",
        "",
        "## Evidence requirements",
        json.dumps(ev_req, indent=2),
        "",
        "## Judge 1",
        json.dumps({"verdict": j1.get("verdict"), "score": j1.get("score"), "reason": j1.get("reason"), "evidence": j1.get("evidence", [])}, indent=2),
        "",
        "## Judge 2",
        json.dumps({"verdict": j2.get("verdict"), "score": j2.get("score"), "reason": j2.get("reason"), "evidence": j2.get("evidence", [])}, indent=2),
        "",
        "## Model output",
        json.dumps(parsed_output, indent=2),
        "",
        "## Instructions",
        "Return a JSON object: verdict (pass|fail), score (0-1), reason (short), evidence (array of {rule, observation} for each rubric rule). You must provide cited rule-by-rule evidence.",
    ]
    return "\n".join(parts)


def arbitrate(
    j1: JudgeOutput,
    j2: JudgeOutput,
    oracle: Dict[str, Any],
    item: Dict[str, Any],
    parsed_output: Dict[str, Any],
    arbiter_fn: Optional[Callable[[str, str], Dict[str, Any]]] = None,
) -> JudgeOutput:
    """
    Run arbiter when judges disagree or score delta >= threshold.
    arbiter_fn(model_name, prompt) -> raw dict; default stub returns structured result with evidence.
    """
    prompt = build_arbiter_prompt(j1, j2, oracle, item, parsed_output)
    model_name = "arbiter"
    if arbiter_fn is not None:
        raw = arbiter_fn(model_name, prompt)
    else:
        raw = _stub_arbiter(model_name, prompt)
    out = _normalize_judge_output(raw)
    out["model_version"] = str(raw.get("model_version", ARBITER_MODEL_VERSION_STUB))
    return out


def _stub_arbiter(model_name: str, prompt: str) -> Dict[str, Any]:
    """Default arbiter stub: conservative fail with rule-by-rule evidence."""
    return {
        "verdict": "fail",
        "score": 0.5,
        "reason": "Arbiter stub: judges disagreed or score delta exceeded threshold; resolve with real LLM.",
        "evidence": [
            {"rule": "arbiter_stub", "observation": "stub arbiter; no LLM call"},
        ],
        "model_version": model_name or ARBITER_MODEL_VERSION_STUB,
    }


def run_rubric_judge(
    oracle: Dict[str, Any],
    parsed_output: Dict[str, Any],
    item: Dict[str, Any],
    raw_prompt: str,
    judge_fn: Optional[Callable[[str, str], Dict[str, Any]]] = None,
    arbiter_fn: Optional[Callable[[str, str], Dict[str, Any]]] = None,
    judge_model_name: str = "judge",
) -> Tuple[bool, float, List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Two independent judge calls (double-blind), then arbitration.
    Returns (passed, score, evidence, judge_outputs).
    judge_outputs is [j1, j2] or [j1, j2, arbiter] when arbitration was used.
    Caller (e.g. A2) should persist judge_outputs as itemid_judge1.json,
    itemid_judge2.json, itemid_arbiter.json (if used) and set eval_result.judge_artifacts_ref.

    Design: rubric_schema_version and evidence_requirements are required for
    verifiability; judge free text is not the final truth — structured evidence is.
    """
    # Require evidence_requirements so the judge is not purely subjective
    if not oracle.get("evidence_requirements"):
        judge_outputs: List[Dict[str, Any]] = []
        evidence = [
            {"kind": "rubric_judge", "message": "oracle.evidence_requirements missing; rubric_judge requires structured evidence criteria."},
        ]
        return False, 0.0, evidence, judge_outputs

    prompt = build_judge_prompt(oracle, parsed_output, item, raw_prompt)
    j1 = call_judge(judge_model_name, prompt, judge_fn=judge_fn)
    j2 = call_judge(judge_model_name, prompt, judge_fn=judge_fn)
    j1["judge_index"] = 1
    j2["judge_index"] = 2
    j1["judge_prompt_version"] = JUDGE_PROMPT_VERSION
    j2["judge_prompt_version"] = JUDGE_PROMPT_VERSION
    j1["rubric_schema_version"] = oracle.get("rubric_schema_version") or RUBRIC_SCHEMA_VERSION
    j2["rubric_schema_version"] = j1["rubric_schema_version"]

    comparison = compare_judgements(j1, j2)
    judge_outputs = [j1, j2]
    arbiter_output: Optional[JudgeOutput] = None

    if comparison["accept_mean"]:
        passed = j1.get("verdict") == "pass"
        score = (float(j1.get("score", 0)) + float(j2.get("score", 0))) / 2.0
        score = max(0.0, min(1.0, score))
    else:
        arbiter_output = arbitrate(j1, j2, oracle, item, parsed_output, arbiter_fn=arbiter_fn)
        arbiter_output["judge_prompt_version"] = JUDGE_PROMPT_VERSION
        arbiter_output["rubric_schema_version"] = j1["rubric_schema_version"]
        judge_outputs.append(arbiter_output)
        passed = arbiter_output.get("verdict") == "pass"
        score = float(arbiter_output.get("score", 0))

    evidence: List[Dict[str, Any]] = [
        {"kind": "rubric_judge", "message": f"judge_prompt_version={JUDGE_PROMPT_VERSION} rubric_schema_version={j1['rubric_schema_version']} judge_models={j1.get('model_version', '')},{j2.get('model_version', '')}"},
        {"kind": "rubric_judge", "message": f"judge_1={j1.get('verdict')} judge_2={j2.get('verdict')} accept_mean={comparison['accept_mean']} arbitration={'used' if arbiter_output else 'no'}"},
    ]
    if not passed:
        evidence.append({"kind": "rubric_judge", "message": f"judge_1_reason={j1.get('reason', '')[:200]}"})
        evidence.append({"kind": "rubric_judge", "message": f"judge_2_reason={j2.get('reason', '')[:200]}"})
        if arbiter_output:
            evidence.append({"kind": "rubric_judge", "message": f"arbiter_reason={arbiter_output.get('reason', '')[:200]}"})
    # Attach structured evidence from final authority (arbiter if used, else mean)
    source = arbiter_output if arbiter_output else j1
    for e in (source.get("evidence") or [])[:10]:
        evidence.append({"kind": "rubric_judge", "rule": e.get("rule"), "observation": e.get("observation", "")})

    return passed, score, evidence, judge_outputs
