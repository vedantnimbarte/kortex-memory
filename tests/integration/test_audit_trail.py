"""The audit trail: what it records, and whether it can be edited.

Two halves, and the second is the one that matters to a buyer.

**Coverage** — before this work the audit log had exactly one writer, so an
export would have produced a file suggesting nothing ever happened in the
system. The tests below assert the five categories a security reviewer asks
about are actually written.

**Integrity** — a trigger that refuses UPDATE and DELETE, and a hash chain that
makes an edit visible even to someone with the rights to make it. Both are
tested by doing the tampering: an integrity claim nobody tried to break is a
claim, not a control.
"""

from __future__ import annotations

import datetime as dt

import pytest
from kortex_core.audit import AuditAction
from kortex_core.db.types import ActorKind, MemoryKind, Role, ScopeType
from kortex_core.repositories.audit_repo import GENESIS, AuditRepository
from kortex_core.security.principal import Principal
from kortex_core.services.api_key_service import ApiKeyService
from kortex_core.services.auth_service import AuthError, AuthService
from kortex_core.services.memory_service import CreateMemoryInput, MemoryService
from kortex_core.services.signup_service import SignupService
from kortex_core.services.user_service import UserService
from sqlalchemy import text

pytestmark = pytest.mark.integration


async def _owner(session, email: str, org: str):  # type: ignore[no-untyped-def]
    result = await SignupService(session).register(
        email=email, password="hunter2pass", org_name=org
    )
    principal = (await AuthService(session).principal_from_jwt(result.access_token)).principal
    return principal, result


async def _actions(session, principal) -> list[str]:  # type: ignore[no-untyped-def]
    entries = await AuditRepository(session, principal=principal).read(
        org_id=principal.org_id, limit=100
    )
    return [e.action for e in entries]


# --- coverage: the five categories ------------------------------------------


async def test_a_successful_login_is_recorded(session) -> None:  # type: ignore[no-untyped-def]
    principal, _ = await _owner(session, "aud1@acme.io", "Audit Co")
    await AuthService(session).login_with_password(email="aud1@acme.io", password="hunter2pass")
    await session.flush()

    assert str(AuditAction.LOGIN) in await _actions(session, principal)


async def test_a_failed_login_against_a_real_account_is_recorded(session) -> None:  # type: ignore[no-untyped-def]
    """Credential stuffing against an account that exists is the signal worth
    having. The password itself is never written — not the value, not a hash,
    not its length."""
    principal, _ = await _owner(session, "aud2@acme.io", "Audit Two")
    with pytest.raises(AuthError):
        await AuthService(session).login_with_password(email="aud2@acme.io", password="wrongpass1")
    await session.flush()

    entries = await AuditRepository(session, principal=principal).read(org_id=principal.org_id)
    failures = [e for e in entries if e.action == str(AuditAction.LOGIN_FAILED)]
    assert len(failures) == 1
    assert failures[0].metadata_ == {}


async def test_an_unknown_email_is_not_filed_under_someone_elses_org(session) -> None:  # type: ignore[no-untyped-def]
    """An entry in the wrong tenant's log is worse than a missing one, because
    it will be believed."""
    principal, _ = await _owner(session, "aud3@acme.io", "Audit Three")
    with pytest.raises(AuthError):
        await AuthService(session).login_with_password(
            email="nobody@example.com", password="hunter2pass"
        )
    await session.flush()

    assert str(AuditAction.LOGIN_FAILED) not in await _actions(session, principal)


async def test_minting_and_revoking_a_key_are_recorded_without_the_secret(session) -> None:  # type: ignore[no-untyped-def]
    principal, _ = await _owner(session, "aud4@acme.io", "Audit Four")
    svc = ApiKeyService(session, principal)
    minted = await svc.mint(name="ci", scopes=["read:memory"])
    await svc.revoke(minted.api_key.public_id)
    await session.flush()

    entries = await AuditRepository(session, principal=principal).read(org_id=principal.org_id)
    actions = [e.action for e in entries]
    assert str(AuditAction.API_KEY_CREATED) in actions
    assert str(AuditAction.API_KEY_REVOKED) in actions

    serialised = str([e.metadata_ for e in entries])
    assert minted.plaintext not in serialised
    assert minted.api_key.prefix in serialised  # identifiable, without being usable


async def test_a_membership_grant_is_recorded_against_the_user(session) -> None:  # type: ignore[no-untyped-def]
    """ "Who can reach this" is the question an access review asks, so the target
    is the user whose access changed."""
    principal, _ = await _owner(session, "aud5@acme.io", "Audit Five")
    system = Principal(
        actor_id=0, actor_kind=ActorKind.SYSTEM, org_id=principal.org_id, is_superuser=True
    )
    scope = next(s for s in principal.roles if s.type == ScopeType.WORKSPACE)
    await UserService(session, system).grant(
        user_id=principal.actor_id,
        scope_type=scope.type,
        scope_id=scope.id,
        role=Role.EDITOR,
    )
    await session.flush()

    entries = await AuditRepository(session, principal=principal).read(org_id=principal.org_id)
    grants = [e for e in entries if e.action == str(AuditAction.MEMBER_GRANTED)]
    assert grants
    assert grants[-1].target_type == "user"
    assert grants[-1].target_id == principal.actor_id
    assert grants[-1].metadata_["role"] == "editor"


async def test_deleting_a_memory_is_recorded(session) -> None:  # type: ignore[no-untyped-def]
    """The one memory event that leaves nothing behind to inspect."""
    principal, _ = await _owner(session, "aud6@acme.io", "Audit Six")
    scope = next(s for s in principal.roles if s.type == ScopeType.WORKSPACE)
    svc = MemoryService(session, principal)
    written = await svc.write(
        CreateMemoryInput(
            scope_type=scope.type, scope_id=scope.id, body="delete me", kind=MemoryKind.FACT
        )
    )
    await session.flush()
    assert await svc.delete(written.memory.public_id) is True
    await session.flush()

    assert str(AuditAction.MEMORY_DELETED) in await _actions(session, principal)


async def test_ordinary_writes_and_reads_are_not_audited(session) -> None:  # type: ignore[no-untyped-def]
    """A log that records everything is a log nobody reads, and the noise buries
    the events that matter."""
    principal, _ = await _owner(session, "aud7@acme.io", "Audit Seven")
    scope = next(s for s in principal.roles if s.type == ScopeType.WORKSPACE)
    for i in range(3):
        await MemoryService(session, principal).write(
            CreateMemoryInput(scope_type=scope.type, scope_id=scope.id, body=f"fact {i}")
        )
    await session.flush()

    assert await _actions(session, principal) == []


# --- integrity: try to break it ----------------------------------------------


async def test_the_chain_starts_at_genesis_and_links_forward(session) -> None:  # type: ignore[no-untyped-def]
    principal, _ = await _owner(session, "aud8@acme.io", "Audit Eight")
    repo = AuditRepository(session, principal=principal)
    first = await repo.append(actor_kind=ActorKind.USER, actor_id=1, action=str(AuditAction.LOGIN))
    second = await repo.append(
        actor_kind=ActorKind.USER, actor_id=1, action=str(AuditAction.LOGOUT)
    )
    await session.flush()

    assert first.prev_hash == GENESIS
    assert second.prev_hash == first.entry_hash
    assert (await repo.verify(principal.org_id)).intact


async def test_an_edited_entry_breaks_the_chain(session) -> None:  # type: ignore[no-untyped-def]
    """The control that matters. Someone with database rights can change a row;
    what they cannot do is make the digest agree afterwards."""
    principal, _ = await _owner(session, "aud9@acme.io", "Audit Nine")
    repo = AuditRepository(session, principal=principal)
    for _ in range(3):
        await repo.append(actor_kind=ActorKind.USER, actor_id=1, action=str(AuditAction.LOGIN))
    await session.flush()
    entries = await repo.read(org_id=principal.org_id)
    assert (await repo.verify(principal.org_id)).intact

    # Straight past the ORM and past the trigger, the way a determined operator
    # would: disable the guard, rewrite history, put it back.
    await session.execute(text("ALTER TABLE audit_log DISABLE TRIGGER audit_log_append_only"))
    await session.execute(
        text("UPDATE audit_log SET action = 'auth.logout' WHERE id = :id"),
        {"id": entries[1].id},
    )
    await session.execute(text("ALTER TABLE audit_log ENABLE TRIGGER audit_log_append_only"))
    session.expire_all()

    status = await repo.verify(principal.org_id)
    assert status.intact is False
    assert status.broken_at == entries[1].id
    assert "no longer matches its digest" in status.detail


async def test_a_removed_entry_breaks_the_chain(session) -> None:  # type: ignore[no-untyped-def]
    """Deleting from the middle is the tamper a plain append-only table cannot
    detect: the rows that remain are individually perfect."""
    principal, _ = await _owner(session, "aud10@acme.io", "Audit Ten")
    repo = AuditRepository(session, principal=principal)
    for _ in range(3):
        await repo.append(actor_kind=ActorKind.USER, actor_id=1, action=str(AuditAction.LOGIN))
    await session.flush()
    entries = await repo.read(org_id=principal.org_id)

    await session.execute(text("ALTER TABLE audit_log DISABLE TRIGGER audit_log_append_only"))
    await session.execute(text("DELETE FROM audit_log WHERE id = :id"), {"id": entries[1].id})
    await session.execute(text("ALTER TABLE audit_log ENABLE TRIGGER audit_log_append_only"))
    session.expire_all()

    status = await repo.verify(principal.org_id)
    assert status.intact is False
    assert "altered or removed" in status.detail


async def test_the_trigger_refuses_an_update(session) -> None:  # type: ignore[no-untyped-def]
    principal, _ = await _owner(session, "aud11@acme.io", "Audit Eleven")
    repo = AuditRepository(session, principal=principal)
    entry = await repo.append(actor_kind=ActorKind.USER, actor_id=1, action=str(AuditAction.LOGIN))
    await session.flush()

    with pytest.raises(Exception, match="append-only"):
        await session.execute(
            text("UPDATE audit_log SET action = 'x' WHERE id = :id"), {"id": entry.id}
        )
    await session.rollback()


async def test_the_trigger_refuses_a_delete_that_did_not_opt_in(session) -> None:  # type: ignore[no-untyped-def]
    """Stops the accident — a stray DELETE, an ORM cascade — which is what
    actually destroys audit trails in practice."""
    principal, _ = await _owner(session, "aud12@acme.io", "Audit Twelve")
    repo = AuditRepository(session, principal=principal)
    entry = await repo.append(actor_kind=ActorKind.USER, actor_id=1, action=str(AuditAction.LOGIN))
    await session.flush()

    with pytest.raises(Exception, match="append-only"):
        await session.execute(text("DELETE FROM audit_log WHERE id = :id"), {"id": entry.id})
    await session.rollback()


# --- retention ---------------------------------------------------------------


async def test_retention_can_delete_and_says_that_it_did(session) -> None:  # type: ignore[no-untyped-def]
    """A log that can be trimmed without saying so is not a log."""
    principal, _ = await _owner(session, "aud13@acme.io", "Audit Thirteen")
    repo = AuditRepository(session, principal=principal)
    await repo.append(actor_kind=ActorKind.USER, actor_id=1, action=str(AuditAction.LOGIN))
    await session.flush()

    removed = await repo.purge_before(
        org_id=principal.org_id, cutoff=dt.datetime.now(tz=dt.UTC) + dt.timedelta(days=1)
    )
    assert removed == 1

    await repo.append(
        actor_kind=ActorKind.SYSTEM,
        actor_id=None,
        action=str(AuditAction.AUDIT_PURGED),
        metadata={"removed": removed},
    )
    await session.flush()
    assert await _actions(session, principal) == [str(AuditAction.AUDIT_PURGED)]


async def test_purging_the_start_of_a_chain_is_not_reported_as_tampering(session) -> None:  # type: ignore[no-untyped-def]
    """Retention is sanctioned. Verification walks forward from what remains,
    so a legitimate purge must not raise the alarm a real edit does."""
    principal, _ = await _owner(session, "aud14@acme.io", "Audit Fourteen")
    repo = AuditRepository(session, principal=principal)
    for _ in range(3):
        await repo.append(actor_kind=ActorKind.USER, actor_id=1, action=str(AuditAction.LOGIN))
    await session.flush()
    entries = await repo.read(org_id=principal.org_id)

    await repo.purge_before(org_id=principal.org_id, cutoff=entries[-1].created_at)
    session.expire_all()

    status = await repo.verify(principal.org_id)
    assert status.entries == 1
    assert status.intact is True
    # Anchored on the earliest surviving entry rather than on GENESIS. A
    # verifier that called retention "tampering" would cry wolf on every org
    # with a retention policy, after which nobody reads its output.
    assert status.anchor_prev != GENESIS  # the gap is reported, not hidden
    assert "earlier entries purged" in status.summary


async def test_the_head_is_stable_and_exportable(session) -> None:  # type: ignore[no-untyped-def]
    """Anchoring the head outside the database is what closes "nothing was
    removed from the end", so it has to be a value you can actually record."""
    principal, _ = await _owner(session, "aud15@acme.io", "Audit Fifteen")
    repo = AuditRepository(session, principal=principal)
    assert await repo.head(principal.org_id) == GENESIS

    entry = await repo.append(actor_kind=ActorKind.USER, actor_id=1, action=str(AuditAction.LOGIN))
    await session.flush()
    assert await repo.head(principal.org_id) == entry.entry_hash


async def test_one_orgs_chain_is_independent_of_another(session) -> None:  # type: ignore[no-untyped-def]
    """A shared chain would serialise every tenant behind the busiest one, and
    leak the existence of other orgs' activity into a digest a customer is
    invited to verify."""
    first, _ = await _owner(session, "aud16@acme.io", "Audit Sixteen")
    second, _ = await _owner(session, "aud17@acme.io", "Audit Seventeen")

    a = AuditRepository(session, principal=first)
    b = AuditRepository(session, principal=second)
    await a.append(actor_kind=ActorKind.USER, actor_id=1, action=str(AuditAction.LOGIN))
    await b.append(actor_kind=ActorKind.USER, actor_id=2, action=str(AuditAction.LOGIN))
    first_second = await a.append(
        actor_kind=ActorKind.USER, actor_id=1, action=str(AuditAction.LOGOUT)
    )
    await session.flush()

    # The second entry for org A chains to org A's first, not to org B's.
    entries = await a.read(org_id=first.org_id)
    assert first_second.prev_hash == entries[0].entry_hash
    assert (await a.verify(first.org_id)).intact
    assert (await b.verify(second.org_id)).intact
