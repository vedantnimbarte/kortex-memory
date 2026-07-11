"""Uvicorn entrypoint: ``kortex-api`` console script."""

from __future__ import annotations

import uvicorn
from kortex_core.settings import get_settings


def run() -> None:
    s = get_settings()
    uvicorn.run(
        "kortex_api.app:app",
        host=s.api_host,
        port=s.api_port,
        log_config=None,
        reload=s.env == "development",
    )


if __name__ == "__main__":
    run()
