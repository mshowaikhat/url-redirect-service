"""FastAPI application entrypoint."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.cache import cache
from app.config import settings
from app.routes import health, redirect

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown hooks (replaces deprecated @app.on_event)."""
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
