"""
Read-through cache for short-code lookups.

This module owns the graceful-degradation contract: every Redis exception is
caught internally and converted into a cache-miss result. Callers see a simple
async API where errors and misses are indistinguishable -- so a route handler
can treat a Redis outage the same as a normal cache miss and fall through to
Firestore. Redis going down therefore cannot surface as a user-facing failure.

OTel counters (cache.hits / cache.misses) are initialised in Cache.init()
after the global MeterProvider is configured by setup_observability().
"""

import logging
from typing import Any

import redis.asyncio as redis_async
from redis.exceptions import RedisError

from app.config import settings

logger = logging.getLogger(__name__)


class Cache:
    """Best-effort async Redis cache. All public methods are no-throw."""

    def __init__(self) -> None:
        self._client: redis_async.Redis | None = None
        self._enabled: bool = False
        # OTel counters — set in init() after MeterProvider is configured
        self._hits: Any = None
        self._misses: Any = None

    async def init(self) -> None:
        """
        Initialize OTel meters, then the Redis connection pool, then probe with PING.
        Non-fatal: if anything fails the cache is left disabled and the
        service continues running against Firestore alone.
        """
        # Wire up OTel counters now that the global MeterProvider is configured.
        try:
            from opentelemetry import metrics

            meter = metrics.get_meter(__name__)
            self._hits = meter.create_counter(
                "cache.hits",
                description="Number of Redis cache hits",
            )
            self._misses = meter.create_counter(
                "cache.misses",
                description="Number of Redis cache misses",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("cache metrics init failed: %s", exc)

        if not settings.redis_host:
            logger.info("REDIS_HOST not set; cache disabled")
            return

        try:
            self._client = redis_async.Redis(
                host=settings.redis_host,
                port=settings.redis_port,
                password=settings.redis_auth or None,
                db=0,
                socket_connect_timeout=2,
                socket_timeout=1,
                decode_responses=True,
                max_connections=10,
            )
            await self._client.ping()
            self._enabled = True
            logger.info(
                "redis cache connected host=%s port=%s",
                settings.redis_host,
                settings.redis_port,
            )
        except (RedisError, OSError) as e:
            logger.warning("redis init failed; cache disabled: %s", e)
            self._client = None
            self._enabled = False

    async def get(self, code: str) -> str | None:
        """Return cached long_url, or None on miss / error."""
        if not self._enabled or self._client is None:
            return None
        try:
            value = await self._client.get(code)
            if value:
                if self._hits is not None:
                    self._hits.add(1, {"code": code})
                return value
            if self._misses is not None:
                self._misses.add(1, {"code": code})
            return None
        except (RedisError, OSError) as e:
            logger.warning("cache get failed code=%s err=%s", code, e)
            return None

    async def set(self, code: str, value: str) -> bool:
        """Best-effort SETEX. Returns True on success, False on any error."""
        if not self._enabled or self._client is None:
            return False
        try:
            await self._client.set(code, value, ex=settings.cache_ttl_seconds)
            return True
        except (RedisError, OSError) as e:
            logger.warning("cache set failed code=%s err=%s", code, e)
            return False

    async def ping(self) -> bool:
        """Return True if Redis is reachable. Used by /readyz."""
        if not self._enabled or self._client is None:
            return False
        try:
            await self._client.ping()
            return True
        except (RedisError, OSError):
            return False

    async def close(self) -> None:
        """Close the connection pool. Safe to call if not initialized."""
        if self._client is None:
            return
        try:
            await self._client.aclose()
        except (RedisError, OSError) as e:
            logger.warning("redis close failed: %s", e)


# Singleton -- imported by main, routes, and health.
cache = Cache()
