"""The review inbox: memories held back from recall until a person looks.

One queue, two reasons to be in it — a low-trust write that reads as
instructions to a model, or a write the project decided to gate. From the
memory's side the state is identical, so the reviewer gets one place to work
rather than two to remember.

Reviewing is an ordinary member action, not a superuser one. The people who
know whether a memory is right are the people using the project; routing every
decision through an operator is how a queue becomes a backlog nobody clears.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query
from kortex_core.services.memory_service import MemoryService

from kortex_api.deps import PrincipalDep, SessionDep
from kortex_api.errors import not_found
from kortex_api.schemas.common import APIModel
from kortex_api.schemas.memory import MemoryOut

router = APIRouter(prefix="/v1/review", tags=["review"])


class ReviewItemOut(APIModel):
    """A held memory, with the context needed to judge it."""

    memory: MemoryOut
    reason: str
    """Why it was held — a heuristic name, or the confidence that fell short."""
    similar: list[MemoryOut]
    """Approved memories that look like this one, so a reviewer can tell a new
    fact from the fourth restatement of one already stored."""


class ReviewQueueOut(APIModel):
    total: int
    items: list[ReviewItemOut]


class BulkReviewIn(APIModel):
    public_ids: list[uuid.UUID]
    approve: bool


class BulkReviewOut(APIModel):
    reviewed: int
    skipped: int
    """Ids that were missing or already decided. Reported rather than silently
    dropped, so a bulk action that half-worked says so."""


@router.get("", response_model=ReviewQueueOut)
async def queue(
    principal: PrincipalDep,
    session: SessionDep,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> ReviewQueueOut:
    svc = MemoryService(session, principal)
    held = await svc.pending_review(limit=limit, offset=offset)
    items = [
        ReviewItemOut(
            memory=MemoryOut.model_validate(memory),
            reason=memory.review_reason or "",
            similar=[
                MemoryOut.model_validate(other)
                for other in await svc.similar_for_review(memory, limit=3)
            ],
        )
        for memory in held
    ]
    return ReviewQueueOut(total=await svc.pending_review_count(), items=items)


@router.post("/{public_id}/approve", response_model=MemoryOut)
async def approve(public_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> MemoryOut:
    """Let a held memory into recall. Recorded in the audit log with the reviewer."""
    memory = await MemoryService(session, principal).review(public_id, approve=True)
    if memory is None:
        raise not_found("memory not found")
    await session.commit()
    return MemoryOut.model_validate(memory)


@router.post("/{public_id}/reject", response_model=MemoryOut)
async def reject(public_id: uuid.UUID, principal: PrincipalDep, session: SessionDep) -> MemoryOut:
    """Keep a held memory out of recall.

    Rejected rather than deleted: what an agent tried to store and why it was
    refused is exactly the evidence worth keeping after a poisoning attempt.
    """
    memory = await MemoryService(session, principal).review(public_id, approve=False)
    if memory is None:
        raise not_found("memory not found")
    await session.commit()
    return MemoryOut.model_validate(memory)


@router.post("/bulk", response_model=BulkReviewOut)
async def bulk(
    payload: BulkReviewIn, principal: PrincipalDep, session: SessionDep
) -> BulkReviewOut:
    """Decide several at once.

    Deliberately takes explicit ids rather than an "approve everything" flag:
    clearing a queue you have not read is the failure mode a review step
    exists to prevent.
    """
    svc = MemoryService(session, principal)
    reviewed = 0
    for public_id in payload.public_ids:
        memory = await svc.review(public_id, approve=payload.approve)
        if memory is not None and memory.reviewed_at is not None:
            reviewed += 1
    await session.commit()
    return BulkReviewOut(reviewed=reviewed, skipped=len(payload.public_ids) - reviewed)
