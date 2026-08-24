"""Conflict annotation for retrieval results.

The write path records ``supersedes`` / ``contradicts`` edges (see
:mod:`kortex_core.skills.conflict_judge`); this module is the read half that
makes them visible. Two things happen to a result page:

1. **Annotate** — every hit carries the conflicting memories it is linked to,
   whether or not those memories are themselves in the page. An agent that gets
   back "we use Postgres for the queue" needs to see that something supersedes
   it even when the successor scored too low to be returned.
2. **Demote** — a memory superseded by another memory *in the same page* sorts
   last, so the current state of the world reads first.

What does **not** happen: nothing is filtered, merged, or deleted. Whether a
contradiction is a genuine correction or two facts that only look
incompatible out of context is a judgement the agent can make and the database
cannot.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from kortex_core.db.types import MemoryLinkType
from kortex_core.repositories.memory_link_repo import MemoryLinkRepository
from kortex_core.repositories.memory_repo import MemoryRepository
from kortex_core.retrieval.hybrid import HybridSearchHit
from kortex_core.security.principal import Principal


@dataclass(frozen=True, slots=True)
class ConflictNote:
    """One conflicting memory, described from the annotated hit's point of view."""

    public_id: str
    title: str
    relation: str
    """``superseded_by`` | ``supersedes`` | ``contradicts``."""
    created_at: str
    """ISO-8601, so the agent can tell which side is newer without another call."""

    @property
    def is_stale_marker(self) -> bool:
        return self.relation == "superseded_by"


def demote_superseded[T](
    items: Sequence[T],
    demoted_ids: set[int],
    key: Callable[[T], int],
) -> list[T]:
    """Stable partition: superseded items keep their relative order, at the end.

    A partition rather than a topological sort — with A supersedes B and
    C supersedes A, both A and B are demoted and C leads, which is the ordering
    we want without having to reason about cycles the judge might emit.
    """
    if not demoted_ids:
        return list(items)
    current = [i for i in items if key(i) not in demoted_ids]
    stale = [i for i in items if key(i) in demoted_ids]
    return current + stale


async def annotate_conflicts(
    session: AsyncSession,
    principal: Principal,
    hits: Sequence[HybridSearchHit],
) -> set[int]:
    """Attach conflict notes to ``hits`` in place; return ids that should sort last.

    Returned ids are only those superseded by a memory *also present* in
    ``hits`` — demoting a hit below a successor the caller never sees would
    just look like a ranking bug.
    """
    if not hits:
        return set()

    present = {h.memory_id: h for h in hits}
    links = await MemoryLinkRepository(session, principal=principal).conflict_links(list(present))
    if not links:
        return set()

    # Resolve every memory named by an edge — including ones that did not make
    # the page. Both sides are fetched even when they are already hits, because
    # HybridSearchHit carries no timestamp and "which of these is newer" is the
    # whole question the agent is trying to answer.
    referenced = {link.from_memory_id for link in links} | {link.to_memory_id for link in links}
    repo = MemoryRepository(session, principal=principal)
    rows = {m.id: m for m in await repo.list_by_ids(sorted(referenced))}

    def describe(memory_id: int) -> tuple[str, str, str] | None:
        """(public_id, title, created_at_iso) for either side of an edge."""
        row = rows.get(memory_id)
        if row is None:
            return None  # soft-deleted or out of tenant — say nothing about it
        return str(row.public_id), row.title, row.created_at.isoformat()

    notes: dict[int, list[ConflictNote]] = {mid: [] for mid in present}
    demoted: set[int] = set()

    for link in links:
        supersedes = link.link_type == MemoryLinkType.SUPERSEDES.value
        # `from` is always the newer memory the judge was asked about.
        for anchor, other, relation in (
            (link.from_memory_id, link.to_memory_id, "supersedes" if supersedes else "contradicts"),
            (
                link.to_memory_id,
                link.from_memory_id,
                "superseded_by" if supersedes else "contradicts",
            ),
        ):
            if anchor not in present:
                continue
            described = describe(other)
            if described is None:
                continue
            public_id, title, created_at = described
            notes[anchor].append(
                ConflictNote(
                    public_id=public_id,
                    title=title,
                    relation=relation,
                    created_at=created_at,
                )
            )
            if relation == "superseded_by" and other in present:
                demoted.add(anchor)

    for memory_id, hit in present.items():
        hit.conflicts = notes[memory_id]
    return demoted
