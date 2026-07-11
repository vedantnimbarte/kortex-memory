"""Org / Workspace / Project schemas."""

from __future__ import annotations

from pydantic import Field

from kortex_api.schemas.common import APIModel, TimestampedOut


class OrgIn(APIModel):
    slug: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9][a-z0-9\-]*$")
    name: str = Field(min_length=1, max_length=200)
    plan: str = "free"


class OrgOut(TimestampedOut):
    # Internal scope id: scoped ops (search, memory, ingest) key on it, and it's
    # already exposed via MemoryOut.scope_id / whoami.org_id.
    id: int
    slug: str
    name: str
    plan: str


class WorkspaceIn(APIModel):
    slug: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9][a-z0-9\-]*$")
    name: str = Field(min_length=1, max_length=200)


class WorkspaceOut(TimestampedOut):
    id: int
    slug: str
    name: str


class ProjectIn(APIModel):
    slug: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9][a-z0-9\-]*$")
    name: str = Field(min_length=1, max_length=200)


class ProjectOut(TimestampedOut):
    id: int
    slug: str
    name: str
