from __future__ import annotations

import logging
from typing import cast

import redis

from app.core.config import settings

logger = logging.getLogger(__name__)

_client: redis.Redis | None = None


def get_client() -> redis.Redis | None:
    """Lazily construct a shared Redis client.

    `redis.Redis.from_url` only parses the URL and builds a connection pool —
    it never opens a socket, so this itself can't fail on a down Redis. Each
    actual command in cache_get/cache_set catches its own exception, so a
    transient Redis outage degrades that one call to "no cache" without
    poisoning the client for the rest of the process's lifetime.
    """
    global _client
    if _client is None:
        _client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _client


def cache_get(key: str) -> str | None:
    client = get_client()
    if client is None:
        return None
    try:
        # redis-py's stubs type .get() as the shared sync/async ResponseT
        # (Union[Awaitable[Any], Any]) since sync and async clients share a
        # command mixin. This client is always the sync one constructed in
        # get_client(), with decode_responses=True, so the real runtime type
        # is str | None.
        return cast("str | None", client.get(key))
    except Exception as e:
        logger.warning(f"Redis GET failed for {key!r}: {e}")
        return None


def cache_set(key: str, value: str, ttl_seconds: int) -> None:
    client = get_client()
    if client is None:
        return
    try:
        client.setex(key, ttl_seconds, value)
    except Exception as e:
        logger.warning(f"Redis SETEX failed for {key!r}: {e}")
