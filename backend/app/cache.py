"""Shared cache and coordination state.

`RedisCache` lets several app processes share seller answers, trip pages, the circuit breaker,
request pacing and job leadership. `MemoryCache` has the same interface for one process
(development, tests, or running without Redis).

Values are bytes. Every key gets the `prefix`, so one Redis can serve several deployments.
"""
from __future__ import annotations

import logging
import time
from collections import OrderedDict
from typing import Protocol

log = logging.getLogger("torobticket")


class Cache(Protocol):
    kind: str

    async def get(self, key: str) -> bytes | None: ...
    async def get_many(self, keys: list[str]) -> list[bytes | None]: ...
    async def set(self, key: str, value: bytes, ttl: float) -> None: ...
    async def set_many(self, items: dict[str, bytes], ttl: float) -> None: ...
    async def delete(self, key: str) -> None: ...
    async def add(self, key: str, value: bytes, ttl: float) -> bool:
        """Set only if absent (a lock / lease). True if this caller got it."""
    async def incr(self, key: str, ttl: float) -> int: ...
    async def next_slot(self, key: str, interval: float) -> float:
        """Reserve the next request slot `interval` seconds after the previous one.
        Returns how many seconds the caller must wait before starting."""
    async def ping(self) -> bool: ...
    async def close(self) -> None: ...


class MemoryCache:
    kind = "memory"

    def __init__(self, max_entries: int = 20000):
        self.max_entries = max_entries
        self._d: OrderedDict[str, tuple[float, bytes]] = OrderedDict()

    def __len__(self):
        return len(self._d)

    def _live(self, key: str) -> bytes | None:
        hit = self._d.get(key)
        if hit is None:
            return None
        if hit[0] <= time.monotonic():
            del self._d[key]
            return None
        return hit[1]

    def _put(self, key: str, value: bytes, ttl: float):
        self._d.pop(key, None)
        self._d[key] = (time.monotonic() + ttl, value)
        if len(self._d) > self.max_entries:
            now = time.monotonic()
            for k in [k for k, (exp, _) in self._d.items() if exp <= now]:
                del self._d[k]
            while len(self._d) > self.max_entries:  # still full: drop the oldest writes
                self._d.popitem(last=False)

    async def get(self, key):
        return self._live(key)

    async def get_many(self, keys):
        return [self._live(k) for k in keys]

    async def set(self, key, value, ttl):
        self._put(key, value, ttl)

    async def set_many(self, items, ttl):
        for k, v in items.items():
            self._put(k, v, ttl)

    async def delete(self, key):
        self._d.pop(key, None)

    async def add(self, key, value, ttl):
        if self._live(key) is not None:
            return False
        self._put(key, value, ttl)
        return True

    async def incr(self, key, ttl):
        n = int(self._live(key) or 0) + 1
        self._put(key, str(n).encode(), ttl)
        return n

    async def next_slot(self, key, interval):
        now = time.monotonic()
        slot = max(now, float(self._live(key) or 0))
        self._put(key, repr(slot + interval).encode(), slot + interval - now + 1)
        return slot - now

    async def ping(self):
        return True

    async def close(self):
        pass


# Pacing must be atomic across processes. Redis TIME keeps every process on one clock.
_NEXT_SLOT = """
local t = redis.call('TIME')
local now = tonumber(t[1]) + tonumber(t[2]) / 1000000
local iv = tonumber(ARGV[1])
local slot = math.max(now, tonumber(redis.call('GET', KEYS[1]) or '0'))
redis.call('SET', KEYS[1], tostring(slot + iv), 'PX', math.ceil((slot + iv - now) * 1000) + 1000)
return tostring(slot - now)
"""


class RedisCache:
    """Redis-backed cache. A Redis outage degrades to cache misses instead of failing requests."""

    kind = "redis"

    def __init__(self, url: str, prefix: str = "tt:"):
        import redis.asyncio as redis  # optional dependency

        self.url, self.prefix = url, prefix
        self.r = redis.from_url(url, socket_timeout=2, socket_connect_timeout=2,
                                health_check_interval=30)
        self._slot = self.r.register_script(_NEXT_SLOT)
        self._warned = 0.0

    def _k(self, key: str) -> str:
        return self.prefix + key

    def _down(self, e: Exception):
        if time.monotonic() - self._warned > 30:  # don't flood the log while Redis is down
            self._warned = time.monotonic()
            log.warning("redis unavailable, continuing without the shared cache: %r", e)

    @staticmethod
    def _ms(ttl: float) -> int:
        return max(1, int(ttl * 1000))

    async def get(self, key):
        try:
            return await self.r.get(self._k(key))
        except Exception as e:
            self._down(e)
            return None

    async def get_many(self, keys):
        if not keys:
            return []
        try:
            return await self.r.mget([self._k(k) for k in keys])
        except Exception as e:
            self._down(e)
            return [None] * len(keys)

    async def set(self, key, value, ttl):
        try:
            await self.r.set(self._k(key), value, px=self._ms(ttl))
        except Exception as e:
            self._down(e)

    async def set_many(self, items, ttl):
        if not items:
            return
        try:
            async with self.r.pipeline(transaction=False) as p:
                for k, v in items.items():
                    p.set(self._k(k), v, px=self._ms(ttl))
                await p.execute()
        except Exception as e:
            self._down(e)

    async def delete(self, key):
        try:
            await self.r.delete(self._k(key))
        except Exception as e:
            self._down(e)

    async def add(self, key, value, ttl):
        try:
            return bool(await self.r.set(self._k(key), value, px=self._ms(ttl), nx=True))
        except Exception as e:
            self._down(e)
            return True  # without Redis every process acts alone, as if it held the lease

    async def incr(self, key, ttl):
        try:
            async with self.r.pipeline(transaction=True) as p:
                p.incr(self._k(key))
                p.pexpire(self._k(key), self._ms(ttl))
                n, _ = await p.execute()
            return int(n)
        except Exception as e:
            self._down(e)
            return 1

    async def next_slot(self, key, interval):
        try:
            return max(0.0, float(await self._slot(keys=[self._k(key)], args=[interval])))
        except Exception as e:
            self._down(e)
            return 0.0

    async def ping(self):
        try:
            return bool(await self.r.ping())
        except Exception:
            return False

    async def close(self):
        await self.r.aclose()


def build_cache(url: str | None = None, prefix: str = "tt:") -> Cache:
    if url:
        return RedisCache(url, prefix)
    return MemoryCache()
