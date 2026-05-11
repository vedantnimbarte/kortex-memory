"""kortex attachment commands.

The upload flow is two HTTP requests + one PUT:

    kortex attachment upload <file> --scope project --scope-id 42

which under the hood:
  * POST /v1/attachments/presign  → returns attachment row + presigned URL
  * httpx.put(url, content=...)   → uploads the body to the blob store
  * POST /v1/attachments/{id}/finalize → marks the row ready-for-processing
"""

from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path
from typing import Annotated

import httpx
import typer

from kortex_cli.client import ApiClient, CliApiError
from kortex_cli.output import fail, print_obj

app = typer.Typer(help="Attachment upload + management.", no_args_is_help=True)


@app.command("upload")
def upload(
    path: Annotated[Path, typer.Argument()],
    scope_type: Annotated[str, typer.Option()] = "project",
    scope_id: Annotated[int, typer.Option()] = 0,
    sensitivity: Annotated[str, typer.Option()] = "internal",
    mime: Annotated[str | None, typer.Option()] = None,
    skip_finalize: Annotated[bool, typer.Option("--skip-finalize")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    if not path.exists():
        fail(f"file not found: {path}")
        return

    body = path.read_bytes()
    detected_mime = mime or mimetypes.guess_type(str(path))[0]
    sha = hashlib.sha256(body).hexdigest()

    with ApiClient() as client:
        try:
            presign = client.post(
                "/v1/attachments/presign",
                json={
                    "scope_type": scope_type,
                    "scope_id": scope_id,
                    "filename": path.name,
                    "mime": detected_mime,
                    "sensitivity": sensitivity,
                    "size_hint": len(body),
                },
            )
        except CliApiError as e:
            fail(str(e))
            return

        upload_info = presign["upload"]
        attachment = presign["attachment"]

        # Upload the body. ``file://`` URLs come from the FS adapter; we write
        # directly to disk in that case.
        url = upload_info["url"]
        try:
            if url.startswith("file://"):
                Path(httpx.URL(url).path.lstrip("/")).write_bytes(body)
            else:
                resp = httpx.put(
                    url,
                    content=body,
                    headers=upload_info.get("headers") or {},
                    timeout=300.0,
                )
                if resp.status_code >= 400:
                    fail(f"upload failed: HTTP {resp.status_code} {resp.text}")
                    return
        except Exception as e:  # noqa: BLE001
            fail(f"upload failed: {e}")
            return

        if skip_finalize:
            print_obj(
                {"attachment": attachment, "uploaded": True, "finalized": False},
                json_output=json_output,
            )
            return

        try:
            finalized = client.post(
                f"/v1/attachments/{attachment['public_id']}/finalize",
                json={
                    "sha256": sha,
                    "size_bytes": len(body),
                    "mime": detected_mime,
                },
            )
        except CliApiError as e:
            fail(str(e))
            return

    print_obj(
        {"attachment": finalized, "uploaded": True, "finalized": True},
        json_output=json_output,
    )


@app.command("list")
def list_attachments(
    scope_type: Annotated[str | None, typer.Option()] = None,
    scope_id: Annotated[int | None, typer.Option()] = None,
    status: Annotated[str | None, typer.Option("--status")] = None,
    limit: Annotated[int, typer.Option()] = 50,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    params: dict = {"limit": limit}
    if scope_type:
        params["scope_type"] = scope_type
    if scope_id is not None:
        params["scope_id"] = scope_id
    if status:
        params["processing_status"] = status
    with ApiClient() as client:
        try:
            result = client.get("/v1/attachments", params=params)
        except CliApiError as e:
            fail(str(e))
            return
    print_obj(result, json_output=json_output)


@app.command("show")
def show(
    public_id: str, json_output: Annotated[bool, typer.Option("--json")] = False
) -> None:
    with ApiClient() as client:
        try:
            result = client.get(f"/v1/attachments/{public_id}")
        except CliApiError as e:
            fail(str(e))
            return
    print_obj(result, json_output=json_output)


@app.command("delete")
def delete(public_id: str) -> None:
    with ApiClient() as client:
        try:
            client.delete(f"/v1/attachments/{public_id}")
        except CliApiError as e:
            fail(str(e))
            return
    print_obj({"deleted": True, "public_id": public_id})


@app.command("search")
def search(
    query: str,
    scope_type: Annotated[str | None, typer.Option()] = None,
    scope_id: Annotated[int | None, typer.Option()] = None,
    limit: Annotated[int, typer.Option()] = 20,
    no_embed: Annotated[bool, typer.Option("--no-embed")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    payload: dict = {"query": query, "limit": limit, "embed_query": not no_embed}
    if scope_type and scope_id is not None:
        payload["scopes"] = [{"scope_type": scope_type, "scope_id": scope_id}]
    with ApiClient() as client:
        try:
            result = client.post("/v1/attachments/search", json=payload)
        except CliApiError as e:
            fail(str(e))
            return
    print_obj(result, json_output=json_output)
