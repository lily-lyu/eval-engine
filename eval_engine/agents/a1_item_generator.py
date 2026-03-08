import logging
import random
import string
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import MAX_LLM_RETRIES_PER_STAGE
from ..core.timeutil import now_iso
from ..llm.structured import generate_and_validate_pydantic
from ..llm.worker_schemas import A1CreativeOutput, A1JobSpec

logger = logging.getLogger(__name__)
_PROMPT_DIR = Path(__file__).resolve().parents[1] / "llm" / "prompts"


def _rand_id(prefix: str, rng: random.Random) -> str:
    suffix = "".join(rng.choice(string.ascii_lowercase + string.digits) for _ in range(12))
    return f"{prefix}_{suffix}"


def _scenario_subtype(materializer_config: Optional[Dict[str, Any]]) -> str:
    """Return scenario_subtype from materializer_config for hard-mode variation."""
    if not materializer_config:
        return "default"
    return (materializer_config.get("scenario_subtype") or "default").lower()


def _make_add_item(
    spec: Dict[str, Any],
    dataset_spec_version: str,
    difficulty: str,
    domain_tags: List[str],
    rng: random.Random,
    *,
    blueprint_id: Optional[str] = None,
    repetition_index: int = 0,
    materializer_config: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    subtype = _scenario_subtype(materializer_config)
    if subtype == "carry_chain":
        a, b = rng.randint(500, 999), rng.randint(500, 999)
        task_line = "Task: Add the two integers. Watch for carry digits.\n"
    elif subtype == "multi_step":
        a, b = rng.randint(1, 100), rng.randint(1, 100)
        c = rng.randint(1, 50)
        input_obj = {"a": a, "b": b, "c": c}
        output_schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["answer"],
            "properties": {"answer": {"type": "integer"}}
        }
        prompt = (
            "You MUST output valid JSON that matches the output_schema.\n"
            "Task: First add a and b, then add that result to c. Return the final sum.\n"
            f"Input JSON: {input_obj}\n"
            'Return JSON: {"answer": (a+b)+c}\n'
        )
        return _add_item_common(dataset_spec_version, difficulty, domain_tags, rng, input_obj, output_schema, prompt)
    elif subtype == "wording_distraction":
        a, b = rng.randint(1, 100), rng.randint(1, 100)
        input_obj = {"a": a, "b": b}
        output_schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["answer"],
            "properties": {"answer": {"type": "integer"}}
        }
        prompt = (
            "You MUST output valid JSON that matches the output_schema.\n"
            "Task: Compute the sum of the two given numbers (ignore any other wording).\n"
            f"Input JSON: {input_obj}\n"
            'Return JSON: {"answer": a_plus_b}\n'
        )
        return _add_item_common(dataset_spec_version, difficulty, domain_tags, rng, input_obj, output_schema, prompt)
    a = rng.randint(1, 1000)
    b = rng.randint(1, 1000)
    input_obj = {"a": a, "b": b}
    output_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["answer"],
        "properties": {"answer": {"type": "integer"}}
    }
    task_line = "Task: Add two integers.\n" if subtype == "default" else "Task: Add the two integers.\n"
    prompt = (
        "You MUST output valid JSON that matches the output_schema.\n"
        f"{task_line}"
        f"Input JSON: {input_obj}\n"
        'Return JSON: {"answer": a_plus_b}\n'
    )
    input_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": list(input_obj.keys()),
        "properties": {k: {"type": "integer"} for k in input_obj}
    }
    return _add_item_common(dataset_spec_version, difficulty, domain_tags, rng, input_obj, output_schema, prompt, input_schema)


def _add_item_common(
    dataset_spec_version: str,
    difficulty: str,
    domain_tags: List[str],
    rng: random.Random,
    input_obj: Dict[str, Any],
    output_schema: Dict[str, Any],
    prompt: str,
    input_schema: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if input_schema is None:
        input_schema = {
            "type": "object",
            "additionalProperties": False,
            "required": list(input_obj.keys()),
            "properties": {k: {"type": "integer"} for k in input_obj}
        }
    return {
        "item_id": _rand_id("item", rng),
        "dataset_spec_version": dataset_spec_version,
        "domain_tags": domain_tags,
        "difficulty": difficulty,
        "task_type": "json_math_add",
        "prompt": prompt,
        "input": input_obj,
        "input_schema": input_schema,
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


def _make_email_item(
    spec: Dict[str, Any],
    dataset_spec_version: str,
    difficulty: str,
    domain_tags: List[str],
    rng: random.Random,
    *,
    blueprint_id: Optional[str] = None,
    repetition_index: int = 0,
    materializer_config: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    subtype = _scenario_subtype(materializer_config)
    seed = hash(blueprint_id or "default") % (2**32) + repetition_index
    variant_rng = random.Random(seed)
    user = "alex" + "".join(rng.choice(string.digits) for _ in range(3))
    email = f"{user}.wu{rng.randint(10,99)}@example.com"
    if subtype == "distractor":
        other = f"bob{rng.randint(1,99)}@other.com"
        text = f"Relevant contact: {email}. Ignore {other}."
        task_line = "Task: Extract the primary/relevant email address from the text.\n"
    elif subtype == "noisy":
        text = f"[Header] --- Forward to: {email} --- [Footer] (do not use support@company.com)."
        task_line = "Task: Extract the forwarding email address from the text (not the footer).\n"
    elif subtype == "multi":
        other = f"cc: team{rng.randint(1,9)}@co.com"
        text = f"To: {email}\n{other}\nSubject: Re: Project. The main recipient is in the To line."
        task_line = "Task: Extract the main recipient email from the To line only.\n"
    elif subtype == "wrapped":
        text = f"---\nForward to: {email}\n---\nSignature: support@company.com"
        task_line = "Task: Extract the forwarding email address from the text (not the signature).\n"
    else:
        variant = variant_rng.randint(0, 2)
        if variant == 0:
            text = f"Please contact Alex at {email} for details."
            task_line = "Task: Extract the email address from the text.\n"
        elif variant == 1:
            other = f"bob{rng.randint(1,99)}@other.com"
            text = f"Relevant contact: {email}. Ignore {other}."
            task_line = "Task: Extract the primary/relevant email address from the text.\n"
        else:
            text = f"---\nForward to: {email}\n---\nSignature: support@company.com"
            task_line = "Task: Extract the forwarding email address from the text (not the signature).\n"

    input_obj = {"text": text}
    output_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["email"],
        "properties": {"email": {"type": "string"}}
    }

    prompt = (
        "You MUST output valid JSON that matches the output_schema.\n"
        f"{task_line}"
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
def _make_sentiment_item(
    spec: Dict[str, Any],
    dataset_spec_version: str,
    difficulty: str,
    domain_tags: List[str],
    rng: random.Random,
    *,
    blueprint_id: Optional[str] = None,
    repetition_index: int = 0,
    materializer_config: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    # Vary template by blueprint + repetition so same family produces different skeletons
    seed = hash(blueprint_id or "default") % (2**32) + repetition_index
    variant_rng = random.Random(seed)
    template_index = variant_rng.randint(0, len(SENTIMENT_TEMPLATES) - 1) if SENTIMENT_TEMPLATES else 0
    text, _ = SENTIMENT_TEMPLATES[template_index] if SENTIMENT_TEMPLATES else ("No content.", "neutral")
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


def _make_trajectory_email_item(
    spec: Dict[str, Any],
    dataset_spec_version: str,
    difficulty: str,
    domain_tags: List[str],
    rng: random.Random,
    *,
    blueprint_id: Optional[str] = None,
    repetition_index: int = 0,
    materializer_config: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Task: You must call search_email_db tool, then answer with the email. scenario_subtype: tool_order_trap, distractor_email, multi_step_dependency, etc."""
    subtype = _scenario_subtype(materializer_config)
    seed = hash(blueprint_id or "default") % (2**32) + repetition_index
    var_rng = random.Random(seed)
    user = "alex" + "".join(rng.choice(string.digits) for _ in range(3))
    email = f"{user}.wu{rng.randint(10,99)}@example.com"
    decoy = f"bob{rng.randint(1,99)}@other.com"
    if subtype == "distractor_email":
        text = f"Primary contact: {email}. Secondary (ignore): {decoy}. Use search_email_db and return the primary email."
        step_phrasing = "Use search_email_db with the text, then return JSON with the primary email only.\n"
    elif subtype == "multi_step_dependency":
        text = f"Step 1: Identify the contact. Step 2: The email to return is {email}. Call search_email_db then answer with that email."
        step_phrasing = "You must call search_email_db first, then return the email identified in step 2.\n"
    elif subtype == "tool_order_trap":
        text = f"Email to return: {email}. You must call search_email_db before returning; do not return without calling the tool."
        step_phrasing = "Call search_email_db first, then return JSON: {\"email\": \"...\"}. Order matters.\n"
    elif subtype == "missing_tool_arg_risk":
        text = f"Document: contact {email}. Use search_email_db(document) then return the email from the document."
        step_phrasing = "Pass the document text to search_email_db, then return the extracted email in JSON.\n"
    else:
        variant = var_rng.randint(0, 2)
        text = f"Please contact Alex at {email} for details."
        if variant == 1:
            text = f"Inbox snippet: ... From: team@co.com. Reply-to: {email}. ..."
        elif variant == 2:
            text = f"Thread: [noise] Target contact: {email} [end]"
        step_phrasing = "Steps: 1) Call search_email_db tool. 2) Return JSON: {\"email\": \"...\"}\n" if variant == 0 else "Use search_email_db then return the requested email in JSON.\n"
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
        f"{step_phrasing}"
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


def _make_structured_extraction_item(
    spec: Dict[str, Any],
    dataset_spec_version: str,
    difficulty: str,
    domain_tags: List[str],
    rng: random.Random,
    *,
    blueprint_id: Optional[str] = None,
    repetition_index: int = 0,
    materializer_config: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Extract email + name from text. Uses programmatic_check; scenario_subtype drives distractor/noisy/multi_record/conflicting_fields."""
    subtype = _scenario_subtype(materializer_config)
    seed = hash(blueprint_id or "default") % (2**32) + repetition_index
    var_rng = random.Random(seed)
    name = "alice" + "".join(rng.choice(string.ascii_lowercase) for _ in range(3))
    email = f"{name}{rng.randint(10, 99)}@example.com"
    if subtype == "distractor":
        text = f"Contact: {name.capitalize()}, {email}. Do not use: john@example.com or Jane."
        input_obj = {"text": text}
    elif subtype == "noisy":
        text = f"[Ticket #123] Requester: {name.capitalize()} | Email: {email} | [End]. Extract name and email only."
        input_obj = {"text": text}
    elif subtype == "multi_record":
        text = f"First: Bob, bob@x.com. Second (use this one): {name.capitalize()}, {email}. Extract the second record only."
        input_obj = {"text": text}
    elif subtype == "conflicting_fields":
        text = f"Name: {name.capitalize()}\nEmail (primary): {email}\nEmail (alt, ignore): other@example.com\nExtract primary name and primary email."
        input_obj = {"text": text}
    else:
        variant = var_rng.randint(0, 2)
        if variant == 0:
            text = f"Contact {name.capitalize()} at {email} for support."
        elif variant == 1:
            text = f"Support ticket #123: Requester {name.capitalize()}, email {email}. Please extract."
        else:
            text = f"Name: {name.capitalize()}\nEmail: {email}\n(Other: john@example.com is not the target.)"
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


# Boundary/negation templates still map to one of positive/neutral/negative for exact-match judge.
BOUNDARY_TEMPLATES = [
    ("Not bad at all, actually quite good.", "positive"),
    ("I wouldn't say I'm disappointed.", "neutral"),
    ("It's not great.", "negative"),
]
NEGATION_TEMPLATES = [
    ("I don't dislike it.", "positive"),
    ("Nothing to complain about, nothing to praise.", "neutral"),
    ("I can't recommend it.", "negative"),
]


def _make_classify_canonical_item(
    spec: Dict[str, Any],
    dataset_spec_version: str,
    difficulty: str,
    domain_tags: List[str],
    rng: random.Random,
    *,
    blueprint_id: Optional[str] = None,
    repetition_index: int = 0,
    materializer_config: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Classification with canonicalization. scenario_subtype: boundary_case, label_confusion, negation."""
    subtype = _scenario_subtype(materializer_config)
    seed = hash(blueprint_id or "default") % (2**32) + repetition_index
    var_rng = random.Random(seed)
    if subtype == "boundary_case" and BOUNDARY_TEMPLATES:
        text, _ = BOUNDARY_TEMPLATES[var_rng.randint(0, len(BOUNDARY_TEMPLATES) - 1)]
    elif subtype == "negation" and NEGATION_TEMPLATES:
        text, _ = NEGATION_TEMPLATES[var_rng.randint(0, len(NEGATION_TEMPLATES) - 1)]
    elif subtype == "label_confusion":
        text = "Mediocre. Not good, not terrible."
        _ = "neutral"
    else:
        idx = var_rng.randint(0, len(SENTIMENT_TEMPLATES) - 1) if SENTIMENT_TEMPLATES else 0
        text, _ = SENTIMENT_TEMPLATES[idx] if SENTIMENT_TEMPLATES else ("Neutral.", "neutral")
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
    spec: Dict[str, Any],
    dataset_spec_version: str,
    difficulty: str,
    domain_tags: List[str],
    rng: random.Random,
    *,
    blueprint_id: Optional[str] = None,
    repetition_index: int = 0,
    materializer_config: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Factual grounded QA; scenario_subtype: distractor_context, near_match, multi_hopish, citation_conflict. Exact-match judgeable."""
    subtype = _scenario_subtype(materializer_config)
    seed = hash(blueprint_id or "default") % (2**32) + repetition_index
    var_rng = random.Random(seed)
    if subtype == "distractor_context":
        context = "The first programmable computer was the Z3 (1941, Konrad Zuse). Unrelated: ENIAC (1945) was the first general-purpose electronic computer. Answer using only the Z3 fact."
        question = "When was the first programmable computer built?"
    elif subtype == "near_match":
        context = "Z3 (1941, Konrad Zuse) was the first programmable computer. ENIAC came later (1945)."
        question = "Which machine was the first programmable computer? Give the exact name."
    elif subtype == "multi_hopish":
        context = "First programmable: 1941. The machine was the Z3, built by Konrad Zuse. Do not confuse with ENIAC (1945)."
        question = "In what year was the Z3 built?"
    elif subtype == "citation_conflict":
        context = "Source A: First programmable computer built in 1941 (Z3). Source B: Z3 built by Konrad Zuse in 1941. Use Source A and B for the year."
        question = "When was the first programmable computer built?"
    else:
        variant = var_rng.randint(0, 2)
        if variant == 0:
            context = "The first programmable computer was built in 1941 (Z3 by Konrad Zuse)."
            question = "When was the first programmable computer built?"
        elif variant == 1:
            context = "Z3 (1941, Konrad Zuse) was the first programmable computer. ENIAC came later (1945)."
            question = "Which machine was the first programmable computer?"
        else:
            context = "First programmable computer: 1941, Z3, Konrad Zuse. Do not confuse with ENIAC (1945)."
            question = "In what year was the first programmable computer built?"
    input_obj = {"context": context, "question": question}
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
        f"Question: {question}\n"
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
    """Template-based generation via task registry; passes blueprint/repetition for variation."""
    from ..tasks.registry import get_task_registry

    task_type = target["task_type"]
    difficulty = target["difficulty"]
    domain_tags = target["domain_tags"]
    variation_kwargs = {
        "blueprint_id": target.get("blueprint_id"),
        "repetition_index": target.get("repetition_index", 0),
        "materializer_config": target.get("materializer_config") or {},
    }

    registry = get_task_registry()
    if task_type not in registry:
        raise ValueError(f"Unsupported task_type in target: {task_type}")
    return registry[task_type].generator(
        spec, dataset_spec_version, difficulty, domain_tags, rng, **variation_kwargs
    )


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


def _materialize_via_llm(
    spec: Dict[str, Any],
    target: Dict[str, Any],
    dataset_spec_version: str,
    rng: random.Random,
    blueprint: Dict[str, Any],
    run_config: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Materialize one eval item via LLM (schema-first). Returns full item dict.
    Merges LLM creative fields with deterministic administrative fields from blueprint/target.
    Raises on parse/validation failure or after exhausting max_llm_retries_per_stage.
    """
    job_spec = A1JobSpec(
        prompt_blueprint=blueprint,
        capability_target=target,
        dataset_spec_version=dataset_spec_version,
        repetition_index=int(target.get("repetition_index", 0)),
    )
    template = (_PROMPT_DIR / "a1_materializer.md").read_text(encoding="utf-8")
    prompt = template + "\n\n## Input\n\n```json\n" + job_spec.model_dump_json(indent=2) + "\n```\n\nOutput only the JSON object with the six creative fields."
    max_retries = int(run_config.get("max_llm_retries_per_stage", MAX_LLM_RETRIES_PER_STAGE))
    creative = generate_and_validate_pydantic(prompt, A1CreativeOutput, max_retries=max_retries)

    # Administrative fields from blueprint/target (not from LLM)
    domain_tags = target.get("domain_tags") or list(spec.get("allowed_domain_tags", ["general"]))
    task_type = target.get("task_type") or blueprint.get("materializer_type", "")
    grounding = blueprint.get("grounding_recipe") or {}
    source = grounding.get("mode", "synthetic") or "synthetic"

    item: Dict[str, Any] = {
        "item_id": _rand_id("item", rng),
        "dataset_spec_version": dataset_spec_version,
        "domain_tags": domain_tags,
        "difficulty": creative.difficulty,
        "task_type": task_type,
        "prompt": creative.prompt,
        "input": creative.input,
        "input_schema": creative.input_schema,
        "output_schema": creative.output_schema,
        "constraints": creative.constraints.model_dump(),
        "provenance": {
            "created_at": now_iso(),
            "created_by": "A1",
            "source": source,
        },
    }
    if target.get("judge_spec_id"):
        item["judge_spec_id"] = target["judge_spec_id"]
    return item


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
    enrich target with blueprint_id, family_id, materializer_config and call generate_item_from_target
    so materializers can consume blueprint variation.
    When run_config.item_generation_mode is hybrid or llm_materialized, tries LLM materializer first;
    on validation/retry exhaustion, falls back to deterministic path (fail closed).
    """
    if blueprint is not None and target.get("blueprint_id"):
        run_config = spec.get("run_config") or {}
        mode = (run_config.get("item_generation_mode") or "deterministic").strip().lower()
        if mode in ("hybrid", "llm_materialized"):
            try:
                return _materialize_via_llm(
                    spec, target, dataset_spec_version, rng, blueprint, run_config
                )
            except Exception as e:
                logger.warning(
                    "A1 LLM materializer failed, falling back to deterministic: %s",
                    e,
                    exc_info=False,
                )
        full_target = {
            **target,
            "blueprint_id": blueprint.get("blueprint_id", ""),
            "family_id": blueprint.get("family_id", ""),
            "materializer_config": blueprint.get("materializer_config") or {},
        }
        item = generate_item_from_target(spec, full_target, dataset_spec_version, rng, tool_broker=tool_broker)
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
