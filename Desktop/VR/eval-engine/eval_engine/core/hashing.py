import hashlib
import json
from typing import Any


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_json(obj: Any) -> str:
    # Stable JSON hash: sorted keys, no whitespace
    b = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(b)


def normalize_prompt(s: str) -> str:
    # Very simple normalization for dedup MVP
    return " ".join(s.strip().lower().split())
