"""Round-trip a tiny tar to confirm the export/import helpers stay symmetric.

We don't hit the DB here — we exercise the JSONL + blob path inside the tar
helpers directly so the export shape is pinned without a Postgres.
"""

from __future__ import annotations

import io
import json
import tarfile

from kortex_core.services.export_service import _add_bytes, _add_jsonl, _read_jsonl


def test_jsonl_roundtrip() -> None:
    buf = io.BytesIO()
    tar = tarfile.open(fileobj=buf, mode="w")
    rows = [
        {"id": 1, "title": "alpha", "body": "first"},
        {"id": 2, "title": "beta", "body": "second"},
    ]
    _add_jsonl(tar, "memories.jsonl", rows)
    _add_bytes(tar, "blobs/x/y.txt", b"hello world")
    tar.close()

    buf.seek(0)
    reopened = tarfile.open(fileobj=buf, mode="r")
    parsed = _read_jsonl(reopened, "memories.jsonl")
    assert parsed == rows

    blob = reopened.extractfile(reopened.getmember("blobs/x/y.txt")).read()  # type: ignore[union-attr]
    assert blob == b"hello world"


def test_read_jsonl_handles_missing_member() -> None:
    buf = io.BytesIO()
    tar = tarfile.open(fileobj=buf, mode="w")
    _add_jsonl(tar, "memories.jsonl", [{"x": 1}])
    tar.close()

    buf.seek(0)
    reopened = tarfile.open(fileobj=buf, mode="r")
    assert _read_jsonl(reopened, "does-not-exist.jsonl") == []


def test_jsonl_preserves_unicode() -> None:
    buf = io.BytesIO()
    tar = tarfile.open(fileobj=buf, mode="w")
    _add_jsonl(tar, "x.jsonl", [{"emoji": "👋", "kanji": "日本"}])
    tar.close()
    reopened = tarfile.open(fileobj=io.BytesIO(buf.getvalue()), mode="r")
    rows = _read_jsonl(reopened, "x.jsonl")
    assert rows[0]["kanji"] == "日本"


def test_idempotent_principal_token_shape() -> None:
    """Sanity-check the helper used by the idempotency middleware."""
    from kortex_api.middleware.idempotency import _principal_token

    class FakeRequest:
        headers = {  # noqa: RUF012 - test fake, not a real mutable-default concern
            "x-api-key": "kx_abcd1234_secretsecretsecretsecretsecretsecretsec"
        }

    token = _principal_token(FakeRequest())  # type: ignore[arg-type]
    assert token.startswith("k:")


def test_manifest_json_is_valid() -> None:
    """The manifest is single-row JSONL — round-trippable through json.loads."""
    payload = {
        "version": 1,
        "source_org_id": 42,
        "source_scope_type": "project",
        "source_scope_id": 7,
        "counts": {"memories": 3},
    }
    serialised = json.dumps(payload, ensure_ascii=False)
    assert json.loads(serialised) == payload
