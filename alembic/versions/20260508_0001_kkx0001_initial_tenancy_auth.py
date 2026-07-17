"""initial tenancy + auth schema (M1)

Revision ID: kkx0001
Revises:
Create Date: 2026-05-08

Creates extensions, enum types, and the M1 tables: orgs, workspaces, projects,
users, memberships, api_keys, jwt_revocations, audit_log.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "kkx0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- extensions ---
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    # --- enums ---
    op.execute(
        "CREATE TYPE scope_type AS ENUM ('org','workspace','project','session')"
    )
    op.execute("CREATE TYPE role AS ENUM ('owner','admin','member','viewer')")
    op.execute("CREATE TYPE actor_kind AS ENUM ('user','api_key','system')")

    # --- orgs ---
    op.create_table(
        "orgs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "public_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            unique=True,
            index=True,
        ),
        sa.Column("slug", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("plan", sa.String(32), nullable=False, server_default="free"),
        sa.Column(
            "settings",
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
    op.create_index("ix_orgs_deleted_at", "orgs", ["deleted_at"])

    # --- workspaces ---
    op.create_table(
        "workspaces",
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
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column(
            "settings",
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
        sa.UniqueConstraint("org_id", "slug", name="uq_workspaces_org_slug"),
    )
    op.create_index("ix_workspaces_org_id", "workspaces", ["org_id"])
    op.create_index("ix_workspaces_deleted_at", "workspaces", ["deleted_at"])

    # --- projects ---
    op.create_table(
        "projects",
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
            "workspace_id",
            sa.BigInteger(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column(
            "settings",
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
        sa.UniqueConstraint("workspace_id", "slug", name="uq_projects_workspace_slug"),
    )
    op.create_index(
        "ix_projects_org_workspace", "projects", ["org_id", "workspace_id"]
    )
    op.create_index("ix_projects_deleted_at", "projects", ["deleted_at"])

    # --- users ---
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "public_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            unique=True,
            index=True,
        ),
        sa.Column(
            "email",
            postgresql.CITEXT(),
            nullable=False,
            unique=True,
            index=True,
        ),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("display_name", sa.String(200), nullable=False, server_default=""),
        sa.Column(
            "is_superuser",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
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
    op.create_index("ix_users_deleted_at", "users", ["deleted_at"])

    # --- memberships ---
    op.create_table(
        "memberships",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "scope_type",
            postgresql.ENUM(
                "org",
                "workspace",
                "project",
                "session",
                name="scope_type",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("scope_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "role",
            postgresql.ENUM(
                "owner", "admin", "member", "viewer", name="role", create_type=False
            ),
            nullable=False,
            server_default="member",
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
        sa.UniqueConstraint(
            "user_id", "scope_type", "scope_id", name="uq_memberships_user_scope"
        ),
    )
    op.create_index("ix_memberships_scope", "memberships", ["scope_type", "scope_id"])
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])

    # --- api_keys ---
    op.create_table(
        "api_keys",
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
        sa.Column("prefix", sa.String(8), nullable=False),
        sa.Column("key_hash", sa.String(255), nullable=False),
        sa.Column("name", sa.String(200), nullable=False, server_default=""),
        sa.Column(
            "scope_type",
            postgresql.ENUM(
                "org",
                "workspace",
                "project",
                "session",
                name="scope_type",
                create_type=False,
            ),
            nullable=True,
        ),
        sa.Column("scope_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "scopes",
            postgresql.ARRAY(sa.String(64)),
            nullable=False,
            server_default=sa.text("'{}'::varchar[]"),
        ),
        sa.Column(
            "created_by",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
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
    op.create_index("ix_api_keys_prefix", "api_keys", ["prefix"])
    op.create_index("ix_api_keys_org_active", "api_keys", ["org_id", "revoked_at"])

    # --- jwt_revocations ---
    op.create_table(
        "jwt_revocations",
        sa.Column("jti", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_jwt_revocations_expires_at", "jwt_revocations", ["expires_at"])

    # --- audit_log ---
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "org_id",
            sa.BigInteger(),
            sa.ForeignKey("orgs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "actor_kind",
            postgresql.ENUM(
                "user", "api_key", "system", name="actor_kind", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("actor_id", sa.BigInteger(), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target_type", sa.String(64), nullable=True),
        sa.Column("target_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_audit_log_org_created", "audit_log", ["org_id", "created_at"])
    op.create_index("ix_audit_log_target", "audit_log", ["target_type", "target_id"])


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("jwt_revocations")
    op.drop_table("api_keys")
    op.drop_table("memberships")
    op.drop_table("users")
    op.drop_table("projects")
    op.drop_table("workspaces")
    op.drop_table("orgs")
    op.execute("DROP TYPE IF EXISTS actor_kind")
    op.execute("DROP TYPE IF EXISTS role")
    op.execute("DROP TYPE IF EXISTS scope_type")
