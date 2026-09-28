"""Instantiate the configured backend."""

from __future__ import annotations

from ..settings import Backend, get_settings
from .base import LLMBackend


def build_backend() -> LLMBackend:
    backend = get_settings().backend
    if backend is Backend.ANTHROPIC:
        from .anthropic_backend import AnthropicBackend

        return AnthropicBackend()
    if backend is Backend.BEDROCK:
        from .bedrock_backend import BedrockBackend

        return BedrockBackend()
    if backend is Backend.OLLAMA:
        from .ollama_backend import OllamaBackend

        return OllamaBackend()
    raise ValueError(f"Unsupported backend: {backend}")
