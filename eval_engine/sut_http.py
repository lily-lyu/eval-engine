import json
import urllib.request
from typing import Any, Dict, Tuple


def run_sut_http(url: str, payload: Dict[str, Any], timeout_s: int = 30) -> Tuple[int, str]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url=url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        status = int(resp.status)
        text = resp.read().decode("utf-8", errors="replace")
        return status, text
