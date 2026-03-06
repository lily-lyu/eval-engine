import json
from pathlib import Path
from typing import Any, Dict, Iterable

from .hashing import sha256_bytes
from .timeutil import now_iso


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, obj: Any) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def append_jsonl(path: Path, records: Iterable[Dict[str, Any]]) -> None:
    with path.open("a", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def save_artifact_text(artifacts_dir: Path, filename: str, text: str, mime: str = "text/plain") -> Dict[str, Any]:
    ensure_dir(artifacts_dir)
    b = text.encode("utf-8")
    h = sha256_bytes(b)
    artifact_path = artifacts_dir / filename
    artifact_path.write_bytes(b)
    return {
        "sha256": h,
        "uri": str(artifact_path),
        "mime": mime,
        "bytes": len(b),
        "created_at": now_iso()
    }
