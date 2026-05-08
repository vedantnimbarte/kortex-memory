"""CLI output helpers."""

from __future__ import annotations

import json
from typing import Any

from rich.console import Console
from rich.table import Table

console = Console()


def print_obj(obj: Any, *, json_output: bool = False) -> None:
    if json_output:
        console.print_json(json.dumps(obj, default=str))
        return
    if isinstance(obj, list):
        if not obj:
            console.print("[dim](no rows)[/dim]")
            return
        keys = list(obj[0].keys())
        table = Table(*keys, show_lines=False)
        for row in obj:
            table.add_row(*(str(row.get(k, "")) for k in keys))
        console.print(table)
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            console.print(f"[bold]{k}[/bold]: {v}")
        return
    console.print(str(obj))


def fail(msg: str) -> None:
    console.print(f"[red]error:[/red] {msg}")
    raise SystemExit(1)
