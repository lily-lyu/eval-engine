"""
Compile pipeline: intent_spec -> eval_families -> prompt_blueprints -> judge_specs -> compiled_plan.
Single entry point for the intent planning layer. Supports deterministic | llm | hybrid planner mode.
"""
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .compiler import compile_to_plan
from .intent_planner import plan_intent
from .judge_planner import compile_judge_specs
from .planner_critic import run_planner_critic
from .prompt_program_compiler import compile_prompt_blueprints
from ..core.handoffs import emit_handoff
from ..core.storage import save_artifact_json, ensure_dir
from ..core.timeutil import now_iso
from ..config import PLANNER_MODE, PLANNER_MODEL, PLANNER_TEMPERATURE


def compile_intent_to_plan(
    intent_spec: Dict[str, Any],
    *,
    planner_mode: str | None = None,
    planner_model: str | None = None,
    planner_temperature: float | None = None,
    allow_experimental: bool | None = None,
    save_raw_planner_outputs: bool = False,
) -> Dict[str, Any]:
    """
    Run the full compile pipeline. Returns compiled_plan (includes compiled_dataset_spec).
    - planner_mode: deterministic | llm | hybrid (default from env PLANNER_MODE).
    - save_raw_planner_outputs: if True and mode is llm/hybrid, compiled_plan compile_metadata
      may include raw_llm_eval_families, raw_llm_prompt_blueprints, raw_llm_judge_specs for audit
      (caller can persist these to run_dir).
    Raises ValueError with failure code on invalid intent or compile error.
    """
    mode = (planner_mode or PLANNER_MODE).lower()
    model = planner_model or PLANNER_MODEL
    temperature = planner_temperature if planner_temperature is not None else PLANNER_TEMPERATURE
    planner_defaults = intent_spec.get("planner_defaults") or {}
    allow_exp = allow_experimental if allow_experimental is not None else bool(
        planner_defaults.get("allow_experimental_families", False)
    )

    raw_ef: List[Dict[str, Any]] | None = None
    raw_bp: List[Dict[str, Any]] | None = None
    raw_judge: List[Dict[str, Any]] | None = None
    llm_round_trips = 0
    fallback_used = False
    warnings: List[str] = []

    # Intent -> eval_families
    if save_raw_planner_outputs and mode in ("llm", "hybrid"):
        eval_families, raw_ef = _plan_intent_with_raw(
            intent_spec, mode=mode, planner_model=model, planner_temperature=temperature, allow_experimental=allow_exp
        )
        llm_round_trips += 1
    else:
        eval_families = plan_intent(
            intent_spec,
            mode=mode,
            planner_model=model,
            planner_temperature=temperature,
            allow_experimental=allow_exp,
        )

    # eval_families -> prompt_blueprints
    if save_raw_planner_outputs and mode in ("llm", "hybrid"):
        prompt_blueprints, raw_bp = _compile_blueprints_with_raw(
            eval_families, intent_spec, mode=mode, planner_model=model, planner_temperature=temperature
        )
        llm_round_trips += 1
    else:
        prompt_blueprints = compile_prompt_blueprints(
            eval_families, intent_spec, mode=mode, planner_model=model, planner_temperature=temperature
        )

    # prompt_blueprints + eval_families -> judge_specs
    if save_raw_planner_outputs and mode in ("llm", "hybrid"):
        judge_specs, raw_judge = _compile_judges_with_raw(
            eval_families, prompt_blueprints, mode=mode, planner_model=model, planner_temperature=temperature
        )
        llm_round_trips += 1
    else:
        judge_specs = compile_judge_specs(
            eval_families, prompt_blueprints, mode=mode, planner_model=model, planner_temperature=temperature
        )

    # Critic once we have all three (llm/hybrid only)
    critic_report = None
    if mode in ("llm", "hybrid"):
        try:
            critic_report = run_planner_critic(
                eval_families, prompt_blueprints, judge_specs,
                mode=mode, planner_model=model, planner_temperature=temperature
            )
        except Exception:
            critic_report = run_planner_critic(
                eval_families, prompt_blueprints, judge_specs, mode="deterministic"
            )
            fallback_used = True
            warnings.append("planner_critic fell back to deterministic")

    compile_metadata_extra: Dict[str, Any] = {
        "planner_mode": mode,
        "planner_model": model,
        "planner_temperature": temperature,
        "fallback_used": fallback_used,
        "llm_round_trips": llm_round_trips,
        "warnings": warnings,
    }
    if save_raw_planner_outputs and (raw_ef is not None or raw_bp is not None or raw_judge is not None):
        compile_metadata_extra["raw_llm_eval_families"] = raw_ef
        compile_metadata_extra["raw_llm_prompt_blueprints"] = raw_bp
        compile_metadata_extra["raw_llm_judge_specs"] = raw_judge
    if critic_report is not None:
        compile_metadata_extra["planner_critic_report"] = critic_report

    compiled_plan = compile_to_plan(
        intent_spec, eval_families, prompt_blueprints, judge_specs,
        compile_metadata_extra=compile_metadata_extra,
    )
    return compiled_plan


def _plan_intent_with_raw(
    intent_spec: Dict[str, Any],
    *,
    mode: str,
    planner_model: str,
    planner_temperature: float,
    allow_experimental: bool,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Return (eval_families, raw_llm_eval_families). Raw is before hybrid normalization."""
    from .intent_planner import _plan_intent_deterministic
    from ..llm.structured import generate_and_validate
    from ..config import require_gemini_key_if_llm
    from pathlib import Path
    import json

    if mode == "deterministic":
        return _plan_intent_deterministic(intent_spec), []

    require_gemini_key_if_llm(mode)
    _PROMPT_DIR = Path(__file__).resolve().parents[1] / "llm" / "prompts"
    template = (_PROMPT_DIR / "intent_planner.md").read_text(encoding="utf-8")
    prompt = template + "\n\n## Input intent_spec\n\n```json\n" + json.dumps(intent_spec, indent=2) + "\n```\n\nOutput only the JSON object with key `eval_families`."
    raw_list = generate_and_validate(
        prompt, "eval_family.schema.json",
        model=planner_model, temperature=planner_temperature,
        parse_list_from_key="eval_families",
    )
    if not isinstance(raw_list, list):
        raw_list = []
    if mode == "hybrid":
        from .intent_planner import _normalize_eval_families_to_catalog
        eval_families = _normalize_eval_families_to_catalog(raw_list, allow_experimental=allow_experimental)
    else:
        eval_families = raw_list
    return eval_families, raw_list


def _compile_blueprints_with_raw(
    eval_families: List[Dict[str, Any]],
    intent_spec: Dict[str, Any],
    *,
    mode: str,
    planner_model: str,
    planner_temperature: float,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]] | None]:
    """Return (prompt_blueprints, raw_llm_prompt_blueprints or None)."""
    from ..llm.structured import generate_and_validate
    from ..config import require_gemini_key_if_llm
    from pathlib import Path
    import json

    if mode == "deterministic":
        return compile_prompt_blueprints(eval_families, intent_spec, mode=mode), None

    require_gemini_key_if_llm(mode)
    _PROMPT_DIR = Path(__file__).resolve().parents[1] / "llm" / "prompts"
    template = (_PROMPT_DIR / "prompt_program_compiler.md").read_text(encoding="utf-8")
    payload = {"eval_families": eval_families, "intent_spec": intent_spec}
    prompt = template + "\n\n## Input\n\n```json\n" + json.dumps(payload, indent=2) + "\n```\n\nOutput only the JSON object with key `prompt_blueprints`."
    raw_list = generate_and_validate(
        prompt, "prompt_blueprint.schema.json",
        model=planner_model, temperature=planner_temperature,
        parse_list_from_key="prompt_blueprints",
    )
    if not isinstance(raw_list, list):
        raw_list = []
    if mode == "hybrid":
        from .prompt_program_compiler import _normalize_blueprints_to_families
        blueprints = _normalize_blueprints_to_families(raw_list, eval_families)
    else:
        blueprints = raw_list
    return blueprints, raw_list


def _compile_judges_with_raw(
    eval_families: List[Dict[str, Any]],
    prompt_blueprints: List[Dict[str, Any]],
    *,
    mode: str,
    planner_model: str,
    planner_temperature: float,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]] | None]:
    """Return (judge_specs, raw_llm_judge_specs or None)."""
    from ..llm.structured import generate_and_validate
    from ..config import require_gemini_key_if_llm
    from pathlib import Path
    import json

    if mode == "deterministic":
        return compile_judge_specs(eval_families, prompt_blueprints, mode=mode), None

    require_gemini_key_if_llm(mode)
    _PROMPT_DIR = Path(__file__).resolve().parents[1] / "llm" / "prompts"
    template = (_PROMPT_DIR / "judge_planner.md").read_text(encoding="utf-8")
    payload = {"eval_families": eval_families, "prompt_blueprints": prompt_blueprints}
    prompt = template + "\n\n## Input\n\n```json\n" + json.dumps(payload, indent=2) + "\n```\n\nOutput only the JSON object with key `judge_specs`."
    raw_list = generate_and_validate(
        prompt, "judge_spec.schema.json",
        model=planner_model, temperature=planner_temperature,
        parse_list_from_key="judge_specs",
    )
    if not isinstance(raw_list, list):
        raw_list = []
    if mode == "hybrid":
        from .judge_planner import _normalize_judge_specs
        judge_specs = _normalize_judge_specs(raw_list, eval_families, prompt_blueprints)
    else:
        judge_specs = raw_list
    return judge_specs, raw_list


def compile_and_save_artifacts(
    intent_spec: Dict[str, Any],
    artifacts_dir: Path,
    run_id: str = "",
    run_dir: Path | None = None,
    emit_handoffs: bool = True,
    *,
    planner_mode: str | None = None,
    planner_model: str | None = None,
    planner_temperature: float | None = None,
    allow_experimental: bool | None = None,
    save_raw_planner_outputs: bool = False,
) -> Dict[str, Any]:
    """
    Compile intent to plan and save all artifacts to artifacts_dir.
    When planner_mode is llm/hybrid and save_raw_planner_outputs is True, saves:
    - planner_metadata.json (planner_mode, planner_model, planner_temperature, fallback_used, llm_round_trips, warnings)
    - raw_llm_eval_families.json, raw_llm_prompt_blueprints.json, raw_llm_judge_specs.json (if present)
    - planner_critic_report.json (if present)
    If run_id and run_dir are set and emit_handoffs True, emits PLAN_INTENT, COMPILE_BLUEPRINTS, COMPILE_JUDGES, COMPILE_DATASET.
    Returns the compiled_plan.
    """
    ensure_dir(artifacts_dir)
    run_dir = run_dir or artifacts_dir.parent
    mode = (planner_mode or PLANNER_MODE).lower()

    compiled_plan = compile_intent_to_plan(
        intent_spec,
        planner_mode=planner_mode,
        planner_model=planner_model,
        planner_temperature=planner_temperature,
        allow_experimental=allow_experimental,
        save_raw_planner_outputs=save_raw_planner_outputs or mode in ("llm", "hybrid"),
    )

    version_bundle = {
        "dataset_spec_version": intent_spec.get("intent_spec_version", "1.0.0"),
        "rubric_schema_version": "v1",
        "eval_script_version": "v1",
        "model_version": "pre-run",
        "tool_snapshot_hash": "",
        "seed": intent_spec.get("defaults", {}).get("seed", 0),
    }

    # Persist planner metadata and optional raw/critic artifacts
    meta = compiled_plan.get("compile_metadata") or {}
    save_artifact_json(artifacts_dir, "planner_metadata.json", {
        "planner_mode": meta.get("planner_mode", "deterministic"),
        "planner_model": meta.get("planner_model"),
        "planner_temperature": meta.get("planner_temperature"),
        "fallback_used": meta.get("fallback_used", False),
        "llm_round_trips": meta.get("llm_round_trips", 0),
        "warnings": meta.get("warnings", []),
    })
    if save_raw_planner_outputs or mode in ("llm", "hybrid"):
        if meta.get("raw_llm_eval_families") is not None:
            save_artifact_json(artifacts_dir, "raw_llm_eval_families.json", meta["raw_llm_eval_families"])
        if meta.get("raw_llm_prompt_blueprints") is not None:
            save_artifact_json(artifacts_dir, "raw_llm_prompt_blueprints.json", meta["raw_llm_prompt_blueprints"])
        if meta.get("raw_llm_judge_specs") is not None:
            save_artifact_json(artifacts_dir, "raw_llm_judge_specs.json", meta["raw_llm_judge_specs"])
        if meta.get("planner_critic_report") is not None:
            save_artifact_json(artifacts_dir, "planner_critic_report.json", meta["planner_critic_report"])

    eval_families = compiled_plan["eval_families"]
    prompt_blueprints = compiled_plan["prompt_blueprints"]
    judge_specs = compiled_plan["judge_specs"]

    save_artifact_json(artifacts_dir, "eval_families.json", eval_families)
    if emit_handoffs and run_id:
        emit_handoff(
            run_dir=run_dir,
            run_id=run_id,
            item_id="",
            agent_id="INTENT_PLANNER",
            stage="PLAN_INTENT",
            status="ok",
            output_ref={"uri": "artifacts/eval_families.json"},
            version_bundle=version_bundle,
        )

    save_artifact_json(artifacts_dir, "prompt_blueprints.json", prompt_blueprints)
    if emit_handoffs and run_id:
        emit_handoff(
            run_dir=run_dir,
            run_id=run_id,
            item_id="",
            agent_id="PROMPT_COMPILER",
            stage="COMPILE_BLUEPRINTS",
            status="ok",
            output_ref={"uri": "artifacts/prompt_blueprints.json"},
            version_bundle=version_bundle,
        )

    save_artifact_json(artifacts_dir, "judge_specs.json", judge_specs)
    if emit_handoffs and run_id:
        emit_handoff(
            run_dir=run_dir,
            run_id=run_id,
            item_id="",
            agent_id="JUDGE_PLANNER",
            stage="COMPILE_JUDGES",
            status="ok",
            output_ref={"uri": "artifacts/judge_specs.json"},
            version_bundle=version_bundle,
        )

    save_artifact_json(artifacts_dir, "compiled_plan.json", compiled_plan)
    save_artifact_json(artifacts_dir, "compiled_dataset_spec.json", compiled_plan["compiled_dataset_spec"])
    save_artifact_json(artifacts_dir, "intent_spec.json", intent_spec)

    if emit_handoffs and run_id:
        emit_handoff(
            run_dir=run_dir,
            run_id=run_id,
            item_id="",
            agent_id="COMPILER",
            stage="COMPILE_DATASET",
            status="ok",
            output_ref={"uri": "artifacts/compiled_plan.json"},
            version_bundle=version_bundle,
        )

    return compiled_plan
