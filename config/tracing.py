"""
OpenTelemetry Distributed Tracing Setup.

Initializes tracing with Jaeger exporter for the notification system.
Traces flow: API → RabbitMQ → Celery Worker → External Provider

Called from config/__init__.py or wsgi.py/asgi.py on startup.
"""

import logging
import os

logger = logging.getLogger(__name__)


def setup_tracing():
    """Initialize OpenTelemetry tracing with Jaeger exporter."""
    enabled = os.getenv("OTEL_ENABLED", "False") == "True"
    if not enabled:
        logger.info("OpenTelemetry tracing is disabled (OTEL_ENABLED != True)")
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.jaeger.thrift import JaegerExporter
        from opentelemetry.instrumentation.celery import CeleryInstrumentor
        from opentelemetry.instrumentation.django import DjangoInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        service_name = os.getenv("OTEL_SERVICE_NAME", "rns-notification-system")
        jaeger_host = os.getenv("OTEL_JAEGER_HOST", "jaeger")
        jaeger_port = int(os.getenv("OTEL_JAEGER_PORT", "6831"))

        # Create resource with service name
        resource = Resource.create({"service.name": service_name})

        # Create tracer provider
        provider = TracerProvider(resource=resource)

        # Configure Jaeger exporter
        jaeger_exporter = JaegerExporter(
            agent_host_name=jaeger_host,
            agent_port=jaeger_port,
        )

        # Add batch processor for efficient export
        provider.add_span_processor(BatchSpanProcessor(jaeger_exporter))

        # Set as global tracer provider
        trace.set_tracer_provider(provider)

        # Instrument Django (auto-traces all HTTP requests)
        DjangoInstrumentor().instrument()

        # Instrument Celery (auto-traces task execution)
        CeleryInstrumentor().instrument()

        logger.info(
            "OpenTelemetry tracing initialized: Jaeger at %s:%s, service=%s",
            jaeger_host, jaeger_port, service_name,
        )

    except ImportError as e:
        logger.warning("OpenTelemetry packages not installed: %s", str(e))
    except Exception as e:
        logger.error("Failed to initialize OpenTelemetry: %s", str(e))
