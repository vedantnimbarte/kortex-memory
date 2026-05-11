"""Attachments router (presign → upload → finalize → search chunks)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status

from kortex_core.db.types import AttachmentStatus, ScopeType, Sensitivity
from kortex_core.embeddings.protocol import EmbeddingError
from kortex_core.embeddings.registry import get_embedder
from kortex_core.repositories.attachment_repo import AttachmentChunkRepository
from kortex_core.repositories.memory_repo import ScopeFilter
from kortex_core.services.attachment_service import (
    AttachmentError,
    AttachmentService,
)

from kortex_api.deps import PrincipalDep, SessionDep
from kortex_api.errors import bad_request, not_found
from kortex_api.schemas.attachment import (
    AttachmentFinalizeIn,
    AttachmentOut,
    AttachmentPresignIn,
    AttachmentPresignOut,
    AttachmentSearchOut,
    AttachmentChunkHitOut,
    PresignedUploadOut,
)
from kortex_api.schemas.search import SearchIn

router = APIRouter(prefix="/v1/attachments", tags=["attachments"])


@router.post(
    "/presign",
    response_model=AttachmentPresignOut,
    status_code=status.HTTP_201_CREATED,
)
async def presign_upload(
    payload: AttachmentPresignIn, principal: PrincipalDep, session: SessionDep
) -> AttachmentPresignOut:
    svc = AttachmentService(session, principal)
    try:
        result = await svc.presign_upload(
            scope_type=payload.scope_type,
            scope_id=payload.scope_id,
            filename=payload.filename,
            mime=payload.mime,
            sensitivity=payload.sensitivity,
            size_hint=payload.size_hint,
            metadata=payload.metadata,
        )
    except AttachmentError as e:
        raise bad_request(str(e)) from e
    await session.commit()
    return AttachmentPresignOut(
        attachment=AttachmentOut.model_validate(result.attachment),
        upload=PresignedUploadOut(
            url=result.upload.url,
            method=result.upload.method,
            headers=result.upload.headers,
            expires_in=result.upload.expires_in,
        ),
    )


@router.post("/{public_id}/finalize", response_model=AttachmentOut)
async def finalize(
    public_id: uuid.UUID,
    payload: AttachmentFinalizeIn,
    principal: PrincipalDep,
    session: SessionDep,
) -> AttachmentOut:
    svc = AttachmentService(session, principal)
    try:
        attachment = await svc.finalize(
            public_id,
            sha256=payload.sha256,
            size_bytes=payload.size_bytes,
            mime=payload.mime,
        )
    except AttachmentError as e:
        raise bad_request(str(e)) from e
    if attachment is None:
        raise not_found("attachment not found")
    await session.commit()
    return AttachmentOut.model_validate(attachment)


@router.get("/{public_id}", response_model=AttachmentOut)
async def get_attachment(
    public_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> AttachmentOut:
    svc = AttachmentService(session, principal)
    attachment = await svc.get(public_id)
    if attachment is None:
        raise not_found("attachment not found")
    return AttachmentOut.model_validate(attachment)


@router.get("", response_model=list[AttachmentOut])
async def list_attachments(
    principal: PrincipalDep,
    session: SessionDep,
    scope_type: ScopeType | None = Query(default=None),
    scope_id: int | None = Query(default=None),
    processing_status: AttachmentStatus | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[AttachmentOut]:
    svc = AttachmentService(session, principal)
    scope = (
        ScopeFilter(scope_type=scope_type, scope_id=scope_id)
        if scope_type and scope_id is not None
        else None
    )
    items = await svc.list_(
        scope=scope, status=processing_status, limit=limit, offset=offset
    )
    return [AttachmentOut.model_validate(a) for a in items]


@router.delete("/{public_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_attachment(
    public_id: uuid.UUID, principal: PrincipalDep, session: SessionDep
) -> None:
    svc = AttachmentService(session, principal)
    ok = await svc.delete(public_id)
    if not ok:
        raise not_found("attachment not found")
    await session.commit()


@router.post("/search", response_model=AttachmentSearchOut)
async def search_attachments(
    payload: SearchIn, principal: PrincipalDep, session: SessionDep
) -> AttachmentSearchOut:
    chunks_repo = AttachmentChunkRepository(session, principal=principal)
    scopes = (
        [ScopeFilter(scope_type=s.scope_type, scope_id=s.scope_id) for s in payload.scopes]
        if payload.scopes
        else None
    )

    query_vector: list[float] | None = None
    used_vector = False
    if payload.embed_query:
        try:
            embedder = get_embedder()
            vectors = await embedder.embed([payload.query])
            query_vector = vectors[0]
            used_vector = True
        except (EmbeddingError, KeyError, RuntimeError):
            query_vector = None

    max_sens = principal.max_sensitivity or Sensitivity.INTERNAL
    hits = await chunks_repo.hybrid_search(
        query=payload.query,
        query_vector=query_vector,
        scopes=scopes,
        max_sensitivity=max_sens,
        limit=payload.limit,
    )
    return AttachmentSearchOut(
        used_vector=used_vector,
        hits=[
            AttachmentChunkHitOut(
                attachment_public_id=h.attachment_public_id,
                filename=h.filename,
                chunk_index=h.chunk_index,
                content=h.content,
                score=h.score,
            )
            for h in hits
        ],
    )
