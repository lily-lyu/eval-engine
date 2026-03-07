"""
MCP resources: URI-addressable data (eval://runs, eval://runs/{run_id}/...).
Register with register_resources(mcp) from server.py.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from eval_engine.services.artifact_service import (
    get_artifact_content_by_run,
    list_run_files,
)
from eval_engine.services.diagnosis_service import list_failure_clusters
from eval_engine.services.run_index_service import get_run_summary, list_runs
from eval_engine.services.run_view_service import get_run_events, get_eval_results

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def register_resources(mcp: "FastMCP") -> None:
    @mcp.resource("eval://runs")
    def runs_resource() -> str:
        return json.dumps({"runs": list_runs(limit=50)}, ensure_ascii=False, indent=2)

    @mcp.resource("eval://runs/{run_id}/summary")
    def run_summary_resource(run_id: str) -> str:
        return json.dumps(get_run_summary(run_id) or {}, ensure_ascii=False, indent=2)

    @mcp.resource("eval://runs/{run_id}/files")
    def run_files_resource(run_id: str) -> str:
        return json.dumps(list_run_files(run_id), ensure_ascii=False, indent=2)

    @mcp.resource("eval://runs/{run_id}/events")
    def run_events_resource(run_id: str) -> str:
        out = get_artifact_content_by_run(run_id, "events.jsonl")
        return json.dumps(out, ensure_ascii=False, indent=2)

    @mcp.resource("eval://runs/{run_id}/eval_results")
    def run_eval_results_resource(run_id: str) -> str:
        out = get_artifact_content_by_run(run_id, "eval_results.jsonl")
        return json.dumps(out, ensure_ascii=False, indent=2)

    @mcp.resource("eval://runs/{run_id}/clusters")
    def run_clusters_resource(run_id: str) -> str:
        return json.dumps(list_failure_clusters(run_id), ensure_ascii=False, indent=2)

    @mcp.resource("eval://runs/{run_id}/events_parsed")
    def run_events_parsed_resource(run_id: str) -> str:
        return json.dumps(get_run_events(run_id), ensure_ascii=False, indent=2)

    @mcp.resource("eval://runs/{run_id}/eval_results_parsed")
    def run_eval_results_parsed_resource(run_id: str) -> str:
        return json.dumps(get_eval_results(run_id), ensure_ascii=False, indent=2)
