"""
Structured JSON logging for Cloud Logging.

Call setup_logging() once at process start (before any other imports that
emit log records) to replace the default basicConfig handler with a JSON
formatter that Cloud Logging auto-parses.

Fields emitted per record:
  time      — ISO 8601 UTC (Cloud Logging "timestamp" equivalent)
  severity  — uppercase log level (Cloud Logging native field)
  message   — the formatted log message
  service   — OTEL_SERVICE_NAME value ("shortener" or "redirect")
  logging.googleapis.com/trace      — Cloud Trace correlation (when active)
  logging.googleapis.com/spanId     — span ID (when active)
  logging.googleapis.com/traceSampled — sampling flag (when active)
"""

import datetime
import logging

from pythonjsonlogger import jsonlogger


class GcpJsonFormatter(jsonlogger.JsonFormatter):
    """JsonFormatter subclass that emits the field names Cloud Logging expects."""

    def __init__(self, service: str, project_id: str, **kwargs):
        super().__init__(**kwargs)
        self._service = service
        self._project_id = project_id

    def add_fields(
        self,
        log_record: dict,
        record: logging.LogRecord,
        message_dict: dict,
    ) -> None:
        super().add_fields(log_record, record, message_dict)

        # Cloud Logging severity field (replaces levelname)
        log_record["severity"] = record.levelname
        log_record.pop("levelname", None)

        # RFC 3339 / ISO 8601 UTC timestamp
        log_record["time"] = datetime.datetime.fromtimestamp(
            record.created, tz=datetime.UTC
        ).isoformat()
        log_record.pop("asctime", None)

        log_record["service"] = self._service

        # Inject OTel trace context so Cloud Logging links logs to Cloud Trace spans
        try:
            from opentelemetry import trace

            span = trace.get_current_span()
            ctx = span.get_span_context()
            if ctx.is_valid:
                log_record["logging.googleapis.com/trace"] = (
                    f"projects/{self._project_id}/traces/{ctx.trace_id:032x}"
                )
                log_record["logging.googleapis.com/spanId"] = f"{ctx.span_id:016x}"
                log_record["logging.googleapis.com/traceSampled"] = bool(
                    ctx.trace_flags & trace.TraceFlags.SAMPLED
                )
        except Exception:  # noqa: BLE001
            pass  # OTel not available or no active span — trace fields omitted


def setup_logging(service: str, project_id: str, level: str = "INFO") -> None:
    """
    Replace all root logger handlers with a single JSON-to-stdout handler.
    Safe to call multiple times (idempotent: clears existing handlers first).
    """
    handler = logging.StreamHandler()
    handler.setFormatter(GcpJsonFormatter(service=service, project_id=project_id))
    root = logging.getLogger()
    root.setLevel(level.upper())
    root.handlers.clear()
    root.addHandler(handler)
