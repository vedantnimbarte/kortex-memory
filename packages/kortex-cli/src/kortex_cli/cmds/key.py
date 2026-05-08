"""kortex key commands."""

from __future__ import annotations

from typing import Annotated

import typer

from kortex_cli.client import ApiClient, CliApiError
from kortex_cli.output import fail, print_obj

app = typer.Typer(help="Manage API keys.", no_args_is_help=True)


@app.command("list")
def list_keys(json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    with ApiClient() as client:
        try:
            result = client.get("/v1/api_keys")
        except CliApiError as e:
            fail(str(e))
            return
    print_obj(result, json_output=json_output)


@app.command("create")
def create(
    name: Annotated[str, typer.Option()],
    scopes: Annotated[
        str,
        typer.Option(help="Comma-separated, e.g. read:memory,write:memory"),
    ] = "read:memory,write:memory",
    scope_type: Annotated[str | None, typer.Option()] = None,
    scope_id: Annotated[int | None, typer.Option()] = None,
    expires_in_days: Annotated[int | None, typer.Option()] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    body: dict = {
        "name": name,
        "scopes": [s.strip() for s in scopes.split(",") if s.strip()],
    }
    if scope_type is not None:
        body["scope_type"] = scope_type
    if scope_id is not None:
        body["scope_id"] = scope_id
    if expires_in_days is not None:
        body["expires_in_days"] = expires_in_days
    with ApiClient() as client:
        try:
            result = client.post("/v1/api_keys", json=body)
        except CliApiError as e:
            fail(str(e))
            return
    print_obj(result, json_output=json_output)


@app.command("revoke")
def revoke(public_id: str) -> None:
    with ApiClient() as client:
        try:
            client.delete(f"/v1/api_keys/{public_id}")
        except CliApiError as e:
            fail(str(e))
            return
    print_obj({"revoked": True, "public_id": public_id})
