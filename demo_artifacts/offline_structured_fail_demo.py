import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import json

from eval_engine.agents.a2_verifier import verify
from eval_engine.agents.a3_diagnoser import diagnose
from eval_engine.agents.a6_data_producer import produce_data_requests
from eval_engine.break_suite import _make_raw_ref

src = Path("examples/break_suite.jsonl")
artifacts_dir = Path("demo_artifacts/offline_structured_fail")
artifacts_dir.mkdir(parents=True, exist_ok=True)

picked = None
for line in src.read_text(encoding="utf-8").splitlines():
    if not line.strip():
        continue
    row = json.loads(line)
    if row.get("scenario_id") == "structured_extraction_fail":
        picked = row
        break

if not picked:
    raise SystemExit("Could not find structured_extraction_fail in break_suite.jsonl")

item = picked["item"]
oracle = picked["oracle"]
raw_output = picked["raw_output"]

raw_ref = _make_raw_ref(artifacts_dir, item["item_id"], raw_output)

result = verify(
    item=item,
    oracle=oracle,
    raw_output=raw_output,
    model_version="break-suite",
    seed=42,
    raw_output_ref=raw_ref,
    tool_trace=[],
    artifacts_dir=artifacts_dir,
)

eval_results = [result]
clusters, plans = diagnose(eval_results)
data_requests = produce_data_requests(clusters, eval_results)

summary = {
    "phase": "offline_structured_fail",
    "item_id": item["item_id"],
    "task_type": item["task_type"],
    "verdict": result.get("verdict"),
    "error_type": result.get("error_type"),
    "evidence_codes": [e.get("code") for e in result.get("evidence", [])],
    "diagnosis": plans,
    "data_requests": data_requests,
}

(artifacts_dir / "picked_row.json").write_text(
    json.dumps(picked, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
(artifacts_dir / "eval_result.json").write_text(
    json.dumps(result, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
(artifacts_dir / "diagnosis.json").write_text(
    json.dumps(plans, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
(artifacts_dir / "data_requests.json").write_text(
    json.dumps(data_requests, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
(artifacts_dir / "summary.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

md = []
md.append("# Demo Report — Structured Extraction Failure")
md.append("")
md.append(f"- Item ID: **{item['item_id']}**")
md.append(f"- Task Type: **{item['task_type']}**")
md.append(f"- Verdict: **{result.get('verdict')}**")
md.append(f"- Error Type: **{result.get('error_type')}**")
md.append(f"- Evidence Codes: **{[e.get('code') for e in result.get('evidence', [])]}**")
md.append("")
md.append("## Diagnoser Output")
for p in plans:
    md.append(f"- `{p.get('cluster_id')}` — {p.get('summary')}")
md.append("")
md.append("## A6 Data Requests")
if data_requests:
    for r in data_requests:
        md.append(f"- `{r.get('issue_type')}` — {r.get('what_to_collect')}")
else:
    md.append("- No A6 data requests generated for this failure type.")
md.append("")

(artifacts_dir / "demo_report.md").write_text(
    "\n".join(md),
    encoding="utf-8",
)

print(json.dumps(summary, ensure_ascii=False, indent=2))
print(f"Saved to {artifacts_dir}")
