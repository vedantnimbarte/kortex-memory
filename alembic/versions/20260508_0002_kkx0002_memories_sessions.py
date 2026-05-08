"""sessions, conversations, messages, memories, memory_links (M2)

Revision ID: kkx0002
Revises: kkx0001
Create Date: 2026-05-08
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "kkx0002"
down_revision: str | None = "kkx0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- enums ---
    op.execute(
        "CREATE TYPE agent_kind AS ENUM "
        "('claude_code','codex','opencode','web','api','other')"
    )
    op.execute(
        "CREATE TYPE message_role AS ENUM ('user','assistant','system','tool')"
    )
    op.execute(
        "CREATE TYPE memory_tier AS ENUM ('short','mid','long')"
    )
    op.execute(
        "CREATE TYPE sensitivity AS ENUM "
        "('public','internal','confidential','secret')"
    )
    op.execute(
        "CREATE TYPE memory_kind AS ENUM "
        "('fact','preference','decision','procedure','code_artifact','event','summary')"
    )
    op.execute(
        "CREATE TYPE memory_source AS ENUM "
        "('message','document','derived','manual','tool_output')"
    )
    op.execute(
        "CREATE TYPE memory_link_type AS ENUM "
        "('related','derived_from','supersedes','contradicts','part_of')"
    )

    # --- sessions ---
    op.create_table(
        "sessions",
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
            "project_id",
            sa.BigInteger(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent_kind",
            postgresql.ENUM(
                "claude_code", "codex", "opencode", "web", "api", "other",
                name="agent_kind", create_type=False,
            ),
            nullable=False,
            server_default="other",
        ),
        sa.Column("title", sa.String(200), nullable=False, server_default=""),
        sa.Column(
            "client_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
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
        "ix_sessions_org_project", "sessions", ["org_id", "project_id"]
    )

    # --- conversations ---
    op.create_table(
        "conversations",
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
            "session_id",
            sa.BigInteger(),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(200), nullable=False, server_default=""),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("summary_embedding", Vector(1024), nullable=True),
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
    op.create_index("ix_conversations_session_id", "conversations", ["session_id"])

    # --- messages ---
    op.create_table(
        "messages",
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
            "conversation_id",
            sa.BigInteger(),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "role",
            postgresql.ENUM(
                "user", "assistant", "system", "tool",
                name="message_role", create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("content_tokens", sa.Integer(), nullable=True),
        sa.Column("tool_name", sa.String(128), nullable=True),
        sa.Column("tool_input", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("tool_output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_messages_conversation_created", "messages", ["conversation_id", "created_at"]
    )

    # --- memories ---
    op.create_table(
        "memories",
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
        sa.Column(
            "source_type",
            postgresql.ENUM(
                "message", "document", "derived", "manual", "tool_output",
                name="memory_source", create_type=False,
            ),
            nullable=False,
            server_default="manual",
        ),
        sa.Column("source_ref", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "kind",
            postgresql.ENUM(
                "fact", "preference", "decision", "procedure",
                "code_artifact", "event", "summary",
                name="memory_kind", create_type=False,
            ),
            nullable=False,
            server_default="fact",
        ),
        sa.Column("title", sa.String(500), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("body_tokens", sa.Integer(), nullable=True),
        sa.Column(
            "tier",
            postgresql.ENUM(
                "short", "mid", "long", name="memory_tier", create_type=False
            ),
            nullable=False,
            server_default="short",
        ),
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
            "importance",
            sa.Float(),
            nullable=False,
            server_default=sa.text("0.5"),
        ),
        sa.Column(
            "pinned", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "access_count", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "decay_score", sa.Float(), nullable=False, server_default=sa.text("1.0")
        ),
        sa.Column("embedding", Vector(1024), nullable=True),
        sa.Column("embedding_model", sa.String(128), nullable=True),
        sa.Column(
            "tsv",
            postgresql.TSVECTOR(),
            sa.Computed(
                "to_tsvector('english', coalesce(title,'') || ' ' || coalesce(body,''))",
                persisted=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
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
        "ix_memories_tenant",
        "memories",
        ["org_id", "scope_type", "scope_id", "deleted_at"],
    )
    op.create_index("ix_memories_tier_decay", "memories", ["tier", "decay_score"])
    op.create_index(
        "ix_memories_expires_at",
        "memories",
        ["expires_at"],
        postgresql_where=sa.text("expires_at IS NOT NULL"),
    )
    # Vector + FTS + trigram indexes (raw SQL for HNSW config).
    op.execute(
        "CREATE INDEX ix_memories_embedding_hnsw ON memories "
        "USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )
    op.execute("CREATE INDEX ix_memories_tsv_gin ON memories USING gin (tsv)")
    op.execute(
        "CREATE INDEX ix_memories_body_trgm ON memories "
        "USING gin (body gin_trgm_ops)"
    )

    # --- memory_links ---
    op.create_table(
        "memory_links",
        sa.Column(
            "from_memory_id",
            sa.BigInteger(),
            sa.ForeignKey("memories.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "to_memory_id",
            sa.BigInteger(),
            sa.ForeignKey("memories.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "link_type",
            postgresql.ENUM(
                "related", "derived_from", "supersedes", "contradicts", "part_of",
                name="memory_link_type", create_type=False,
            ),
            primary_key=True,
            server_default="related",
        ),
        sa.Column(
            "weight", sa.Float(), nullable=False, server_default=sa.text("1.0")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_memory_links_to", "memory_links", ["to_memory_id"])


def downgrade() -> None:
    op.drop_table("memory_links")
    op.execute("DROP INDEX IF EXISTS ix_memories_body_trgm")
    op.execute("DROP INDEX IF EXISTS ix_memories_tsv_gin")
    op.execute("DROP INDEX IF EXISTS ix_memories_embedding_hnsw")
    op.drop_table("memories")
    op.drop_table("messages")
    op.drop_table("conversations")
    op.drop_table("sessions")
    for t in (
        "memory_link_type",
        "memory_source",
        "memory_kind",
        "sensitivity",
        "memory_tier",
        "message_role",
        "agent_kind",
    ):
        op.execute(f"DROP TYPE IF EXISTS {t}")
