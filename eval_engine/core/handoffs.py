from pathlib import Path
from typing import Any, Dict, List

from .schema import validate_or_raise
from .storage import append_jsonl
from .timeutil import now_iso


def emit_handoff(
    run_dir: Path,
    run_id: str,
    item_id: str,
    agent_id: str,
    stage: str,
    status: str,
    output_ref: Dict[str, Any],
    version_bundle: Dict[str, Any],
    input_refs: List[Dict[str, Any]] | None = None,
    failure_code: str = "",
    message: str = "",
) -> Dict[str, Any]:
    rec = {
        "run_id": run_id,
        "item_id": item_id,
        "agent_id": agent_id,
        "stage": stage,
        "status": status,
        "failure_code": failure_code,
        "message": message,
        "input_refs": input_refs or [],
        "output_ref": output_ref,
        "version_bundle": version_bundle,
        "created_at": now_iso(),
    }
    validate_or_raise("agent_handoff.schema.json", rec)
    append_jsonl(run_dir / "agent_handoffs.jsonl", [rec])
    return rec
