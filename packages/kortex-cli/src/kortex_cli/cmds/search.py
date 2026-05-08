"""kortex search commands."""

from __future__ import annotations

from typing import Annotated

import typer

from kortex_cli.client import ApiClient, CliApiError
from kortex_cli.output import fail, print_obj

app = typer.Typer(help="Hybrid search across memories.", no_args_is_help=True, invoke_without_command=False)


def _do_search(
    query: str,
    scope_type: str | None,
    scope_id: int | None,
    limit: int,
    no_embed: bool,
    json_output: bool,
) -> None:
    payload: dict = {"query": query, "limit": limit, "embed_query": not no_embed}
    if scope_type and scope_id is not None:
        payload["scopes"] = [{"scope_type": scope_type, "scope_id": scope_id}]
    with ApiClient() as client:
        try:
            result = client.post("/v1/search", json=payload)
        except CliApiError as e:
            fail(str(e))
            return
    print_obj(result, json_output=json_output)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    query: Annotated[str | None, typer.Argument()] = None,
    scope_type: Annotated[str | None, typer.Option()] = None,
    scope_id: Annotated[int | None, typer.Option()] = None,
    limit: Annotated[int, typer.Option()] = 20,
    no_embed: Annotated[bool, typer.Option("--no-embed")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    if ctx.invoked_subcommand is not None:
        return
    if not query:
        typer.echo("usage: kortex search <query>")
        raise typer.Exit(2)
    _do_search(query, scope_type, scope_id, limit, no_embed, json_output)
