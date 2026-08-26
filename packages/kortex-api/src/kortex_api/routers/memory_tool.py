"""Claude's native memory tool, proxied onto a Kortex scope.

An application holding a Claude conversation forwards each ``memory`` tool_use
here and puts the response straight back in the ``tool_result`` block. That is
the whole integration — no SDK, no language requirement, one endpoint.

The endpoint answers **200 even for a failed command**. That is deliberate and
worth stating, because it looks wrong: a 404 for a missing file would be
correct HTTP and useless to the caller, who has to turn it back into a string
for Claude anyway. Claude recovers from ``The path /memories/x does not exist``;
it cannot recover from an exception the proxy swallowed. Real failures —
unauthenticated, no such scope, database down — still error normally.
"""

from __future__ import annotations

from fastapi import APIRouter
from kortex_core.db.types import ScopeType, Sensitivity
from kortex_core.memory_tool import MemoryToolBackend

from kortex_api.deps import PrincipalDep, SessionDep
from kortex_api.errors import bad_request
from kortex_api.schemas.memory_tool import MemoryToolIn, MemoryToolOut

router = APIRouter(prefix="/v1/memory-tool", tags=["memory-tool"])


@router.post("", response_model=MemoryToolOut)
async def execute_memory_tool(
    payload: MemoryToolIn,
    principal: PrincipalDep,
    session: SessionDep,
) -> MemoryToolOut:
    """Execute one ``memory_20250818`` command against a scope.

    Post the tool_use block's ``input`` verbatim, plus the scope it belongs to.
    Return ``content`` to Claude as the tool result, and set ``is_error`` on the
    block when this says so.
    """
    try:
        scope_type = ScopeType(payload.scope_type)
        sensitivity = Sensitivity(payload.sensitivity)
    except ValueError as e:
        raise bad_request(str(e)) from e

    backend = MemoryToolBackend(
        session,
        principal,
        scope_type=scope_type,
        scope_id=payload.scope_id,
        sensitivity=sensitivity,
    )
    result = await backend.execute(payload.command)
    # Committed even on a reported error: a partially applied command is not a
    # thing here (each one is a single write), and a rolled-back success would
    # tell Claude it saved something it did not.
    await session.commit()
    return MemoryToolOut(content=result.content, is_error=result.is_error)
