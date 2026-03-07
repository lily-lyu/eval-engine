"""Mock tool broker for tests and synthetic pipeline; no real web or vision calls."""
from typing import Any, Dict

from ..tool_broker import ToolBroker


class MockToolBroker(ToolBroker):
    """Returns deterministic mock results for web_search and understand_image."""

    def web_search(self, query: str) -> Dict[str, Any]:
        return {
            "query": query,
            "url": "https://example.com/mock",
            "title": f"Mock result for: {query}",
            "snippet": f"Mock snippet for query: {query}.",
        }

    def understand_image(self, image_ref: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "description": "Mock image description",
            "ref": image_ref,
        }
