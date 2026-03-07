import argparse
import json
import sys
from pathlib import Path

from .regression import generate_golden_suite
from .break_suite import run_break_suite, write_break_suite_jsonl
from .services import (
    RunBatchRequest,
    run_batch_service,
    RegressionRequest,
    run_regression_service,
)


def main() -> None:
    parser = argparse.ArgumentParser(prog="eval_engine")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run_p = sub.add_parser("run", help="Run a batch end-to-end.")
    run_p.add_argument("--spec", required=True, help="Path to dataset_spec.json")
    run_p.add_argument("--quota", type=int, default=20, help="How many items to generate")
    run_p.add_argument("--sut", type=str, default="mock", help="SUT name: mock | mock_fail | http")
    run_p.add_argument("--sut_url", type=str, default="", help="HTTP SUT URL when --sut http")
    run_p.add_argument("--sut_timeout", type=int, default=30, help="HTTP timeout seconds")
    run_p.add_argument("--model_version", type=str, default="mock-1", help="model version label for run_record")

    reg_p = sub.add_parser("regression", help="Run golden regression suite against HTTP SUT; exit non-zero if gate fails.")
    reg_p.add_argument("--suite", required=True, help="Path to golden_suite.jsonl")
    reg_p.add_argument("--sut_url", required=True, help="HTTP SUT URL")
    reg_p.add_argument("--sut_timeout", type=int, default=30, help="HTTP timeout seconds")
    reg_p.add_argument("--min_pass_rate", type=float, default=0.95, help="Minimum pass rate (0-1); gate fails if below")
    reg_p.add_argument("--artifacts_dir", type=str, default="", help="Optional dir for run artifacts")

    gen_p = sub.add_parser("generate-golden", help="Generate frozen golden_suite.jsonl from spec.")
    gen_p.add_argument("--spec", required=True, help="Path to dataset_spec.json")
    gen_p.add_argument("--output", required=True, help="Output path for golden_suite.jsonl")
    gen_p.add_argument("--quota", type=int, default=50, help="Number of items to generate")
    gen_p.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility")

    break_p = sub.add_parser("break-suite", help="Run frozen break suite; exit non-zero if any pathway fails.")
    break_p.add_argument("--suite", default="examples/break_suite.jsonl", help="Path to break_suite.jsonl")
    break_p.add_argument("--artifacts_dir", type=str, default="", help="Optional dir for run artifacts")

    gen_break_p = sub.add_parser("generate-break-suite", help="Regenerate examples/break_suite.jsonl from break_suite_data.")
    gen_break_p.add_argument("--output", default="examples/break_suite.jsonl", help="Output path for break_suite.jsonl")

    gate_p = sub.add_parser("gate", help="Run invariant gate: break-suite first, then regression.")
    gate_p.add_argument("--break_suite", default="examples/break_suite.jsonl", help="Path to break_suite.jsonl")
    gate_p.add_argument("--golden_suite", required=True, help="Path to golden_suite.jsonl")
    gate_p.add_argument("--sut_url", required=True, help="HTTP SUT URL for regression")
    gate_p.add_argument("--sut_timeout", type=int, default=30, help="HTTP timeout seconds")
    gate_p.add_argument("--min_pass_rate", type=float, default=0.95, help="Minimum pass rate (0-1) for regression")
    gate_p.add_argument("--artifacts_dir", type=str, default="", help="Optional dir for run artifacts")

    args = parser.parse_args()
    project_root = Path(__file__).resolve().parents[1]

    if args.cmd == "run":
        spec_path = Path(args.spec)
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        request = RunBatchRequest(
            project_root=project_root,
            spec=spec,
            quota=args.quota,
            sut_name=args.sut,
            model_version=args.model_version,
            sut_url=args.sut_url,
            sut_timeout=args.sut_timeout,
        )
        response = run_batch_service(request)
        run_dir = response.run_dir
        print(f"\n✅ Run complete: {run_dir}\n")
        print(f"- events: {run_dir / 'events.jsonl'}")
        print(f"- record: {run_dir / 'run_record.json'}")
        print(f"- summary: {run_dir / 'run_summary.json'}")

    elif args.cmd == "regression":
        suite_path = Path(args.suite)
        artifacts_dir = Path(args.artifacts_dir) if args.artifacts_dir else None
        request = RegressionRequest(
            suite_path=suite_path,
            sut_url=args.sut_url,
            sut_timeout=args.sut_timeout,
            artifacts_dir=artifacts_dir,
            min_pass_rate=args.min_pass_rate,
        )
        response = run_regression_service(request)
        print(f"Regression: pass_rate={response.pass_rate:.2%} min_pass_rate={response.min_pass_rate:.2%} gate={'PASS' if response.passed_gate else 'FAIL'}")
        if response.failures:
            print(f"Failures ({len(response.failures)}):")
            for r in response.failures[:10]:
                print(f"  - {r['item_id']} verdict={r['verdict']} error_type={r.get('error_type')}")
        if not response.passed_gate:
            sys.exit(1)

    elif args.cmd == "generate-golden":
        spec_path = Path(args.spec)
        output_path = Path(args.output)
        generate_golden_suite(spec_path=spec_path, output_path=output_path, quota=args.quota, seed=args.seed)

    elif args.cmd == "break-suite":
        suite_path = project_root / args.suite if not Path(args.suite).is_absolute() else Path(args.suite)
        artifacts_dir = Path(args.artifacts_dir) if args.artifacts_dir else None
        results, errors = run_break_suite(suite_path, artifacts_dir=artifacts_dir)
        passed = sum(1 for r in results if r["passed"])
        print(f"Break suite: {passed}/{len(results)} scenarios passed")
        if errors:
            for e in errors:
                print(f"  ERROR: {e}")
        if passed != len(results) or errors:
            sys.exit(1)

    elif args.cmd == "generate-break-suite":
        output_path = project_root / args.output if not Path(args.output).is_absolute() else Path(args.output)
        write_break_suite_jsonl(output_path)
        print(f"Wrote {output_path}")

    elif args.cmd == "gate":
        artifacts_dir = Path(args.artifacts_dir) if args.artifacts_dir else None
        break_suite_path = project_root / args.break_suite if not Path(args.break_suite).is_absolute() else Path(args.break_suite)
        results, errors = run_break_suite(break_suite_path, artifacts_dir=artifacts_dir)
        passed = sum(1 for r in results if r["passed"])
        print(f"Break suite: {passed}/{len(results)} scenarios passed")
        if passed != len(results) or errors:
            for e in errors:
                print(f"  ERROR: {e}")
            sys.exit(1)
        reg_request = RegressionRequest(
            suite_path=Path(args.golden_suite),
            sut_url=args.sut_url,
            sut_timeout=args.sut_timeout,
            artifacts_dir=artifacts_dir,
            min_pass_rate=args.min_pass_rate,
        )
        reg_response = run_regression_service(reg_request)
        print(f"Regression: pass_rate={reg_response.pass_rate:.2%} gate={'PASS' if reg_response.passed_gate else 'FAIL'}")
        if reg_response.failures:
            for r in reg_response.failures[:10]:
                print(f"  - {r['item_id']} verdict={r['verdict']} error_type={r.get('error_type')}")
        if not reg_response.passed_gate:
            sys.exit(1)


if __name__ == "__main__":
    main()
