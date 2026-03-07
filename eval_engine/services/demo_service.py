"""
Demo service: run a single guaranteed-failure batch for demo day.
Strict case-name mapping; SUT is called with demo_case (or trajectory_test_mode for trajectory cases).
"""
from __future__ import annotations

import os
from typing import Any

BASE_SUT_URL = os.getenv("DEFAULT_SUT_URL", "http://localhost:8001/sut/run")

from eval_engine.services.run_index_service import get_repo_root
from eval_engine.services.run_service import RunBatchRequest, run_batch_service

# Supported demo cases. SUT URL uses demo_case={case_name} for all; trajectory SUTs use that same name.
DEMO_SPECS = {
    "wrong_email": {
        "dataset_name": "demo_wrong_email",
        "dataset_spec_version": "1.0.0",
        "allowed_domain_tags": ["extraction"],
        "capability_targets": [
            {
                "target_id": "demo_wrong_email",
                "domain_tags": ["extraction"],
                "difficulty": "easy",
                "task_type": "json_extract_email",
                "quota_weight": 1,
            }
        ],
        "defaults": {
            "max_prompt_length": 20000,
            "max_retries_per_stage": 2,
            "seed": 42,
        },
    },
    "wrong_sentiment": {
        "dataset_name": "demo_wrong_sentiment",
        "dataset_spec_version": "1.0.0",
        "allowed_domain_tags": ["classification"],
        "capability_targets": [
            {
                "target_id": "demo_wrong_sentiment",
                "domain_tags": ["classification"],
                "difficulty": "easy",
                "task_type": "json_classify_sentiment",
                "quota_weight": 1,
            }
        ],
        "defaults": {
            "max_prompt_length": 20000,
            "max_retries_per_stage": 2,
            "seed": 42,
        },
    },
    "wrong_math": {
        "dataset_name": "demo_wrong_math",
        "dataset_spec_version": "1.0.0",
        "allowed_domain_tags": ["math"],
        "capability_targets": [
            {
                "target_id": "demo_wrong_math",
                "domain_tags": ["math"],
                "difficulty": "easy",
                "task_type": "json_math_add",
                "quota_weight": 1,
            }
        ],
        "defaults": {
            "max_prompt_length": 20000,
            "max_retries_per_stage": 2,
            "seed": 42,
        },
    },
    "traj_arg_bad": {
        "dataset_name": "demo_trajectory_arg_bad",
        "dataset_spec_version": "1.0.0",
        "allowed_domain_tags": ["trajectory"],
        "capability_targets": [
            {
                "target_id": "demo_trajectory",
                "domain_tags": ["trajectory"],
                "difficulty": "easy",
                "task_type": "trajectory_email_then_answer",
                "quota_weight": 1,
            }
        ],
        "defaults": {
            "max_prompt_length": 20000,
            "max_retries_per_stage": 2,
            "seed": 42,
        },
    },
    "traj_binding_mismatch": {
        "dataset_name": "demo_trajectory_binding_mismatch",
        "dataset_spec_version": "1.0.0",
        "allowed_domain_tags": ["trajectory"],
        "capability_targets": [
            {
                "target_id": "demo_trajectory",
                "domain_tags": ["trajectory"],
                "difficulty": "easy",
                "task_type": "trajectory_email_then_answer",
                "quota_weight": 1,
            }
        ],
        "defaults": {
            "max_prompt_length": 20000,
            "max_retries_per_stage": 2,
            "seed": 42,
        },
    },
}


def list_demo_cases() -> list[str]:
    """Return supported demo case names (for frontend dropdown)."""
    return sorted(DEMO_SPECS.keys())


def run_demo_failure(
    case_name: str,
    base_sut_url: str = BASE_SUT_URL,
    sut_timeout: int = 30,
) -> dict[str, Any]:
    """
    Run one demo failure batch. case_name must be one of DEMO_SPECS.
    Strict mapping: wrong_email, wrong_sentiment, wrong_math -> demo_case={case_name};
    traj_arg_bad -> demo_case=traj_arg_bad (SUT uses for trajectory_test_mode=arg_bad);
    traj_binding_mismatch -> demo_case=traj_binding_mismatch.
    Executes a real run and persists run_record.json, events.jsonl, eval_results.jsonl, clusters, run index.
    Returns run_batch response dict. Raises ValueError for unsupported case (caller should return 400).
    """
    if case_name not in DEMO_SPECS:
        raise ValueError(
            f"Unsupported demo case: {case_name}. Allowed: {sorted(DEMO_SPECS.keys())}"
        )

    sut_url = (
        f"{base_sut_url.rstrip('/')}?demo_case={case_name}"
        if "?" not in base_sut_url
        else f"{base_sut_url}&demo_case={case_name}"
    )
    request = RunBatchRequest(
        project_root=get_repo_root(),
        spec=DEMO_SPECS[case_name],
        quota=1,
        sut_name="http",
        model_version="http-sut-local-demo",
        sut_url=sut_url,
        sut_timeout=sut_timeout,
    )
    response = run_batch_service(request)
    return response.to_dict()
