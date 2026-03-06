"""
Shared task/checker registry. Single source of truth for task_type -> generator, oracle, mock_sut, verifier.
"""
from typing import Any, Callable, Dict, Optional

from ..agents.a1_item_generator import (
    _make_add_item,
    _make_email_item,
    _make_sentiment_item,
    _make_trajectory_email_item,
    _make_structured_extraction_item,
    _make_classify_canonical_item,
)
from ..agents.a1b_oracle_builder import (
    build_add_oracle,
    build_email_oracle,
    build_sentiment_oracle,
    build_trajectory_oracle,
    build_structured_extraction_oracle,
    build_classify_canonical_oracle,
)
from .mock_suts import (
    solve_add,
    solve_email,
    solve_sentiment,
    solve_trajectory_email,
    solve_structured_extraction,
    solve_classify_canonical,
)


class TaskDef:
    def __init__(
        self,
        *,
        generator: Callable[..., Dict[str, Any]],
        oracle_builder: Callable[[Dict[str, Any]], Dict[str, Any]],
        mock_sut: Callable[[Dict[str, Any]], str],
        verifier_plan: str,
        checker_name: Optional[str] = None,
    ):
        self.generator = generator
        self.oracle_builder = oracle_builder
        self.mock_sut = mock_sut
        self.verifier_plan = verifier_plan
        self.checker_name = checker_name


TASK_REGISTRY: Dict[str, TaskDef] = {
    "json_math_add": TaskDef(
        generator=_make_add_item,
        oracle_builder=build_add_oracle,
        mock_sut=solve_add,
        verifier_plan="programmatic_check",
        checker_name="math_add_v1",
    ),
    "json_extract_email": TaskDef(
        generator=_make_email_item,
        oracle_builder=build_email_oracle,
        mock_sut=solve_email,
        verifier_plan="exact_match",
        checker_name=None,
    ),
    "json_classify_sentiment": TaskDef(
        generator=_make_sentiment_item,
        oracle_builder=build_sentiment_oracle,
        mock_sut=solve_sentiment,
        verifier_plan="exact_match",
        checker_name=None,
    ),
    "trajectory_email_then_answer": TaskDef(
        generator=_make_trajectory_email_item,
        oracle_builder=build_trajectory_oracle,
        mock_sut=solve_trajectory_email,
        verifier_plan="trajectory_check",
        checker_name=None,
    ),
    "json_extract_structured": TaskDef(
        generator=_make_structured_extraction_item,
        oracle_builder=build_structured_extraction_oracle,
        mock_sut=solve_structured_extraction,
        verifier_plan="programmatic_check",
        checker_name="structured_extraction_v1",
    ),
    "json_classify_canonical": TaskDef(
        generator=_make_classify_canonical_item,
        oracle_builder=build_classify_canonical_oracle,
        mock_sut=solve_classify_canonical,
        verifier_plan="programmatic_check",
        checker_name="classification_canonical_v1",
    ),
}


def get_task_registry() -> Dict[str, TaskDef]:
    return TASK_REGISTRY


# Checker registry: for programmatic_check (and future checkers) lookup by checker_name
from ..eval_methods.programmatic_check import (
    run_programmatic_check_math_add,
    run_programmatic_check_structured_extraction,
    run_programmatic_check_classification_canonical,
)

CHECKER_REGISTRY: Dict[str, Callable[..., Any]] = {
    "math_add_v1": run_programmatic_check_math_add,
    "structured_extraction_v1": run_programmatic_check_structured_extraction,
    "classification_canonical_v1": run_programmatic_check_classification_canonical,
}
