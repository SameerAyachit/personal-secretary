"""Tool registry: safety classes, registration, and LLM schemas (plan §8.2, §8.5).

Every tool has a safety class:
  A: read  -> execute immediately
  B: reversible write -> execute, echo result, offer Undo
  C: consequential -> never from the LLM turn; goes to pending_actions
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pydantic import BaseModel


class SafetyClass(StrEnum):
    A = "A"  # read
    B = "B"  # reversible write
    C = "C"  # consequential


@dataclass
class ToolSpec:
    name: str
    group: str
    safety_class: SafetyClass
    description: str
    args_model: type[BaseModel] | None = None
    fn: Callable | None = None


class Registry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def list(self) -> list[ToolSpec]:
        return list(self._tools.values())

    def schemas(self) -> list[dict]:
        """OpenAI-compatible tool schemas (name/description/parameters only).

        Safety class and group stay on :class:`ToolSpec`; strict providers
        reject unknown properties inside a function definition.
        """
        out: list[dict] = []
        for spec in self._tools.values():
            schema: dict[str, Any] = {
                "name": spec.name,
                "description": spec.description,
            }
            if spec.args_model is not None:
                schema["parameters"] = spec.args_model.model_json_schema()
            out.append(schema)
        return out
