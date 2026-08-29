"""``kortex doctor`` — prove the write path actually works, end to end.

Every other check in this repo answers "is the process up?". This one answers
the question that matters to someone using Kortex: **if I remember something,
can I find it again?** Between those two lies the API, the database, Celery,
the embedder, and vector search — and the failure mode we care about is the
quiet one, where `remember` returns 201 and the memory never becomes
searchable.

So the last check writes a real memory, waits for it to be embedded, searches
for it, and deletes it. Exit code is non-zero if anything fails, which makes
this usable as a deploy gate or a cron canary.
"""

from __future__ import annotations

import time
import uuid
from typing import Annotated, Any

import httpx
import typer
from rich.console import Console
from rich.table import Table

from kortex_cli.client import ApiClient, CliApiError
from kortex_cli.config import get_profile

console = Console()

app = typer.Typer(help="Diagnose a Kortex install.", no_args_is_help=False)

OK = "[green]ok[/green]"
WARN = "[yellow]warn[/yellow]"
FAIL = "[red]fail[/red]"


class Report:
    """Collected check results. Warnings inform; only failures set the exit code."""

    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str]] = []
        self.failed = 0

    def add(self, name: str, status: str, detail: str = "") -> None:
        self.rows.append((name, status, detail))
        if status == FAIL:
            self.failed += 1

    def render(self) -> None:
        table = Table("check", "status", "detail", show_lines=False)
        for name, status, detail in self.rows:
            table.add_row(name, status, detail)
        console.print(table)


def _check_api(client: ApiClient, report: Report) -> dict[str, Any] | None:
    profile = get_profile()
    try:
        who = client.get("/v1/auth/whoami")
    except CliApiError as e:
        report.add("credentials", FAIL, f"rejected ({e.status}) — run `kortex auth login`")
        return None
    except httpx.HTTPError as e:
        report.add("api reachable", FAIL, f"{profile.api_url}: {e}")
        return None
    report.add("api reachable", OK, profile.api_url)
    report.add("credentials", OK, str(who.get("email") or who.get("actor_kind", "")))
    return dict(who)


def _check_ingest(client: ApiClient, report: Report, *, max_pending_age: float) -> None:
    try:
        status = client.get("/v1/admin/ingest-status")
    except CliApiError as e:
        report.add("write path", WARN, f"ingest-status unavailable ({e.status})")
        return

    failed = int(status.get("failed", 0))
    pending = int(status.get("pending", 0))
    oldest = float(status.get("oldest_pending_seconds", 0.0))

    if failed:
        first = (status.get("recent_failures") or [{}])[0]
        report.add(
            "embeddings parked",
            FAIL,
            f"{failed} failed after {status.get('max_attempts')} attempts; "
            f"e.g. {first.get('error', '')[:60]} — `kortex admin retry-embeddings`",
        )
    else:
        report.add("embeddings parked", OK, "none")

    if pending and oldest > max_pending_age:
        report.add(
            "embedding backlog",
            FAIL,
            f"{pending} pending, oldest {oldest:.0f}s — is the worker running?",
        )
    else:
        report.add("embedding backlog", OK, f"{pending} pending")


def _check_round_trip(
    client: ApiClient, report: Report, *, timeout: float, who: dict[str, Any]
) -> None:
    """Write → embed → search → delete, against a real scope.

    An api key is bound to one scope and holds a role there and nowhere else,
    so the canary has to be written into *that* scope — picking the first
    workspace instead denies a project-scoped key on its own install.
    """
    scope_type, scope_id = who.get("scope_type"), who.get("scope_id")
    if not scope_type:
        workspaces = client.get("/v1/workspaces") or []
        if not workspaces:
            report.add("round trip", WARN, "no workspace to write into")
            return
        scope_type, scope_id = "workspace", workspaces[0]["id"]

    marker = f"kortex-doctor-{uuid.uuid4().hex[:12]}"
    created = client.post(
        "/v1/memories",
        json={
            "scope_type": scope_type,
            "scope_id": scope_id,
            "title": "kortex doctor canary",
            "body": f"Canary {marker}. Safe to delete.",
            "kind": "event",
        },
    )
    public_id = created["public_id"]
    try:
        report.add("write", OK, f"created {public_id}")

        deadline = time.monotonic() + timeout
        state = created.get("embedding_state", "pending")
        while state == "pending" and time.monotonic() < deadline:
            time.sleep(2.0)
            state = client.get(f"/v1/memories/{public_id}").get("embedding_state", "pending")

        if state == "ok":
            report.add("embed", OK, "canary embedded")
        elif state == "failed":
            report.add("embed", FAIL, "canary failed to embed — check the worker's embedder")
            return
        else:
            report.add(
                "embed",
                FAIL,
                f"still pending after {timeout:.0f}s — worker down, or embedder still warming",
            )
            return

        hits = client.post("/v1/search", json={"query": marker, "limit": 5}).get("hits", [])
        if any(h["public_id"] == public_id for h in hits):
            report.add("search", OK, "canary retrievable")
        else:
            report.add("search", FAIL, "canary embedded but not returned by search")
    finally:
        try:
            client.delete(f"/v1/memories/{public_id}")
        except CliApiError:
            report.add("cleanup", WARN, f"could not delete canary {public_id}")


@app.callback(invoke_without_command=True)
def doctor(
    ctx: typer.Context,
    timeout: Annotated[
        float, typer.Option(help="Seconds to wait for the canary to be embedded.")
    ] = 90.0,
    max_pending_age: Annotated[
        float, typer.Option(help="Backlog age (seconds) treated as a stalled worker.")
    ] = 600.0,
    skip_round_trip: Annotated[
        bool, typer.Option("--skip-round-trip", help="Checks only; write nothing.")
    ] = False,
) -> None:
    """Check that memories written to this Kortex actually become searchable."""
    if ctx.invoked_subcommand is not None:
        return
    report = Report()
    with ApiClient() as client:
        who = _check_api(client, report)
        if who is None:
            report.render()
            raise typer.Exit(1)
        _check_ingest(client, report, max_pending_age=max_pending_age)
        if not skip_round_trip:
            try:
                _check_round_trip(client, report, timeout=timeout, who=who)
            except CliApiError as e:
                report.add("round trip", FAIL, str(e))

    report.render()
    if report.failed:
        console.print(f"\n[red]{report.failed} check(s) failed.[/red]")
        raise typer.Exit(1)
    console.print("\n[green]All checks passed.[/green]")
