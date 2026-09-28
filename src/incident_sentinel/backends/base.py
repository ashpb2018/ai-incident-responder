"""The abstract contract every LLM backend implements.

A backend is stateful for the duration of one investigation: it accumulates the
running conversation so the agent only has to feed it new messages.

    backend.set_tools(schemas)
    turn = await backend.send(initial_prompt)      # str -> first user message
    while turn.stop_reason == "tool_use":
        results = run_tools(turn.tool_calls)
        turn = await backend.send(results)          # list[dict] -> tool results
    report_json = await backend.summarise_json(prompt, schema)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass(slots=True)
class Turn:
    """A normalised assistant response."""

    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = "end_turn"  # "end_turn" | "tool_use"

    @property
    def wants_tools(self) -> bool:
        return self.stop_reason == "tool_use" and bool(self.tool_calls)


class LLMBackend(ABC):
    @abstractmethod
    def set_tools(self, tool_schemas: list[dict]) -> None:
        """Register the Anthropic-style tool schemas the model may call."""

    @abstractmethod
    async def send(self, content: str | list[dict]) -> Turn:
        """Send the initial prompt (str) or tool results (list of dicts)."""

    @abstractmethod
    def transcript(self) -> str:
        """Return the assistant's accumulated text, for report extraction."""

    @abstractmethod
    async def summarise_json(self, prompt: str, schema: dict) -> str:
        """Make a focused call that returns a JSON string matching ``schema``."""

    @property
    @abstractmethod
    def label(self) -> str:
        ...

    @property
    @abstractmethod
    def model(self) -> str:
        ...
