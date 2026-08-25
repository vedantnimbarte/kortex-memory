"""memories.content_hash (WU-2.2 — write-time deduplication)

Fingerprint of the normalised title+body, looked up before every insert so a
verbatim rewrite folds into the existing memory instead of competing with it
for space in the same recall result.

The index is **not** unique. A unique constraint would make the `force` escape
hatch impossible — a caller that deliberately wants a second copy would get an
IntegrityError instead — and would turn the rare concurrent-identical-write
race into a hard failure rather than a duplicate row, which is the behaviour
that already existed. Dedup here is a best-effort lookup, not a guarantee.

Existing rows keep NULL and are exempt: computing the fingerprint needs the
Python normaliser (NFKC folding, whitespace collapse), which SQL cannot
reproduce faithfully. They start participating the next time they are written.
No backfill task ships with this because the back catalogue is small; add one
if that stops being true.

Created CONCURRENTLY — `memories` is the hot table.

Revision ID: kkx0007
Revises: kkx0006
Create Date: 2026-08-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "kkx0007"
down_revision: str | None = "kkx0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "ix_memories_content_hash"


def upgrade() -> None:
    op.add_column("memories", sa.Column("content_hash", sa.String(length=64), nullable=True))
    with op.get_context().autocommit_block():
        op.create_index(
            _INDEX,
            "memories",
            ["org_id", "scope_type", "scope_id", "content_hash"],
            postgresql_where=sa.text("content_hash IS NOT NULL AND deleted_at IS NULL"),
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
    op.drop_column("memories", "content_hash")
