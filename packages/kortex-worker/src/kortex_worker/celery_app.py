"""Celery application factory."""

from __future__ import annotations

from celery import Celery
from kortex_core.settings import get_settings
from kortex_core.telemetry.logging import configure_logging
from kortex_core.telemetry.otel import configure_otel


def make_celery() -> Celery:
    s = get_settings()
    app = Celery(
        "kortex",
        broker=s.redis_url,
        backend=s.redis_url,
        include=[
            "kortex_worker.tasks.audit",
            "kortex_worker.tasks.embedding",
            "kortex_worker.tasks.attachments",
            "kortex_worker.tasks.decay",
            "kortex_worker.tasks.conflict",
            "kortex_worker.tasks.consolidate",
            "kortex_worker.tasks.summary",
        ],
    )
    app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        result_expires=24 * 3600,
        task_default_queue="default",
        task_routes={
            "kortex.embedding.*": {"queue": "embed"},
            "kortex.decay.*": {"queue": "slow"},
            "kortex.conflict.*": {"queue": "slow"},
            "kortex.consolidate.*": {"queue": "slow"},
            "kortex.summary.*": {"queue": "slow"},
            "kortex.attachment.*": {"queue": "default"},
            "kortex.audit.*": {"queue": "slow"},
        },
        broker_connection_retry_on_startup=True,
    )

    # Beat schedule for cadence-driven tasks (plan §K).
    app.conf.beat_schedule = {
        "embed-pending": {
            "task": "kortex.embedding.embed_pending",
            "schedule": 30.0,
        },
        "conflict-detect": {
            # Every 60s. The scan is a partial-index lookup that hits nothing
            # when the queue is empty, so a tight cadence is cheap and keeps a
            # contradiction from surviving more than a minute past its write.
            "task": "kortex.conflict.detect_pending",
            "schedule": 60.0,
        },
        "decay-tick": {
            # Every 6h, fan-out per-org from the task body.
            "task": "kortex.decay.decay_tick",
            "schedule": 6 * 3600.0,
        },
        "consolidate-tier": {
            # Daily at 03:00 UTC; Celery beat uses crontab semantics here.
            "task": "kortex.consolidate.consolidate_tier",
            "schedule": _daily_at(3, 0),
        },
        "audit-retention": {
            # Daily at 04:00 UTC, an hour after consolidation so the two long
            # write jobs do not contend. A no-op unless audit_retention_days
            # is set, which it is not by default.
            "task": "kortex.audit.purge_expired",
            "schedule": _daily_at(4, 0),
        },
        "generate-summary": {
            "task": "kortex.summary.generate_summary",
            "schedule": 5 * 60.0,
        },
    }
    return app


def _daily_at(hour: int, minute: int) -> object:
    """Crontab schedule helper — kept inline so callers don't need to know Celery's API."""
    from celery.schedules import crontab

    return crontab(hour=hour, minute=minute)


celery_app = make_celery()


def init() -> None:
    """Run once per worker process at boot."""
    configure_logging()
    configure_otel()
