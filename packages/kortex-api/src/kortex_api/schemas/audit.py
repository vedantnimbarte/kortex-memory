"""Audit schemas."""

from __future__ import annotations

from kortex_api.schemas.common import APIModel


class AuditVerifyOut(APIModel):
    org_id: int
    entries: int
    unchained: int
    """Entries written before hash chaining existed. Not a failure, and not a
    guarantee either — they are reported so the number is never mistaken for
    coverage."""
    intact: bool
    broken_at: int | None = None
    detail: str = ""
    summary: str
    head: str
    """The current head digest. Record it somewhere this database's operator
    does not control; a chain checked only against itself cannot prove nothing
    was removed from the end."""
