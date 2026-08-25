"""review queue: unify quarantine into one held state (WU-2.3)

kkx0008 gave suspicious memories their own hold (``quarantined_at``). Adding a
second hold for low-confidence writes would mean two exclusion filters to keep
in step and two inboxes to remember to check — and a governance control nobody
checks is worse than none, because it looks like coverage.

So both collapse into ``review_status``. From a memory's point of view the
outcome was always identical: stored, invisible to recall, waiting on a person.
Only *why* differs, and that is what ``review_reason`` is for.

Existing quarantined rows carry over as ``pending`` with their reason intact;
everything else becomes ``approved``, which is the pre-existing behaviour.
``projects.review_mode`` defaults to ``off`` — a memory layer that makes every
fact wait on a human is not solving the problem it exists for.

Revision ID: kkx0009
Revises: kkx0008
Create Date: 2026-08-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "kkx0009"
down_revision: str | None = "kkx0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_INDEX = "ix_memories_quarantined"
_NEW_INDEX = "ix_memories_review_pending"


def upgrade() -> None:
    postgresql.ENUM("approved", "pending", "rejected", name="review_status").create(
        op.get_bind(), checkfirst=True
    )
    postgresql.ENUM("off", "low_confidence", "all", name="review_mode").create(
        op.get_bind(), checkfirst=True
    )

    op.add_column(
        "memories",
        sa.Column(
            "review_status",
            postgresql.ENUM(
                "approved", "pending", "rejected", name="review_status", create_type=False
            ),
            nullable=False,
            server_default="approved",
        ),
    )
    op.add_column("memories", sa.Column("review_reason", sa.String(length=200), nullable=True))
    op.add_column("memories", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "memories",
        sa.Column(
            "reviewed_by",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column("memories", sa.Column("confidence", sa.Float(), nullable=True))

    # Carry the quarantine hold over rather than releasing it: these are the
    # rows a reviewer has not yet looked at, and dropping the flag would put
    # suspected injections straight back into recall.
    op.execute(
        sa.text(
            "UPDATE memories SET review_status = 'pending', review_reason = quarantine_reason "
            "WHERE quarantined_at IS NOT NULL"
        )
    )

    op.add_column(
        "projects",
        sa.Column(
            "review_mode",
            postgresql.ENUM("off", "low_confidence", "all", name="review_mode", create_type=False),
            nullable=False,
            server_default="off",
        ),
    )

    with op.get_context().autocommit_block():
        op.create_index(
            _NEW_INDEX,
            "memories",
            ["org_id", "review_status"],
            postgresql_where=sa.text("review_status = 'pending'"),
            postgresql_concurrently=True,
            if_not_exists=True,
        )
        op.drop_index(
            _OLD_INDEX, table_name="memories", postgresql_concurrently=True, if_exists=True
        )

    op.drop_column("memories", "quarantine_reason")
    op.drop_column("memories", "quarantined_at")


def downgrade() -> None:
    op.add_column(
        "memories", sa.Column("quarantined_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("memories", sa.Column("quarantine_reason", sa.String(length=200), nullable=True))
    op.execute(
        sa.text(
            "UPDATE memories SET quarantined_at = COALESCE(reviewed_at, now()), "
            "quarantine_reason = review_reason WHERE review_status = 'pending'"
        )
    )
    with op.get_context().autocommit_block():
        op.create_index(
            _OLD_INDEX,
            "memories",
            ["org_id", "quarantined_at"],
            postgresql_where=sa.text("quarantined_at IS NOT NULL"),
            postgresql_concurrently=True,
            if_not_exists=True,
        )
        op.drop_index(
            _NEW_INDEX, table_name="memories", postgresql_concurrently=True, if_exists=True
        )
    op.drop_column("projects", "review_mode")
    op.drop_column("memories", "confidence")
    op.drop_column("memories", "reviewed_by")
    op.drop_column("memories", "reviewed_at")
    op.drop_column("memories", "review_reason")
    op.drop_column("memories", "review_status")
    postgresql.ENUM(name="review_mode").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="review_status").drop(op.get_bind(), checkfirst=True)
