"""
Pydantic schemas for LLM worker outputs (A1, and later A2/A3).
A1: LLM produces only creative fields; administrative fields are merged from blueprint/target.
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# ----- A1 Materializer -----

class A1JobSpec(BaseModel):
    """Strict input for A1 LLM materializer: blueprint + capability_target + context."""
    prompt_blueprint: Dict[str, Any] = Field(..., description="Prompt blueprint from compiler")
    capability_target: Dict[str, Any] = Field(..., description="Capability target for this slot")
    dataset_spec_version: str = Field(..., min_length=1, max_length=64)
    repetition_index: int = Field(default=0, ge=0, description="Repetition index for this target")


class ItemConstraints(BaseModel):
    """Item constraints shape; LLM may set safety_notes and locked_fields."""
    no_subjective_judgement: Literal[True] = True
    safety_notes: str = Field(default="", max_length=2000)
    locked_fields: List[str] = Field(..., min_length=1, max_length=32)


class A1CreativeOutput(BaseModel):
    """
    Creative/concrete fields only. LLM must not output administrative fields
    (item_id, dataset_spec_version, domain_tags, task_type, provenance).
    Those are set deterministically from blueprint/target in _materialize_via_llm.
    """
    prompt: str = Field(..., min_length=1, max_length=20000)
    difficulty: Literal["easy", "medium", "hard", "expert"] = Field(...)
    input: Dict[str, Any] = Field(...)
    input_schema: Dict[str, Any] = Field(...)
    output_schema: Dict[str, Any] = Field(...)
    constraints: ItemConstraints = Field(...)


# ----- A2 Judge -----

class A2JudgeOutput(BaseModel):
    """Strict output schema for LLM rubric judge. Verdict uppercase; mapped to eval_result pass/fail by caller."""
    score: float = Field(..., ge=0.0, le=1.0)
    verdict: Literal["PASS", "FAIL", "ERROR"] = Field(...)
    error_type: Optional[str] = Field(default=None, max_length=128)
    evidence: List[str] = Field(
        ...,
        min_length=0,
        max_length=50,
        description="Specific quotes or frame references justifying the score",
    )
    confidence: float = Field(..., ge=0.0, le=1.0)


# ----- A3 Analyst -----

class A3ClusterSummary(BaseModel):
    """Enriched summary for one failure cluster from the LLM analyst."""
    cluster_id: str = Field(..., min_length=1, max_length=256)
    title: str = Field(..., min_length=1, max_length=512, description="Concise, human-readable summary of the failure mode")
    affected_share: float = Field(..., ge=0.0, le=1.0)
    likely_root_cause: str = Field(..., min_length=1, max_length=2000)
    owner: str = Field(..., min_length=1, max_length=64, description="e.g. Model Training, Data Production, Product UX")
    recommended_actions: List[str] = Field(..., min_length=0, max_length=20)
    evidence_examples: List[str] = Field(default_factory=list, max_length=20, description="Short snippets of evidence")


class A3AnalystReport(BaseModel):
    """Wrapper for LLM analyst output: list of enriched cluster summaries."""
    clusters: List[A3ClusterSummary] = Field(..., min_length=0, max_length=100)
