"""
Mock SUT router: /sut/run for eval-engine batch and regression calls.
Supports demo_case query param for intentional failures.
"""
import json
import os
import re
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Query
from pydantic import BaseModel

from eval_engine.tasks.registry import get_task_registry

router = APIRouter(prefix="/sut", tags=["sut"])

SUT_MODEL_VERSION = os.getenv("SUT_MODEL_VERSION", "http-sut-local")


class RunPayload(BaseModel):
    item_id: str
    prompt: str
    input: dict
    output_schema: dict
    task_type: str | None = None


def _run_registry_mock(task_type: str, inp: dict) -> dict:
    reg = get_task_registry()
    if task_type not in reg:
        return {}
    item = {"input": inp}
    raw = reg[task_type].mock_sut(item)
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _apply_demo_case(
    task_type: str,
    inp: dict,
    output: dict,
    demo_case: str,
) -> tuple[dict, list]:
    tool_trace: list = []

    if demo_case == "wrong_email" and task_type == "json_extract_email":
        return {"email": "definitely_wrong@example.com"}, []

    if demo_case == "wrong_sentiment" and task_type == "json_classify_sentiment":
        return {"label": "negative"}, []

    if demo_case == "wrong_math" and task_type == "json_math_add":
        a = inp.get("a", 0)
        b = inp.get("b", 0)
        return {"answer": a + b + 1}, []

    if task_type != "trajectory_email_then_answer":
        return output, tool_trace

    text = inp.get("text", "")
    m = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
    extracted_email = m.group(0) if m else ""

    args_obj = {"query": text}
    result_obj = {"email": extracted_email}
    final_output = output

    if demo_case == "traj_arg_bad":
        args_obj = {"text": text}

    if demo_case == "traj_binding_mismatch":
        final_output = {"email": "wrong@example.com"}

    base = {
        "name": "search_email_db",
        "args": args_obj,
        "result": result_obj,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if demo_case == "traj_missing":
        tool_trace = []
    elif demo_case == "traj_too_many":
        tool_trace = [base, {**base, "timestamp": datetime.now(timezone.utc).isoformat()}]
    elif demo_case == "traj_wrong_order":
        tool_trace = [
            {"name": "other_tool", "args": {}, "result": None, "timestamp": datetime.now(timezone.utc).isoformat()},
            {"name": "search_email_db", "args": args_obj, "result": result_obj, "timestamp": datetime.now(timezone.utc).isoformat()},
        ]
    else:
        tool_trace = [base]

    return final_output, tool_trace


@router.post("/run")
def run(payload: RunPayload, demo_case: str | None = Query(default=None)):
    t0 = time.perf_counter()
    task_type = payload.task_type or ""

    output = _run_registry_mock(task_type, payload.input)

    env_mode = os.environ.get("TRAJECTORY_TEST_MODE", "").strip().lower()
    selected_demo_case = (demo_case or env_mode or "").strip().lower()

    output, tool_trace = _apply_demo_case(
        task_type=task_type,
        inp=payload.input,
        output=output,
        demo_case=selected_demo_case,
    )

    latency_ms = max(1, int(round((time.perf_counter() - t0) * 1000)))
    return {
        "model_version": SUT_MODEL_VERSION,
        "output": output,
        "latency_ms": latency_ms,
        "tool_trace": tool_trace,
    }
