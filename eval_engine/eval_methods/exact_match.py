from typing import Any, Tuple


def deep_equal(a: Any, b: Any) -> bool:
    return a == b


def run_exact_match(parsed_output: Any, expected: Any) -> Tuple[bool, str]:
    if deep_equal(parsed_output, expected):
        return True, "exact_match passed"
    return False, f"exact_match failed: expected={expected} got={parsed_output}"
