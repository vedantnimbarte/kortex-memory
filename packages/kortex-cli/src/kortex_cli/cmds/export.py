"""kortex export / import commands."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import httpx
import typer

from kortex_cli.client import ApiClient, CliApiError
from kortex_cli.config import get_profile
from kortex_cli.output import fail, print_obj

app = typer.Typer(help="Export/import scopes.", no_args_is_help=True)


@app.command("scope")
def export_scope(
    scope_type: Annotated[str, typer.Option()] = "project",
    scope_id: Annotated[int, typer.Option()] = 0,
    out: Annotated[Path, typer.Option("-o", "--out")] = Path("kortex-export.tar"),
    include_attachments: Annotated[bool, typer.Option("--include-attachments/--skip-attachments")] = True,
) -> None:
    """GET /v1/export and write the tarball to ``--out``."""
    profile = get_profile()
    headers: dict[str, str] = {"Accept": "application/x-tar"}
    if profile.api_key:
        headers["X-API-Key"] = profile.api_key
    elif profile.access_token:
        headers["Authorization"] = f"Bearer {profile.access_token}"

    params = {
        "scope_type": scope_type,
        "scope_id": scope_id,
        "include_attachments": str(include_attachments).lower(),
    }
    try:
        resp = httpx.get(
            f"{profile.api_url}/v1/export",
            headers=headers,
            params=params,
            timeout=300.0,
        )
    except httpx.HTTPError as e:
        fail(f"export failed: {e}")
        return
    if resp.status_code >= 400:
        fail(f"export failed: HTTP {resp.status_code} {resp.text}")
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(resp.content)
    print_obj(
        {
            "exported": True,
            "path": str(out),
            "size_bytes": len(resp.content),
        }
    )


@app.command("import")
def import_scope(
    file: Annotated[Path, typer.Argument()],
    target_scope_type: Annotated[str, typer.Option()] = "project",
    target_scope_id: Annotated[int, typer.Option()] = 0,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    if not file.exists():
        fail(f"file not found: {file}")
        return
    body = file.read_bytes()
    profile = get_profile()
    headers: dict[str, str] = {}
    if profile.api_key:
        headers["X-API-Key"] = profile.api_key
    elif profile.access_token:
        headers["Authorization"] = f"Bearer {profile.access_token}"
    try:
        resp = httpx.post(
            f"{profile.api_url}/v1/export/import",
            headers=headers,
            params={
                "target_scope_type": target_scope_type,
                "target_scope_id": target_scope_id,
            },
            files={"file": (file.name, body, "application/x-tar")},
            timeout=300.0,
        )
    except httpx.HTTPError as e:
        fail(f"import failed: {e}")
        return
    if resp.status_code >= 400:
        fail(f"import failed: HTTP {resp.status_code} {resp.text}")
        return
    print_obj(resp.json(), json_output=json_output)


# Silence ApiClient unused-import warning under coverage.
_ = (ApiClient, CliApiError)
