"""memories.conflict_checked_at (contradiction surfacing)

Adds the queue marker the conflict-detection worker drains, plus a partial
index so its every-minute scan never touches the table when the queue is empty.

Existing rows are left NULL, which enqueues the whole back catalogue for a
one-time pass. That is intentional — the backfill is rate-limited by
``conflict_batch_size`` and the per-org daily quota, so it drains gradually
instead of billing an entire corpus to the LLM at once.

The index is created CONCURRENTLY: ``memories`` is the hot table, and a plain
CREATE INDEX takes an ACCESS EXCLUSIVE lock for the duration of the build.
That requires running outside a transaction.

Revision ID: kkx0005
Revises: kkx0004
Create Date: 2026-08-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "kkx0005"
down_revision: str | None = "kkx0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "ix_memories_conflict_pending"


def upgrade() -> None:
    op.add_column(
        "memories",
        sa.Column("conflict_checked_at", sa.DateTime(timezone=True), nullable=True),
    )
    with op.get_context().autocommit_block():
        op.create_index(
            _INDEX,
            "memories",
            ["id"],
            postgresql_where=sa.text(
                "conflict_checked_at IS NULL AND embedding IS NOT NULL AND deleted_at IS NULL"
            ),
            postgresql_concurrently=True,
            if_not_exists=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            _INDEX,
            table_name="memories",
            postgresql_concurrently=True,
            if_exists=True,
        )
    op.drop_column("memories", "conflict_checked_at")
