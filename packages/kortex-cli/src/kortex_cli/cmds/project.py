"""kortex project commands."""

from __future__ import annotations

from typing import Annotated

import typer

from kortex_cli.client import ApiClient, CliApiError
from kortex_cli.output import fail, print_obj

app = typer.Typer(help="Manage projects.", no_args_is_help=True)


@app.command("list")
def list_projects(
    workspace: Annotated[str, typer.Option(help="Workspace public_id")],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    with ApiClient() as client:
        try:
            result = client.get(f"/v1/workspaces/{workspace}/projects")
        except CliApiError as e:
            fail(str(e))
            return
    print_obj(result, json_output=json_output)


@app.command("create")
def create(
    workspace: Annotated[str, typer.Option(help="Workspace public_id")],
    slug: str,
    name: Annotated[str, typer.Option()],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    with ApiClient() as client:
        try:
            result = client.post(
                f"/v1/workspaces/{workspace}/projects",
                json={"slug": slug, "name": name},
            )
        except CliApiError as e:
            fail(str(e))
            return
    print_obj(result, json_output=json_output)


@app.command("show")
def show(
    workspace: Annotated[str, typer.Option(help="Workspace public_id")],
    public_id: str,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    with ApiClient() as client:
        try:
            result = client.get(f"/v1/workspaces/{workspace}/projects/{public_id}")
        except CliApiError as e:
            fail(str(e))
            return
    print_obj(result, json_output=json_output)
