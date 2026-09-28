"""Console entry point: run the webhook server."""

from __future__ import annotations

from .settings import get_settings


def main() -> None:
    import uvicorn

    settings = get_settings()
    print(
        f"Sentinel starting — backend={settings.backend.value} "
        f"model={settings.active_model} on http://{settings.host}:{settings.port}"
    )
    uvicorn.run(
        "incident_sentinel.app:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
