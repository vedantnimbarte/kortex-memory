"""per-project text search configuration (multilingual)

Keyword search was hardcoded to English in three places: the ``tsv`` generated
columns on ``memories`` and ``attachment_chunks``, and every
``plainto_tsquery('english', …)`` in the repository. A French or Japanese
corpus was stemmed with English rules, so search still returned *something* —
which is the worst failure mode, because nothing looks broken.

**This is the riskiest migration in the plan.** It drops and recreates a
generated column on the largest table, which rewrites it, and rebuilds the GIN
index over it. On an empty database that is instant; on a large one it is a
full table rewrite holding ACCESS EXCLUSIVE. Read the runbook before running
it against real data.

The design turns on one Postgres detail: ``to_tsvector(regconfig, text)`` is
IMMUTABLE and so may drive a generated column, while
``to_tsvector(text::regconfig, text)`` is not, because the cast performs a
catalog lookup. Storing the configuration in a ``regconfig``-typed column is
therefore what lets the tsvector stay generated instead of needing a trigger.

The column is denormalised onto each row because a generation expression may
only reference its own row; ``projects.text_search_config`` remains the source
of truth, and changing it rewrites the rows in that scope.

Revision ID: kkx0010
Revises: kkx0009
Create Date: 2026-08-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "kkx0010"
down_revision: str | None = "kkx0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _swap_tsv(table: str, expression: str, index: str) -> None:
    """Rebuild a generated tsvector column against the row's own configuration.

    Postgres 16 has no ``ALTER COLUMN … SET EXPRESSION`` (that arrives in 17),
    so the column has to be dropped and re-added. The index goes with it and is
    rebuilt afterwards.
    """
    op.execute(sa.text(f"DROP INDEX IF EXISTS {index}"))
    op.drop_column(table, "tsv")
    op.execute(
        sa.text(
            f"ALTER TABLE {table} ADD COLUMN tsv tsvector "
            f"GENERATED ALWAYS AS ({expression}) STORED"
        )
    )
    op.execute(sa.text(f"CREATE INDEX {index} ON {table} USING gin (tsv)"))


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "text_search_config", sa.String(length=64), nullable=False, server_default="english"
        ),
    )
    for table in ("memories", "attachment_chunks"):
        op.execute(
            sa.text(
                f"ALTER TABLE {table} ADD COLUMN ts_config regconfig "
                f"NOT NULL DEFAULT 'english'::regconfig"
            )
        )

    _swap_tsv(
        "memories",
        "to_tsvector(ts_config, coalesce(title,'') || ' ' || coalesce(body,''))",
        "ix_memories_tsv_gin",
    )
    _swap_tsv(
        "attachment_chunks",
        "to_tsvector(ts_config, coalesce(content,''))",
        "ix_attachment_chunks_tsv_gin",
    )


def downgrade() -> None:
    _swap_tsv(
        "memories",
        "to_tsvector('english', coalesce(title,'') || ' ' || coalesce(body,''))",
        "ix_memories_tsv_gin",
    )
    _swap_tsv(
        "attachment_chunks",
        "to_tsvector('english', coalesce(content,''))",
        "ix_attachment_chunks_tsv_gin",
    )
    for table in ("memories", "attachment_chunks"):
        op.drop_column(table, "ts_config")
    op.drop_column("projects", "text_search_config")
