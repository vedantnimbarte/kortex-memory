"""Keyword search stems text with the project's language, not always English.

The acceptance path for #17. The failure this closes is a quiet one: a French
corpus analysed by the English stemmer still returns *something*, so nothing
looks broken -- recall is just worse than it should be, in a way no error
message ever mentions.

The control assertion is what makes the test mean anything. Without it, "the
English project found nothing" is equally consistent with a broken fixture.
"""

from __future__ import annotations

import pytest
from kortex_core.db.types import MemoryKind, ScopeType
from kortex_core.repositories.memory_repo import MemoryRepository, ScopeFilter
from kortex_core.repositories.project_repo import ProjectRepository
from kortex_core.services.auth_service import AuthService
from kortex_core.services.memory_service import CreateMemoryInput, MemoryService
from kortex_core.services.signup_service import SignupService

pytestmark = pytest.mark.integration

FRENCH_BODY = "Nous avons décidé de conserver les journaux pendant trente jours."
"""``décidé`` is a past participle. The French stemmer reduces it to the same
root as the infinitive ``décider``; the English stemmer leaves both alone and
they stay two different tokens."""


async def _owner(session, email: str, org: str):  # type: ignore[no-untyped-def]
    result = await SignupService(session).register(
        email=email, password="hunter2pass", org_name=org
    )
    return (await AuthService(session).principal_from_jwt(result.access_token)).principal


async def _project(session, principal, *, slug: str, ts_config: str):  # type: ignore[no-untyped-def]
    """A project analysed by ``ts_config``, holding the same French sentence."""
    ws = next(s for s in principal.roles if s.type == ScopeType.WORKSPACE)
    repo = ProjectRepository(session, principal=principal)
    project = await repo.create(workspace_id=ws.id, slug=slug, name=slug)
    project.text_search_config = ts_config
    await session.flush()

    await MemoryService(session, principal).write(
        CreateMemoryInput(
            scope_type=ScopeType.PROJECT,
            scope_id=project.id,
            title="Rétention",
            body=FRENCH_BODY,
            kind=MemoryKind.FACT,
        )
    )
    await session.flush()
    return project


async def _search(session, principal, project, query: str) -> int:  # type: ignore[no-untyped-def]
    """Number of hits for ``query`` in ``project`` -- BM25 only, no embedder."""
    hits = await MemoryRepository(session, principal=principal).hybrid_search(
        query=query,
        query_vector=None,
        scopes=[ScopeFilter(scope_type=ScopeType.PROJECT, scope_id=project.id)],
    )
    return len(hits)


async def test_a_french_project_stems_french_and_english_does_not(session) -> None:  # type: ignore[no-untyped-def]
    principal = await _owner(session, "fr@acme.io", "Bonjour SA")
    french = await _project(session, principal, slug="fr", ts_config="french")
    english = await _project(session, principal, slug="en", ts_config="english")

    # Control first: the English project's row *is* stored and searchable. Only
    # the inflected form defeats it.
    assert await _search(session, principal, english, "décidé") == 1

    assert await _search(session, principal, french, "décider") == 1
    assert await _search(session, principal, english, "décider") == 0


async def test_changing_the_configuration_re_stems_what_is_already_stored(session) -> None:  # type: ignore[no-untyped-def]
    """A setting that only applied to future writes would leave a project's
    corpus half-analysed one way and half the other, with nothing to say which
    memories were which."""
    principal = await _owner(session, "fr2@acme.io", "Bonjour Deux")
    project = await _project(session, principal, slug="mixed", ts_config="english")
    assert await _search(session, principal, project, "décider") == 0

    project.text_search_config = "french"
    await MemoryRepository(session, principal=principal).reanalyse_scope(
        scope_type=ScopeType.PROJECT,
        scope_id=project.id,
        ts_config="french",
    )
    await session.flush()

    assert await _search(session, principal, project, "décider") == 1
