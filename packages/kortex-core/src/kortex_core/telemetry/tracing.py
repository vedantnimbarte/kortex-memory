"""Small wrappers around OpenTelemetry that no-op when OTel isn't configured.

Lets retrieval/agent_loop emit spans without dragging the SDK into hot paths
or test environments.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from typing import Any


@contextlib.contextmanager
def span(name: str, **attrs: Any) -> Iterator[Any]:
    """Open a span by name with attributes. No-op when OTel is disabled.

    Usage::

        with span("kortex.retrieval.recall", query=q) as s:
            s.set_attribute("hits", len(hits))
    """
    try:
        from opentelemetry import trace
    except ImportError:  # pragma: no cover - OTel API is a hard core dep
        yield _NoopSpan()
        return

    tracer = trace.get_tracer("kortex")
    with tracer.start_as_current_span(name) as s:
        for k, v in attrs.items():
            try:
                s.set_attribute(k, v)
            except Exception:
                pass
        yield s


class _NoopSpan:
    def set_attribute(self, *_args: Any, **_kw: Any) -> None:
        pass

    def add_event(self, *_args: Any, **_kw: Any) -> None:
        pass
