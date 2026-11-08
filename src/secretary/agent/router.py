"""Tool router: keyword-based selection of tool groups (plan §8.1).

The core group is always available; other groups are added by keyword match on
the user's text. Returns :class:`~secretary.tools.registry.ToolSpec` objects.
"""

from __future__ import annotations

from typing import Any

from secretary.tools.registry import Registry, ToolSpec


class Router:
    CORE_GROUP = "core"

    def __init__(self, registry: Registry) -> None:
        self.registry = registry
        self._keywords: dict[str, list[str]] = {}

    def route(self, name: str, keywords: list[str]) -> None:
        """Register keyword triggers for a tool."""
        self._keywords[name] = [k.lower() for k in keywords]

    def select(self, user_text: str, ctx: dict[str, Any]) -> list[ToolSpec]:
        text = (user_text or "").lower()
        chosen: list[ToolSpec] = []
        seen: set[str] = set()

        # Core group is always available (§8.6 routing).
        for spec in self.registry.list():
            if spec.group == self.CORE_GROUP and spec.name not in seen:
                chosen.append(spec)
                seen.add(spec.name)

        for name, keywords in self._keywords.items():
            spec = self.registry.get(name)
            if spec is None or spec.name in seen:
                continue
            if any(k in text for k in keywords):
                chosen.append(spec)
                seen.add(spec.name)
        return chosen
