"""Org, Workspace, Project."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from kortex_core.db.base import Base
from kortex_core.models.mixins import PublicIdMixin, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from kortex_core.models.api_key import ApiKey


class Org(Base, PublicIdMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "orgs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    plan: Mapped[str] = mapped_column(String(32), nullable=False, default="free")
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    workspaces: Mapped[list[Workspace]] = relationship(
        back_populates="org", cascade="all, delete-orphan"
    )
    api_keys: Mapped[list[ApiKey]] = relationship(
        back_populates="org", cascade="all, delete-orphan"
    )


class Workspace(Base, PublicIdMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "workspaces"
    __table_args__ = (
        UniqueConstraint("org_id", "slug", name="uq_workspaces_org_slug"),
        Index("ix_workspaces_org_id", "org_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    org_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False
    )
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    org: Mapped[Org] = relationship(back_populates="workspaces")
    projects: Mapped[list[Project]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )


class Project(Base, PublicIdMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("workspace_id", "slug", name="uq_projects_workspace_slug"),
        Index("ix_projects_org_workspace", "org_id", "workspace_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    org_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False
    )
    workspace_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    settings: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    workspace: Mapped[Workspace] = relationship(back_populates="projects")
