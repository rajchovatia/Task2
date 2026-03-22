from .celery import app as celery_app
from .tracing import setup_tracing

# Initialize OpenTelemetry tracing (if OTEL_ENABLED=True)
setup_tracing()

__all__ = ("celery_app",)
