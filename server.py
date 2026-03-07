import json
import os
import re
import time
from datetime import datetime, timezone

from fastapi import FastAPI, Query
from pydantic import BaseModel

from eval_engine.tasks.registry import get_task_registry

app = FastAPI()

# Set this to your real model identifier when deploying (e.g. "doubao-pro-xxx")
SUT_MODEL_VERSION = "http-sut-local"


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


def _apply_trajectory_test_mode(task_type: str, inp: dict, output: dict) -> tuple[dict, list]:
    tool_trace: list = []
    if task_type != "trajectory_email_then_answer":
        return output, tool_trace

    mode = os.environ.get("TRAJECTORY_TEST_MODE", "").strip().lower()

    text = inp.get("text", "")
    m = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
    extracted_email = m.group(0) if m else ""

    args_obj = {"query": text}
    result_obj = {"email": extracted_email}

    if mode == "arg_bad":
        args_obj = {"text": text}
    if mode == "binding_mismatch":
        output = {"email": "wrong@example.com"}

    base = {
        "name": "search_email_db",
        "args": args_obj,
        "result": result_obj,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if mode == "missing":
        tool_trace = []
    elif mode == "too_many":
        tool_trace = [base, {**base, "timestamp": datetime.now(timezone.utc).isoformat()}]
    elif mode == "wrong_order":
        tool_trace = [
            {"name": "other_tool", "args": {}, "result": None, "timestamp": datetime.now(timezone.utc).isoformat()},
            {
                "name": "search_email_db",
                "args": args_obj,
                "result": result_obj,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        ]
    else:
        tool_trace = [base]

    return output, tool_trace


@app.post("/run")
def run(payload: RunPayload, demo_case: str | None = Query(default=None)):
    t0 = time.perf_counter()
    task_type = payload.task_type or ""

    # Intentional failure demo: exact-match wrong email
    if demo_case == "wrong_email" and task_type == "json_extract_email":
        return {
            "model_version": SUT_MODEL_VERSION,
            "output": {"email": "definitely_wrong@example.com"},
            "latency_ms": 5,
            "tool_trace": [],
        }

    # Intentional failure demo: wrong sentiment label
    if demo_case == "wrong_sentiment" and task_type == "json_classify_sentiment":
        return {
            "model_version": SUT_MODEL_VERSION,
            "output": {"label": "negative"},
            "latency_ms": 5,
            "tool_trace": [],
        }

    # Normal stub behavior
    output = _run_registry_mock(task_type, payload.input)
    output, tool_trace = _apply_trajectory_test_mode(task_type, payload.input, output)
    latency_ms = max(1, int(round((time.perf_counter() - t0) * 1000)))
    return {
        "model_version": SUT_MODEL_VERSION,
        "output": output,
        "latency_ms": latency_ms,
        "tool_trace": tool_trace,
    }
