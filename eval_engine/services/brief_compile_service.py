"""
Brief compile service: natural-language brief_text -> intent_spec.
Maps only to supported catalog capability tokens; does not invent families.
target_domain from the request is set on intent_spec and flows through to
compiled_dataset_spec.allowed_domain_tags and capability_targets[].domain_tags.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from ..core.family_catalog import CAPABILITY_TO_FAMILIES
from ..core.failure_codes import INTENT_UNDER_SPECIFIED, UNSUPPORTED_CAPABILITY_FOCUS

# Supported capability tokens (catalog-bounded).
SUPPORTED_CAPABILITY_TOKENS = frozenset(CAPABILITY_TO_FAMILIES.keys())

# Keyword -> capability_focus (lowercase). Only map to supported tokens.
BRIEF_CAPABILITY_KEYWORDS: Dict[str, List[str]] = {
    "extract": ["extraction"],
    "extraction": ["extraction"],
    "email": ["email", "extraction"],
    "structured": ["structured"],
    "structure": ["structured"],
    "classif": ["classification"],
    "classification": ["classification"],
    "sentiment": ["sentiment"],
    "canonical": ["canonical"],
    "trajectory": ["trajectory"],
    "tool use": ["tool_use", "trajectory"],
    "tool-use": ["tool_use", "trajectory"],
    "tool_use": ["tool_use"],
    "grounded": ["grounded_qa"],
    "factual": ["factual", "grounded_qa"],
    "qa": ["grounded_qa", "factual"],
    "math": ["math"],
    "schema": ["extraction", "structured"],
    "adherence": ["trajectory", "tool_use"],
    "correctness": ["trajectory", "tool_use", "extraction"],
}

# Regex-based phrases for natural paraphrases (pattern, [capability tokens]).
# Still maps only to supported catalog tokens.
BRIEF_CAPABILITY_PHRASES: List[Tuple[str, List[str]]] = [
    (r"\btool\s*calling\b", ["tool_use", "trajectory"]),
    (r"\btool\s*usage\b", ["tool_use", "trajectory"]),
    (r"\bmulti-?step\s+reasoning\b", ["trajectory", "tool_use"]),
    (r"\bmulti-?step\s+(?:tool|flow)\b", ["trajectory", "tool_use"]),
    (r"\bextraction\s+from\s+text\b", ["extraction"]),
    (r"\bextract\s+(?:from\s+)?text\b", ["extraction"]),
    (r"\bstructured\s+parsing\b", ["structured", "extraction"]),
    (r"\bstructured\s+extraction\b", ["structured", "extraction"]),
    (r"\bparsing\s+(?:structure|json)\b", ["structured"]),
    (r"\blookup\s+flows?\b", ["trajectory", "email"]),
    (r"\b(?:email|db)\s+lookup\b", ["trajectory", "email"]),
    (r"\bgrounded\s+factual\s+qa\b", ["grounded_qa", "factual"]),
    (r"\bgrounded\s+qa\b", ["grounded_qa"]),
    (r"\bfactual\s+qa\b", ["factual", "grounded_qa"]),
    (r"\bcontext-?based\s+qa\b", ["grounded_qa", "factual"]),
    (r"\breasoning\s+with\s+tools\b", ["trajectory", "tool_use"]),
    (r"\b(?:api|function)\s+calling\b", ["tool_use", "trajectory"]),
]

# Phrases that imply grounding.
GROUNDING_PHRASES = [
    (r"\bweb\b|\bgrounded\b|\bfact\b|\bfactual\b", "web_grounded"),
    (r"\bimage\b|\bvisual\b", "image_grounded"),
]

# Planner objective from brief language.
OBJECTIVE_PHRASES = [
    (r"\bsmoke\b", "smoke"),
    (r"\bregression\b", "regression"),
    (r"\bfailure-seeking\b|\bfailure seeking\b|\badversarial\b|\bstress\b|\bedge\s*cases\b|\bhard\s*edge\b", "failure_seeking"),
]

# Difficulty hints.
DIFFICULTY_EASY = re.compile(r"\beasy\b", re.I)
DIFFICULTY_HARD = re.compile(r"\bhard\b|\bedge\s*cases\b|\bstress\b|\badversarial\b", re.I)
BATCH_SIZE_NUM = re.compile(r"\b(\d{1,5})\s*(?:items?|samples?|cases?|batch)?\b", re.I)


def _clean_brief(brief_text: str) -> str:
    return " ".join(brief_text.strip().split()) if brief_text else ""


def _infer_capability_focus(brief: str) -> List[str]:
    """Infer capability_focus from brief; only return supported tokens. Uses keywords and regex phrases."""
    brief_lower = brief.lower()
    seen: set = set()
    out: List[str] = []

    for phrase, caps in BRIEF_CAPABILITY_KEYWORDS.items():
        if phrase in brief_lower:
            for c in caps:
                if c in SUPPORTED_CAPABILITY_TOKENS and c not in seen:
                    seen.add(c)
                    out.append(c)

    for pattern, caps in BRIEF_CAPABILITY_PHRASES:
        if re.search(pattern, brief_lower, re.IGNORECASE):
            for c in caps:
                if c in SUPPORTED_CAPABILITY_TOKENS and c not in seen:
                    seen.add(c)
                    out.append(c)

    return out


def _infer_grounding(brief: str) -> List[str]:
    brief_lower = brief.lower()
    for pattern, mode in GROUNDING_PHRASES:
        if re.search(pattern, brief_lower):
            return [mode]
    return ["synthetic"]


def _infer_planner_objective(brief: str) -> str:
    brief_lower = brief.lower()
    for pattern, obj in OBJECTIVE_PHRASES:
        if re.search(pattern, brief_lower):
            return obj
    return "balanced"


def _infer_difficulty_mix(brief: str) -> Dict[str, float]:
    if DIFFICULTY_HARD.search(brief):
        return {"medium": 0.3, "hard": 0.7}
    if DIFFICULTY_EASY.search(brief):
        return {"easy": 0.7, "medium": 0.3}
    return {"easy": 0.4, "medium": 0.4, "hard": 0.2}


def _infer_batch_size(brief: str, quota: int | None) -> int:
    m = BATCH_SIZE_NUM.search(brief)
    if m:
        return max(1, min(10000, int(m.group(1))))
    return max(1, quota or 12)


def brief_to_intent_spec(
    brief_text: str,
    *,
    quota: int | None = None,
    planner_mode: str | None = None,
    planner_model: str | None = None,
    planner_temperature: float | None = None,
    allow_experimental: bool = False,
    target_domain: List[str] | None = None,
) -> Dict[str, Any]:
    """
    Convert a natural-language brief into a valid intent_spec.
    - evaluation_goal = cleaned brief.
    - capability_focus inferred from keywords and synonym phrases; only supported tokens.
    - target_domain is set on intent_spec and flows to compiled_dataset_spec.allowed_domain_tags
      and each capability_target.domain_tags (used for domain filtering).
    - Raises ValueError with structured code if capability_focus cannot be inferred.
    """
    brief = _clean_brief(brief_text)
    if not brief:
        raise ValueError(
            f"{INTENT_UNDER_SPECIFIED}: brief_text is required and must be non-empty."
        )

    capability_focus = _infer_capability_focus(brief)
    if not capability_focus:
        raise ValueError(
            f"{UNSUPPORTED_CAPABILITY_FOCUS}: could not infer capability_focus from the brief. "
            "Mention at least one supported capability: extraction, email, structured, classification, "
            "sentiment, canonical, trajectory, tool_use, grounded_qa, factual, math."
        )

    # target_domain flows to compiler -> capability_targets[].domain_tags and allowed_domain_tags
    domain = target_domain if target_domain else ["general"]

    intent_spec: Dict[str, Any] = {
        "intent_name": "brief_plan",
        "intent_spec_version": "1.0.0",
        "evaluation_goal": brief,
        "capability_focus": capability_focus,
        "target_domain": domain,
        "grounding_requirements": _infer_grounding(brief),
        "planner_objective": _infer_planner_objective(brief),
        "difficulty_mix": _infer_difficulty_mix(brief),
        "batch_size": _infer_batch_size(brief, quota),
        "defaults": {
            "seed": 42,
            "max_prompt_length": 20000,
            "max_retries_per_stage": 2,
        },
        "planner_defaults": {
            "allow_experimental_families": allow_experimental,
            "max_families": 20,
        },
    }
    return intent_spec
