import random
import string
from typing import Any, Dict, List, Optional

from ..core.timeutil import now_iso


def _rand_id(prefix: str, rng: random.Random) -> str:
    suffix = "".join(rng.choice(string.ascii_lowercase + string.digits) for _ in range(12))
    return f"{prefix}_{suffix}"


def _make_add_item(spec: Dict[str, Any], dataset_spec_version: str, difficulty: str, domain_tags: List[str], rng: random.Random) -> Dict[str, Any]:
    a = rng.randint(1, 1000)
    b = rng.randint(1, 1000)

    input_obj = {"a": a, "b": b}
    output_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["answer"],
        "properties": {"answer": {"type": "integer"}}
    }

    prompt = (
        "You MUST output valid JSON that matches the output_schema.\n"
        "Task: Add two integers.\n"
        f"Input JSON: {input_obj}\n"
        'Return JSON: {"answer": a_plus_b}\n'
    )

    return {
        "item_id": _rand_id("item", rng),
        "dataset_spec_version": dataset_spec_version,
        "domain_tags": domain_tags,
        "difficulty": difficulty,
        "task_type": "json_math_add",
        "prompt": prompt,
        "input": input_obj,
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["a", "b"],
            "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}}
        },
        "output_schema": output_schema,
        "constraints": {
            "no_subjective_judgement": True,
            "safety_notes": "",
            "locked_fields": ["dataset_spec_version", "domain_tags", "difficulty", "task_type"]
        },
        "provenance": {
            "created_at": now_iso(),
            "created_by": "A1",
            "source": "synthetic"
        }
    }


def _make_email_item(spec: Dict[str, Any], dataset_spec_version: str, difficulty: str, domain_tags: List[str], rng: random.Random) -> Dict[str, Any]:
    user = "alex" + "".join(rng.choice(string.digits) for _ in range(3))
    email = f"{user}.wu{rng.randint(10,99)}@example.com"
    text = f"Please contact Alex at {email} for details."

    input_obj = {"text": text}
    output_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["email"],
        "properties": {"email": {"type": "string"}}
    }

    prompt = (
        "You MUST output valid JSON that matches the output_schema.\n"
        "Task: Extract the email address from the text.\n"
        f"Input JSON: {input_obj}\n"
        'Return JSON: {"email": "..."}\n'
    )

    return {
        "item_id": _rand_id("item", rng),
        "dataset_spec_version": dataset_spec_version,
        "domain_tags": domain_tags,
        "difficulty": difficulty,
        "task_type": "json_extract_email",
        "prompt": prompt,
        "input": input_obj,
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["text"],
            "properties": {"text": {"type": "string"}}
        },
        "output_schema": output_schema,
        "constraints": {
            "no_subjective_judgement": True,
            "safety_notes": "",
            "locked_fields": ["dataset_spec_version", "domain_tags", "difficulty", "task_type"]
        },
        "provenance": {
            "created_at": now_iso(),
            "created_by": "A1",
            "source": "synthetic"
        }
    }


# 12+ templates per label for low duplicate rate; oracle uses same mapping in a1b_oracle_builder
SENTIMENT_TEMPLATES = [
    ("I love this product. It works perfectly!", "positive"),
    ("This is amazing. Best purchase ever.", "positive"),
    ("Really happy with it. Exceeds expectations.", "positive"),
    ("Fantastic quality. Would buy again.", "positive"),
    ("Excellent service and product. Very pleased.", "positive"),
    ("Could not be happier. Highly recommend.", "positive"),
    ("Outstanding. Exactly what I needed.", "positive"),
    ("Great value. Delivered as described.", "positive"),
    ("Wonderful experience from start to finish.", "positive"),
    ("Top notch. No complaints at all.", "positive"),
    ("Superb. Will definitely order again.", "positive"),
    ("Impressive. Lives up to the hype.", "positive"),
    ("It is okay. Nothing special.", "neutral"),
    ("Average. Does the job.", "neutral"),
    ("Neither good nor bad. As expected.", "neutral"),
    ("Acceptable. No strong feelings either way.", "neutral"),
    ("Decent. Could be better could be worse.", "neutral"),
    ("Mediocre. Met basic expectations.", "neutral"),
    ("Fair. Nothing to write home about.", "neutral"),
    ("So-so. Standard quality.", "neutral"),
    ("Adequate. Serves its purpose.", "neutral"),
    ("Unremarkable. Middle of the road.", "neutral"),
    ("Run of the mill. Fine.", "neutral"),
    ("Moderate. Mixed experience.", "neutral"),
    ("This is terrible. Completely broken.", "negative"),
    ("Waste of money. Do not buy.", "negative"),
    ("Very disappointed. Poor quality.", "negative"),
    ("Broken on arrival. Useless.", "negative"),
    ("Awful. Returned immediately.", "negative"),
    ("Horrible experience. Regret buying.", "negative"),
    ("Worst purchase I have ever made.", "negative"),
    ("Defective. Customer service was no help.", "negative"),
    ("Cheap and flimsy. Fell apart.", "negative"),
    ("Not worth a penny. Avoid.", "negative"),
    ("Extremely poor. Total letdown.", "negative"),
    ("Rubbish. Would give zero stars if possible.", "negative"),
    ("Failed to work. Complete junk.", "negative"),
]
def _make_sentiment_item(spec: Dict[str, Any], dataset_spec_version: str, difficulty: str, domain_tags: List[str], rng: random.Random) -> Dict[str, Any]:
    text, _ = rng.choice(SENTIMENT_TEMPLATES)
    input_obj = {"text": text}
    output_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["label"],
        "properties": {"label": {"type": "string", "enum": ["positive", "neutral", "negative"]}}
    }

    prompt = (
        "You MUST output valid JSON that matches the output_schema.\n"
        "Task: Classify sentiment into one of: positive, neutral, negative.\n"
        f"Input JSON: {input_obj}\n"
        'Return JSON: {"label": "positive|neutral|negative"}\n'
    )

    return {
        "item_id": _rand_id("item", rng),
        "dataset_spec_version": dataset_spec_version,
        "domain_tags": domain_tags,
        "difficulty": difficulty,
        "task_type": "json_classify_sentiment",
        "prompt": prompt,
        "input": input_obj,
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["text"],
            "properties": {"text": {"type": "string"}}
        },
        "output_schema": output_schema,
        "constraints": {
            "no_subjective_judgement": True,
            "safety_notes": "",
            "locked_fields": ["dataset_spec_version", "domain_tags", "difficulty", "task_type"]
        },
        "provenance": {
            "created_at": now_iso(),
            "created_by": "A1",
            "source": "synthetic"
        }
    }


def _make_trajectory_email_item(spec: Dict[str, Any], dataset_spec_version: str, difficulty: str, domain_tags: List[str], rng: random.Random) -> Dict[str, Any]:
    """Task: You must call search_email_db tool, then answer with the email."""
    user = "alex" + "".join(rng.choice(string.digits) for _ in range(3))
    email = f"{user}.wu{rng.randint(10,99)}@example.com"
    text = f"Please contact Alex at {email} for details."
    input_obj = {"text": text}
    output_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["email"],
        "properties": {"email": {"type": "string"}}
    }
    prompt = (
        "You MUST call the search_email_db tool first, then output valid JSON that matches the output_schema.\n"
        "Task: Use search_email_db to find the email in the text, then return it.\n"
        f"Input JSON: {input_obj}\n"
        "Steps: 1) Call search_email_db tool. 2) Return JSON: {\"email\": \"...\"}\n"
    )
    return {
        "item_id": _rand_id("item", rng),
        "dataset_spec_version": dataset_spec_version,
        "domain_tags": domain_tags,
        "difficulty": difficulty,
        "task_type": "trajectory_email_then_answer",
        "prompt": prompt,
        "input": input_obj,
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["text"],
            "properties": {"text": {"type": "string"}}
        },
        "output_schema": output_schema,
        "constraints": {
            "no_subjective_judgement": True,
            "safety_notes": "",
            "locked_fields": ["dataset_spec_version", "domain_tags", "difficulty", "task_type"]
        },
        "provenance": {
            "created_at": now_iso(),
            "created_by": "A1",
            "source": "synthetic"
        }
    }


def _make_structured_extraction_item(spec: Dict[str, Any], dataset_spec_version: str, difficulty: str, domain_tags: List[str], rng: random.Random) -> Dict[str, Any]:
    """Extract email + name from text. Uses programmatic_check with structured_extraction_v1."""
    name = "alice" + "".join(rng.choice(string.ascii_lowercase) for _ in range(3))
    email = f"{name}{rng.randint(10, 99)}@example.com"
    text = f"Contact {name.capitalize()} at {email} for support."
    input_obj = {"text": text}
    output_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["email", "name"],
        "properties": {
            "email": {"type": "string"},
            "name": {"type": "string"},
        },
    }
    prompt = (
        "You MUST output valid JSON that matches the output_schema.\n"
        "Task: Extract the email and the person's name from the text.\n"
        f"Input JSON: {input_obj}\n"
        'Return JSON: {"email": "...", "name": "..."}\n'
    )
    return {
        "item_id": _rand_id("item", rng),
        "dataset_spec_version": dataset_spec_version,
        "domain_tags": domain_tags,
        "difficulty": difficulty,
        "task_type": "json_extract_structured",
        "prompt": prompt,
        "input": input_obj,
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["text"],
            "properties": {"text": {"type": "string"}},
        },
        "output_schema": output_schema,
        "constraints": {
            "no_subjective_judgement": True,
            "safety_notes": "",
            "locked_fields": ["dataset_spec_version", "domain_tags", "difficulty", "task_type"],
        },
        "provenance": {
            "created_at": now_iso(),
            "created_by": "A1",
            "source": "synthetic",
        },
    }


def _make_classify_canonical_item(spec: Dict[str, Any], dataset_spec_version: str, difficulty: str, domain_tags: List[str], rng: random.Random) -> Dict[str, Any]:
    """Classification with canonicalization (e.g. Positive -> positive). Uses programmatic_check classification_canonical_v1."""
    text, _ = rng.choice(SENTIMENT_TEMPLATES)
    input_obj = {"text": text}
    output_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["label"],
        "properties": {"label": {"type": "string"}},
    }
    prompt = (
        "You MUST output valid JSON that matches the output_schema.\n"
        "Task: Classify sentiment into one of: positive, neutral, negative.\n"
        f"Input JSON: {input_obj}\n"
        'Return JSON: {"label": "positive" | "neutral" | "negative"}\n'
    )
    return {
        "item_id": _rand_id("item", rng),
        "dataset_spec_version": dataset_spec_version,
        "domain_tags": domain_tags,
        "difficulty": difficulty,
        "task_type": "json_classify_canonical",
        "prompt": prompt,
        "input": input_obj,
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["text"],
            "properties": {"text": {"type": "string"}},
        },
        "output_schema": output_schema,
        "constraints": {
            "no_subjective_judgement": True,
            "safety_notes": "",
            "locked_fields": ["dataset_spec_version", "domain_tags", "difficulty", "task_type"],
        },
        "provenance": {
            "created_at": now_iso(),
            "created_by": "A1",
            "source": "synthetic",
        },
    }


def _make_factual_grounded_qa_item(
    spec: Dict[str, Any], dataset_spec_version: str, difficulty: str, domain_tags: List[str], rng: random.Random
) -> Dict[str, Any]:
    """Minimal synthetic placeholder for factual_grounded_qa (used when source_policy is synthetic)."""
    context = "The first programmable computer was built in 1941 (Z3 by Konrad Zuse)."
    input_obj = {"context": context, "question": "When was the first programmable computer built?"}
    output_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["answer"],
        "properties": {"answer": {"type": "string"}},
    }
    prompt = (
        "You MUST output valid JSON that matches the output_schema.\n"
        "Task: Answer the question using only the provided context.\n"
        f"Context: {context}\n"
        "Question: When was the first programmable computer built?\n"
        'Return JSON: {"answer": "..."}\n'
    )
    return {
        "item_id": _rand_id("item", rng),
        "dataset_spec_version": dataset_spec_version,
        "domain_tags": domain_tags,
        "difficulty": difficulty,
        "task_type": "factual_grounded_qa",
        "prompt": prompt,
        "input": input_obj,
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["context", "question"],
            "properties": {"context": {"type": "string"}, "question": {"type": "string"}},
        },
        "output_schema": output_schema,
        "constraints": {
            "no_subjective_judgement": True,
            "safety_notes": "",
            "locked_fields": ["dataset_spec_version", "domain_tags", "difficulty", "task_type"],
        },
        "provenance": {
            "created_at": now_iso(),
            "created_by": "A1",
            "source": "synthetic",
        },
    }


def _generate_synthetic_item(
    spec: Dict[str, Any], target: Dict[str, Any], dataset_spec_version: str, rng: random.Random
) -> Dict[str, Any]:
    """Template-based generation via task registry (current behavior)."""
    from ..tasks.registry import get_task_registry

    task_type = target["task_type"]
    difficulty = target["difficulty"]
    domain_tags = target["domain_tags"]

    registry = get_task_registry()
    if task_type not in registry:
        raise ValueError(f"Unsupported task_type in target: {task_type}")
    return registry[task_type].generator(spec, dataset_spec_version, difficulty, domain_tags, rng)


def _generate_web_grounded_item(
    spec: Dict[str, Any],
    target: Dict[str, Any],
    dataset_spec_version: str,
    rng: random.Random,
    tool_broker: Optional[Any] = None,
) -> Dict[str, Any]:
    """Generate a factual QA item grounded by web search; uses mock broker if tool_broker is None."""
    from ..tools.providers.mock_tools import MockToolBroker

    broker = tool_broker if tool_broker is not None else MockToolBroker()
    difficulty = target["difficulty"]
    domain_tags = target["domain_tags"]
    task_type = target.get("task_type", "factual_grounded_qa")

    query = "When was the first programmable computer built?"
    result = broker.web_search(query)
    source_refs = [{"url": result.get("url", ""), "title": result.get("title", "")}]
    tool_calls = [{"tool": "web_search", "query": query}]

    prompt = (
        "You MUST output valid JSON that matches the output_schema.\n"
        "Task: Answer the question using only the provided context.\n"
        f"Context: {result.get('snippet', '')}\n"
        f"Question: {query}\n"
        'Return JSON: {"answer": "..."}\n'
    )
    input_obj = {
        "context": result.get("snippet", ""),
        "question": query,
        "source_refs": source_refs,
    }
    output_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["answer"],
        "properties": {"answer": {"type": "string"}},
    }

    item_id = _rand_id("item", rng)
    return {
        "item_id": item_id,
        "dataset_spec_version": dataset_spec_version,
        "domain_tags": domain_tags,
        "difficulty": difficulty,
        "task_type": task_type,
        "prompt": prompt,
        "input": input_obj,
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["context", "question"],
            "properties": {
                "context": {"type": "string"},
                "question": {"type": "string"},
                "source_refs": {"type": "array", "items": {"type": "object"}},
            },
        },
        "output_schema": output_schema,
        "constraints": {
            "no_subjective_judgement": True,
            "safety_notes": "",
            "locked_fields": ["dataset_spec_version", "domain_tags", "difficulty", "task_type"],
        },
        "provenance": {
            "created_at": now_iso(),
            "created_by": "A1",
            "source": "web_grounded",
            "source_refs": source_refs,
            "tool_calls": tool_calls,
        },
    }


def _generate_image_grounded_item(
    spec: Dict[str, Any],
    target: Dict[str, Any],
    dataset_spec_version: str,
    rng: random.Random,
    tool_broker: Optional[Any] = None,
) -> Dict[str, Any]:
    """Generate an item grounded by image understanding; uses mock broker if tool_broker is None."""
    from ..tools.providers.mock_tools import MockToolBroker

    broker = tool_broker if tool_broker is not None else MockToolBroker()
    difficulty = target["difficulty"]
    domain_tags = target["domain_tags"]
    task_type = target.get("task_type", "factual_grounded_qa")

    image_ref = {"uri": "mock://image/placeholder", "mime": "image/png"}
    result = broker.understand_image(image_ref)
    asset_refs = [image_ref]
    tool_calls = [{"tool": "understand_image", "image_ref": image_ref}]

    description = result.get("description", "Mock image description")
    prompt = (
        "You MUST output valid JSON that matches the output_schema.\n"
        "Task: Describe what you see in the image (use the provided description as the image content).\n"
        f"Image description: {description}\n"
        'Return JSON: {"description": "..."}\n'
    )
    input_obj = {"image_description": description, "asset_refs": asset_refs}
    output_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["description"],
        "properties": {"description": {"type": "string"}},
    }

    item_id = _rand_id("item", rng)
    return {
        "item_id": item_id,
        "dataset_spec_version": dataset_spec_version,
        "domain_tags": domain_tags,
        "difficulty": difficulty,
        "task_type": task_type,
        "prompt": prompt,
        "input": input_obj,
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["image_description"],
            "properties": {
                "image_description": {"type": "string"},
                "asset_refs": {"type": "array", "items": {"type": "object"}},
            },
        },
        "output_schema": output_schema,
        "constraints": {
            "no_subjective_judgement": True,
            "safety_notes": "",
            "locked_fields": ["dataset_spec_version", "domain_tags", "difficulty", "task_type"],
        },
        "provenance": {
            "created_at": now_iso(),
            "created_by": "A1",
            "source": "image_grounded",
            "asset_refs": asset_refs,
            "tool_calls": tool_calls,
        },
    }


def generate_item_from_blueprint(
    spec: Dict[str, Any],
    blueprint: Dict[str, Any],
    dataset_spec_version: str,
    rng: random.Random,
    domain_tags: Optional[List[str]] = None,
    difficulty: Optional[str] = None,
    tool_broker: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Generate one eval item from a prompt_blueprint. Dispatches by materializer_type
    (same as task_type in registry). Compatibility adapter: uses existing task generators.
    """
    materializer_type = blueprint.get("materializer_type", "")
    domain_tags = domain_tags or spec.get("allowed_domain_tags", ["general"])
    difficulty = difficulty or "easy"
    target = {
        "target_id": blueprint.get("blueprint_id", "bp"),
        "domain_tags": list(domain_tags),
        "difficulty": difficulty,
        "task_type": materializer_type,
        "source_policy": blueprint.get("grounding_recipe", {}).get("mode", "synthetic"),
    }
    return generate_item_from_target(spec, target, dataset_spec_version, rng, tool_broker=tool_broker)


def materialize_target_to_item(
    spec: Dict[str, Any],
    target: Dict[str, Any],
    dataset_spec_version: str,
    rng: random.Random,
    tool_broker: Optional[Any] = None,
    blueprint: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Generate item from target. If blueprint is provided and target has blueprint_id,
    use generate_item_from_blueprint; otherwise use generate_item_from_target (current behavior).
    """
    if blueprint is not None and target.get("blueprint_id"):
        item = generate_item_from_blueprint(
            spec,
            blueprint,
            dataset_spec_version,
            rng,
            domain_tags=target.get("domain_tags"),
            difficulty=target.get("difficulty"),
            tool_broker=tool_broker,
        )
        if target.get("judge_spec_id"):
            item["judge_spec_id"] = target["judge_spec_id"]
        return item
    return generate_item_from_target(spec, target, dataset_spec_version, rng, tool_broker=tool_broker)


def generate_item_from_target(
    spec: Dict[str, Any],
    target: Dict[str, Any],
    dataset_spec_version: str,
    rng: random.Random,
    tool_broker: Optional[Any] = None,
) -> Dict[str, Any]:
    """Generate one eval item from a capability target; dispatches by source_policy."""
    source_policy = target.get("source_policy", "synthetic")
    if source_policy == "synthetic":
        return _generate_synthetic_item(spec, target, dataset_spec_version, rng)
    if source_policy == "web_grounded":
        return _generate_web_grounded_item(
            spec, target, dataset_spec_version, rng, tool_broker=tool_broker
        )
    if source_policy == "image_grounded":
        return _generate_image_grounded_item(
            spec, target, dataset_spec_version, rng, tool_broker=tool_broker
        )
    raise ValueError(f"Unsupported source_policy in target: {source_policy}")
