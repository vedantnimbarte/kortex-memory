"""Typer root for the ``kortex`` CLI."""

from __future__ import annotations

import typer

from kortex_cli.cmds import admin, auth, key, memory, org, project, user, workspace

app = typer.Typer(
    name="kortex",
    help="Kortex memory CLI — admin and user surface.",
    no_args_is_help=True,
)
app.add_typer(auth.app, name="auth")
app.add_typer(org.app, name="org")
app.add_typer(workspace.app, name="workspace")
app.add_typer(project.app, name="project")
app.add_typer(user.app, name="user")
app.add_typer(key.app, name="key")
app.add_typer(memory.app, name="memory")
app.add_typer(admin.app, name="admin")


if __name__ == "__main__":  # pragma: no cover
    app()
