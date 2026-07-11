"""Orgs router (superuser-only mutations; reads scoped to principal)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status
from kortex_core.services.org_service import OrgService

from kortex_api.deps import PrincipalDep, SessionDep
from kortex_api.errors import forbidden, not_found
from kortex_api.schemas.org import OrgIn, OrgOut

router = APIRouter(prefix="/v1/orgs", tags=["orgs"])


@router.post("", response_model=OrgOut, status_code=status.HTTP_201_CREATED)
async def create_org(payload: OrgIn, principal: PrincipalDep, session: SessionDep) -> OrgOut:
    if not principal.is_superuser:
        raise forbidden("only superusers may create orgs")
    svc = OrgService(session, principal)
    org = await svc.create(slug=payload.slug, name=payload.name, plan=payload.plan)
    await session.commit()
    return OrgOut.model_validate(org)


@router.get("", response_model=list[OrgOut])
async def list_orgs(principal: PrincipalDep, session: SessionDep) -> list[OrgOut]:
    svc = OrgService(session, principal)
    orgs = await svc.list_()
    return [OrgOut.model_validate(o) for o in orgs]


@router.get("/{public_id}", response_model=OrgOut)
async def get_org(public_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> OrgOut:
    svc = OrgService(session, principal)
    org = await svc.get(public_id)
    if org is None:
        raise not_found("org not found")
    return OrgOut.model_validate(org)
