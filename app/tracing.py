"""
OpenTelemetry setup: Cloud Trace exporter + Cloud Monitoring metrics exporter.

Both exporters require Application Default Credentials. In Cloud Run they are
available automatically. In local Docker Compose they are not, so each setup
step is wrapped in try/except — a failure logs a warning and the app continues
without traces/metrics (graceful degradation).
"""

import logging

logger = logging.getLogger(__name__)


def setup_observability(service_name: str, project_id: str) -> None:
    """Configure the global OTel TracerProvider and MeterProvider. Call once at startup."""
    _setup_tracing(service_name, project_id)
    _setup_metrics(service_name, project_id)


def _setup_tracing(service_name: str, project_id: str) -> None:
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
        from opentelemetry.propagate import set_global_textmap
        from opentelemetry.propagators.cloud_trace_format import CloudTraceFormatPropagator
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource({"service.name": service_name})
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(
            BatchSpanProcessor(CloudTraceSpanExporter(project_id=project_id))
        )
        trace.set_tracer_provider(provider)
        # Parse X-Cloud-Trace-Context headers (injected by Cloud Run's load balancer)
        set_global_textmap(CloudTraceFormatPropagator())
        logger.info("cloud trace configured service=%s project=%s", service_name, project_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("cloud trace setup skipped (no credentials?): %s", exc)


def _setup_metrics(service_name: str, project_id: str) -> None:
    try:
        from opentelemetry import metrics
        from opentelemetry.exporter.cloud_monitoring import CloudMonitoringMetricsExporter
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource

        resource = Resource({"service.name": service_name})
        exporter = CloudMonitoringMetricsExporter(project_id=project_id)
        reader = PeriodicExportingMetricReader(exporter, export_interval_millis=60_000)
        provider = MeterProvider(resource=resource, metric_readers=[reader])
        metrics.set_meter_provider(provider)
        logger.info(
            "cloud monitoring metrics configured service=%s project=%s",
            service_name,
            project_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("cloud monitoring metrics setup skipped (no credentials?): %s", exc)
