"""The catalogue of investigation tools available to the agent.

Each tool module exposes a list of :class:`ToolSpec`. :func:`build_catalogue`
merges them into the schema list handed to an LLM backend and a name→handler
map used to dispatch tool calls.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

Handler = Callable[[dict[str, Any]], Awaitable[str]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Handler
    required: tuple[str, ...] = ()

    def schema(self) -> dict:
        """Anthropic-style tool schema (the canonical format we convert from)."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": self.parameters,
                "required": list(self.required),
                "additionalProperties": False,
            },
        }


class Catalogue:
    def __init__(self, specs: list[ToolSpec]) -> None:
        self._specs = specs
        self._by_name = {spec.name: spec for spec in specs}

    def schemas(self) -> list[dict]:
        return [spec.schema() for spec in self._specs]

    def handler(self, name: str) -> Handler | None:
        spec = self._by_name.get(name)
        return spec.handler if spec else None

    def names(self) -> list[str]:
        return list(self._by_name)


def build_catalogue() -> Catalogue:
    from . import datadog, diagnostics, kubernetes, prometheus

    specs: list[ToolSpec] = []
    for module in (prometheus, datadog, kubernetes, diagnostics):
        specs.extend(module.SPECS)
    return Catalogue(specs)
