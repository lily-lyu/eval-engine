"""Shared mock SUT solvers: one per task type. Used by a0 run_sut_mock and server for demo consistency."""
import json
import re
from typing import Any, Dict

# Must match SENTIMENT_TEMPLATES / mapping in a1_item_generator and a1b_oracle_builder
SENTIMENT_MAPPING = {
    "I love this product. It works perfectly!": "positive",
    "This is amazing. Best purchase ever.": "positive",
    "Really happy with it. Exceeds expectations.": "positive",
    "Fantastic quality. Would buy again.": "positive",
    "Excellent service and product. Very pleased.": "positive",
    "Could not be happier. Highly recommend.": "positive",
    "Outstanding. Exactly what I needed.": "positive",
    "Great value. Delivered as described.": "positive",
    "Wonderful experience from start to finish.": "positive",
    "Top notch. No complaints at all.": "positive",
    "Superb. Will definitely order again.": "positive",
    "Impressive. Lives up to the hype.": "positive",
    "It is okay. Nothing special.": "neutral",
    "Average. Does the job.": "neutral",
    "Neither good nor bad. As expected.": "neutral",
    "Acceptable. No strong feelings either way.": "neutral",
    "Decent. Could be better could be worse.": "neutral",
    "Mediocre. Met basic expectations.": "neutral",
    "Fair. Nothing to write home about.": "neutral",
    "So-so. Standard quality.": "neutral",
    "Adequate. Serves its purpose.": "neutral",
    "Unremarkable. Middle of the road.": "neutral",
    "Run of the mill. Fine.": "neutral",
    "Moderate. Mixed experience.": "neutral",
    "This is terrible. Completely broken.": "negative",
    "Waste of money. Do not buy.": "negative",
    "Very disappointed. Poor quality.": "negative",
    "Broken on arrival. Useless.": "negative",
    "Awful. Returned immediately.": "negative",
    "Horrible experience. Regret buying.": "negative",
    "Worst purchase I have ever made.": "negative",
    "Defective. Customer service was no help.": "negative",
    "Cheap and flimsy. Fell apart.": "negative",
    "Not worth a penny. Avoid.": "negative",
    "Extremely poor. Total letdown.": "negative",
    "Rubbish. Would give zero stars if possible.": "negative",
    "Failed to work. Complete junk.": "negative",
}


def solve_add(item: Dict[str, Any]) -> str:
    inp = item["input"]
    return json.dumps({"answer": int(inp["a"]) + int(inp["b"])})


def solve_email(item: Dict[str, Any]) -> str:
    inp = item["input"]
    m = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", inp["text"])
    email = m.group(0) if m else ""
    return json.dumps({"email": email})


def solve_sentiment(item: Dict[str, Any]) -> str:
    inp = item["input"]
    return json.dumps({"label": SENTIMENT_MAPPING.get(inp["text"], "neutral")})


def solve_trajectory_email(item: Dict[str, Any]) -> str:
    """Returns JSON output only (no tool_trace). Server adds tool_trace for HTTP envelope."""
    return solve_email(item)


def solve_structured_extraction(item: Dict[str, Any]) -> str:
    """Extract email + name from text (same logic as oracle)."""
    inp = item["input"]
    text = inp["text"]
    email_m = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
    email = email_m.group(0) if email_m else ""
    name_m = re.search(r"Contact\s+(\w+)\s+at\s+", text, re.IGNORECASE)
    name = name_m.group(1).capitalize() if name_m else ""
    return json.dumps({"email": email, "name": name})


def solve_classify_canonical(item: Dict[str, Any]) -> str:
    """Return canonical label (lowercase) from sentiment mapping."""
    return solve_sentiment(item)
