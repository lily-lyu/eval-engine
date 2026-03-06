from pathlib import Path

from .hashing import sha256_bytes


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
