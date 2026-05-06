"""Liveness and readiness endpoints."""

import asyncio

from fastapi import APIRouter, Response, status

from app.cache import cache
from app.firestore_client import ping as firestore_ping

router = APIRouter(tags=["health"])


@router.get("/livez")
async def livez() -> dict:
    """Liveness -- process is up. Does NOT check backing services."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(response: Response) -> dict:
    """
    Readiness.

    Firestore is required: if it's down the service returns 503.
    Redis is best-effort: if it's down the service still serves traffic
    (falling back to Firestore on every lookup) and reports 200 with
    status=degraded so dashboards can flag the cache outage.
    """
    firestore_ok, redis_ok = await asyncio.gather(
        firestore_ping(),
        cache.ping(),
    )

    details = {
        "firestore": "ok" if firestore_ok else "unreachable",
        "redis": "ok" if redis_ok else "unreachable",
    }

    if not firestore_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "degraded", "details": details}

    if not redis_ok:
        return {"status": "degraded", "details": details}

    return {"status": "ok", "details": details}
