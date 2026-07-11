"""kortex session commands."""

from __future__ import annotations

from typing import Annotated

import typer

from kortex_cli.client import ApiClient, CliApiError
from kortex_cli.output import fail, print_obj

app = typer.Typer(help="Manage agent sessions.", no_args_is_help=True)


@app.command("start")
def start(
    project: Annotated[str, typer.Option(help="Project public_id")],
    agent: Annotated[str, typer.Option(help="agent_kind")] = "other",
    title: Annotated[str, typer.Option()] = "",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    body = {
        "project_public_id": project,
        "agent_kind": agent,
        "title": title,
    }
    with ApiClient() as client:
        try:
            result = client.post("/v1/sessions", json=body)
        except CliApiError as e:
            fail(str(e))
            return
    print_obj(result, json_output=json_output)


@app.command("show")
def show(
    public_id: str,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    with ApiClient() as client:
        try:
            result = client.get(f"/v1/sessions/{public_id}")
        except CliApiError as e:
            fail(str(e))
            return
    print_obj(result, json_output=json_output)


@app.command("end")
def end(public_id: str, json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    with ApiClient() as client:
        try:
            result = client.post(f"/v1/sessions/{public_id}/end")
        except CliApiError as e:
            fail(str(e))
            return
    print_obj(result, json_output=json_output)
