"""
A6 data producer: route failures by error_type, evidence.code, task_type into
data requests (backlog). Single routing table; one request per issue_type (deduped).
"""
from typing import Dict, List, Optional

from ..core.schema import validate_or_raise
from ..eval_methods.trajectory_check import (
    TOOL_ARGS_SCHEMA_FAILED,
    TOOL_BINDING_MISMATCH,
    TOOL_SEQUENCE_MISSING,
    TOOL_MAX_CALLS_EXCEEDED,
    TOOL_TRACE_NOT_LIST,
    TOOL_BINDING_MISSING_OUTPUT,
    TOOL_BINDING_MISSING_TOOL,
)


def _evidence_code(eval_result: Dict) -> Optional[str]:
    """First evidence entry with a code, or None."""
    for e in eval_result.get("evidence", []) or []:
        if e.get("code"):
            return e["code"]
    return None


def _make_request(
    cluster_id: str,
    issue_type: str,
    priority: int,
    owner_type: str,
    what: str,
    hint: str,
    verif: str,
) -> Dict:
    req = {
        "cluster_id": cluster_id,
        "issue_type": issue_type,
        "priority": priority,
        "owner_type": owner_type,
        "what_to_collect": what,
        "template_hint": hint,
        "verification_eval": verif,
    }
    validate_or_raise("data_request.schema.json", req)
    return req


def _from_trajectory_failure(r: Dict, code: Optional[str]) -> Optional[Dict]:
    """Map TRAJECTORY_CHECK_FAILED + evidence code to one data request."""
    if code == TOOL_BINDING_MISMATCH:
        return _make_request(
            cluster_id="TRAJECTORY/TOOL_RESULT_IGNORED_OR_HALLUCINATION",
            issue_type="TOOL_RESULT_IGNORED_OR_HALLUCINATION",
            priority=1,
            owner_type="data",
            what="Collect agent trajectories where tool returns a value, but model output must copy/transform it exactly; include adversarial distractors.",
            hint="Generate tool-use examples with varied tool outputs; require output field to equal tool result field.",
            verif="Add/expand trajectory_check bindings tests; expect bindings mismatch rate to drop.",
        )
    if code == TOOL_ARGS_SCHEMA_FAILED:
        return _make_request(
            cluster_id="TRAJECTORY/TOOL_ARGS_BAD",
            issue_type="TOOL_ARGS_BAD",
            priority=1,
            owner_type="data",
            what="Collect tool-call examples with correct query formulation; include negative examples of malformed args.",
            hint="Add templates that force query formatting constraints (length, keywords); grade via arg_schema.",
            verif="Trajectory_check arg_schema failure rate drops.",
        )
    if code in (
        TOOL_SEQUENCE_MISSING,
        TOOL_MAX_CALLS_EXCEEDED,
        TOOL_TRACE_NOT_LIST,
        TOOL_BINDING_MISSING_OUTPUT,
        TOOL_BINDING_MISSING_TOOL,
    ):
        return _make_request(
            cluster_id="TRAJECTORY/MISSING_OR_WRONG_TOOL_SEQUENCE",
            issue_type="MISSING_OR_WRONG_TOOL_SEQUENCE",
            priority=1,
            owner_type="data",
            what="Collect examples where tool call is mandatory; train agent to call tool first; include cases where skipping tool leads to wrong answer.",
            hint="Trajectory task with required_first + required_sequence; grade deterministically.",
            verif="required_first/required_sequence failure rate drops.",
        )
    # Fallback when no structured code (e.g. old evidence)
    msgs = " ".join([e.get("message", "") for e in r.get("evidence", [])])
    if "bindings mismatch" in msgs:
        return _make_request(
            cluster_id="TRAJECTORY/TOOL_RESULT_IGNORED_OR_HALLUCINATION",
            issue_type="TOOL_RESULT_IGNORED_OR_HALLUCINATION",
            priority=1,
            owner_type="data",
            what="Collect agent trajectories where tool returns a value, but model output must copy/transform it exactly; include adversarial distractors.",
            hint="Generate tool-use examples with varied tool outputs; require output field to equal tool result field.",
            verif="Add/expand trajectory_check bindings tests; expect bindings mismatch rate to drop.",
        )
    if "arg_schema failed" in msgs:
        return _make_request(
            cluster_id="TRAJECTORY/TOOL_ARGS_BAD",
            issue_type="TOOL_ARGS_BAD",
            priority=1,
            owner_type="data",
            what="Collect tool-call examples with correct query formulation; include negative examples of malformed args.",
            hint="Add templates that force query formatting constraints (length, keywords); grade via arg_schema.",
            verif="Trajectory_check arg_schema failure rate drops.",
        )
    return _make_request(
        cluster_id="TRAJECTORY/MISSING_OR_WRONG_TOOL_SEQUENCE",
        issue_type="MISSING_OR_WRONG_TOOL_SEQUENCE",
        priority=1,
        owner_type="data",
        what="Collect examples where tool call is mandatory; train agent to call tool first; include cases where skipping tool leads to wrong answer.",
        hint="Trajectory task with required_first + required_sequence; grade deterministically.",
        verif="required_first/required_sequence failure rate drops.",
    )


def produce_data_requests(eval_results: List[Dict]) -> List[Dict]:
    """Route failures by error_type / evidence.code / task_type into data requests. Dedupe by issue_type."""
    requests: List[Dict] = []

    for r in eval_results:
        et = r.get("error_type", "")
        task_type = r.get("task_type", "")
        code = _evidence_code(r)

        if et == "TRAJECTORY_CHECK_FAILED":
            req = _from_trajectory_failure(r, code)
            if req:
                requests.append(req)

        elif et == "EXACT_MATCH_FAILED":
            requests.append(
                _make_request(
                    cluster_id=f"EXACT/{task_type or 'unknown'}",
                    issue_type="LABEL_OR_FIELD_VALUE_WRONG",
                    priority=2,
                    owner_type="data",
                    what="Collect more direct-answer supervision for exact field/value copying under distractors.",
                    hint="Add near-miss negatives and copy-exactly cases.",
                    verif="Exact-match failure rate drops on same slice.",
                )
            )

        elif et == "PROGRAMMATIC_CHECK_FAILED":
            if task_type == "json_extract_structured":
                requests.append(
                    _make_request(
                        cluster_id="PROGRAMMATIC/STRUCTURED_EXTRACTION",
                        issue_type="STRUCTURED_FIELD_EXTRACTION_BAD",
                        priority=1,
                        owner_type="data",
                        what="Collect structured extraction examples with paraphrased layouts, distractors, and missing-field robustness.",
                        hint="Vary field order, separators, and distractor spans.",
                        verif="Programmatic structured extraction failure rate drops.",
                    )
                )
            elif task_type == "json_classify_canonical":
                requests.append(
                    _make_request(
                        cluster_id="PROGRAMMATIC/CANONICAL_CLASSIFICATION",
                        issue_type="CANONICAL_LABEL_MAPPING_BAD",
                        priority=1,
                        owner_type="data",
                        what="Collect canonical-label mapping examples with synonyms, casing variants, and normalization edge cases.",
                        hint="Include alias->canonical supervision and adversarial label variants.",
                        verif="Canonical classification failure rate drops.",
                    )
                )
            else:
                requests.append(
                    _make_request(
                        cluster_id="PROGRAMMATIC/RULE_BASED",
                        issue_type="RULE_BASED_OUTPUT_FAILURE",
                        priority=2,
                        owner_type="data",
                        what="Collect examples that satisfy the programmatic checker; add coverage for failing patterns.",
                        hint="Align outputs with checker expectations and add edge cases.",
                        verif="Programmatic check failure rate drops for this task type.",
                    )
                )

        elif et in ("MODEL_OUTPUT_NOT_JSON", "MODEL_OUTPUT_SCHEMA_VIOLATION", "SCHEMA_INVALID"):
            requests.append(
                _make_request(
                    cluster_id="FORMAT/STRUCTURED_OUTPUT",
                    issue_type="STRUCTURED_OUTPUT_FORMAT_BAD",
                    priority=1,
                    owner_type="training",
                    what="Collect constrained JSON-format outputs under varied prompt conditions.",
                    hint="Train on strict output-schema compliance with negative examples.",
                    verif="MODEL_OUTPUT_NOT_JSON / schema-invalid rate drops.",
                )
            )

        elif et == "EVAL_METHOD_UNSUPPORTED":
            requests.append(
                _make_request(
                    cluster_id="EVAL/INFRA",
                    issue_type="EVAL_INFRA_CONFIGURATION_GAP",
                    priority=1,
                    owner_type="eval",
                    what="Add missing checker registry coverage and verifier contract tests.",
                    hint="Create break-suite scenarios for unsupported methods and unknown checkers.",
                    verif="Zero EVAL_METHOD_UNSUPPORTED failures in break suite.",
                )
            )

        else:
            continue

    uniq: Dict[str, Dict] = {}
    for x in requests:
        uniq[x["issue_type"]] = x
    return list(uniq.values())
