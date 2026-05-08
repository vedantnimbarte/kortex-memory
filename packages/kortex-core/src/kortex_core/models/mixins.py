"""Reusable model mixins."""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column


def _new_public_id() -> uuid.UUID:
    return uuid.uuid4()


class TimestampMixin:
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SoftDeleteMixin:
    deleted_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )


class PublicIdMixin:
    """External-facing UUID4. Indexed but not unique-by-default; subclasses can add."""

    public_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        default=_new_public_id,
        nullable=False,
        unique=True,
        index=True,
    )
