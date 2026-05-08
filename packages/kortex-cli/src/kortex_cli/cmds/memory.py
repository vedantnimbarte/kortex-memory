"""kortex memory commands. Stub for M1; full impl lands in M2."""

from __future__ import annotations

from typing import Annotated

import typer

from kortex_cli.output import print_obj

app = typer.Typer(help="Memory CRUD and search (M2).", no_args_is_help=True)


@app.command("list")
def list_memories(
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Placeholder until M2 ships memory endpoints."""
    print_obj([], json_output=json_output)
