"""tamper-evident audit log (WU-3.1 — audit export)

Two independent mechanisms, because they fail in different ways.

**Prevention** is a trigger that refuses UPDATE outright and refuses DELETE
unless the session has opted in via ``SET LOCAL kortex.audit_purge = 'on'``.
That stops an accidental ``DELETE FROM audit_log`` and an ORM bug, which is
what actually destroys audit trails in practice. It does not stop a determined
superuser, who can drop the trigger.

**Detection** is a hash chain: every row carries the digest of its own content
plus the previous row's digest, per org. A tampered or removed row breaks the
chain from that point on, and the break is visible even to someone who did the
tampering with full database rights — provided the head digest was recorded
somewhere they do not control. That is the point of exporting it.

Neither is worth much alone. A trigger without a chain is a lock on a door
whose owner has the key; a chain without a trigger detects damage that a
constraint could have prevented.

Revision ID: kkx0011
Revises: kkx0010
Create Date: 2026-08-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "kkx0011"
down_revision: str | None = "kkx0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GUARD = """
CREATE OR REPLACE FUNCTION kortex_audit_log_guard() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'audit_log is append-only: UPDATE is not permitted';
    END IF;
    -- Retention still has to be able to delete. The opt-in is session-local so
    -- it cannot leak past the transaction that set it.
    IF current_setting('kortex.audit_purge', true) IS DISTINCT FROM 'on' THEN
        RAISE EXCEPTION
            'audit_log is append-only: DELETE requires kortex.audit_purge';
    END IF;
    RETURN OLD;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    op.add_column("audit_log", sa.Column("entry_hash", sa.String(length=64), nullable=True))
    op.add_column("audit_log", sa.Column("prev_hash", sa.String(length=64), nullable=True))
    # Nullable, not backfilled: rows written before this migration were never
    # chained, and inventing digests for them would assert an integrity
    # guarantee that did not exist. The verifier reports them as unchained.
    op.create_index(
        "ix_audit_log_org_id_desc",
        "audit_log",
        ["org_id", sa.text("id DESC")],
    )
    op.execute(sa.text(GUARD))
    op.execute(
        sa.text(
            "CREATE TRIGGER audit_log_append_only "
            "BEFORE UPDATE OR DELETE ON audit_log "
            "FOR EACH ROW EXECUTE FUNCTION kortex_audit_log_guard()"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP TRIGGER IF EXISTS audit_log_append_only ON audit_log"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS kortex_audit_log_guard()"))
    op.drop_index("ix_audit_log_org_id_desc", table_name="audit_log")
    op.drop_column("audit_log", "prev_hash")
    op.drop_column("audit_log", "entry_hash")
