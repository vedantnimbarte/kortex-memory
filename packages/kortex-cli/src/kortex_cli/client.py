"""HTTP client used by user-facing CLI commands."""

from __future__ import annotations

from typing import Any

import httpx
from rich.console import Console

from kortex_cli.config import CliProfile, get_profile

console = Console(stderr=True)


class CliApiError(Exception):
    def __init__(self, status: int, body: Any) -> None:
        super().__init__(f"HTTP {status}: {body}")
        self.status = status
        self.body = body


class ApiClient:
    def __init__(self, profile: CliProfile | None = None):
        self.profile = profile or get_profile()
        headers: dict[str, str] = {"Accept": "application/json"}
        if self.profile.api_key:
            headers["X-API-Key"] = self.profile.api_key
        elif self.profile.access_token:
            headers["Authorization"] = f"Bearer {self.profile.access_token}"
        self._client = httpx.Client(
            base_url=self.profile.api_url,
            headers=headers,
            timeout=30.0,
        )

    def __enter__(self) -> ApiClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self._client.close()

    def request(
        self, method: str, path: str, *, json: Any | None = None, params: dict | None = None
    ) -> Any:
        resp = self._client.request(method, path, json=json, params=params)
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except ValueError:
                body = resp.text
            raise CliApiError(resp.status_code, body)
        if resp.status_code == 204 or not resp.content:
            return None
        return resp.json()

    def get(self, path: str, **kw: Any) -> Any:
        return self.request("GET", path, **kw)

    def post(self, path: str, **kw: Any) -> Any:
        return self.request("POST", path, **kw)

    def delete(self, path: str, **kw: Any) -> Any:
        return self.request("DELETE", path, **kw)

    def patch(self, path: str, **kw: Any) -> Any:
        return self.request("PATCH", path, **kw)
