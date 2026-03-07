"""
Regression service: run golden suite against SUT; returns structured result.
No print or sys.exit; caller decides exit code and output.
"""
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..regression import run_regression


class RegressionRequest:
    """Request for regression run."""

    def __init__(
        self,
        suite_path: Path,
        sut_url: str,
        sut_timeout: int = 30,
        artifacts_dir: Optional[Path] = None,
        min_pass_rate: float = 0.95,
    ):
        self.suite_path = Path(suite_path)
        self.sut_url = sut_url
        self.sut_timeout = sut_timeout
        self.artifacts_dir = Path(artifacts_dir) if artifacts_dir else None
        self.min_pass_rate = min_pass_rate


class RegressionResponse:
    """Structured response from run_regression_service."""

    def __init__(
        self,
        passed_gate: bool,
        pass_rate: float,
        results: List[Dict[str, Any]],
        failures: List[Dict[str, Any]],
        min_pass_rate: float,
    ):
        self.passed_gate = passed_gate
        self.pass_rate = pass_rate
        self.results = results
        self.failures = failures
        self.min_pass_rate = min_pass_rate

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed_gate": self.passed_gate,
            "pass_rate": self.pass_rate,
            "results": self.results,
            "failures": self.failures,
            "min_pass_rate": self.min_pass_rate,
        }


def run_regression_service(request: RegressionRequest) -> RegressionResponse:
    """
    Run golden regression suite against HTTP SUT.
    Returns typed response; caller uses passed_gate for exit code.
    """
    passed_gate, pass_rate, results, failures = run_regression(
        suite_path=request.suite_path,
        sut_url=request.sut_url,
        sut_timeout=request.sut_timeout,
        artifacts_dir=request.artifacts_dir,
        min_pass_rate=request.min_pass_rate,
    )
    return RegressionResponse(
        passed_gate=passed_gate,
        pass_rate=pass_rate,
        results=results,
        failures=failures,
        min_pass_rate=request.min_pass_rate,
    )
