"""kortex recall — agentic recall with optional answer synthesis."""

from __future__ import annotations

from typing import Annotated

import typer

from kortex_cli.client import ApiClient, CliApiError
from kortex_cli.output import fail, print_obj

app = typer.Typer(
    help="Agentic recall against the memory layer.",
    no_args_is_help=True,
    invoke_without_command=False,
)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    query: Annotated[str | None, typer.Argument()] = None,
    scope_type: Annotated[str | None, typer.Option()] = None,
    scope_id: Annotated[int | None, typer.Option()] = None,
    synthesize: Annotated[bool, typer.Option("--synthesize")] = False,
    max_tokens: Annotated[int, typer.Option("--max-tokens")] = 0,
    per_item_max: Annotated[int, typer.Option("--per-item-max")] = 800,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    if ctx.invoked_subcommand is not None:
        return
    if not query:
        typer.echo("usage: kortex recall <query> [--synthesize]")
        raise typer.Exit(2)
    payload: dict = {
        "query": query,
        "synthesize": synthesize,
        "max_tokens": max_tokens,
        "per_item_max": per_item_max,
    }
    if scope_type and scope_id is not None:
        payload["scopes"] = [{"scope_type": scope_type, "scope_id": scope_id}]
    with ApiClient() as client:
        try:
            result = client.post("/v1/search/recall", json=payload)
        except CliApiError as e:
            fail(str(e))
            return
    print_obj(result, json_output=json_output)
