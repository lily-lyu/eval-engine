"""
Thin FastAPI backend over eval-engine services. Backend → service layer directly (no MCP).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8001")


def default_sut_url() -> str:
    return f"{PUBLIC_BASE_URL.rstrip('/')}/sut/run"

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Redact local paths from responses so they are not exposed in shared demos.
_PATH_REDACTED = "[redacted]"


def _redact_paths(obj: Any) -> Any:
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            if k in ("run_dir", "path", "run_dir_path") and isinstance(v, str) and (
                v.startswith("/") or "\\" in v or (len(v) > 2 and v[1] == ":")
            ):
                out[k] = _PATH_REDACTED
            else:
                out[k] = _redact_paths(v)
        return out
    if isinstance(obj, list):
        return [_redact_paths(x) for x in obj]
    return obj


from eval_engine.services.run_index_service import (
    get_repo_root,
    get_run_summary,
    get_item_result,
    list_runs,
)
from eval_engine.services.artifact_service import (
    list_run_files,
    get_artifact_content_by_run,
)
from eval_engine.services.job_service import get_job_status as get_job_status_service
from eval_engine.services.run_service import RunBatchRequest, run_batch_service
from eval_engine.agents.compile_pipeline import compile_intent_to_plan
from eval_engine.services.brief_compile_service import brief_to_intent_spec
from eval_engine.services.regression_service import (
    RegressionRequest,
    run_regression_service,
)
from eval_engine.services.demo_service import list_demo_cases, run_demo_failure
from eval_engine.services.diagnosis_service import list_failure_clusters
from eval_engine.services.run_view_service import get_run_events, get_eval_results, get_run_stage_metrics

from eval_engine.api.sut import router as sut_router

app = FastAPI(
    title="eval-engine-api",
    version="1.0.0",
    description="Thin REST API over eval-engine services",
)

# For local development only. Tighten before public deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sut_router)


class RunBatchRequestSchema(BaseModel):
    """Either spec_json (dataset_spec) or intent_json (intent_spec); intent_json takes precedence if both set."""
    spec_json: str | None = None
    intent_json: str | None = None
    quota: int = 1
    sut: str = "http"
    sut_url: str | None = None
    sut_timeout: int = 30
    model_version: str = "http-sut-local"
    planner_mode: str | None = None
    planner_model: str | None = None
    planner_temperature: float | None = None
    allow_experimental: bool | None = None
    save_raw_planner_outputs: bool = False
    item_generation_mode: str | None = None
    judge_mode: str | None = None
    diagnoser_mode: str | None = None
    max_llm_retries_per_stage: int | None = None


class CompileRequestSchema(BaseModel):
    intent_json: str
    planner_mode: str | None = None
    planner_model: str | None = None
    planner_temperature: float | None = None
    allow_experimental: bool | None = None
    save_raw_planner_outputs: bool = False


class CompileBriefRequestSchema(BaseModel):
    """Planning-only; sut_url is a run-time concern and is not accepted here."""
    brief_text: str
    quota: int | None = None
    planner_mode: str | None = None
    planner_model: str | None = None
    planner_temperature: float | None = None
    allow_experimental: bool | None = None
    target_domain: list[str] | None = None


@app.post("/compile-brief")
def api_compile_brief(req: CompileBriefRequestSchema) -> dict[str, Any]:
    """Compile natural-language brief to intent_spec, then to compiled_plan. Planning only; use /runs with spec_json for execution."""
    try:
        intent_spec = brief_to_intent_spec(
            req.brief_text,
            quota=req.quota,
            planner_mode=req.planner_mode,
            planner_model=req.planner_model,
            planner_temperature=req.planner_temperature,
            allow_experimental=bool(req.allow_experimental),
            target_domain=req.target_domain,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    try:
        compiled_plan = compile_intent_to_plan(
            intent_spec,
            planner_mode=req.planner_mode,
            planner_model=req.planner_model,
            planner_temperature=req.planner_temperature,
            allow_experimental=req.allow_experimental,
            save_raw_planner_outputs=False,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    compiled_dataset_spec = compiled_plan.get("compiled_dataset_spec", {})
    compile_metadata = compiled_plan.get("compile_metadata", {})
    return _redact_paths({
        "brief_text": req.brief_text,
        "intent_spec": intent_spec,
        "compiled_plan": compiled_plan,
        "compiled_dataset_spec": compiled_dataset_spec,
        "compile_metadata": compile_metadata,
    })


@app.post("/compile")
def api_compile(req: CompileRequestSchema) -> dict[str, Any]:
    """Compile intent_spec to compiled_plan (no run). Returns compiled_plan or 400 with failure code."""
    try:
        intent_spec = json.loads(req.intent_json)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {e}")
    try:
        compiled_plan = compile_intent_to_plan(
            intent_spec,
            planner_mode=req.planner_mode,
            planner_model=req.planner_model,
            planner_temperature=req.planner_temperature,
            allow_experimental=req.allow_experimental,
            save_raw_planner_outputs=req.save_raw_planner_outputs,
        )
        return _redact_paths(compiled_plan)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


class RegressionRequestSchema(BaseModel):
    suite_path: str
    sut_url: str | None = None
    sut_timeout: int = 30
    min_pass_rate: float = 0.95
    artifacts_dir: str | None = None


class DemoFailureRequest(BaseModel):
    case_name: str


@app.get("/")
def root() -> dict[str, str]:
    return {
        "name": "eval-engine-api",
        "status": "ok",
        "docs": "/docs",
        "health": "/healthz",
    }


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {"ok": True}


@app.get("/planner-status")
def api_planner_status() -> dict[str, Any]:
    """Return planner mode and whether Gemini is configured (for UI; never exposes API key)."""
    from eval_engine.config import PLANNER_MODE, GEMINI_API_KEY
    return {
        "planner_mode": PLANNER_MODE,
        "gemini_configured": bool(GEMINI_API_KEY),
    }


@app.get("/runs")
def api_list_runs(limit: int = Query(default=20, ge=1, le=200)) -> dict[str, Any]:
    return _redact_paths({"runs": list_runs(limit=limit)})


@app.post("/runs")
def api_run_batch(req: RunBatchRequestSchema) -> dict[str, Any]:
    if req.intent_json:
        try:
            intent_spec = json.loads(req.intent_json)
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=400, detail=f"Invalid intent_json: {e}")
        spec = {}  # will be replaced by compiled_dataset_spec in service
        # When both planner batch_size and UI quota are set, use the smaller (cap released items)
        batch_size = intent_spec.get("batch_size") if isinstance(intent_spec.get("batch_size"), int) else None
        effective_quota = min(req.quota, batch_size) if batch_size is not None else req.quota
        request = RunBatchRequest(
            project_root=get_repo_root(),
            spec=spec,
            quota=effective_quota,
            sut_name=req.sut,
            sut_url=req.sut_url or default_sut_url(),
            sut_timeout=req.sut_timeout,
            model_version=req.model_version,
            intent_spec=intent_spec,
            planner_mode=req.planner_mode,
            planner_model=req.planner_model,
            planner_temperature=req.planner_temperature,
            allow_experimental=req.allow_experimental,
            save_raw_planner_outputs=req.save_raw_planner_outputs,
            item_generation_mode=req.item_generation_mode,
            judge_mode=req.judge_mode,
            diagnoser_mode=req.diagnoser_mode,
            max_llm_retries_per_stage=req.max_llm_retries_per_stage,
        )
    else:
        if not req.spec_json:
            raise HTTPException(status_code=400, detail="Either spec_json or intent_json is required")
        try:
            spec = json.loads(req.spec_json)
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=400, detail=f"Invalid spec_json: {e}")
        request = RunBatchRequest(
            project_root=get_repo_root(),
            spec=spec,
            quota=req.quota,
            sut_name=req.sut,
            sut_url=req.sut_url or default_sut_url(),
            sut_timeout=req.sut_timeout,
            model_version=req.model_version,
            item_generation_mode=req.item_generation_mode,
            judge_mode=req.judge_mode,
            diagnoser_mode=req.diagnoser_mode,
            max_llm_retries_per_stage=req.max_llm_retries_per_stage,
        )
    response = run_batch_service(request)
    return _redact_paths(response.to_dict())


@app.get("/jobs/{job_id}")
def api_get_job_status(job_id: str) -> dict[str, Any]:
    job = get_job_status_service(get_repo_root(), job_id)
    if job is None:
        return {
            "error": {
                "kind": "not_found",
                "code": "JOB_NOT_FOUND",
                "message": f"Job not found: {job_id}",
                "details": {"job_id": job_id},
            }
        }
    return job


@app.get("/runs/{run_id}")
def api_get_run_summary(run_id: str) -> dict[str, Any]:
    return _redact_paths(get_run_summary(run_id))


@app.get("/runs/{run_id}/files")
def api_list_run_files(run_id: str) -> dict[str, Any]:
    return _redact_paths(list_run_files(run_id))


@app.get("/runs/{run_id}/events")
def api_get_run_events(
    run_id: str,
    limit: int = Query(default=200, ge=1, le=2000),
) -> dict[str, Any]:
    return get_run_events(run_id, limit=limit)


@app.get("/runs/{run_id}/results")
def api_get_eval_results(
    run_id: str,
    limit: int = Query(default=200, ge=1, le=2000),
) -> dict[str, Any]:
    return get_eval_results(run_id, limit=limit)


@app.get("/runs/{run_id}/clusters")
def api_get_failure_clusters(run_id: str) -> dict[str, Any]:
    return list_failure_clusters(run_id)


@app.get("/runs/{run_id}/stage-metrics")
def api_get_run_stage_metrics(run_id: str) -> dict[str, Any]:
    """Pre-aggregated pipeline stage metrics from the full event log (no truncation)."""
    return get_run_stage_metrics(run_id)


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _read_text(path: Path) -> str | None:
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/runs/{run_id}/items/{item_id}/trace")
def get_item_trace(run_id: str, item_id: str) -> dict[str, Any]:
    runs_dir = Path(os.getenv("EVAL_ENGINE_RUNS_DIR", str(Path.cwd() / "runs")))
    run_dir = runs_dir / run_id
    if not run_dir.exists():
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

    items = _read_jsonl(run_dir / "released_items.jsonl")
    oracles = _read_jsonl(run_dir / "released_oracles.jsonl")
    results = _read_jsonl(run_dir / "eval_results.jsonl")
    action_plans = _read_jsonl(run_dir / "action_plans.jsonl")
    data_requests = _read_jsonl(run_dir / "data_requests.jsonl")
    events = _read_jsonl(run_dir / "events.jsonl")
    run_record = _read_json(run_dir / "run_record.json") or {}

    item = next((row for row in items if row.get("item_id") == item_id), None)
    oracle = next((row for row in oracles if row.get("item_id") == item_id), None)
    result = next((row for row in results if row.get("item_id") == item_id), None)

    if not item or not oracle or not result:
        raise HTTPException(status_code=404, detail=f"Trace not found for item: {item_id}")

    related_action_plans = [
        row for row in action_plans
        if any(ex.get("item_id") == item_id for ex in row.get("top_examples", []))
    ]
    related_data_requests = [
        row for row in data_requests
        if item_id in row.get("sample_item_ids", []) or row.get("source_item_id") == item_id
    ]
    related_events = [row for row in events if row.get("item_id") == item_id]

    artifacts_dir = run_dir / "artifacts"
    qa_report = _read_json(artifacts_dir / f"{item_id}_qa_report.json")
    tool_trace = _read_json(artifacts_dir / f"{item_id}_tool_trace.json")
    raw_output = _read_text(artifacts_dir / f"{item_id}_raw.txt")

    version_bundle = {
        "dataset_spec_version": run_record.get("dataset_spec_version"),
        "model_version": result.get("model_version") or run_record.get("model_version"),
        "tool_snapshot_hash": run_record.get("tool_snapshot_hash"),
        "seed": run_record.get("seed"),
    }

    return {
        "content": {
            "run_id": run_id,
            "item_id": item_id,
            "item": item,
            "oracle": oracle,
            "qa_report": qa_report,
            "result": result,
            "action_plans": related_action_plans,
            "data_requests": related_data_requests,
            "events": related_events,
            "raw_output": raw_output,
            "tool_trace": tool_trace,
            "version_bundle": version_bundle,
        }
    }


@app.get("/runs/{run_id}/items/{item_id}")
def api_get_item_result(run_id: str, item_id: str) -> dict[str, Any]:
    result = get_item_result(run_id, item_id)
    if not result:
        return {
            "error": {
                "kind": "not_found",
                "code": "ITEM_NOT_FOUND",
                "message": f"Item {item_id} not found in run {run_id}",
                "details": {"run_id": run_id, "item_id": item_id},
            }
        }
    return {"content": result}


@app.get("/runs/{run_id}/artifacts/{filename:path}")
def api_get_artifact(run_id: str, filename: str) -> dict[str, Any]:
    return _redact_paths(get_artifact_content_by_run(run_id, filename))


@app.post("/regression")
def api_run_regression(req: RegressionRequestSchema) -> dict[str, Any]:
    request = RegressionRequest(
        suite_path=Path(req.suite_path),
        sut_url=req.sut_url or default_sut_url(),
        sut_timeout=req.sut_timeout,
        artifacts_dir=Path(req.artifacts_dir) if req.artifacts_dir else None,
        min_pass_rate=req.min_pass_rate,
    )
    response = run_regression_service(request)
    return response.to_dict()


@app.get("/demo/cases")
def api_list_demo_cases() -> dict[str, Any]:
    """Return supported demo case names for the frontend dropdown."""
    return {"cases": list_demo_cases()}


@app.post("/demo/failure")
def api_run_demo_failure(req: DemoFailureRequest) -> dict[str, Any]:
    """Run a real demo failure batch. Returns 400 if case is unsupported."""
    try:
        return run_demo_failure(req.case_name, base_sut_url=default_sut_url())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
