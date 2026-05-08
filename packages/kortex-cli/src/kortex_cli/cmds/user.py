"""kortex user commands."""

from __future__ import annotations

import getpass
from typing import Annotated

import typer

from kortex_cli.client import ApiClient, CliApiError
from kortex_cli.output import fail, print_obj

app = typer.Typer(help="Manage users and memberships.", no_args_is_help=True)


@app.command("create")
def create(
    email: Annotated[str, typer.Option()],
    display_name: Annotated[str, typer.Option()] = "",
    superuser: Annotated[bool, typer.Option("--superuser")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    password = getpass.getpass("password: ")
    with ApiClient() as client:
        try:
            result = client.post(
                "/v1/users",
                json={
                    "email": email,
                    "password": password,
                    "display_name": display_name,
                    "is_superuser": superuser,
                },
            )
        except CliApiError as e:
            fail(str(e))
            return
    print_obj(result, json_output=json_output)


@app.command("show")
def show(public_id: str, json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    with ApiClient() as client:
        try:
            result = client.get(f"/v1/users/{public_id}")
        except CliApiError as e:
            fail(str(e))
            return
    print_obj(result, json_output=json_output)


@app.command("grant")
def grant(
    public_id: str,
    scope_type: Annotated[str, typer.Option()],
    scope_id: Annotated[int, typer.Option()],
    role: Annotated[str, typer.Option()],
) -> None:
    with ApiClient() as client:
        try:
            client.post(
                f"/v1/users/{public_id}/memberships",
                json={"scope_type": scope_type, "scope_id": scope_id, "role": role},
            )
        except CliApiError as e:
            fail(str(e))
            return
    print_obj({"granted": True})


@app.command("revoke")
def revoke(
    public_id: str,
    scope_type: Annotated[str, typer.Option()],
    scope_id: Annotated[int, typer.Option()],
    role: Annotated[str, typer.Option()] = "member",
) -> None:
    with ApiClient() as client:
        try:
            client.delete(
                f"/v1/users/{public_id}/memberships",
                json={"scope_type": scope_type, "scope_id": scope_id, "role": role},
            )
        except CliApiError as e:
            fail(str(e))
            return
    print_obj({"revoked": True})
