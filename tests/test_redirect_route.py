"""
Route-level tests for the redirect endpoint.

These tests verify the graceful-degradation contract at the HTTP boundary:
a Redis outage (or a cold cache) must still produce a 302, never a 5xx.

TestClient triggers the FastAPI lifespan. The lifespan initialises the cache
(which stays disabled — no REDIS_HOST in the test env) and sets up OTel
providers (which fall back to no-ops without GCP credentials). All Firestore
and Redis interactions are patched at the route-module boundary.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    """Single TestClient for the module — lifespan runs once."""
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FIRESTORE_PATCH = "app.routes.redirect.get_long_url"
_CLICK_PATCH = "app.routes.redirect.increment_click_count"
_CACHE_GET_PATCH = "app.routes.redirect.cache.get"
_CACHE_SET_PATCH = "app.routes.redirect.cache.set"


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


def test_cache_miss_falls_through_to_firestore(client: TestClient) -> None:
    """Cache miss → Firestore hit → 302 with correct Location."""
    with (
        patch(_CACHE_GET_PATCH, AsyncMock(return_value=None)),
        patch(_CACHE_SET_PATCH, AsyncMock(return_value=True)),
        patch(_FIRESTORE_PATCH, AsyncMock(return_value="https://example.com")),
        patch(_CLICK_PATCH, AsyncMock()),
    ):
        r = client.get("/abc12345", follow_redirects=False)

    assert r.status_code == 302
    assert r.headers["location"] == "https://example.com"


def test_cache_hit_skips_firestore(client: TestClient) -> None:
    """Cache hit → 302 and Firestore is never called."""
    mock_fs = AsyncMock(return_value="https://cached.example.com")
    with (
        patch(_CACHE_GET_PATCH, AsyncMock(return_value="https://cached.example.com")),
        patch(_FIRESTORE_PATCH, mock_fs),
        patch(_CLICK_PATCH, AsyncMock()),
    ):
        r = client.get("/abc12345", follow_redirects=False)

    assert r.status_code == 302
    assert r.headers["location"] == "https://cached.example.com"
    mock_fs.assert_not_called()


# ---------------------------------------------------------------------------
# Graceful-degradation: Redis broken but redirect still works
# ---------------------------------------------------------------------------


def test_broken_redis_still_produces_302(client: TestClient) -> None:
    """
    Simulate a broken Redis: cache.get returns None (as Cache.get() does on
    any RedisError) and cache.set returns False. The redirect must still work
    via Firestore — this is the primary graceful-degradation assertion.
    """
    with (
        patch(_CACHE_GET_PATCH, AsyncMock(return_value=None)),
        patch(_CACHE_SET_PATCH, AsyncMock(return_value=False)),
        patch(_FIRESTORE_PATCH, AsyncMock(return_value="https://example.com")),
        patch(_CLICK_PATCH, AsyncMock()),
    ):
        r = client.get("/abc12345", follow_redirects=False)

    assert r.status_code == 302
    assert r.headers["location"] == "https://example.com"


# ---------------------------------------------------------------------------
# 404 path
# ---------------------------------------------------------------------------


def test_code_not_found_returns_404(client: TestClient) -> None:
    """Code missing from both cache and Firestore → 404, not 5xx."""
    with (
        patch(_CACHE_GET_PATCH, AsyncMock(return_value=None)),
        patch(_FIRESTORE_PATCH, AsyncMock(return_value=None)),
        patch(_CLICK_PATCH, AsyncMock()),
    ):
        r = client.get("/deadcode", follow_redirects=False)

    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Health probes (sanity — must not be swallowed by the /{code} catch-all)
# ---------------------------------------------------------------------------


def test_livez_returns_200(client: TestClient) -> None:
    assert client.get("/livez").status_code == 200


def test_readyz_returns_200_or_503(client: TestClient) -> None:
    """readyz probes backing services; in tests Firestore is unreachable → 503."""
    r = client.get("/readyz")
    assert r.status_code in (200, 503)
