"""Declarative base with stable constraint naming for autogen migrations."""

from __future__ import annotations

from typing import Any

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

naming_convention: dict[str, str] = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=naming_convention)

    # ``TimestampMixin.updated_at`` uses ``onupdate=func.now()`` — a SQL
    # expression the ORM cannot evaluate client-side, so after any UPDATE it
    # marks the attribute expired. Reading it then triggers a lazy refresh,
    # which under asyncio raises MissingGreenlet: sync IO in an async context.
    #
    # That made every async path that serialises a just-updated row fail —
    # MCP `end_session` and `update_memory` among them. `eager_defaults` makes
    # Postgres return the generated value with the UPDATE itself (RETURNING),
    # so the attribute is never expired and the database stays the single
    # clock source for both timestamps.
    __mapper_args__: dict[str, Any] = {"eager_defaults": True}  # noqa: RUF012
