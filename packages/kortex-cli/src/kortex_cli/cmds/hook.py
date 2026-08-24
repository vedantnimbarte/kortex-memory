"""``kortex hook`` — commands invoked by agent-harness hooks, not by humans.

Installed by ``kortex init`` into the harness config. The contract with the
harness is stdout: a hook prints one JSON object and exits 0.

**A hook must never break the session.** Every failure path here — no
credentials, API down, no project scope — prints empty context and exits 0.
The agent then behaves exactly as it would without Kortex installed.
"""

from __future__ import annotations

import json
from typing import Annotated

import httpx
import typer

from kortex_cli.client import ApiClient, CliApiError
from kortex_cli.config import get_profile

app = typer.Typer(help="Hook entrypoints for agent harnesses.", no_args_is_help=True)

MAX_MEMORIES = 20
MAX_BODY_CHARS = 400


def _emit(context: str) -> None:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": context,
                }
            }
        )
    )


def _render(project_slug: str, memories: list[dict]) -> str:
    lines = [f"## Kortex memory — project `{project_slug}`", ""]
    for memory in memories:
        title = memory.get("title") or "(untitled)"
        body = (memory.get("body") or "").strip()
        if len(body) > MAX_BODY_CHARS:
            body = body[:MAX_BODY_CHARS].rstrip() + "…"
        pin = "📌 " if memory.get("pinned") else ""
        lines.append(f"- {pin}**{title}** ({memory.get('kind', 'fact')}): {body}")
    lines.append("")
    lines.append(
        "Use the `recall` and `search_memory` tools for anything not covered here, "
        "and `remember` to record new decisions."
    )
    return "\n".join(lines)


@app.command("session-start")
def session_start(
    limit: Annotated[int, typer.Option(help="How many memories to inject.")] = MAX_MEMORIES,
) -> None:
    """Inject this project's memories into a starting agent session."""
    # Imported here so a hook invocation doesn't pay for the init command's imports.
    from kortex_cli.cmds.init import _project_root, _slugify

    root = _project_root()
    slug = _slugify(root.name)
    try:
        with ApiClient(get_profile()) as client:
            workspaces = client.get("/v1/workspaces") or []
            project = next(
                (
                    p
                    for w in workspaces
                    for p in (client.get(f"/v1/workspaces/{w['public_id']}/projects") or [])
                    if p["slug"] == slug
                ),
                None,
            )
            if project is None:
                _emit("")
                return
            memories = (
                client.get(
                    "/v1/memories",
                    params={
                        "scope_type": "project",
                        "scope_id": project["id"],
                        "limit": limit,
                    },
                )
                or []
            )
    except (CliApiError, httpx.HTTPError, OSError, SystemExit):
        _emit("")  # never break the session over a memory lookup
        return

    _emit(_render(slug, memories) if memories else "")
