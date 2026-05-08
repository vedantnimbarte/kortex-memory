"""kortex workspace commands."""

from __future__ import annotations

from typing import Annotated

import typer

from kortex_cli.client import ApiClient, CliApiError
from kortex_cli.output import fail, print_obj

app = typer.Typer(help="Manage workspaces.", no_args_is_help=True)


@app.command("list")
def list_workspaces(
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    with ApiClient() as client:
        try:
            result = client.get("/v1/workspaces")
        except CliApiError as e:
            fail(str(e))
            return
    print_obj(result, json_output=json_output)


@app.command("create")
def create(
    slug: str,
    name: Annotated[str, typer.Option()],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    with ApiClient() as client:
        try:
            result = client.post("/v1/workspaces", json={"slug": slug, "name": name})
        except CliApiError as e:
            fail(str(e))
            return
    print_obj(result, json_output=json_output)


@app.command("show")
def show(public_id: str, json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    with ApiClient() as client:
        try:
            result = client.get(f"/v1/workspaces/{public_id}")
        except CliApiError as e:
            fail(str(e))
            return
    print_obj(result, json_output=json_output)
