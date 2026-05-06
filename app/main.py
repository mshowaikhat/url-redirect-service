"""FastAPI application entrypoint."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.cache import cache
from app.config import settings
from app.logging_config import setup_logging
from app.routes import health, redirect
from app.tracing import setup_observability

# Configure JSON logging before any module emits a log record.
setup_logging(
    service=settings.otel_service_name,
    project_id=settings.gcp_project_id,
    level=settings.log_level,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown hooks."""
    # OTel providers must be configured before cache.init() creates meters.
    setup_observability(settings.otel_service_name, settings.gcp_project_id)

    # Auto-instrument FastAPI; relies on TracerProvider being set above.
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
        logger.info("FastAPI OTel instrumentation active")
    except Exception as exc:  # noqa: BLE001
        logger.warning("FastAPI instrumentation skipped: %s", exc)

    logger.info(
        "redirect starting: project=%s collection=%s emulator=%s",
        settings.gcp_project_id,
        settings.firestore_collection,
        settings.firestore_emulator_host or "none",
    )
    await cache.init()
    try:
        yield
    finally:
        logger.info("redirect shutting down")
        await cache.close()


app = FastAPI(
    title="URL Redirect Service",
    description="Resolves short codes to long URLs via HTTP 302.",
    version="1.0.0",
    lifespan=lifespan,
)

# IMPORTANT: register health routes FIRST.
# The redirect router uses /{code} which would otherwise match /livez, /readyz.
app.include_router(health.router)
app.include_router(redirect.router)
