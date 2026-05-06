"""Redirect endpoint."""

import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from fastapi.responses import RedirectResponse

from app.cache import cache
from app.firestore_client import get_long_url, increment_click_count

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/{code}", include_in_schema=True)
async def redirect(code: str, background_tasks: BackgroundTasks):
    """
    Look up the code and return a 302 to the long URL.
    Read-through cache: Redis first, Firestore on miss/error.
    Click counter increments AFTER the response is sent (non-blocking).
    """
    cached_url = await cache.get(code)
    if cached_url:
        background_tasks.add_task(increment_click_count, code)
        logger.info("redirect hit (cache) code=%s", code)
        return RedirectResponse(url=cached_url, status_code=status.HTTP_302_FOUND)

    long_url = await get_long_url(code)
    if long_url is None:
        logger.info("redirect miss code=%s", code)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Short code not found: {code}",
        )

    # Populate cache and increment click count after the response is sent.
    background_tasks.add_task(cache.set, code, long_url)
    background_tasks.add_task(increment_click_count, code)

    logger.info("redirect hit (firestore) code=%s", code)
    return RedirectResponse(url=long_url, status_code=status.HTTP_302_FOUND)
