"""Shared SQLAlchemy types and enums."""

from __future__ import annotations

import enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pgvector.sqlalchemy import Vector

try:  # runtime import; pgvector is required at runtime, optional for type checkers
    from pgvector.sqlalchemy import Vector as _PgVector
except ImportError:  # pragma: no cover - dev environments without pgvector
    _PgVector = None  # type: ignore[assignment,misc]


class ScopeType(str, enum.Enum):
    """Polymorphic scope reference. The scope_id column is interpreted by this."""

    ORG = "org"
    WORKSPACE = "workspace"
    PROJECT = "project"
    SESSION = "session"


class Role(str, enum.Enum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class Sensitivity(str, enum.Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    SECRET = "secret"


class MemoryTier(str, enum.Enum):
    SHORT = "short"
    MID = "mid"
    LONG = "long"


class MemoryKind(str, enum.Enum):
    FACT = "fact"
    PREFERENCE = "preference"
    DECISION = "decision"
    PROCEDURE = "procedure"
    CODE_ARTIFACT = "code_artifact"
    EVENT = "event"
    SUMMARY = "summary"


class MemorySource(str, enum.Enum):
    MESSAGE = "message"
    DOCUMENT = "document"
    DERIVED = "derived"
    MANUAL = "manual"
    TOOL_OUTPUT = "tool_output"


class MemoryTrust(str, enum.Enum):
    """Provenance-derived confidence. Distinct from sensitivity, which governs
    who may read a memory rather than whether it should be believed."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ReviewStatus(str, enum.Enum):
    """Whether a memory is visible to recall.

    Only ``approved`` is retrievable. ``pending`` covers both held-for-quality
    and held-for-suspicion, because the outcome is identical and two exclusion
    filters would be two things to keep in step.
    """

    APPROVED = "approved"
    PENDING = "pending"
    REJECTED = "rejected"


class ReviewMode(str, enum.Enum):
    """Per-project gating. ``off`` is the default: a memory layer that makes
    every fact wait on a human is not solving the problem it exists for."""

    OFF = "off"
    LOW_CONFIDENCE = "low_confidence"
    ALL = "all"


class MemoryLinkType(str, enum.Enum):
    RELATED = "related"
    DERIVED_FROM = "derived_from"
    SUPERSEDES = "supersedes"
    CONTRADICTS = "contradicts"
    PART_OF = "part_of"


class AttachmentStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class AgentKind(str, enum.Enum):
    CLAUDE_CODE = "claude_code"
    CODEX = "codex"
    OPENCODE = "opencode"
    WEB = "web"
    API = "api"
    OTHER = "other"


class MessageRole(str, enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class ActorKind(str, enum.Enum):
    USER = "user"
    API_KEY = "api_key"
    SYSTEM = "system"


# 1024-dim vector alias for the default BGE-large embedding dimension.
def Vector1024() -> Vector:  # noqa: N802 (factory-style alias)
    if _PgVector is None:
        raise RuntimeError("pgvector not installed")
    return _PgVector(1024)


class ULIDType:
    """Marker for ULID-encoded UUID columns. Kept as a type alias for clarity."""
