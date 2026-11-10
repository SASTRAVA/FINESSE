"""Optional OpenTelemetry wiring. Importing FINESSE does not require OTel packages."""
from __future__ import annotations

import logging
from contextlib import nullcontext

from .config import cfg

logger = logging.getLogger("finesse.telemetry")
_configured = False


def configure_telemetry(app=None) -> bool:
    """Configure OTLP tracing only when explicitly enabled and fully configured."""
    global _configured
    if not cfg.OTEL_ENABLED:
        return False
    if _configured:
        return True
    if not cfg.OTEL_EXPORTER_OTLP_ENDPOINT:
        logger.warning("OTEL_ENABLED is true but OTEL_EXPORTER_OTLP_ENDPOINT is empty")
        return False
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = TracerProvider(resource=Resource.create({"service.name": "finesse"}))
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(
            endpoint=cfg.OTEL_EXPORTER_OTLP_ENDPOINT)))
        trace.set_tracer_provider(provider)
        if app is not None:
            FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
        _configured = True
        return True
    except ImportError:
        logger.exception("Install requirements-observability.txt to enable OpenTelemetry")
        return False


def span(name: str, **attributes):
    """Return a current-span context manager; safely no-op when disabled."""
    if not cfg.OTEL_ENABLED:
        return nullcontext()
    try:
        from opentelemetry import trace
        return trace.get_tracer("finesse").start_as_current_span(name, attributes=attributes)
    except ImportError:
        return nullcontext()
