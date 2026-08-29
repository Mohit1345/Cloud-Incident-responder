"""
app/observability.py — OpenTelemetry setup for the Flash-Sale Simulator.
"""
import os
import logging

from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor

logger = logging.getLogger(__name__)


def setup_otel(app):
    """Instrument FastAPI and Redis — must be called at module level, before app starts."""
    FastAPIInstrumentor.instrument_app(app)
    RedisInstrumentor().instrument()


def init_otel_providers():
    """Initialize OTLP exporters — call inside lifespan so each worker creates its own
    gRPC channel after uvicorn forks, avoiding channel inheritance issues."""
    service_name = os.getenv("OTEL_SERVICE_NAME", "flashsale-app")
    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317")
    deployment_env = os.getenv("DEPLOYMENT_ENV", os.getenv("OTEL_ENV", "dev"))

    resource = Resource.create({
        SERVICE_NAME: service_name,
        "deployment.environment": deployment_env,
    })

    # Traces
    trace_provider = TracerProvider(resource=resource)
    trace_exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
    trace_provider.add_span_processor(BatchSpanProcessor(trace_exporter))
    trace.set_tracer_provider(trace_provider)

    # Metrics
    metric_reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=otlp_endpoint, insecure=True),
        export_interval_millis=5000,
    )
    metrics_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(metrics_provider)

    logger.info(
        "OpenTelemetry providers initialized: service=%s env=%s endpoint=%s",
        service_name,
        deployment_env,
        otlp_endpoint,
    )
