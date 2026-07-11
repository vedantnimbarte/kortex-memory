"""kortex memory commands."""

from __future__ import annotations

from typing import Annotated

import typer

from kortex_cli.client import ApiClient, CliApiError
from kortex_cli.output import fail, print_obj

app = typer.Typer(help="Memory CRUD and management.", no_args_is_help=True)


@app.command("list")
def list_memories(
    scope_type: Annotated[str | None, typer.Option()] = None,
    scope_id: Annotated[int | None, typer.Option()] = None,
    tier: Annotated[str | None, typer.Option()] = None,
    kind: Annotated[str | None, typer.Option()] = None,
    limit: Annotated[int, typer.Option()] = 50,
    offset: Annotated[int, typer.Option()] = 0,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    params: dict = {"limit": limit, "offset": offset}
    if scope_type is not None:
        params["scope_type"] = scope_type
    if scope_id is not None:
        params["scope_id"] = scope_id
    if tier is not None:
        params["tier"] = tier
    if kind is not None:
        params["kind"] = kind
    with ApiClient() as client:
        try:
            result = client.get("/v1/memories", params=params)
        except CliApiError as e:
            fail(str(e))
            return
    print_obj(result, json_output=json_output)


@app.command("create")
def create(
    body: Annotated[str, typer.Option()],
    scope_type: Annotated[str, typer.Option()] = "project",
    scope_id: Annotated[int, typer.Option()] = 0,
    title: Annotated[str, typer.Option()] = "",
    kind: Annotated[str, typer.Option()] = "fact",
    sensitivity: Annotated[str, typer.Option()] = "internal",
    pin: Annotated[bool, typer.Option("--pin")] = False,
    embed: Annotated[bool, typer.Option("--embed")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    payload = {
        "scope_type": scope_type,
        "scope_id": scope_id,
        "body": body,
        "title": title,
        "kind": kind,
        "sensitivity": sensitivity,
        "pinned": pin,
    }
    with ApiClient() as client:
        try:
            result = client.post(
                "/v1/memories",
                json=payload,
                params={"embed_inline": str(embed).lower()},
            )
        except CliApiError as e:
            fail(str(e))
            return
    print_obj(result, json_output=json_output)


@app.command("show")
def show(public_id: str, json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    with ApiClient() as client:
        try:
            result = client.get(f"/v1/memories/{public_id}")
        except CliApiError as e:
            fail(str(e))
            return
    print_obj(result, json_output=json_output)


@app.command("update")
def update(
    public_id: str,
    body: Annotated[str | None, typer.Option()] = None,
    title: Annotated[str | None, typer.Option()] = None,
    sensitivity: Annotated[str | None, typer.Option()] = None,
    importance: Annotated[float | None, typer.Option()] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    payload: dict = {}
    if body is not None:
        payload["body"] = body
    if title is not None:
        payload["title"] = title
    if sensitivity is not None:
        payload["sensitivity"] = sensitivity
    if importance is not None:
        payload["importance"] = importance
    with ApiClient() as client:
        try:
            result = client.patch(f"/v1/memories/{public_id}", json=payload)
        except CliApiError as e:
            fail(str(e))
            return
    print_obj(result, json_output=json_output)


@app.command("delete")
def delete(public_id: str) -> None:
    with ApiClient() as client:
        try:
            client.delete(f"/v1/memories/{public_id}")
        except CliApiError as e:
            fail(str(e))
            return
    print_obj({"deleted": True, "public_id": public_id})


@app.command("pin")
def pin(public_id: str, json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    with ApiClient() as client:
        try:
            result = client.post(f"/v1/memories/{public_id}/pin")
        except CliApiError as e:
            fail(str(e))
            return
    print_obj(result, json_output=json_output)


@app.command("unpin")
def unpin(public_id: str, json_output: Annotated[bool, typer.Option("--json")] = False) -> None:
    with ApiClient() as client:
        try:
            result = client.delete(f"/v1/memories/{public_id}/pin")
        except CliApiError as e:
            fail(str(e))
            return
    print_obj(result, json_output=json_output)


@app.command("link")
def link(
    from_id: str,
    to_id: str,
    link_type: Annotated[str, typer.Option()] = "related",
    weight: Annotated[float, typer.Option()] = 1.0,
) -> None:
    with ApiClient() as client:
        try:
            client.post(
                f"/v1/memories/{from_id}/links",
                json={
                    "to_public_id": to_id,
                    "link_type": link_type,
                    "weight": weight,
                },
            )
        except CliApiError as e:
            fail(str(e))
            return
    print_obj({"linked": True, "from": from_id, "to": to_id, "type": link_type})
