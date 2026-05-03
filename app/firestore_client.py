"""Firestore client wrapper for the redirect service."""

import asyncio
import logging

from google.cloud import firestore

from app.config import settings

logger = logging.getLogger(__name__)

_client: firestore.Client | None = None


def get_client() -> firestore.Client:
    """Lazy-init Firestore client. Reused across requests."""
    global _client
    if _client is None:
        _client = firestore.Client(project=settings.gcp_project_id)
    return _client


def _collection() -> firestore.CollectionReference:
    return get_client().collection(settings.firestore_collection)


async def get_long_url(code: str) -> str | None:
    """Look up a short code and return its long_url, or None if not found."""

    def _sync() -> str | None:
        doc = _collection().document(code).get()
        if not doc.exists:
            return None
        data = doc.to_dict() or {}
        return data.get("long_url")

    return await asyncio.to_thread(_sync)


async def increment_click_count(code: str) -> None:
    """
    Fire-and-forget click counter. Errors are logged, never raised —
    we never want a counter failure to affect the user-facing redirect.
    """

    def _sync() -> None:
        try:
            _collection().document(code).update(
                {"click_count": firestore.Increment(1)}
            )
        except Exception as e:
            logger.warning("click increment failed for %s: %s", code, e)

    await asyncio.to_thread(_sync)


async def ping() -> bool:
    """Health check — verify we can reach Firestore."""

    def _sync() -> bool:
        list(_collection().limit(1).stream())
        return True

    try:
        return await asyncio.to_thread(_sync)
    except Exception:
        return False