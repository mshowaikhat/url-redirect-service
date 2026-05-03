"""FastAPI application entrypoint."""

import logging

from fastapi import FastAPI

from app.config import settings
from app.routes import health, redirect

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="URL Redirect Service",
    description="Resolves short codes to long URLs via HTTP 302.",
    version="1.0.0",
)

# IMPORTANT: register health routes FIRST.
# The redirect router uses /{code} which would otherwise match /livez, /readyz.
app.include_router(health.router)
app.include_router(redirect.router)


@app.on_event("startup")
async def on_startup() -> None:
    logger.info(
        "redirect starting: project=%s collection=%s emulator=%s",
        settings.gcp_project_id,
        settings.firestore_collection,
        settings.firestore_emulator_host or "none",
    )


@app.on_event("shutdown")
async def on_shutdown() -> None:
    logger.info("redirect shutting down")