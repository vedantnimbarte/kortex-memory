"""API keys router."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from kortex_core.services.api_key_service import ApiKeyService

from kortex_api.deps import PrincipalDep, SessionDep
from kortex_api.errors import not_found
from kortex_api.schemas.api_key import ApiKeyIn, ApiKeyMintOut, ApiKeyOut

router = APIRouter(prefix="/v1/api_keys", tags=["api_keys"])


@router.post("", response_model=ApiKeyMintOut, status_code=status.HTTP_201_CREATED)
async def mint_api_key(
    payload: ApiKeyIn, principal: PrincipalDep, session: SessionDep
) -> ApiKeyMintOut:
    svc = ApiKeyService(session, principal)
    minted = await svc.mint(
        name=payload.name,
        scopes=payload.scopes,
        scope_type=payload.scope_type,
        scope_id=payload.scope_id,
        expires_in_days=payload.expires_in_days,
    )
    await session.commit()
    out = ApiKeyOut.model_validate(minted.api_key).model_dump()
    return ApiKeyMintOut(**out, plaintext=minted.plaintext)


@router.get("", response_model=list[ApiKeyOut])
async def list_api_keys(
    principal: PrincipalDep, session: SessionDep
) -> list[ApiKeyOut]:
    svc = ApiKeyService(session, principal)
    keys = await svc.list_()
    return [ApiKeyOut.model_validate(k) for k in keys]


@router.delete("/{public_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    public_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> None:
    svc = ApiKeyService(session, principal)
    revoked = await svc.revoke(public_id)
    if revoked is None:
        raise not_found("api key not found")
    await session.commit()
