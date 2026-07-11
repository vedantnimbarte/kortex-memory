"""OpenTelemetry setup. Disabled unless KORTEX_OTEL_ENABLED=true."""

from __future__ import annotations

from typing import TYPE_CHECKING

from kortex_core.settings import get_settings

if TYPE_CHECKING:
    from opentelemetry.trace import Tracer

_configured = False


def configure_otel() -> None:
    """Configure tracer + meter providers. Idempotent."""
    global _configured
    if _configured:
        return
    s = get_settings()
    if not s.otel_enabled:
        _configured = True
        return

    from opentelemetry import metrics, trace
    from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create(
        {
            "service.name": s.otel_service_name,
            "service.namespace": "kortex",
            "deployment.environment": s.env,
        }
    )

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=s.otel_endpoint))
    )
    trace.set_tracer_provider(tracer_provider)

    reader = PeriodicExportingMetricReader(OTLPMetricExporter(endpoint=s.otel_endpoint))
    meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(meter_provider)

    _configured = True


def get_tracer(name: str = "kortex") -> Tracer:
    from opentelemetry import trace

    return trace.get_tracer(name)
