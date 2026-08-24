"""Tenant-isolation lint.

Custom AST check: inside any module under ``packages/*/repositories/``, the
only allowed entry point into a query is ``self.tenant_query(...)`` or
``cls.tenant_query(...)``. Raw ``select(Model)`` or ``select(...)`` calls in
those modules are a CI failure.

Ruff doesn't ship a plugin API for custom rules in stable yet (the plugin RFC
is still moving), so this module is invoked as a standalone CLI from the
pre-commit hook and from CI. The plan documents this as the long-term home
once ruff exposes plugin entrypoints.

Usage::

    python -m tools.ruff_plugins.tenant_check packages/

Exit code 1 if any violation is found, 0 otherwise.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_GLOB = "packages/*/src/*/repositories/*.py"

ALLOWED_BASENAMES = {"base.py", "__init__.py"}

# Models that have an ``org_id`` column. Raw ``select(Model)`` on these would
# escape tenancy if the caller forgets to add an explicit org filter, so the
# lint flags them. Auth-time models (Org, User, ApiKey, Membership) are
# legitimately tenant-less and excluded here.
TENANT_BOUND_MODELS = {
    "Memory",
    "MemoryLink",
    "Attachment",
    "AttachmentChunk",
    "Session",
    "Conversation",
    "Message",
}


def _select_target_name(call: ast.Call) -> str | None:
    """If this is a ``select(Model)``/``select(Model.col)`` call, return ``Model``."""
    func = call.func
    is_select = (isinstance(func, ast.Name) and func.id == "select") or (
        isinstance(func, ast.Attribute) and func.attr == "select"
    )
    if not is_select:
        return None
    if not call.args:
        return None
    arg = call.args[0]
    if isinstance(arg, ast.Name):
        return arg.id
    if isinstance(arg, ast.Attribute) and isinstance(arg.value, ast.Name):
        return arg.value.id
    return None


def check_file(path: Path) -> list[tuple[int, str]]:
    """Return a list of (lineno, message) violations."""
    if path.name in ALLOWED_BASENAMES:
        return []
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as e:  # pragma: no cover - syntax errors fail upstream
        return [(e.lineno or 1, f"syntax error: {e.msg}")]

    lines = source.splitlines()
    violations: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = _select_target_name(node)
        if target is None or target not in TENANT_BOUND_MODELS:
            continue
        line = lines[node.lineno - 1] if 0 < node.lineno <= len(lines) else ""
        if "tenancy: ok" in line:
            continue
        violations.append(
            (
                node.lineno,
                f"raw select({target}) — use BaseRepository.tenant_query() "
                "(or add `# tenancy: ok` with reason if intentional)",
            )
        )
    return violations


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    root = Path(args[0] if args else ".")
    files = list(root.glob(REPO_GLOB))
    failed = False
    for path in files:
        for lineno, msg in check_file(path):
            print(f"{path}:{lineno}: {msg}")
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
