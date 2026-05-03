"""Liveness and readiness endpoints."""

from fastapi import APIRouter, Response, status

from app.firestore_client import ping

router = APIRouter(tags=["health"])


@router.get("/livez")
async def livez() -> dict:
    """Liveness — process is up. Does NOT check Firestore."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(response: Response) -> dict:
    """Readiness — true only if Firestore is reachable."""
    firestore_ok = await ping()
    if not firestore_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "degraded", "details": {"firestore": "unreachable"}}
    return {"status": "ok", "details": {"firestore": "ok"}}