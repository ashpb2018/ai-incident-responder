"""AWS Bedrock backend using the Converse API.

Two auth transports:
  * IAM (default): the boto3 ``bedrock-runtime`` client, run in a worker thread
    because boto3 is synchronous.
  * API key: a bearer token sent to the Converse REST endpoint over httpx.
"""

from __future__ import annotations

import asyncio
import json

from ..settings import get_settings
from .anthropic_backend import SYSTEM_PROMPT
from .base import LLMBackend, ToolCall, Turn
from .jsonutil import extract_object


def _to_bedrock_tools(anthropic_tools: list[dict]) -> dict:
    return {
        "tools": [
            {
                "toolSpec": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "inputSchema": {"json": tool.get("input_schema", {"type": "object", "properties": {}})},
                }
            }
            for tool in anthropic_tools
        ]
    }


class BedrockBackend(LLMBackend):
    def __init__(self) -> None:
        settings = get_settings()
        self._model = settings.bedrock_model_id
        self._region = settings.aws_region
        self._max_tokens = settings.max_tokens
        self._api_key = settings.bedrock_api_key
        self._tool_config: dict | None = None
        self._messages: list[dict] = []
        self._text_parts: list[str] = []
        self._client = None
        if not self._api_key:
            import boto3

            session = boto3.Session(
                region_name=self._region,
                aws_access_key_id=settings.aws_access_key_id or None,
                aws_secret_access_key=settings.aws_secret_access_key or None,
                aws_session_token=settings.aws_session_token or None,
            )
            self._client = session.client("bedrock-runtime")

    @property
    def label(self) -> str:
        return "AWS Bedrock"

    @property
    def model(self) -> str:
        return self._model

    def set_tools(self, tool_schemas: list[dict]) -> None:
        self._tool_config = _to_bedrock_tools(tool_schemas)

    def transcript(self) -> str:
        return "\n\n".join(self._text_parts)

    async def send(self, content: str | list[dict]) -> Turn:
        if isinstance(content, str):
            self._messages.append({"role": "user", "content": [{"text": content}]})
        else:
            self._messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "toolResult": {
                                "toolUseId": item["tool_use_id"],
                                "content": [{"text": item["content"]}],
                            }
                        }
                        for item in content
                    ],
                }
            )

        response = await self._converse(self._messages, tools=True)
        message = response["output"]["message"]
        self._messages.append(message)

        text = ""
        tool_calls: list[ToolCall] = []
        for block in message.get("content", []):
            if "text" in block:
                text += block["text"]
            elif "toolUse" in block:
                use = block["toolUse"]
                tool_calls.append(
                    ToolCall(id=use["toolUseId"], name=use["name"], arguments=use.get("input", {}))
                )
        if text:
            self._text_parts.append(text)

        stop = "tool_use" if tool_calls else "end_turn"
        return Turn(text=text, tool_calls=tool_calls, stop_reason=stop)

    async def summarise_json(self, prompt: str, schema: dict) -> str:
        instruction = (
            f"{prompt}\n\nReturn ONLY a JSON object matching this schema:\n{json.dumps(schema)}"
        )
        messages = [{"role": "user", "content": [{"text": instruction}]}]
        response = await self._converse(messages, tools=False)
        text = "".join(
            b.get("text", "") for b in response["output"]["message"].get("content", [])
        )
        return extract_object(text)

    async def _converse(self, messages: list[dict], *, tools: bool) -> dict:
        params: dict = {
            "modelId": self._model,
            "messages": messages,
            "inferenceConfig": {"maxTokens": self._max_tokens, "temperature": 0},
            "system": [{"text": SYSTEM_PROMPT}],
        }
        if tools and self._tool_config:
            params["toolConfig"] = self._tool_config

        if self._client is not None:
            return await asyncio.to_thread(self._client.converse, **params)
        return await self._converse_via_api_key(params)

    async def _converse_via_api_key(self, params: dict) -> dict:
        import httpx

        url = (
            f"https://bedrock-runtime.{self._region}.amazonaws.com/"
            f"model/{params['modelId']}/converse"
        )
        body = {k: v for k, v in params.items() if k != "modelId"}
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                url,
                headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
                json=body,
            )
            resp.raise_for_status()
            return resp.json()
