"""memories embed failure tracking (WU-1.3 — write-path integrity)

Before this, a memory whose embedding failed kept ``embedding IS NULL``
forever: invisible to vector search, retried on every 30s tick, with no
counter, no recorded reason, and no way for the user to find out. These four
columns make that state observable and bounded.

* ``embed_attempts``       — how many times we have tried
* ``embed_error``          — why the last attempt failed
* ``embed_failed_at``      — attempts exhausted; parked, not retried
* ``embed_next_attempt_at``— backoff gate; NULL means eligible now

Existing rows default to zero attempts and NULL everywhere else, which is
exactly "never tried, eligible now" — the correct starting state for a
back catalogue that may contain silently-dropped embeddings.

Indexes are created CONCURRENTLY (``memories`` is the hot table), which
requires running outside a transaction.

Revision ID: kkx0006
Revises: kkx0005
Create Date: 2026-08-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "kkx0006"
down_revision: str | None = "kkx0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FAILED_INDEX = "ix_memories_embed_failed"


def upgrade() -> None:
    op.add_column(
        "memories",
        sa.Column("embed_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("memories", sa.Column("embed_error", sa.Text(), nullable=True))
    op.add_column(
        "memories",
        sa.Column("embed_failed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "memories",
        sa.Column("embed_next_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    with op.get_context().autocommit_block():
        op.create_index(
            _FAILED_INDEX,
            "memories",
            ["embed_failed_at"],
            postgresql_where=sa.text("embed_failed_at IS NOT NULL"),
            postgresql_concurrently=True,
            if_not_exists=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            _FAILED_INDEX,
            table_name="memories",
            postgresql_concurrently=True,
            if_exists=True,
        )
    op.drop_column("memories", "embed_next_attempt_at")
    op.drop_column("memories", "embed_failed_at")
    op.drop_column("memories", "embed_error")
    op.drop_column("memories", "embed_attempts")
