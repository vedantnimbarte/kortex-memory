"""kortex ingest commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from kortex_cli.client import ApiClient, CliApiError
from kortex_cli.output import fail, print_obj

app = typer.Typer(help="Ingest external data.", no_args_is_help=True)


@app.command("messages")
def ingest_messages(
    file: Annotated[Path, typer.Argument(help="JSONL file of {role, content, ...}")],
    session: Annotated[str, typer.Option(help="Session public_id")],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    if not file.exists():
        fail(f"file not found: {file}")
        return
    messages: list[dict] = []
    with file.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                messages.append(json.loads(line))
            except json.JSONDecodeError as e:
                fail(f"bad jsonl line: {e}")
                return
    with ApiClient() as client:
        try:
            result = client.post(
                f"/v1/ingest/sessions/{session}/messages",
                json={"messages": messages},
            )
        except CliApiError as e:
            fail(str(e))
            return
    print_obj(result, json_output=json_output)


@app.command("document")
def ingest_document(
    file: Annotated[Path, typer.Argument(help="Plain text or markdown")],
    scope_type: Annotated[str, typer.Option()] = "project",
    scope_id: Annotated[int, typer.Option()] = 0,
    title: Annotated[str | None, typer.Option()] = None,
    sensitivity: Annotated[str, typer.Option()] = "internal",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    if not file.exists():
        fail(f"file not found: {file}")
        return
    body = file.read_text(encoding="utf-8")
    payload = {
        "scope_type": scope_type,
        "scope_id": scope_id,
        "title": title or file.name,
        "body": body,
        "kind": "procedure",
        "sensitivity": sensitivity,
        "source_type": "document",
        "source_ref": {"path": str(file)},
    }
    with ApiClient() as client:
        try:
            result = client.post("/v1/memories", json=payload)
        except CliApiError as e:
            fail(str(e))
            return
    print_obj(result, json_output=json_output)


@app.command("git-log")
def ingest_git_log(
    repo: Annotated[Path, typer.Argument(help="Path to a git repository")],
    scope_type: Annotated[str, typer.Option()] = "project",
    scope_id: Annotated[int, typer.Option()] = 0,
    limit: Annotated[int, typer.Option(help="Max commits to ingest")] = 200,
    sensitivity: Annotated[str, typer.Option()] = "internal",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Parse ``git log`` output and post each commit as an EVENT memory."""
    import subprocess

    if not (repo / ".git").exists():
        fail(f"not a git repo: {repo}")
        return
    try:
        out = subprocess.check_output(  # noqa: S603
            [
                "git",
                "-C",
                str(repo),
                "log",
                f"-n{limit}",
                "--pretty=format:%H%x1f%an%x1f%aI%x1f%B%x1e",
            ]
        )
    except subprocess.CalledProcessError as e:
        fail(f"git log failed: {e}")
        return

    commits: list[dict] = []
    for record in out.decode("utf-8", errors="replace").split("\x1e"):
        record = record.strip()
        if not record:
            continue
        parts = record.split("\x1f", 3)
        if len(parts) < 4:
            continue
        sha, author, date, message = parts
        commits.append(
            {
                "sha": sha,
                "author": author,
                "date": date,
                "message": message.strip(),
            }
        )

    payload = {
        "scope_type": scope_type,
        "scope_id": scope_id,
        "sensitivity": sensitivity,
        "commits": commits,
    }
    with ApiClient() as client:
        try:
            result = client.post("/v1/ingest/git-log", json=payload)
        except CliApiError as e:
            fail(str(e))
            return
    print_obj(result, json_output=json_output)
