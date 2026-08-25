"""memory governance: trust, pii_flags, quarantine (WU-2.4)

Sensitivity governs who may read a memory. None of the schema said whether a
memory should have been allowed to influence anything — so a sentence scraped
out of a fetched page and a sentence a person wrote were treated identically,
and a stored prompt injection was re-injected into every session that
retrieved it.

* ``trust``            — derived from source_type at write time
* ``pii_flags``        — counts by kind, never the matched values
* ``quarantined_at``   — low-trust content that reads as instructions
* ``quarantine_reason``— which heuristics fired

Existing rows default to ``medium`` trust and no findings. That is the
deliberate choice: back-scanning the corpus would need the detector to run over
every row, and silently reclassifying memories an operator already relies on is
exactly what the ``tag`` default policy exists to avoid. Rows are classified
the next time they are written.

Revision ID: kkx0008
Revises: kkx0007
Create Date: 2026-08-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "kkx0008"
down_revision: str | None = "kkx0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "ix_memories_quarantined"
_ENUM = "memory_trust"


def upgrade() -> None:
    trust = postgresql.ENUM("high", "medium", "low", name=_ENUM)
    trust.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "memories",
        sa.Column(
            "trust",
            postgresql.ENUM("high", "medium", "low", name=_ENUM, create_type=False),
            nullable=False,
            server_default="medium",
        ),
    )
    op.add_column(
        "memories",
        sa.Column(
            "pii_flags",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "memories", sa.Column("quarantined_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "memories", sa.Column("quarantine_reason", sa.String(length=200), nullable=True)
    )
    with op.get_context().autocommit_block():
        op.create_index(
            _INDEX,
            "memories",
            ["org_id", "quarantined_at"],
            postgresql_where=sa.text("quarantined_at IS NOT NULL"),
            postgresql_concurrently=True,
            if_not_exists=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            _INDEX, table_name="memories", postgresql_concurrently=True, if_exists=True
        )
    op.drop_column("memories", "quarantine_reason")
    op.drop_column("memories", "quarantined_at")
    op.drop_column("memories", "pii_flags")
    op.drop_column("memories", "trust")
    postgresql.ENUM(name=_ENUM).drop(op.get_bind(), checkfirst=True)
