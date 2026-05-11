"""Unit test for the tenant_check ruff plugin AST scan."""

from __future__ import annotations

from pathlib import Path

from tools.ruff_plugins.tenant_check import check_file


def _write(tmp_path: Path, name: str, source: str) -> Path:
    f = tmp_path / name
    f.write_text(source, encoding="utf-8")
    return f


def test_flags_raw_select_on_tenant_bound_model(tmp_path: Path) -> None:
    f = _write(
        tmp_path,
        "leaky_repo.py",
        "from sqlalchemy import select\n"
        "from kortex_core.models.memory import Memory\n"
        "async def bad(session):\n"
        "    stmt = select(Memory).where(Memory.id == 1)\n"
        "    return await session.execute(stmt)\n",
    )
    violations = check_file(f)
    assert any("select(Memory)" in v[1] for v in violations)


def test_ignores_marker_comment(tmp_path: Path) -> None:
    f = _write(
        tmp_path,
        "exempt_repo.py",
        "from sqlalchemy import select\n"
        "from kortex_core.models.memory import Memory\n"
        "async def bypass(session):\n"
        "    stmt = select(Memory)  # tenancy: ok — worker fan-out\n"
        "    return await session.execute(stmt)\n",
    )
    assert check_file(f) == []


def test_does_not_flag_auth_time_models(tmp_path: Path) -> None:
    f = _write(
        tmp_path,
        "user_repo.py",
        "from sqlalchemy import select\n"
        "from kortex_core.models.user import User\n"
        "async def lookup(session, email):\n"
        "    stmt = select(User).where(User.email == email)\n"
        "    return await session.execute(stmt)\n",
    )
    assert check_file(f) == []


def test_skips_base_and_init(tmp_path: Path) -> None:
    f = _write(tmp_path, "base.py", "from sqlalchemy import select; select(Memory)\n")
    assert check_file(f) == []
