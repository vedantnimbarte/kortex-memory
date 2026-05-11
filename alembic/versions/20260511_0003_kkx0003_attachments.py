"""attachments + attachment_chunks (M4)

Revision ID: kkx0003
Revises: kkx0002
Create Date: 2026-05-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "kkx0003"
down_revision: str | None = "kkx0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE TYPE attachment_status AS ENUM "
        "('pending','processing','ready','failed')"
    )

    op.create_table(
        "attachments",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "public_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            unique=True,
            index=True,
        ),
        sa.Column(
            "org_id",
            sa.BigInteger(),
            sa.ForeignKey("orgs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "scope_type",
            postgresql.ENUM(
                "org", "workspace", "project", "session",
                name="scope_type", create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("scope_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_by",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("filename", sa.String(500), nullable=False, server_default=""),
        sa.Column("mime", sa.String(200), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("sha256", sa.String(64), nullable=True),
        sa.Column("s3_bucket", sa.String(200), nullable=False),
        sa.Column("s3_key", sa.String(500), nullable=False, unique=True),
        sa.Column(
            "sensitivity",
            postgresql.ENUM(
                "public", "internal", "confidential", "secret",
                name="sensitivity", create_type=False,
            ),
            nullable=False,
            server_default="internal",
        ),
        sa.Column(
            "processing_status",
            postgresql.ENUM(
                "pending", "processing", "ready", "failed",
                name="attachment_status", create_type=False,
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("processing_error", sa.Text(), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_attachments_tenant",
        "attachments",
        ["org_id", "scope_type", "scope_id", "deleted_at"],
    )
    op.create_index("ix_attachments_status", "attachments", ["processing_status"])
    op.create_index("ix_attachments_sha256", "attachments", ["sha256"])

    op.create_table(
        "attachment_chunks",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "org_id",
            sa.BigInteger(),
            sa.ForeignKey("orgs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "attachment_id",
            sa.BigInteger(),
            sa.ForeignKey("attachments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_tokens", sa.Integer(), nullable=True),
        sa.Column("embedding", Vector(1024), nullable=True),
        sa.Column("embedding_model", sa.String(128), nullable=True),
        sa.Column(
            "tsv",
            postgresql.TSVECTOR(),
            sa.Computed(
                "to_tsvector('english', coalesce(content,''))", persisted=True
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_attachment_chunks_attachment_idx",
        "attachment_chunks",
        ["attachment_id", "chunk_index"],
        unique=True,
    )
    op.create_index(
        "ix_attachment_chunks_tenant",
        "attachment_chunks",
        ["org_id", "attachment_id"],
    )
    op.execute(
        "CREATE INDEX ix_attachment_chunks_embedding_hnsw "
        "ON attachment_chunks USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )
    op.execute(
        "CREATE INDEX ix_attachment_chunks_tsv_gin "
        "ON attachment_chunks USING gin (tsv)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_attachment_chunks_tsv_gin")
    op.execute("DROP INDEX IF EXISTS ix_attachment_chunks_embedding_hnsw")
    op.drop_table("attachment_chunks")
    op.drop_table("attachments")
    op.execute("DROP TYPE IF EXISTS attachment_status")
