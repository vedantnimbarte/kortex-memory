"""Conversation summariser.

Every 5 minutes we look for conversations whose last message is older than
30 minutes and that don't yet have a stored summary. We render the last 50
messages and ask the configured ``Summarizer`` to write a paragraph.
"""

from __future__ import annotations

import asyncio
import datetime as dt

from sqlalchemy import text

from kortex_core.db.engine import close_engine
from kortex_core.db.session import session_scope
from kortex_core.db.types import ActorKind, MessageRole
from kortex_core.models.session import Conversation, Message
from kortex_core.security.principal import Principal
from kortex_core.skills.summarizer import get_summarizer
from kortex_core.telemetry.logging import get_logger

from kortex_worker.celery_app import celery_app

log = get_logger("kortex.worker.summary")


def _superuser() -> Principal:
    return Principal(
        actor_id=0,
        actor_kind=ActorKind.SYSTEM,
        org_id=0,
        is_superuser=True,
    )


async def _find_idle(limit: int = 16) -> list[tuple[int, int]]:
    """Return ``(conversation_id, org_id)`` pairs that need summarising."""
    sql = text(
        """
        SELECT c.id, c.org_id
        FROM conversations c
        WHERE c.summary IS NULL
          AND EXISTS (SELECT 1 FROM messages m WHERE m.conversation_id = c.id)
          AND (
            SELECT MAX(m.created_at) FROM messages m WHERE m.conversation_id = c.id
          ) < (now() - interval '30 minutes')
        ORDER BY c.id ASC
        LIMIT :lim
        """
    )
    async with session_scope() as session:
        rows = (await session.execute(sql, {"lim": limit})).all()
    return [(int(r[0]), int(r[1])) for r in rows]


async def _summarise_conversation(conversation_id: int) -> bool:
    summarizer = get_summarizer()
    async with session_scope() as session:
        msg_rows = (
            await session.execute(
                text(
                    "SELECT role, content FROM messages "
                    "WHERE conversation_id = :cid "
                    "ORDER BY created_at DESC LIMIT 50"
                ),
                {"cid": conversation_id},
            )
        ).all()
        if not msg_rows:
            return False
        rendered = list(reversed([(str(r[0]), str(r[1])) for r in msg_rows]))
        try:
            summary = await summarizer.summarize(rendered)
        except Exception as e:  # noqa: BLE001
            log.warning("summary_failed", conversation_id=conversation_id, error=str(e))
            return False
        if not summary.strip():
            return False
        await session.execute(
            text("UPDATE conversations SET summary = :s WHERE id = :id"),
            {"s": summary, "id": conversation_id},
        )
    return True


async def _generate_summaries() -> dict[str, int]:
    idle = await _find_idle()
    done = 0
    for cid, _org in idle:
        if await _summarise_conversation(cid):
            done += 1
    return {"checked": len(idle), "summarised": done}


@celery_app.task(name="kortex.summary.generate_summary", bind=False)
def generate_summary() -> dict[str, int]:
    try:
        return asyncio.run(_generate_summaries())
    finally:
        try:
            asyncio.run(close_engine())
        except Exception:  # pragma: no cover
            pass


# Keep the imports module-side for static analysis (otherwise unused).
_ = (Conversation, Message, MessageRole, ActorKind, dt)
