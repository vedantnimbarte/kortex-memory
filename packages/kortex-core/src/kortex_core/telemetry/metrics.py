"""Named meters for the various subsystems.

Importing this module is cheap; meter creation is lazy via the OpenTelemetry SDK.
"""

from __future__ import annotations

from opentelemetry import metrics


def get_meter(name: str = "kortex") -> metrics.Meter:
    return metrics.get_meter(name)
