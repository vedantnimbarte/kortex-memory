"""Which Postgres text-search configuration analyses a scope's text.

Keyword search used to be hardcoded to ``english`` everywhere — in the ``tsv``
generated columns and in every ``plainto_tsquery``. A French or Japanese corpus
was stemmed with English rules, so search still returned *something*, which is
the worst failure mode: nothing looks broken, recall is just quietly bad.

The setting lives on the project and is copied onto each memory/chunk row at
write time, because a generated column may only reference its own row.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortex_core.db.types import ScopeType
from kortex_core.repositories.project_repo import ProjectRepository
from kortex_core.security.principal import Principal

if TYPE_CHECKING:  # import cycle: memory_repo imports this module at runtime
    from kortex_core.repositories.memory_repo import ScopeFilter

DEFAULT_TS_CONFIG = "english"
"""Used for any scope that is not a project, and for projects that never said."""


async def config_for_scope(
    session: AsyncSession,
    principal: Principal,
    scope_type: ScopeType | None,
    scope_id: int | None,
) -> str:
    """The analyser configured for one scope.

    Only projects carry the setting; sessions and workspaces fall back to the
    default rather than walking up the hierarchy, which would cost a query per
    write to express a preference nobody has asked to set at those levels.
    """
    if scope_type is not ScopeType.PROJECT or scope_id is None:
        return DEFAULT_TS_CONFIG
    project = await ProjectRepository(session, principal=principal).get_by_id(scope_id)
    return project.text_search_config if project else DEFAULT_TS_CONFIG


async def config_for_scopes(
    session: AsyncSession,
    principal: Principal,
    scopes: list[ScopeFilter] | None,
) -> str:
    """One analyser for a whole query, taken from the first project searched.

    A search may span scopes with different configurations, but the *query*
    can only be parsed one way — and it has to be a constant, or the tsquery
    becomes row-dependent and the GIN index stops being usable, turning keyword
    search into a sequential scan. Rows written under another analyser still
    match on shared vocabulary; they just aren't stemmed to suit.
    """
    for sf in scopes or []:
        if sf.scope_type is ScopeType.PROJECT:
            return await config_for_scope(session, principal, sf.scope_type, sf.scope_id)
    return DEFAULT_TS_CONFIG


async def supported_configs(session: AsyncSession) -> set[str]:
    """Configuration names this server actually has.

    Asked of the database rather than hardcoded: the set depends on which
    dictionaries and extensions are installed, and an unrecognised name makes
    every subsequent query in that project raise instead of returning nothing.
    """
    rows = (await session.execute(text("SELECT cfgname FROM pg_ts_config"))).all()
    return {str(r[0]) for r in rows}
