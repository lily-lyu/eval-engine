"""
Demo service: run a single guaranteed-failure batch for demo day.
Uses mock HTTP SUT with demo_case query param (wrong_email / wrong_sentiment, etc.).
"""
from __future__ import annotations

import os
from typing import Any

BASE_SUT_URL = os.getenv("DEFAULT_SUT_URL", "http://localhost:8001/sut/run")

from eval_engine.services.run_index_service import get_repo_root
from eval_engine.services.run_service import RunBatchRequest, run_batch_service


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
}


def run_demo_failure(
    case_name: str,
    base_sut_url: str = BASE_SUT_URL,
    sut_timeout: int = 30,
) -> dict[str, Any]:
    """
    Run one demo failure batch. case_name must be one of DEMO_SPECS (e.g. wrong_email, wrong_sentiment).
    SUT is called with ?demo_case={case_name} so the repo-root server returns intentional wrong output.
    Returns run_batch response dict or error dict.
    """
    if case_name not in DEMO_SPECS:
        return {
            "error": {
                "kind": "invalid_input",
                "code": "UNKNOWN_DEMO_CASE",
                "message": f"Unknown demo case: {case_name}",
                "details": {"allowed": sorted(DEMO_SPECS.keys())},
            }
        }

    sut_url = f"{base_sut_url.rstrip('/')}?demo_case={case_name}" if "?" not in base_sut_url else f"{base_sut_url}&demo_case={case_name}"
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
