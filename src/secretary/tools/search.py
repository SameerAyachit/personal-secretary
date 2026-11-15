"""Web search tool (plan §14). Search results are untrusted: they are treated as
data, never as instructions (Section 8.6)."""

from __future__ import annotations

import asyncio

from pydantic import BaseModel

from secretary.integrations.search.provider import SearchProvider, SearchUnavailable
from secretary.tools.registry import SafetyClass, ToolSpec


class WebSearchArgs(BaseModel):
    query: str
    n: int = 5


async def web_search(con, turn_id: str, args: dict) -> dict:
    parsed = WebSearchArgs(**args)
    provider: SearchProvider = con.search_provider  # set by the app
    try:
        # The provider does blocking network I/O: keep it off the worker loop (chat shares it).
        results = await asyncio.to_thread(provider.search, parsed.query, parsed.n)
    except SearchUnavailable as exc:
        return {"status": "unavailable", "reason": str(exc)}
    return {
        "results": [r.to_dict() for r in results],
    }


def register(registry) -> None:
    registry.register(
        ToolSpec(
            name="web_search",
            group="research",
            safety_class=SafetyClass.A,
            description="Search the web for information.",
            args_model=WebSearchArgs,
            fn=web_search,
        )
    )
