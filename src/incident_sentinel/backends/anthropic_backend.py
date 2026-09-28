"""Anthropic Claude backend using the Messages API with tool use."""

from __future__ import annotations

import json

from ..settings import get_settings
from .base import LLMBackend, ToolCall, Turn
from .jsonutil import extract_object

SYSTEM_PROMPT = (
    "You are Sentinel, a senior site reliability engineer investigating a live "
    "production incident. Use the available tools to gather evidence from "
    "metrics, logs, Kubernetes, and host diagnostics before drawing "
    "conclusions. Reason step by step, prefer concrete evidence over "
    "speculation, and stop once you can explain the most likely root cause."
)


class AnthropicBackend(LLMBackend):
    def __init__(self) -> None:
        from anthropic import AsyncAnthropic

        settings = get_settings()
        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set.")
        self._client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._model = settings.anthropic_model
        self._max_tokens = settings.max_tokens
        self._tools: list[dict] = []
        self._messages: list[dict] = []
        self._text_parts: list[str] = []

    @property
    def label(self) -> str:
        return "Anthropic"

    @property
    def model(self) -> str:
        return self._model

    def set_tools(self, tool_schemas: list[dict]) -> None:
        self._tools = tool_schemas

    def transcript(self) -> str:
        return "\n\n".join(self._text_parts)

    async def send(self, content: str | list[dict]) -> Turn:
        if isinstance(content, str):
            self._messages.append({"role": "user", "content": content})
        else:
            self._messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": item["tool_use_id"],
                            "content": item["content"],
                        }
                        for item in content
                    ],
                }
            )

        response = await self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=SYSTEM_PROMPT,
            tools=self._tools,
            messages=self._messages,
        )

        # Persist the assistant turn verbatim so tool_use/tool_result pair up.
        self._messages.append({"role": "assistant", "content": response.content})

        text = ""
        tool_calls: list[ToolCall] = []
        for block in response.content:
            if block.type == "text":
                text += block.text
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(id=block.id, name=block.name, arguments=block.input or {}))
        if text:
            self._text_parts.append(text)

        stop = "tool_use" if response.stop_reason == "tool_use" else "end_turn"
        return Turn(text=text, tool_calls=tool_calls, stop_reason=stop)

    async def summarise_json(self, prompt: str, schema: dict) -> str:
        instruction = (
            f"{prompt}\n\nReturn ONLY a JSON object matching this schema, with no "
            f"prose or code fences:\n{json.dumps(schema)}"
        )
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            messages=[{"role": "user", "content": instruction}],
        )
        text = "".join(b.text for b in response.content if b.type == "text")
        return extract_object(text)
