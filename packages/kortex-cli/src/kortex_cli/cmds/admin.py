"""kortex admin commands (DB-direct, requires KORTEX_DATABASE_URL)."""

from __future__ import annotations

import subprocess

import typer

app = typer.Typer(help="Server-side admin (DB-direct).", no_args_is_help=True)
migrate = typer.Typer(help="Alembic migration helpers.", no_args_is_help=True)
app.add_typer(migrate, name="migrate")


@migrate.command("up")
def migrate_up() -> None:
    """Run alembic upgrade head."""
    subprocess.run(["alembic", "upgrade", "head"], check=True)  # noqa: S603,S607


@migrate.command("down")
def migrate_down(revision: str = "-1") -> None:
    """Run alembic downgrade <revision>."""
    subprocess.run(["alembic", "downgrade", revision], check=True)  # noqa: S603,S607


@migrate.command("current")
def migrate_current() -> None:
    subprocess.run(["alembic", "current"], check=True)  # noqa: S603,S607


@migrate.command("history")
def migrate_history() -> None:
    subprocess.run(["alembic", "history"], check=True)  # noqa: S603,S607
