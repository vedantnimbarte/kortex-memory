"""What the audit log records, and where.

The vocabulary lives in one place so a typo'd action string cannot silently
become an audit gap that nobody notices until someone goes looking for an event
that was never written under the name they searched for.

**What is instrumented, and why only this.** Not everything — an audit log that
records every read is a log nobody reads, and the cost is paid on the hot path.
The five categories below are the ones a security reviewer asks about, and they
are the same five regardless of which buyer is asking:

1. **Authentication** — who got in, and who tried and failed.
2. **Authorisation changes** — who was granted or revoked what.
3. **Credential lifecycle** — API keys minted and revoked.
4. **Data egress** — scopes exported, scopes imported.
5. **Destructive and governance actions** — deletions, review decisions,
   retention purges.

Ordinary reads and writes are deliberately absent. They are high-volume, they
are what the product does all day, and recording them would bury the events
above in noise. `memories.access_count` and the memory rows themselves already
say what was stored and what was read.
"""

from __future__ import annotations

import enum


class AuditAction(str, enum.Enum):
    """Every action name the system writes. Nothing writes a literal."""

    # --- authentication ---
    LOGIN = "auth.login"
    LOGIN_FAILED = "auth.login_failed"
    """Recorded with the email attempted and never with the password, not even
    a hash of it: a failed-login log that captures credentials is a credential
    store with a misleading name."""
    LOGOUT = "auth.logout"

    # --- authorisation ---
    MEMBER_INVITED = "member.invited"
    MEMBER_GRANTED = "member.granted"
    MEMBER_REVOKED = "member.revoked"

    # --- credentials ---
    API_KEY_CREATED = "api_key.created"
    API_KEY_REVOKED = "api_key.revoked"

    # --- data egress ---
    SCOPE_EXPORTED = "scope.exported"
    SCOPE_IMPORTED = "scope.imported"

    # --- destructive / governance ---
    MEMORY_DELETED = "memory.deleted"
    MEMORY_REVIEW_APPROVED = "memory.review.approved"
    MEMORY_REVIEW_REJECTED = "memory.review.rejected"
    PROJECT_REVIEW_MODE_CHANGED = "project.review_mode_changed"
    AUDIT_PURGED = "audit.purged"
    """Retention deleting audit entries is itself an audited event, written
    after the delete. A log that can be trimmed without saying so is not a log."""

    def __str__(self) -> str:
        return self.value
