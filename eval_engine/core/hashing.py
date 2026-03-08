import hashlib
import json
from typing import Any, Dict, Tuple


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_json(obj: Any) -> str:
    # Stable JSON hash: sorted keys, no whitespace
    b = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(b)


def normalize_prompt(s: str) -> str:
    # Very simple normalization for dedup MVP
    return " ".join(s.strip().lower().split())


def compute_dedup_fingerprint_inputs(
    item: Dict[str, Any],
    *,
    include_structural: bool = True,
) -> Dict[str, Any]:
    """
    Build the dict of fields used for dedup fingerprinting.
    When include_structural is True and item has provenance (blueprint_id, family_id),
    includes them so different blueprints/scenarios do not collapse.
    Does NOT include raw random literals (e.g. exact names/emails) so trivial
    duplicates are still caught.
    """
    norm = normalize_prompt(item.get("prompt", ""))
    inputs: Dict[str, Any] = {
        "prompt": norm,
        "task_type": item.get("task_type", ""),
        "difficulty": item.get("difficulty", ""),
    }
    if include_structural:
        prov = item.get("provenance") or {}
        if prov.get("blueprint_id"):
            inputs["blueprint_id"] = prov["blueprint_id"]
        if prov.get("family_id"):
            inputs["family_id"] = prov["family_id"]
        # materializer_type = task_type for synthetic; include for consistency
        if prov.get("materializer_type"):
            inputs["materializer_type"] = prov["materializer_type"]
    return inputs


def compute_dedup_fingerprint(item: Dict[str, Any], *, include_structural: bool = True) -> Tuple[str, Dict[str, Any]]:
    """
    Returns (fingerprint_hash, fingerprint_inputs).
    Structural fields (blueprint_id, family_id) are included when present so
    items that differ in scenario structure are not collapsed.
    """
    inputs = compute_dedup_fingerprint_inputs(item, include_structural=include_structural)
    return sha256_json(inputs), inputs
