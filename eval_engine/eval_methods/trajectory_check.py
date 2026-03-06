"""
Trajectory check: validate tool-use behavior (required tools, order, max_calls).
Emits structured evidence with codes for diagnosis and data-production.
"""
from collections import Counter

from jsonschema import Draft202012Validator

# Structured failure codes for clustering and a6_data_producer
TOOL_TRACE_NOT_LIST = "TOOL_TRACE_NOT_LIST"
TOOL_SEQUENCE_MISSING = "TOOL_SEQUENCE_MISSING"
TOOL_MAX_CALLS_EXCEEDED = "TOOL_MAX_CALLS_EXCEEDED"
TOOL_ARGS_SCHEMA_FAILED = "TOOL_ARGS_SCHEMA_FAILED"
TOOL_BINDING_MISMATCH = "TOOL_BINDING_MISMATCH"
TOOL_BINDING_MISSING_OUTPUT = "TOOL_BINDING_MISSING_OUTPUT"
TOOL_BINDING_MISSING_TOOL = "TOOL_BINDING_MISSING_TOOL"


def run_trajectory_check(expected, tool_trace, parsed_output=None):
    evidence = []

    # 0) type check
    if not isinstance(tool_trace, list):
        evidence.append({
            "kind": "trajectory_check",
            "code": TOOL_TRACE_NOT_LIST,
            "dimension": "tool_use",
            "message": "tool_trace is not a list",
        })
        return False, "trajectory_check failed (tool_trace type)", evidence

    names = [t.get("name") for t in tool_trace if isinstance(t, dict)]
    counts = Counter(names)

    # 1) required_first
    req_first = expected.get("required_first")
    if req_first:
        if len(names) == 0:
            evidence.append({
                "kind": "trajectory_check",
                "code": TOOL_SEQUENCE_MISSING,
                "dimension": "tool_use",
                "expected": {"required_first": req_first},
                "observed": {"names": []},
                "message": f"required_first set but tool_trace is empty; expected first in {req_first}",
            })
            return False, "trajectory_check failed (required_first)", evidence
        if names[0] not in req_first:
            evidence.append({
                "kind": "trajectory_check",
                "code": TOOL_SEQUENCE_MISSING,
                "dimension": "tool_use",
                "expected": {"required_first": req_first},
                "observed": {"first_tool": names[0]},
                "message": f"first tool must be one of {req_first}, got '{names[0]}'",
            })
            return False, "trajectory_check failed (required_first)", evidence

    # 2) must_include
    for t in expected.get("must_include", []) or []:
        if counts.get(t, 0) < 1:
            evidence.append({
                "kind": "trajectory_check",
                "code": TOOL_SEQUENCE_MISSING,
                "dimension": "tool_use",
                "tool_name": t,
                "expected": {"must_include": t},
                "observed": {"count": counts.get(t, 0)},
                "message": f"missing tool {t}",
            })
            return False, "trajectory_check failed (must_include)", evidence

    # 3) max_calls
    for t, m in (expected.get("max_calls") or {}).items():
        if counts.get(t, 0) > m:
            evidence.append({
                "kind": "trajectory_check",
                "code": TOOL_MAX_CALLS_EXCEEDED,
                "dimension": "tool_use",
                "tool_name": t,
                "expected": {"max_calls": m},
                "observed": {"count": counts.get(t, 0)},
                "message": f"called tool {t} {counts.get(t,0)} times (max {m})",
            })
            return False, "trajectory_check failed (max_calls)", evidence

    # 4) required_sequence (subsequence)
    seq = expected.get("required_sequence") or []
    if seq:
        i = 0
        for n in names:
            if i < len(seq) and n == seq[i]:
                i += 1
        if i < len(seq):
            evidence.append({
                "kind": "trajectory_check",
                "code": TOOL_SEQUENCE_MISSING,
                "dimension": "tool_use",
                "expected": {"required_sequence": seq},
                "observed": {"names": names},
                "message": f"required_sequence not satisfied; expected subsequence {seq}, saw {names}",
            })
            return False, "trajectory_check failed (required_sequence)", evidence

    # 5) arg_schema
    arg_schema = expected.get("arg_schema")
    if arg_schema:
        tool = arg_schema.get("tool")
        schema = arg_schema.get("schema")
        calls = [t for t in tool_trace if isinstance(t, dict) and t.get("name") == tool]
        if not calls:
            evidence.append({
                "kind": "trajectory_check",
                "code": TOOL_SEQUENCE_MISSING,
                "dimension": "schema",
                "tool_name": tool,
                "expected": {"tool": tool},
                "message": f"arg_schema: missing tool {tool}",
            })
            return False, "trajectory_check failed (arg_schema)", evidence
        args = calls[0].get("args") or {}
        v = Draft202012Validator(schema)
        errs = sorted(v.iter_errors(args), key=lambda e: e.path)
        if errs:
            msg = "; ".join([f"{list(e.path)}: {e.message}" for e in errs[:3]])
            evidence.append({
                "kind": "trajectory_check",
                "code": TOOL_ARGS_SCHEMA_FAILED,
                "dimension": "schema",
                "tool_name": tool,
                "expected": {"schema": schema},
                "observed": {"args": args, "validation_errors": [{"path": list(e.path), "message": e.message} for e in errs[:3]]},
                "message": f"arg_schema failed for {tool}: {msg}",
            })
            return False, "trajectory_check failed (arg_schema)", evidence

    # 6) bindings (tool result must match final output)
    bindings = expected.get("bindings") or []
    if bindings:
        if parsed_output is None:
            evidence.append({
                "kind": "trajectory_check",
                "code": TOOL_BINDING_MISSING_OUTPUT,
                "dimension": "grounding",
                "message": "bindings present but parsed_output is None",
            })
            return False, "trajectory_check failed (bindings)", evidence

        def jget(obj, path):
            if not path.startswith("$."):
                return None
            cur = obj
            for part in path[2:].split("."):
                if not isinstance(cur, dict) or part not in cur:
                    return None
                cur = cur[part]
            return cur

        for b in bindings:
            tool = b["tool"]
            tool_path = b["tool_path"]
            out_path = b["output_path"]
            calls = [t for t in tool_trace if isinstance(t, dict) and t.get("name") == tool]
            if not calls:
                evidence.append({
                    "kind": "trajectory_check",
                    "code": TOOL_BINDING_MISSING_TOOL,
                    "dimension": "grounding",
                    "tool_name": tool,
                    "locator": {"tool_path": tool_path, "output_path": out_path},
                    "message": f"bindings: missing tool {tool}",
                })
                return False, "trajectory_check failed (bindings)", evidence
            result = calls[0].get("result") or {}
            tool_val = jget(result, tool_path)
            out_val = jget(parsed_output, out_path)
            if tool_val != out_val:
                evidence.append({
                    "kind": "trajectory_check",
                    "code": TOOL_BINDING_MISMATCH,
                    "dimension": "grounding",
                    "tool_name": tool,
                    "expected": {"output_path": out_path, "value": tool_val},
                    "observed": {"value": out_val},
                    "locator": {"tool_path": tool_path, "output_path": out_path},
                    "message": f"bindings mismatch: {tool}{tool_path}={tool_val} != output{out_path}={out_val}",
                })
                return False, "trajectory_check failed (bindings)", evidence

    return True, "trajectory_check passed", evidence
