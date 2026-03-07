"""
Tool broker abstraction: separates "A1 wants grounding" from "which tool stack provides it."
Concrete implementations: mock_tools (MVP), mcp_tools (later).
"""
from typing import Any, Dict


class ToolBroker:
    """Abstract broker for grounding tools (web search, image understanding)."""

    def web_search(self, query: str) -> Dict[str, Any]:
        """Run a web search; return a result dict (e.g. snippets, url, title)."""
        raise NotImplementedError("web_search must be implemented by concrete broker")

    def understand_image(self, image_ref: Dict[str, Any]) -> Dict[str, Any]:
        """Understand an image from a ref (uri/sha256/etc); return description or structured result."""
        raise NotImplementedError("understand_image must be implemented by concrete broker")
