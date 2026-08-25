"""Org / Workspace / Project schemas."""

from __future__ import annotations

from typing import Literal

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


class ProjectReviewIn(APIModel):
    review_mode: Literal["off", "low_confidence", "all"]


class ProjectTextSearchIn(APIModel):
    text_search_config: str = Field(min_length=1, max_length=64, pattern=r"^[a-z_][a-z0-9_]*$")
    """A Postgres text-search configuration name: ``english``, ``french``,
    ``simple``, and so on. Checked against the ones this server actually has
    before it is stored -- an unrecognised name would make every subsequent
    search in the project raise rather than return nothing."""


class ProjectOut(TimestampedOut):
    id: int
    slug: str
    name: str
    review_mode: str = "off"
    """Whether writes here wait for a human: off, low_confidence, or all."""
    text_search_config: str = "english"
    """Postgres text-search configuration used to stem this project's text."""
