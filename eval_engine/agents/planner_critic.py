"""
Planner critic: review proposed eval_families, prompt_blueprints, judge_specs for issues.
Returns structured JSON (critic_report with issues, summary, passed). LLM or deterministic.
"""
from pathlib import Path
from typing import Any, Dict, List

import json

from ..config import PLANNER_MODE, PLANNER_MODEL, PLANNER_TEMPERATURE, require_gemini_key_if_llm
from ..core.schema import validate_or_raise
from ..llm.structured import generate_and_validate

_PROMPT_DIR = Path(__file__).resolve().parents[1] / "llm" / "prompts"
ALLOWED_EVAL_METHODS = frozenset(
    {"programmatic_check", "exact_match", "trajectory_check", "schema_check", "rubric_judge"}
)


def _load_prompt(name: str) -> str:
    path = _PROMPT_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt template not found: {path}")
    return path.read_text(encoding="utf-8")


def _critic_deterministic(
    eval_families: List[Dict[str, Any]],
    prompt_blueprints: List[Dict[str, Any]],
    judge_specs: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Deterministic checks: duplicate families, rubric without evidence, eval_method not in allowed."""
    issues: List[Dict[str, Any]] = []
    family_ids = [f.get("family_id") for f in eval_families if f.get("family_id")]
    if len(family_ids) != len(set(family_ids)):
        seen = set()
        for fid in family_ids:
            if fid in seen:
                issues.append({
                    "severity": "warning",
                    "code": "DUPLICATE_FAMILY",
                    "message": f"Duplicate family_id: {fid}",
                    "location": f"family_id={fid}",
                })
            seen.add(fid)

    judge_by_family = {j.get("family_id"): j for j in judge_specs if j.get("family_id")}
    for spec in judge_specs:
        fid = spec.get("family_id")
        if spec.get("eval_method") == "rubric_judge" and not spec.get("evidence_requirements"):
            issues.append({
                "severity": "error",
                "code": "RUBRIC_WITHOUT_EVIDENCE",
                "message": "rubric_judge requires evidence_requirements",
                "location": f"judge_spec_id={spec.get('judge_spec_id', fid)}",
            })
        fam = next((f for f in eval_families if f.get("family_id") == fid), None)
        if fam and spec.get("eval_method") and spec["eval_method"] not in (fam.get("allowed_eval_methods") or []):
            issues.append({
                "severity": "error",
                "code": "INVALID_EVAL_METHOD",
                "message": f"eval_method '{spec.get('eval_method')}' not in family allowed_eval_methods",
                "location": f"family_id={fid}",
            })

    passed = not any(i.get("severity") == "error" for i in issues)
    summary = "No errors." if passed else f"{sum(1 for i in issues if i.get('severity') == 'error')} error(s) found."
    return {
        "critic_report": {
            "issues": issues,
            "summary": summary,
            "passed": passed,
        }
    }


def run_planner_critic(
    eval_families: List[Dict[str, Any]],
    prompt_blueprints: List[Dict[str, Any]],
    judge_specs: List[Dict[str, Any]],
    *,
    mode: str | None = None,
    planner_model: str | None = None,
    planner_temperature: float | None = None,
) -> Dict[str, Any]:
    """
    Critique proposed artifacts. Returns dict with key critic_report: { issues, summary, passed }.
    - deterministic: rule-based checks (duplicates, rubric evidence, eval_method in allowed).
    - llm / hybrid: Gemini produces structured critic_report (same shape).
    """
    mode = (mode or PLANNER_MODE).lower()

    if mode == "deterministic":
        return _critic_deterministic(eval_families, prompt_blueprints, judge_specs)

    require_gemini_key_if_llm(mode)
    template = _load_prompt("planner_critic")
    payload = {
        "eval_families": eval_families,
        "prompt_blueprints": prompt_blueprints,
        "judge_specs": judge_specs,
    }
    prompt = template + "\n\n## Input\n\n```json\n" + json.dumps(payload, indent=2) + "\n```\n\nOutput only the JSON object with key `critic_report`."
    result = generate_and_validate(
        prompt,
        "planner_critic_report.schema.json",
        model=planner_model or PLANNER_MODEL,
        temperature=planner_temperature if planner_temperature is not None else PLANNER_TEMPERATURE,
    )
    if not isinstance(result, dict) or "critic_report" not in result:
        return _critic_deterministic(eval_families, prompt_blueprints, judge_specs)
    validate_or_raise("planner_critic_report.schema.json", result)
    return result
