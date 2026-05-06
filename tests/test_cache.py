"""
Unit tests for app.cache.Cache.

Core contract: every Redis failure returns a safe default (None / False)
and never raises an exception to the caller. All tests use AsyncMock to
inject failures without requiring a real Redis instance.
"""

from unittest.mock import AsyncMock, patch

import pytest
from redis.exceptions import RedisError

from app.cache import Cache


@pytest.fixture
def live_cache() -> Cache:
    """Cache instance in the 'connected' state with a mock Redis client."""
    c = Cache()
    c._enabled = True
    c._client = AsyncMock()
    return c


# ---------------------------------------------------------------------------
# Cache.get
# ---------------------------------------------------------------------------


async def test_get_hit_returns_value(live_cache: Cache) -> None:
    live_cache._client.get = AsyncMock(return_value="https://example.com")
    assert await live_cache.get("abc12345") == "https://example.com"


async def test_get_miss_returns_none(live_cache: Cache) -> None:
    live_cache._client.get = AsyncMock(return_value=None)
    assert await live_cache.get("abc12345") is None


async def test_get_redis_error_returns_none(live_cache: Cache) -> None:
    live_cache._client.get = AsyncMock(side_effect=RedisError("boom"))
    assert await live_cache.get("abc12345") is None  # must not raise


async def test_get_os_error_returns_none(live_cache: Cache) -> None:
    live_cache._client.get = AsyncMock(side_effect=OSError("network gone"))
    assert await live_cache.get("abc12345") is None  # must not raise


async def test_get_disabled_returns_none() -> None:
    c = Cache()  # _enabled=False by default
    assert await c.get("abc12345") is None


# ---------------------------------------------------------------------------
# Cache.set
# ---------------------------------------------------------------------------


async def test_set_success_returns_true(live_cache: Cache) -> None:
    live_cache._client.set = AsyncMock(return_value=True)
    assert await live_cache.set("abc12345", "https://example.com") is True


async def test_set_redis_error_returns_false(live_cache: Cache) -> None:
    live_cache._client.set = AsyncMock(side_effect=RedisError("boom"))
    assert await live_cache.set("abc12345", "https://example.com") is False  # must not raise


async def test_set_os_error_returns_false(live_cache: Cache) -> None:
    live_cache._client.set = AsyncMock(side_effect=OSError("network gone"))
    assert await live_cache.set("abc12345", "https://example.com") is False


async def test_set_disabled_returns_false() -> None:
    c = Cache()
    assert await c.set("abc12345", "https://example.com") is False


# ---------------------------------------------------------------------------
# Cache.ping
# ---------------------------------------------------------------------------


async def test_ping_reachable(live_cache: Cache) -> None:
    live_cache._client.ping = AsyncMock(return_value=True)
    assert await live_cache.ping() is True


async def test_ping_redis_error_returns_false(live_cache: Cache) -> None:
    live_cache._client.ping = AsyncMock(side_effect=RedisError("timeout"))
    assert await live_cache.ping() is False  # must not raise


async def test_ping_disabled_returns_false() -> None:
    c = Cache()
    assert await c.ping() is False


# ---------------------------------------------------------------------------
# Cache.init — connection lifecycle
# ---------------------------------------------------------------------------


async def test_init_no_redis_host_leaves_disabled() -> None:
    """When REDIS_HOST is unset the cache must stay disabled (graceful no-op)."""
    c = Cache()
    with patch("app.cache.settings") as mock_settings:
        mock_settings.redis_host = None
        await c.init()
    assert c._enabled is False
    assert c._client is None


async def test_init_connection_refused_leaves_disabled() -> None:
    """When Redis refuses the connection, cache stays disabled and no exception escapes."""
    c = Cache()
    mock_client = AsyncMock()
    mock_client.ping = AsyncMock(side_effect=RedisError("Connection refused"))

    with (
        patch("app.cache.settings") as mock_settings,
        patch("app.cache.redis_async.Redis", return_value=mock_client),
    ):
        mock_settings.redis_host = "127.0.0.1"
        mock_settings.redis_port = 6379
        mock_settings.redis_auth = None
        await c.init()

    assert c._enabled is False


async def test_init_success_enables_cache() -> None:
    """Successful PING during init must set _enabled=True."""
    c = Cache()
    mock_client = AsyncMock()
    mock_client.ping = AsyncMock(return_value=True)

    with (
        patch("app.cache.settings") as mock_settings,
        patch("app.cache.redis_async.Redis", return_value=mock_client),
    ):
        mock_settings.redis_host = "127.0.0.1"
        mock_settings.redis_port = 6379
        mock_settings.redis_auth = None
        await c.init()

    assert c._enabled is True
