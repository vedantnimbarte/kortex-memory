"""``kortex init`` — wire an agent harness to this Kortex install in one command.

Six steps, each idempotent and individually re-runnable:

1. **Credentials** — verify the active profile can talk to the API.
2. **Scope** — find (or create) the Project scope for this git repo.
3. **Key** — mint a project-scoped API key, falling back to the profile key.
4. **Transport** — probe the MCP SSE endpoint; fall back to stdio.
5. **Config** — merge a Kortex server entry into the harness config (+ hooks).
6. **Verify** — write a canary memory, read it back, delete it.

Re-running is safe: the config merge is byte-stable and the canary cleans up
after itself.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Annotated, NoReturn

import httpx
import typer
from rich.console import Console

from kortex_cli.client import ApiClient, CliApiError
from kortex_cli.config import CliProfile, get_profile
from kortex_cli.harnesses import (
    HARNESSES,
    HOOK_COMMAND,
    HarnessError,
    McpServer,
    claude_settings_path,
    global_path,
    merge_session_start_hook,
    read_text_if_exists,
    write_merged,
)
from kortex_cli.output import fail

console = Console()

DEFAULT_DATABASE_URL = "postgresql+asyncpg://kortex:kortex@localhost:5432/kortex"
MCP_SCOPES = ["read:memory", "write:memory", "read:attachment", "write:attachment"]

# Registered on the root app as a plain command, not a sub-Typer: a group's
# callback cannot take options *after* its positional argument, and
# `kortex init claude-code --transport sse` is the only word order anyone types.


# --- small helpers -----------------------------------------------------------


def _die(msg: str) -> NoReturn:
    """``fail`` typed as never-returning, so the checks below narrow correctly.

    ``output.fail`` itself stays ``-> None``: retyping it would mark the
    ``return`` after every existing ``fail(...)`` call site as unreachable, and
    that cleanup does not belong in this change.
    """
    fail(msg)
    raise SystemExit(1)  # pragma: no cover - fail() has already exited


def _ok(msg: str) -> None:
    console.print(f"  [green]✓[/green] {msg}")


def _note(msg: str) -> None:
    console.print(f"  [yellow]•[/yellow] {msg}")


def _project_root() -> Path:
    """The git root containing the cwd, or the cwd when this isn't a repo."""
    here = Path.cwd().resolve()
    for candidate in (here, *here.parents):
        if (candidate / ".git").exists():
            return candidate
    return here


def _slugify(name: str) -> str:
    """Coerce a directory name into the API's slug pattern (^[a-z0-9][a-z0-9-]*$)."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return slug[:64] if len(slug) >= 2 else "project"


def _default_mcp_url(api_url: str) -> str:
    """The MCP SSE endpoint that sits beside a given API origin (compose: :8765)."""
    return str(httpx.URL(api_url).copy_with(port=8765, path="/sse", query=None))


def _sse_alive(url: str) -> bool:
    """True when something at ``url`` answers as the Kortex SSE transport.

    Probed *without* a bearer on purpose: the transport rejects the anonymous
    request immediately, which makes 401 a fast liveness signal. Probing with a
    valid token would open a long-lived stream instead.
    """
    try:
        resp = httpx.get(url, timeout=3.0)
    except httpx.HTTPError:
        return False
    return resp.status_code in (401, 403)


def _resolve_database_url(explicit: str | None, root: Path) -> str:
    """stdio needs a DSN: flag, then env, then the repo's .env, then the documented default."""
    if explicit:
        return explicit
    from_env = os.environ.get("KORTEX_DATABASE_URL")
    if from_env:
        return from_env
    dotenv = root / ".env"
    if dotenv.exists():
        for line in dotenv.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "KORTEX_DATABASE_URL" and value.strip():
                return value.strip().strip("'\"")
    return DEFAULT_DATABASE_URL


# --- steps -------------------------------------------------------------------


def _resolve_project(
    client: ApiClient, workspace: str | None, root: Path, *, create: bool = True
) -> dict:
    """Find the Project scope matching this repo, creating it when absent.

    ``create=False`` reports what a real run would do and stops there: a dry
    run that leaves a project behind is not a dry run.
    """
    workspaces: list[dict] = client.get("/v1/workspaces") or []
    if not workspaces:
        _die("no workspaces found — create one first: kortex workspace create <slug> --name <name>")
    chosen = (
        next(
            (w for w in workspaces if workspace in (w["public_id"], w["slug"])),
            None,
        )
        if workspace
        else workspaces[0]
    )
    if chosen is None:
        _die(f"workspace {workspace!r} not found")

    slug = _slugify(root.name)
    projects: list[dict] = client.get(f"/v1/workspaces/{chosen['public_id']}/projects") or []
    for project in projects:
        if project["slug"] == slug:
            return project
    if not create:
        _note(f"project `{slug}` does not exist yet — would create it")
        return {"id": 0, "slug": slug, "public_id": ""}
    created: dict = client.post(
        f"/v1/workspaces/{chosen['public_id']}/projects",
        json={"slug": slug, "name": root.name},
    )
    return created


def _resolve_key(
    client: ApiClient, project: dict, fallback: str | None, *, mint: bool = True
) -> str:
    """Mint a project-scoped key; reuse the profile's key when we're not allowed to.

    ``mint=False`` for a dry run — a minted key is a real credential whether or
    not anything was written to disk.
    """
    if not mint:
        _note("would mint a project-scoped api key")
        return fallback or "kx_<minted on a real run>"
    try:
        minted = client.post(
            "/v1/api_keys",
            json={
                "name": f"kortex init — {project['slug']}",
                "scopes": MCP_SCOPES,
                "scope_type": "project",
                "scope_id": project["id"],
            },
        )
        return str(minted["plaintext"])
    except CliApiError as e:
        if not fallback:
            _die(f"could not mint an API key and the profile has none to reuse ({e})")
        _note(f"could not mint a project-scoped key ({e.status}); reusing the profile key")
        return fallback


def _write_configs(
    harness_key: str,
    root: Path,
    server: McpServer,
    *,
    remote: bool,
    use_global: bool,
    install_hooks: bool,
    dry_run: bool,
) -> None:
    harness = HARNESSES[harness_key]
    prefer_global = use_global or not harness.project_scoped
    path = global_path(harness) if prefer_global else harness.path(root)
    merged = harness.merge(read_text_if_exists(path), path, server, remote)

    if dry_run:
        console.print(f"  [dim]would write {path}[/dim]")
    else:
        _ok(f"{write_merged(path, merged)} {path}")

    if not install_hooks or harness.key != "claude-code":
        return
    hook_path = claude_settings_path(root)
    hook_text = merge_session_start_hook(read_text_if_exists(hook_path), hook_path)
    if dry_run:
        console.print(f"  [dim]would write {hook_path}[/dim]")
    else:
        _ok(f"{write_merged(hook_path, hook_text)} {hook_path} (SessionStart hook)")


def _verify(profile: CliProfile, api_key: str, project: dict) -> None:
    """Write a canary memory, read it back, then delete it.

    As the key we just installed, not as the profile. An api key holds a role
    in the one scope it is bound to, so the profile's own credential is denied
    in a project it does not belong to — which says nothing about whether the
    wiring works, and fails on a healthy install.
    """
    with ApiClient(
        CliProfile(name=profile.name, api_url=profile.api_url, api_key=api_key)
    ) as client:
        _canary(client, project)


def _canary(client: ApiClient, project: dict) -> None:
    created = client.post(
        "/v1/memories",
        json={
            "scope_type": "project",
            "scope_id": project["id"],
            "title": "kortex init canary",
            "body": f"Kortex was wired to the {project['slug']} project.",
            "kind": "event",
        },
    )
    public_id = created["public_id"]
    try:
        client.get(f"/v1/memories/{public_id}")
        _ok("write → read round trip succeeded")
    finally:
        client.delete(f"/v1/memories/{public_id}")


# --- command -----------------------------------------------------------------


def init(
    harness: Annotated[
        str,
        typer.Argument(help=f"One of: {', '.join(HARNESSES)}"),
    ],
    transport: Annotated[
        str, typer.Option(help="auto | sse | stdio — auto probes the SSE endpoint first.")
    ] = "auto",
    workspace: Annotated[
        str | None, typer.Option(help="Workspace public_id or slug (default: the first one).")
    ] = None,
    mcp_url: Annotated[
        str | None, typer.Option("--mcp-url", help="SSE endpoint (default: the API host on :8765).")
    ] = None,
    database_url: Annotated[
        str | None, typer.Option("--database-url", help="DSN for the stdio transport.")
    ] = None,
    hooks: Annotated[
        bool, typer.Option("--hooks/--no-hooks", help="Install the Claude Code SessionStart hook.")
    ] = True,
    use_global: Annotated[
        bool, typer.Option("--global", help="Write the user-level config instead of the repo's.")
    ] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Report, change nothing.")] = False,
) -> None:
    """Wire an agent harness to this Kortex install."""
    if harness not in HARNESSES:
        _die(f"unknown harness {harness!r} — expected one of: {', '.join(HARNESSES)}")
    if transport not in {"auto", "sse", "stdio"}:
        _die(f"unknown transport {transport!r} — expected auto, sse, or stdio")

    target = HARNESSES[harness]
    root = _project_root()
    profile = get_profile()
    console.print(f"[bold]Wiring {target.label}[/bold] → {profile.api_url}  ({root})")

    with ApiClient(profile) as client:
        try:
            client.get("/v1/auth/whoami")
        except CliApiError as e:
            _die(f"credentials rejected ({e.status}) — run `kortex auth login` first")
        except httpx.HTTPError as e:
            _die(f"cannot reach {profile.api_url} ({e}) — is the stack up? try `make dev`")
        _ok(f"authenticated against {profile.api_url}")

        try:
            project = _resolve_project(client, workspace, root, create=not dry_run)
        except CliApiError as e:
            _die(f"could not resolve a project scope: {e}")
        _ok(f"project scope `{project['slug']}` (id {project['id']})")

        api_key = _resolve_key(client, project, profile.api_key, mint=not dry_run)

        url = mcp_url or _default_mcp_url(profile.api_url)
        remote = _sse_alive(url) if transport == "auto" else transport == "sse"
        if remote and not target.remote_ok:
            _note(f"{target.label} has no remote-MCP form; using stdio instead")
            remote = False
        if remote:
            _ok(f"MCP over SSE at {url}")
        else:
            if shutil.which("kortex-mcp") is None:
                _note(
                    "`kortex-mcp` is not on PATH — run `uv sync --all-packages` "
                    "before starting the agent"
                )
            _ok("MCP over stdio")

        server = McpServer(
            url=url,
            api_key=api_key,
            env={
                "KORTEX_API_KEY": api_key,
                "KORTEX_DATABASE_URL": _resolve_database_url(database_url, root),
            },
        )
        try:
            _write_configs(
                harness,
                root,
                server,
                remote=remote,
                use_global=use_global,
                install_hooks=hooks,
                dry_run=dry_run,
            )
        except HarnessError as e:
            _die(str(e))

        if dry_run:
            console.print("[dim]dry run — nothing written, canary skipped[/dim]")
            return
        try:
            _verify(profile, api_key, project)
        except CliApiError as e:
            _die(f"verification failed: {e}")

    console.print(f"\n[bold green]Done.[/bold green] Restart {target.label} to pick up the tools.")
    if hooks and harness == "claude-code":
        console.print(f"[dim]SessionStart hook installed: {HOOK_COMMAND}[/dim]")
