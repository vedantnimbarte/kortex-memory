"""Attachment MCP tools: attach_file, finalize_attachment, get_attachment.

The MCP host uploads the bytes itself (via the presigned URL we return). The
client side is responsible for streaming the body to S3 / MinIO / FS, then
calling ``finalize_attachment`` to kick off the ``process_attachment`` worker.
"""

from __future__ import annotations

import uuid
from typing import Any

from kortex_core.db.types import ScopeType, Sensitivity
from kortex_core.models.attachment import Attachment
from kortex_core.services.attachment_service import (
    AttachmentError,
    AttachmentService,
)

from kortex_mcp.context import tool_context
from kortex_mcp.tools.base import ToolDef


def _attachment_out(a: Attachment) -> dict[str, Any]:
    return {
        "public_id": str(a.public_id),
        "scope_type": a.scope_type,
        "scope_id": a.scope_id,
        "filename": a.filename,
        "mime": a.mime,
        "size_bytes": a.size_bytes,
        "sha256": a.sha256,
        "sensitivity": a.sensitivity,
        "processing_status": a.processing_status,
        "processing_error": a.processing_error,
        "processed_at": a.processed_at,
        "s3_bucket": a.s3_bucket,
        "s3_key": a.s3_key,
        "created_at": a.created_at,
        "updated_at": a.updated_at,
        "metadata": a.metadata_,
    }


# ---------- attach_file (presign) ----------


async def _attach_file(args: dict[str, Any]) -> dict[str, Any]:
    async with tool_context() as (session, principal):
        svc = AttachmentService(session, principal)
        try:
            result = await svc.presign_upload(
                scope_type=ScopeType(args["scope_type"]),
                scope_id=int(args["scope_id"]),
                filename=args["filename"],
                mime=args.get("mime"),
                sensitivity=Sensitivity(args.get("sensitivity", Sensitivity.INTERNAL.value)),
                size_hint=args.get("size_hint"),
                metadata=args.get("metadata"),
            )
        except AttachmentError as e:
            return {"error": str(e)}
        return {
            "attachment": _attachment_out(result.attachment),
            "upload": {
                "url": result.upload.url,
                "method": result.upload.method,
                "headers": result.upload.headers,
                "expires_in": result.upload.expires_in,
            },
        }


_ATTACH = ToolDef(
    name="attach_file",
    description=(
        "Create an attachment record and return a presigned PUT URL the client "
        "uses to upload the body directly to blob storage. After the upload "
        "completes, call `finalize_attachment` to start processing."
    ),
    input_schema={
        "type": "object",
        "required": ["scope_type", "scope_id", "filename"],
        "properties": {
            "scope_type": {
                "type": "string",
                "enum": [s.value for s in ScopeType],
            },
            "scope_id": {"type": "integer"},
            "filename": {"type": "string", "minLength": 1, "maxLength": 500},
            "mime": {"type": ["string", "null"], "default": None},
            "sensitivity": {
                "type": "string",
                "enum": [s.value for s in Sensitivity],
                "default": Sensitivity.INTERNAL.value,
            },
            "size_hint": {"type": ["integer", "null"], "minimum": 0, "default": None},
            "metadata": {"type": ["object", "null"], "default": None},
        },
        "additionalProperties": False,
    },
    handler=_attach_file,
)


# ---------- finalize_attachment ----------


async def _finalize(args: dict[str, Any]) -> dict[str, Any] | None:
    async with tool_context() as (session, principal):
        svc = AttachmentService(session, principal)
        try:
            attachment = await svc.finalize(
                uuid.UUID(args["public_id"]),
                sha256=args.get("sha256"),
                size_bytes=args.get("size_bytes"),
                mime=args.get("mime"),
            )
        except AttachmentError as e:
            return {"error": str(e)}
        return _attachment_out(attachment) if attachment else None


_FINALIZE = ToolDef(
    name="finalize_attachment",
    description=(
        "Mark a pending attachment as ready for processing. The server verifies "
        "the object exists in blob storage and queues `process_attachment`."
    ),
    input_schema={
        "type": "object",
        "required": ["public_id"],
        "properties": {
            "public_id": {"type": "string", "format": "uuid"},
            "sha256": {"type": ["string", "null"], "default": None},
            "size_bytes": {"type": ["integer", "null"], "default": None},
            "mime": {"type": ["string", "null"], "default": None},
        },
        "additionalProperties": False,
    },
    handler=_finalize,
)


# ---------- get_attachment ----------


async def _get(args: dict[str, Any]) -> dict[str, Any] | None:
    async with tool_context() as (session, principal):
        svc = AttachmentService(session, principal)
        attachment = await svc.get(uuid.UUID(args["public_id"]))
        return _attachment_out(attachment) if attachment else None


_GET = ToolDef(
    name="get_attachment",
    description="Fetch an attachment's metadata + processing status.",
    input_schema={
        "type": "object",
        "required": ["public_id"],
        "properties": {"public_id": {"type": "string", "format": "uuid"}},
        "additionalProperties": False,
    },
    handler=_get,
)


TOOLS: list[ToolDef] = [_ATTACH, _FINALIZE, _GET]
