"""kortex admin commands (DB-direct, requires KORTEX_DATABASE_URL)."""

from __future__ import annotations

import subprocess
from typing import Annotated

import typer

from kortex_cli.client import ApiClient, CliApiError
from kortex_cli.output import fail, print_obj

app = typer.Typer(help="Server-side admin (DB-direct).", no_args_is_help=True)
migrate = typer.Typer(help="Alembic migration helpers.", no_args_is_help=True)
app.add_typer(migrate, name="migrate")


@migrate.command("up")
def migrate_up() -> None:
    """Run alembic upgrade head."""
    subprocess.run(["alembic", "upgrade", "head"], check=True)


@migrate.command("down")
def migrate_down(revision: str = "-1") -> None:
    """Run alembic downgrade <revision>."""
    subprocess.run(["alembic", "downgrade", revision], check=True)


@migrate.command("current")
def migrate_current() -> None:
    subprocess.run(["alembic", "current"], check=True)


@migrate.command("history")
def migrate_history() -> None:
    subprocess.run(["alembic", "history"], check=True)


@app.command("force-decay-tick")
def force_decay_tick(
    org_id: Annotated[int | None, typer.Option()] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Dispatch the decay tick task (superuser API)."""
    params: dict = {}
    if org_id is not None:
        params["org_id"] = org_id
    with ApiClient() as client:
        try:
            result = client.post("/v1/admin/force_decay_tick", params=params)
        except CliApiError as e:
            fail(str(e))
            return
    print_obj(result, json_output=json_output)


@app.command("reindex-embeddings")
def reindex_embeddings(
    batch_size: Annotated[int, typer.Option()] = 64,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Clear all embeddings and let embed_pending refill them (superuser API)."""
    with ApiClient() as client:
        try:
            result = client.post(
                "/v1/admin/reindex_embeddings",
                json={"batch_size": batch_size},
            )
        except CliApiError as e:
            fail(str(e))
            return
    print_obj(result, json_output=json_output)


@app.command("consolidate")
def consolidate(
    org_id: Annotated[int | None, typer.Option()] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Dispatch the mid→long consolidation task."""
    params: dict = {}
    if org_id is not None:
        params["org_id"] = org_id
    with ApiClient() as client:
        try:
            result = client.post("/v1/admin/consolidate_tier", params=params)
        except CliApiError as e:
            fail(str(e))
            return
    print_obj(result, json_output=json_output)
