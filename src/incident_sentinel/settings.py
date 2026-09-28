"""Runtime configuration for Sentinel.

Settings come from the environment (and an optional ``.env`` file). Grouped by
concern: the LLM backend, each observability integration, the webhook server,
and the agent's operating limits.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Backend(str, Enum):
    ANTHROPIC = "anthropic"
    BEDROCK = "bedrock"
    OLLAMA = "ollama"


def _default_kubeconfig() -> str:
    return str(Path.home() / ".kube" / "config")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- backend selection ---------------------------------------------------
    backend: Backend = Field(default=Backend.ANTHROPIC, alias="llm_backend")

    # --- anthropic -----------------------------------------------------------
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-3-5-sonnet-20241022"

    # --- aws bedrock ---------------------------------------------------------
    aws_region: str = "us-east-1"
    bedrock_api_key: str = ""
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_session_token: str = ""
    bedrock_model_id: str = "anthropic.claude-3-5-sonnet-20241022-v2:0"

    # --- ollama / openai-compatible ------------------------------------------
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"

    # --- prometheus ----------------------------------------------------------
    prometheus_url: str = "http://localhost:9090"

    # --- datadog -------------------------------------------------------------
    datadog_api_key: str = ""
    datadog_app_key: str = ""
    datadog_site: str = "datadoghq.com"

    # --- webhooks ------------------------------------------------------------
    pagerduty_webhook_secret: str = ""
    opsgenie_webhook_secret: str = ""

    # --- kubernetes ----------------------------------------------------------
    kubeconfig: str = Field(default_factory=_default_kubeconfig)
    kubectl_timeout: int = 30

    # --- server --------------------------------------------------------------
    # Bind to loopback by default; opt into 0.0.0.0 explicitly for deployment.
    host: str = "127.0.0.1"
    port: int = 8080

    # --- agent limits --------------------------------------------------------
    max_agent_steps: int = 20
    max_tokens: int = 8000
    min_severity: str = "high"

    @property
    def active_model(self) -> str:
        return {
            Backend.ANTHROPIC: self.anthropic_model,
            Backend.BEDROCK: self.bedrock_model_id,
            Backend.OLLAMA: self.ollama_model,
        }[self.backend]


_settings: Settings | None = None


def get_settings(*, refresh: bool = False) -> Settings:
    """Return a process-wide :class:`Settings` singleton."""
    global _settings
    if _settings is None or refresh:
        _settings = Settings()
    return _settings
