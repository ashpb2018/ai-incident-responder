"""OpenAI-compatible backend (Ollama, vLLM, LM Studio, llama.cpp)."""

from __future__ import annotations

import json

import httpx

from ..settings import get_settings
from .anthropic_backend import SYSTEM_PROMPT
from .base import LLMBackend, ToolCall, Turn
from .jsonutil import extract_object

_TIMEOUT = 120


def _to_openai_tools(anthropic_tools: list[dict]) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("input_schema", {"type": "object", "properties": {}}),
            },
        }
        for tool in anthropic_tools
    ]


class OllamaBackend(LLMBackend):
    def __init__(self) -> None:
        settings = get_settings()
        self._base = settings.ollama_base_url.rstrip("/")
        self._model = settings.ollama_model
        self._max_tokens = settings.max_tokens
        self._tools: list[dict] = []
        self._messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

    @property
    def label(self) -> str:
        return "OpenAI-compatible"

    @property
    def model(self) -> str:
        return self._model

    def set_tools(self, tool_schemas: list[dict]) -> None:
        self._tools = _to_openai_tools(tool_schemas)

    def transcript(self) -> str:
        return "\n\n".join(
            m["content"] for m in self._messages
            if m["role"] == "assistant" and m.get("content")
        )

    async def _post(self, payload: dict) -> dict:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(f"{self._base}/v1/chat/completions", json=payload)
            resp.raise_for_status()
            return resp.json()

    async def send(self, content: str | list[dict]) -> Turn:
        if isinstance(content, str):
            self._messages.append({"role": "user", "content": content})
        else:
            for item in content:
                self._messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": item["tool_use_id"],
                        "content": item["content"],
                    }
                )

        payload: dict = {"model": self._model, "messages": self._messages, "max_tokens": self._max_tokens}
        if self._tools:
            payload["tools"] = self._tools
            payload["tool_choice"] = "auto"

        message = (await self._post(payload))["choices"][0]["message"]
        self._messages.append(message)

        tool_calls: list[ToolCall] = []
        for call in message.get("tool_calls") or []:
            fn = call.get("function", {})
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(ToolCall(id=call.get("id", ""), name=fn.get("name", ""), arguments=args))

        stop = "tool_use" if tool_calls else "end_turn"
        return Turn(text=message.get("content") or "", tool_calls=tool_calls, stop_reason=stop)

    async def summarise_json(self, prompt: str, schema: dict) -> str:
        instruction = (
            f"{prompt}\n\nReturn ONLY a JSON object matching this schema:\n{json.dumps(schema)}"
        )
        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": instruction}],
            "max_tokens": self._max_tokens,
            "response_format": {"type": "json_object"},
        }
        try:
            body = await self._post(payload)
        except httpx.HTTPError:
            # Some servers reject response_format; retry without it.
            payload.pop("response_format", None)
            body = await self._post(payload)
        return extract_object(body["choices"][0]["message"].get("content") or "{}")
