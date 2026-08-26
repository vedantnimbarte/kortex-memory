"""``kortex import`` — bring a corpus over from another memory tool.

The parsers do not write. Records go through the ordinary ``POST /v1/memories``
path, so an imported memory is subject to the same dedup, PII scanning, trust
policy and review gating as anything an agent writes. That is the point: an
import that bypassed governance would be a hole straight through it, and
"we imported it" is not an argument a compliance reviewer accepts.

It also makes the command **idempotent for free** — content-hash dedup is on by
default, so re-running a half-finished import folds the repeats into the
memories already stored instead of doubling them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from kortex_cli.client import ApiClient, CliApiError
from kortex_cli.importers import PARSERS, SourceMemory, UnreadableExportError, parse_file
from kortex_cli.output import console, fail, print_obj

PREVIEW_ROWS = 5


def import_command(
    file: Annotated[Path, typer.Argument(help="The export file (JSON or JSONL)")],
    from_: Annotated[
        str,
        typer.Option("--from", help=f"Source tool: {', '.join(PARSERS)}"),
    ],
    scope_type: Annotated[
        str, typer.Option(help="org | workspace | project | session")
    ] = "project",
    scope_id: Annotated[int, typer.Option()] = 0,
    sensitivity: Annotated[str, typer.Option()] = "internal",
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Parse and show what would be written; write nothing"),
    ] = False,
    limit: Annotated[int, typer.Option(help="Stop after N records; 0 means all")] = 0,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Import memories from mem0, Zep, Letta, or any JSON array.

    Run with ``--dry-run`` first. These formats are not published contracts and
    they move; seeing what the parser made of your file costs one second and
    saves finding out after ten thousand writes.
    """
    if not file.exists():
        fail(f"file not found: {file}")
        return
    try:
        records = parse_file(from_, file.read_text(encoding="utf-8"))
    except UnreadableExportError as e:
        fail(str(e))
        return
    except UnicodeDecodeError:
        fail(f"{file} is not UTF-8 text — is it an archive rather than an export?")
        return

    if limit > 0:
        records = records[:limit]
    if not records:
        fail(f"no importable memories found in {file}")
        return

    if dry_run:
        _preview(records, source=from_, json_output=json_output)
        return

    written, deduped, failed = _write(
        records, scope_type=scope_type, scope_id=scope_id, sensitivity=sensitivity
    )
    print_obj(
        {
            "source": from_,
            "parsed": len(records),
            "created": written,
            "deduped": deduped,
            "failed": failed,
            "scope": f"{scope_type}:{scope_id}",
        },
        json_output=json_output,
    )
    if failed:
        raise SystemExit(1)


def _preview(records: list[SourceMemory], *, source: str, json_output: bool) -> None:
    print_obj(
        {
            "source": source,
            "parsed": len(records),
            "would_write": len(records),
            "dry_run": True,
        },
        json_output=json_output,
    )
    if json_output:
        return
    console.print(f"\n[bold]First {min(PREVIEW_ROWS, len(records))} of {len(records)}:[/bold]")
    for record in records[:PREVIEW_ROWS]:
        body = record.body if len(record.body) <= 160 else record.body[:159] + "…"
        console.print(f"  [dim]{record.kind}[/dim]  {record.title}")
        console.print(f"    {body}")


def _write(
    records: list[SourceMemory],
    *,
    scope_type: str,
    scope_id: int,
    sensitivity: str,
) -> tuple[int, int, int]:
    """Send each record through the normal create path.

    ponytail: one request per memory, sequentially. A 50k-memory import is slow
    — parallelise or add a bulk-create endpoint if that becomes a real
    complaint. It is deliberately not clever today: the server dedups, so a
    failed run is safe to simply re-run, and that property is worth more than
    throughput to someone migrating their corpus for the first time.
    """
    written = deduped = failed = 0
    with ApiClient() as client:
        for record in records:
            payload = {
                "scope_type": scope_type,
                "scope_id": scope_id,
                "body": record.body,
                "title": record.title,
                "kind": record.kind,
                "sensitivity": sensitivity,
                # `derived`, not `manual`: a human did not write this, another
                # system did, and provenance is what the trust policy reads.
                "source_type": "derived",
                "source_ref": {"importer": record.metadata.get("imported_from", "json")}
                | ({"source_id": record.source_id} if record.source_id else {}),
                "metadata": record.metadata,
            }
            try:
                result = client.post("/v1/memories", json=payload)
            except CliApiError as e:
                failed += 1
                console.print(f"[yellow]skipped[/yellow] {record.title[:60]}: {e}")
                continue
            if isinstance(result, dict) and result.get("deduped"):
                deduped += 1
            else:
                written += 1
    return written, deduped, failed
