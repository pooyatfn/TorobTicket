"""Postgres store, Redis cache, multi-process coordination and the response-time features.

Postgres and Redis tests run when these are set (CI sets them; they are skipped otherwise):
  TORUB_TEST_DATABASE_URL=postgresql://user@host:5432/db
  TORUB_TEST_REDIS_URL=redis://host:6379/15
"""
import asyncio
import json
import os
import time
import uuid
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.cache import MemoryCache, RedisCache
from app.main import create_app
from app.models import AlertIn, Flight, Offer, SearchQuery
from app.providers.base import poll_delay
from app.service import SearchService
from app.store import PgStore, Store, open_store

PG = os.getenv("TORUB_TEST_DATABASE_URL")
REDIS = os.getenv("TORUB_TEST_REDIS_URL")
needs_pg = pytest.mark.skipif(not PG, reason="TORUB_TEST_DATABASE_URL not set")
needs_redis = pytest.mark.skipif(not REDIS, reason="TORUB_TEST_REDIS_URL not set")

D = (date.today() + timedelta(days=3)).isoformat()
Q = SearchQuery(origin="THR", destination="MHD", date=D)


def trip(seller: str, number: str, price: int) -> Flight:
    return Flight(id="", airline="A", airline_code="A", flight_number=number, origin="THR", destination="MHD",
                  departure=datetime.fromisoformat(D + "T08:00"), arrival=datetime.fromisoformat(D + "T09:30"),
                  offers=[Offer(seller=seller, price=price, url="https://example.com")])


class Seller:
    def __init__(self, name, delay=0.0, flights=None):
        self.name, self.delay, self.calls = name, delay, 0
        self.flights = flights if flights is not None else [trip(name, "100", 1_000_000)]

    async def search(self, q):
        self.calls += 1
        await asyncio.sleep(self.delay)
        return [f.model_copy(deep=True) for f in self.flights]


def svc(tmp_path, providers, **kw):
    return SearchService(providers, Store(str(tmp_path / f"{uuid.uuid4().hex}.db")), **kw)


# ---------------- streaming: fast sellers first
def test_stream_yields_fast_seller_before_slow_one(tmp_path):
    fast = Seller("fast", 0.0, [trip("fast", "100", 1_000_000)])
    slow = Seller("slow", 0.3, [trip("slow", "100", 900_000), trip("slow", "200", 1_200_000)])
    s = svc(tmp_path, [fast, slow])

    async def go():
        out = []
        t0 = time.monotonic()
        async for r in s.search_stream(Q):
            out.append((time.monotonic() - t0, r))
        return out

    events = asyncio.run(go())
    assert len(events) == 2
    (t1, first), (t2, last) = events
    assert t1 < 0.15 and t2 >= 0.3
    assert not first.done and first.pending == ["slow"] and list(first.providers) == ["fast"]
    assert [f.min_price for f in first.flights] == [1_000_000]
    assert last.done and last.pending == [] and list(last.providers) == ["fast", "slow"]
    assert [f.min_price for f in last.flights] == [900_000, 1_200_000]
    assert last.flights[0].seller_count == 2  # merged across sellers


def test_plain_search_returns_only_the_final_answer(tmp_path):
    s = svc(tmp_path, [Seller("a"), Seller("b", 0.05)])
    r = asyncio.run(s.search(Q))
    assert r.done and r.pending == [] and set(r.providers) == {"a", "b"}


def test_abandoned_stream_still_finishes_and_records(tmp_path):
    slow = Seller("slow", 0.2)
    s = svc(tmp_path, [Seller("fast"), slow])

    async def go():
        async for r in s.search_stream(Q):
            break  # the visitor leaves after the first event
        await s.drain()
        return await s.store.history(r.flights[0].id)

    assert len(asyncio.run(go())) == 1 and slow.calls == 1
    # the slow seller's answer was cached for the next visitor
    assert asyncio.run(s.search(Q)).providers["slow"].cached and slow.calls == 1


def test_sse_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("TORUB_PROVIDERS", "demo")
    with TestClient(create_app(str(tmp_path / "t.db"), alert_interval=0, watch_interval=0, redis_url="")) as c:
        with c.stream("GET", "/api/search/stream", params={"origin": "THR", "destination": "MHD", "date": D}) as r:
            assert r.headers["content-type"].startswith("text/event-stream")
            assert "content-encoding" not in r.headers  # never gzip a stream
            events = [json.loads(line[6:]) for line in r.iter_lines() if line.startswith("data: ")]
        assert events and events[-1]["done"] and events[-1]["flights"]
        assert c.get("/api/search/stream", params={"origin": "THR", "destination": "THR", "date": D}).status_code == 422


# ---------------- stale-while-revalidate and write-behind
def test_stale_while_revalidate_answers_instantly_and_refreshes(tmp_path):
    p = Seller("p", 0.2)
    s = svc(tmp_path, [p], cache_ttl=0.05, swr_ttl=60)

    async def go():
        await s.search(Q)
        await asyncio.sleep(0.1)  # past cache_ttl, within swr_ttl
        t0 = time.monotonic()
        r = await s.search(Q)
        took = time.monotonic() - t0
        await s.drain()
        return r, took

    r, took = asyncio.run(go())
    st = r.providers["p"]
    assert took < 0.1 and st.cached and st.refreshing and st.age is not None
    assert p.calls == 2  # refreshed in the background


def test_write_behind_records_after_answering(tmp_path):
    s = svc(tmp_path, [Seller("p")], write_behind=True)

    async def go():
        r = await s.search(Q)
        await s.drain()
        return await s.store.history(r.flights[0].id)

    assert len(asyncio.run(go())) == 1


def test_trip_lookup_is_served_from_cache(tmp_path):
    s = svc(tmp_path, [Seller("p")])
    r = asyncio.run(s.search(Q))
    t, q = asyncio.run(s.get_trip(r.flights[0].id))
    assert t.min_price == 1_000_000 and q == Q
    assert asyncio.run(s.get_trip("nope")) is None


# ---------------- several processes sharing one cache
def _shared(tmp_path, cache, provider, **kw):
    """Two SearchService instances on one cache behave like two app processes on one Redis."""
    return [svc(tmp_path, [provider], cache=cache, **kw) for _ in range(2)]


@pytest.fixture(params=["memory", pytest.param("redis", marks=needs_redis)])
def shared_cache(request):
    if request.param == "memory":
        return lambda: MemoryCache()
    return lambda: RedisCache(REDIS, prefix=f"test:{uuid.uuid4().hex}:")


def test_two_processes_share_one_seller_call(tmp_path, shared_cache):
    p = Seller("p", 0.3)

    async def go():
        a, b = _shared(tmp_path, shared_cache(), p)
        # different service objects, so only the shared lease can stop the second call
        ra, rb = await asyncio.gather(a.search(Q), b.search(Q))
        await a.cache.close()
        return ra, rb

    ra, rb = asyncio.run(go())
    assert p.calls == 1 and ra.flights[0].id == rb.flights[0].id


def test_breaker_is_shared(tmp_path, shared_cache):
    class Down(Seller):
        async def search(self, q):
            self.calls += 1
            raise RuntimeError("down")

    p = Down("down")

    async def go():
        a, b = _shared(tmp_path, shared_cache(), p, retries=0, fail_threshold=2)
        await a.search(Q)
        await b.search(Q)  # second failure, counted across processes: breaker opens
        r = await a.search(Q)
        st = await b.provider_status()
        await a.cache.close()
        return r, st

    r, st = asyncio.run(go())
    assert p.calls == 2 and r.providers["down"].error == "circuit_open" and st["down"]["state"] == "open"


def test_pacing_is_shared(tmp_path, shared_cache):
    p = Seller("p")
    p.min_interval = 0.15

    async def go():
        a, b = _shared(tmp_path, shared_cache(), p)
        t0 = time.monotonic()
        await asyncio.gather(a.search(Q), b.search(SearchQuery(origin="THR", destination="SYZ", date=D)))
        await a.cache.close()
        return time.monotonic() - t0

    assert asyncio.run(go()) >= 0.14  # second request waited for the first one's slot


# ---------------- Redis cache
@needs_redis
def test_redis_cache_operations():
    async def go():
        c = RedisCache(REDIS, prefix=f"test:{uuid.uuid4().hex}:")
        assert await c.ping()
        await c.set("a", b"1", 0.2)
        await c.set_many({"b": b"2", "c": b"3"}, 10)
        assert await c.get_many(["a", "b", "x"]) == [b"1", b"2", None]
        assert await c.add("lock", b"me", 10) and not await c.add("lock", b"you", 10)
        assert [await c.incr("n", 10) for _ in range(3)] == [1, 2, 3]
        waits = [await c.next_slot("slot", 0.5) for _ in range(3)]
        assert waits[0] == 0 and 0.4 < waits[1] <= 0.5 and 0.9 < waits[2] <= 1.0
        await asyncio.sleep(0.25)
        assert await c.get("a") is None  # expired
        await c.delete("b")
        assert await c.get("b") is None
        await c.close()
    asyncio.run(go())


def test_redis_outage_degrades_to_cache_misses(tmp_path):
    async def go():
        c = RedisCache("redis://127.0.0.1:1/0")  # nothing listens there
        s = SearchService([Seller("p")], Store(str(tmp_path / "x.db")), cache=c)
        r = await s.search(Q)
        await c.close()
        return r
    r = asyncio.run(go())
    assert r.providers["p"].ok and r.flights


# ---------------- Postgres store
@pytest.fixture
def pg():
    async def make(demo=False):
        st = PgStore(PG, demo_history=demo)
        p = await st.pool()
        await p.execute("TRUNCATE history; TRUNCATE alerts RESTART IDENTITY")
        return st
    return make


@needs_pg
def test_pg_history_dedupes_and_batches(pg):
    async def go():
        st = await pg()
        now = datetime(2026, 1, 1, 12)
        assert await st.record_many([("a", 100), ("b", 200), ("a", 90)], now) == 2  # one row per trip, cheapest
        assert await st.record_many([("a", 90), ("b", 200)], now + timedelta(minutes=10)) == 0  # same price, <1h
        assert await st.record_many([("a", 95)], now + timedelta(minutes=20)) == 1  # price changed
        assert await st.record_many([("a", 95)], now + timedelta(hours=2)) == 1  # an hour later
        h = await st.history("a")
        assert [p.price for p in h] == [90, 95, 95] and h[0].ts == now
        assert await st.purge_history(1, now + timedelta(days=1, minutes=30)) == 3  # a@12:00, b, a@12:20
        await st.close()
    asyncio.run(go())


@needs_pg
def test_pg_demo_backfill(pg):
    async def go():
        st = await pg(demo=True)
        await st.record_many([("t", 1_000_000)])
        await st.record_many([("t", 1_000_000)])
        n = len(await st.history("t"))
        await st.close()
        return n
    assert asyncio.run(go()) == 15  # 14 back-filled days + today, once


@needs_pg
def test_pg_alerts(pg):
    async def go():
        st = await pg()
        a = await st.add_alert(AlertIn(mode="bus", origin="THR", destination="MHD", date=D, target_price=5,
                                       contact="۰۹۱۲۱۲۳۴۵۶۷"))
        b = await st.add_alert(AlertIn(origin="THR", destination="SYZ", date=D, target_price=9, contact="a@b.co"))
        assert a.id == 1 and a.mode == "bus" and a.contact == "09121234567" and a.notified_at is None
        assert [x.id for x in await st.list_alerts()] == [2, 1]
        assert [x.id for x in await st.list_alerts("a@b.co")] == [2]
        await st.mark_alert(1, 4, True)
        await st.mark_alert(1, 3, True)  # the first trigger time is kept
        await st.mark_notified(1)
        x = (await st.list_alerts("09121234567"))[0]
        assert x.last_price == 3 and x.triggered_at and x.notified_at
        assert [x.id for x in await st.list_alerts(pending=True)] == [2]
        assert await st.delete_alert(2) and not await st.delete_alert(2)
        await st.close()
    asyncio.run(go())


@needs_pg
def test_pg_schema_creation_is_safe_from_several_processes():
    async def go():
        stores = [PgStore(PG) for _ in range(4)]
        ok = await asyncio.gather(*(s.ping() for s in stores))
        for s in stores:
            await s.close()
        return ok
    assert asyncio.run(go()) == [True] * 4


@needs_pg
@needs_redis
def test_app_on_postgres_and_redis(monkeypatch):
    monkeypatch.setenv("TORUB_PROVIDERS", "demo")
    monkeypatch.setenv("TORUB_REDIS_PREFIX", f"test:{uuid.uuid4().hex}:")
    with TestClient(create_app(PG, alert_interval=0, watch_interval=0, redis_url=REDIS)) as c:
        h = c.get("/api/health", params={"deep": 1}).json()
        assert h == {"status": "ok", "store": "postgres", "cache": "redis", "store_ok": True, "cache_ok": True}
        r = c.get("/api/search", params={"origin": "THR", "destination": "MHD", "date": D})
        assert r.headers.get("content-encoding") == "gzip"
        tid = r.json()["flights"][0]["id"]
        assert c.get(f"/api/trips/{tid}").json()["trip"]["id"] == tid
        a = c.post("/api/alerts", json={"origin": "THR", "destination": "MHD", "date": D, "target_price": 1,
                                        "contact": "a@b.co"}).json()
        assert c.get("/api/alerts", params={"contact": "a@b.co"}).json()[0]["id"] == a["id"]
    with TestClient(create_app(PG, alert_interval=0, watch_interval=0, redis_url=REDIS)) as c2:
        assert c2.get(f"/api/trips/{tid}").status_code == 200  # another process sees the trip
        assert len(c2.get(f"/api/trips/{tid}/history").json()) >= 1


# ---------------- small pieces
def test_open_store_picks_backend(tmp_path):
    assert isinstance(open_store("postgresql://u@h/db"), PgStore)
    assert isinstance(open_store(str(tmp_path / "x.db")), Store)


def test_poll_delay_starts_short():
    assert [round(poll_delay(1.0, n), 2) for n in range(5)] == [0.25, 0.4, 0.5, 0.5, 0.5]
    assert poll_delay(0, 3) == 0


def test_health_and_gzip_on_sqlite(tmp_path, monkeypatch):
    monkeypatch.setenv("TORUB_PROVIDERS", "demo")
    with TestClient(create_app(str(tmp_path / "t.db"), alert_interval=0, watch_interval=0, redis_url="")) as c:
        assert c.get("/api/health", params={"deep": 1}).json()["store"] == "sqlite"
        r = c.get("/api/search", params={"origin": "THR", "destination": "MHD", "date": D})
        assert r.headers.get("content-encoding") == "gzip" and r.json()["done"] is True


def test_memory_cache_basics():
    async def go():
        c = MemoryCache(max_entries=3)
        assert await c.add("k", b"1", 10) and not await c.add("k", b"2", 10)
        for i in range(5):
            await c.set(f"x{i}", b"v", 10)
        assert len(c) == 3
        assert await c.next_slot("s", 0.2) == 0 and 0.15 < await c.next_slot("s", 0.2) <= 0.2
    asyncio.run(go())


@needs_pg
def test_migrate_sqlite_to_postgres(tmp_path, pg):
    from app.migrate import migrate

    async def go():
        src = Store(str(tmp_path / "old.db"))
        await src.record_many([("a", 100), ("b", 200)], datetime(2026, 1, 1))
        await src.add_alert(AlertIn(origin="THR", destination="MHD", date=D, target_price=5, contact="a@b.co"))
        await src.add_alert(AlertIn(mode="train", origin="THR", destination="MHD", date=D, target_price=6,
                                    contact="a@b.co"))
        await src.close()
        await (await pg()).close()  # empty tables
        n = await migrate(str(tmp_path / "old.db"), PG)
        st = PgStore(PG)
        new = await st.add_alert(AlertIn(origin="THR", destination="SYZ", date=D, target_price=7, contact="c@d.co"))
        out = n, [p.price for p in await st.history("b")], sorted(a.mode for a in await st.list_alerts("a@b.co")), new.id
        with pytest.raises(SystemExit):  # refuses to copy twice
            await migrate(str(tmp_path / "old.db"), PG)
        await st.close()
        return out

    assert asyncio.run(go()) == ((2, 2), [200], ["flight", "train"], 3)
