from pathlib import Path
from typing import Any, Dict, List

from .hashing import sha256_bytes


def build_version_bundle(
    spec: Dict[str, Any],
    model_version: str,
    tool_snapshot_hash: str,
    seed: int,
    rubric_schema_version: str = "v1",
    eval_script_version: str = "v1",
    judge_prompt_version: str = "",
    judge_models: List[str] | None = None,
) -> Dict[str, Any]:
    return {
        "dataset_spec_version": spec["dataset_spec_version"],
        "rubric_schema_version": rubric_schema_version,
        "eval_script_version": eval_script_version,
        "model_version": model_version,
        "tool_snapshot_hash": tool_snapshot_hash,
        "seed": seed,
        "judge_prompt_version": judge_prompt_version,
        "judge_models": judge_models or [],
    }


def compute_tool_snapshot_hash(project_root: Path) -> str:
    """
    MVP: hash schema file bytes + python source bytes.
    Later you can add git commit, pip freeze, tool versions, etc.
    """
    parts = []
    schemas_dir = project_root / "schemas"
    for p in sorted(schemas_dir.glob("*.json")):
        parts.append(p.read_bytes())

    src_dir = project_root / "eval_engine"
    for p in sorted(src_dir.rglob("*.py")):
        parts.append(p.read_bytes())

    blob = b"\n".join(parts)
    return sha256_bytes(blob)
