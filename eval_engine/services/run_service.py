"""
Run batch service: execute a full batch from spec; returns structured response.
Creates a job and updates status/progress for async status API.
Supports Mode 1: direct dataset_spec; Mode 2: intent_spec (compile then run).
"""
import json
from pathlib import Path
from typing import Any, Dict, Optional

from ..agents.a0_orchestrator import run_batch
from ..agents.compile_pipeline import compile_intent_to_plan
from ..core.job_store import create_job, update_job
from ..core.storage import save_artifact_json, ensure_dir


class RunBatchRequest:
    """Request to run a batch. All fields for orchestration; no CLI-specific args."""

    def __init__(
        self,
        project_root: Path,
        spec: Dict[str, Any],
        quota: int = 20,
        sut_name: str = "mock",
        model_version: str = "mock-1",
        sut_url: str = "",
        sut_timeout: int = 30,
        intent_spec: Optional[Dict[str, Any]] = None,
        planner_mode: Optional[str] = None,
        planner_model: Optional[str] = None,
        planner_temperature: Optional[float] = None,
        allow_experimental: Optional[bool] = None,
        save_raw_planner_outputs: bool = False,
    ):
        self.project_root = Path(project_root)
        self.spec = spec
        self.quota = quota
        self.sut_name = sut_name
        self.model_version = model_version
        self.sut_url = sut_url
        self.sut_timeout = sut_timeout
        self.intent_spec = intent_spec
        self.planner_mode = planner_mode
        self.planner_model = planner_model
        self.planner_temperature = planner_temperature
        self.allow_experimental = allow_experimental
        self.save_raw_planner_outputs = save_raw_planner_outputs


class RunBatchResponse:
    """Structured response from run_batch_service."""

    def __init__(
        self,
        run_id: str,
        run_dir: Path,
        paths: Dict[str, str],
        metrics: Dict[str, Any],
        run_record: Optional[Dict[str, Any]] = None,
        job_id: Optional[str] = None,
    ):
        self.run_id = run_id
        self.run_dir = Path(run_dir)
        self.paths = paths
        self.metrics = metrics
        self.run_record = run_record or {}
        self.job_id = job_id

    def to_dict(self) -> Dict[str, Any]:
        out = {
            "run_id": self.run_id,
            "run_dir": str(self.run_dir),
            "paths": self.paths,
            "metrics": self.metrics,
            "run_record": self.run_record,
        }
        if self.job_id is not None:
            out["job_id"] = self.job_id
        return out


def run_batch_service(request: RunBatchRequest) -> RunBatchResponse:
    """
    Run a batch end-to-end. Creates a job and updates status/progress so
    get_job_status(job_id) can be polled.
    Mode 1: request.spec is dataset_spec -> run_batch(spec).
    Mode 2: request.intent_spec is set -> compile to plan, save artifacts, then run_batch(compiled_dataset_spec).
    """
    project_root = request.project_root
    job_id = create_job(project_root)
    spec = request.spec
    compiled_plan: Optional[Dict[str, Any]] = None

    if request.intent_spec is not None:
        try:
            compiled_plan = compile_intent_to_plan(
                request.intent_spec,
                planner_mode=request.planner_mode,
                planner_model=request.planner_model,
                planner_temperature=request.planner_temperature,
                allow_experimental=request.allow_experimental,
                save_raw_planner_outputs=request.save_raw_planner_outputs,
            )
            spec = compiled_plan["compiled_dataset_spec"]
        except Exception as e:
            update_job(project_root, job_id, status="failed", error_message=str(e))
            raise

    def progress_callback(event: str, **kwargs: Any) -> None:
        if event == "started":
            update_job(project_root, job_id, run_id=kwargs.get("run_id", ""), status="running")
        elif event == "progress":
            update_job(
                project_root,
                job_id,
                current_stage=kwargs.get("stage"),
                current_item=kwargs.get("item_id"),
                progress_pct=kwargs.get("progress_pct"),
            )

    try:
        run_dir = run_batch(
            project_root=project_root,
            spec=spec,
            quota=request.quota,
            sut_name=request.sut_name,
            model_version=request.model_version,
            sut_url=request.sut_url,
            sut_timeout=request.sut_timeout,
            progress_callback=progress_callback,
        )
        update_job(project_root, job_id, status="completed", progress_pct=100.0, current_stage="END", current_item=None)
    except Exception as e:
        update_job(
            project_root,
            job_id,
            status="failed",
            error_message=str(e),
        )
        raise

    run_id = run_dir.name
    run_record_path = run_dir / "run_record.json"
    run_record: Dict[str, Any] = {}
    if run_record_path.exists():
        run_record = json.loads(run_record_path.read_text(encoding="utf-8"))

    if request.intent_spec is not None and compiled_plan is not None:
        artifacts_dir = run_dir / "artifacts"
        ensure_dir(artifacts_dir)
        save_artifact_json(artifacts_dir, "intent_spec.json", request.intent_spec)
        save_artifact_json(artifacts_dir, "eval_families.json", compiled_plan["eval_families"])
        save_artifact_json(artifacts_dir, "prompt_blueprints.json", compiled_plan["prompt_blueprints"])
        save_artifact_json(artifacts_dir, "judge_specs.json", compiled_plan["judge_specs"])
        save_artifact_json(artifacts_dir, "compiled_plan.json", compiled_plan)
        save_artifact_json(artifacts_dir, "compiled_dataset_spec.json", compiled_plan["compiled_dataset_spec"])
        meta = compiled_plan.get("compile_metadata") or {}
        if meta.get("planner_mode"):
            save_artifact_json(artifacts_dir, "planner_metadata.json", {
                "planner_mode": meta.get("planner_mode"),
                "planner_model": meta.get("planner_model"),
                "planner_temperature": meta.get("planner_temperature"),
                "fallback_used": meta.get("fallback_used", False),
                "llm_round_trips": meta.get("llm_round_trips", 0),
                "warnings": meta.get("warnings", []),
            })
        if meta.get("raw_llm_eval_families") is not None:
            save_artifact_json(artifacts_dir, "raw_llm_eval_families.json", meta["raw_llm_eval_families"])
        if meta.get("raw_llm_prompt_blueprints") is not None:
            save_artifact_json(artifacts_dir, "raw_llm_prompt_blueprints.json", meta["raw_llm_prompt_blueprints"])
        if meta.get("raw_llm_judge_specs") is not None:
            save_artifact_json(artifacts_dir, "raw_llm_judge_specs.json", meta["raw_llm_judge_specs"])
        if meta.get("planner_critic_report") is not None:
            save_artifact_json(artifacts_dir, "planner_critic_report.json", meta["planner_critic_report"])

    paths = run_record.get("paths", {})
    metrics = run_record.get("metrics", {})
    return RunBatchResponse(
        run_id=run_id,
        run_dir=run_dir,
        paths=paths,
        metrics=metrics,
        run_record=run_record,
        job_id=job_id,
    )
