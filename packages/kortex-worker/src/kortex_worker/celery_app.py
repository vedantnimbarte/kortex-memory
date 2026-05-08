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
            "kortex_worker.tasks.embedding",
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
            "kortex.consolidate.*": {"queue": "slow"},
            "kortex.attachment.*": {"queue": "default"},
            "kortex.audit.*": {"queue": "slow"},
        },
        broker_connection_retry_on_startup=True,
    )

    # Beat schedule for cadence-driven tasks. We start with embed_pending; M6 adds the rest.
    app.conf.beat_schedule = {
        "embed-pending": {
            "task": "kortex.embedding.embed_pending",
            "schedule": 30.0,
        },
    }
    return app


celery_app = make_celery()


def init() -> None:
    """Run once per worker process at boot."""
    configure_logging()
    configure_otel()
