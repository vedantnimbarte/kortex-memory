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
from kortex_core.db.types import ActorKind, MemoryKind, Role, ScopeType
from kortex_core.repositories.memory_repo import MemoryRepository, ScopeFilter
from kortex_core.repositories.project_repo import ProjectRepository
from kortex_core.repositories.workspace_repo import WorkspaceRepository
from kortex_core.security.principal import Principal
from kortex_core.services.auth_service import AuthService
from kortex_core.services.memory_service import CreateMemoryInput, MemoryService
from kortex_core.services.project_service import ProjectService
from kortex_core.services.signup_service import SignupService

pytestmark = pytest.mark.integration

FRENCH_BODY = "Nous avons décidé de conserver les journaux pendant trente jours."
"""``décidé`` is a past participle. The French stemmer reduces it to the same
root as the infinitive ``décider``; the English stemmer leaves both alone and
they stay two different tokens."""


async def _projects(session, email: str, org: str, configs: dict[str, str]):  # type: ignore[no-untyped-def]
    """An owner plus one project per requested configuration, each holding the
    same French sentence.

    Fiddly for a real reason: creating a project confers no membership on it,
    and an org owner cannot grant on a project it has no role on either. So the
    grants go through a system principal, the way the other integration suites
    seed tenants, and the principal is re-materialised afterwards because roles
    resolve at materialisation time.
    """
    registered = await SignupService(session).register(
        email=email, password="hunter2pass", org_name=org
    )
    auth = AuthService(session)
    principal = (await auth.principal_from_jwt(registered.access_token)).principal

    ws = next(s for s in principal.roles if s.type == ScopeType.WORKSPACE)
    workspace = await WorkspaceRepository(session, principal=principal).get_by_id(ws.id)
    assert workspace is not None

    system = Principal(
        actor_id=0,
        actor_kind=ActorKind.SYSTEM,
        org_id=principal.org_id,
        is_superuser=True,
    )
    from kortex_core.services.user_service import UserService

    created: dict[str, int] = {}
    for slug, ts_config in configs.items():
        project = await ProjectService(session, principal).create(
            workspace_public_id=workspace.public_id, slug=slug, name=slug
        )
        assert project is not None
        project.text_search_config = ts_config
        await UserService(session, system).grant(
            user_id=principal.actor_id,
            scope_type=ScopeType.PROJECT,
            scope_id=project.id,
            role=Role.OWNER,
        )
        created[slug] = project.id
    await session.flush()
    principal = (await auth.principal_from_jwt(registered.access_token)).principal

    svc = MemoryService(session, principal)
    for project_id in created.values():
        await svc.write(
            CreateMemoryInput(
                scope_type=ScopeType.PROJECT,
                scope_id=project_id,
                title="Rétention",
                body=FRENCH_BODY,
                kind=MemoryKind.FACT,
            )
        )
    await session.flush()
    return principal, created


async def _search(session, principal, project_id: int, query: str) -> int:  # type: ignore[no-untyped-def]
    """Number of hits for ``query`` in a project -- BM25 only, no embedder."""
    hits = await MemoryRepository(session, principal=principal).hybrid_search(
        query=query,
        query_vector=None,
        scopes=[ScopeFilter(scope_type=ScopeType.PROJECT, scope_id=project_id)],
    )
    return len(hits)


async def test_a_french_project_stems_french_and_english_does_not(session) -> None:  # type: ignore[no-untyped-def]
    principal, projects = await _projects(
        session, "fr@acme.io", "Bonjour SA", {"fr": "french", "en": "english"}
    )

    # Control first: the English project's row *is* stored and searchable. Only
    # the inflected form defeats it.
    assert await _search(session, principal, projects["en"], "décidé") == 1

    assert await _search(session, principal, projects["fr"], "décider") == 1
    assert await _search(session, principal, projects["en"], "décider") == 0


async def test_changing_the_configuration_re_stems_what_is_already_stored(session) -> None:  # type: ignore[no-untyped-def]
    """A setting that only applied to future writes would leave a project's
    corpus half-analysed one way and half the other, with nothing to say which
    memories were which."""
    principal, projects = await _projects(
        session, "fr2@acme.io", "Bonjour Deux", {"mixed": "english"}
    )
    project_id = projects["mixed"]
    assert await _search(session, principal, project_id, "décider") == 0

    project = await ProjectRepository(session, principal=principal).get_by_id(project_id)
    assert project is not None
    project.text_search_config = "french"
    await MemoryRepository(session, principal=principal).reanalyse_scope(
        scope_type=ScopeType.PROJECT,
        scope_id=project_id,
        ts_config="french",
    )
    await session.flush()

    assert await _search(session, principal, project_id, "décider") == 1
