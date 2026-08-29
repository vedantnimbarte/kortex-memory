"""Typer root for the ``kortex`` CLI."""

from __future__ import annotations

import sys

import typer

from kortex_cli.cmds import (
    admin,
    attachment,
    auth,
    doctor,
    export,
    hook,
    ingest,
    key,
    memory,
    org,
    project,
    recall,
    search,
    session,
    user,
    workspace,
)
from kortex_cli.cmds.import_ import import_command
from kortex_cli.cmds.init import init as init_command

# Every command prints ✓, • or → through rich. A console that encodes cp1252
# (Windows' default) or ASCII (a POSIX C locale) raises UnicodeEncodeError on
# the first one, so `kortex init` died on its banner before doing any work.
# Degrade those glyphs instead of the process: rich resolves ``sys.stdout``
# per write, so doing this before any Console is used covers every command.
for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if _reconfigure is not None:  # pragma: no cover - stream-dependent
        _reconfigure(errors="replace")

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
app.add_typer(session.app, name="session")
app.add_typer(memory.app, name="memory")
app.add_typer(attachment.app, name="attachment")
app.add_typer(search.app, name="search")
app.add_typer(recall.app, name="recall")
app.add_typer(ingest.app, name="ingest")
app.add_typer(export.app, name="export")
app.add_typer(admin.app, name="admin")
app.add_typer(hook.app, name="hook")
app.add_typer(doctor.app, name="doctor")
app.command("init")(init_command)
# Root commands, not sub-apps: a Typer group callback cannot take options
# after a positional, so `kortex import file --from mem0` only parses when
# `import` is a plain command.
app.command("import")(import_command)


if __name__ == "__main__":  # pragma: no cover
    app()
