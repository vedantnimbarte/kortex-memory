"""Export / import router."""

from __future__ import annotations

from fastapi import APIRouter, UploadFile, status
from fastapi.responses import Response
from kortex_core.db.types import ScopeType
from kortex_core.services.export_service import ExportService

from kortex_api.deps import PrincipalDep, SessionDep
from kortex_api.errors import bad_request
from kortex_api.schemas.common import APIModel

router = APIRouter(prefix="/v1/export", tags=["export"])


class ImportOut(APIModel):
    memories: int
    links: int
    attachments: int


@router.get("", responses={200: {"content": {"application/x-tar": {}}}})
async def export_scope(
    scope_type: ScopeType,
    scope_id: int,
    principal: PrincipalDep,
    session: SessionDep,
    include_attachments: bool = True,
) -> Response:
    svc = ExportService(session, principal)
    body = await svc.export_to_tar(
        scope_type=scope_type,
        scope_id=scope_id,
        include_attachments=include_attachments,
    )
    return Response(
        content=body,
        media_type="application/x-tar",
        headers={
            "Content-Disposition": (
                f'attachment; filename="kortex-{scope_type.value}-{scope_id}.tar"'
            )
        },
    )


@router.post(
    "/import",
    response_model=ImportOut,
    status_code=status.HTTP_201_CREATED,
)
async def import_scope(
    target_scope_type: ScopeType,
    target_scope_id: int,
    file: UploadFile,
    principal: PrincipalDep,
    session: SessionDep,
) -> ImportOut:
    body = await file.read()
    if not body:
        raise bad_request("empty upload")
    svc = ExportService(session, principal)
    result = await svc.import_from_tar(
        body,
        target_scope_type=target_scope_type,
        target_scope_id=target_scope_id,
    )
    await session.commit()
    return ImportOut(
        memories=result.memories,
        links=result.links,
        attachments=result.attachments,
    )
