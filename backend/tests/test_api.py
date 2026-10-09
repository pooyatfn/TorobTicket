import asyncio
from datetime import date, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models import SearchQuery
from app.providers.http_json import HttpJsonProvider

D = (date.today() + timedelta(days=5)).isoformat()


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(str(tmp_path / "t.db"), alert_interval=0, watch_interval=0)) as c:
        yield c


def test_search_merges_sellers_sorted(client):
    r = client.get("/api/search", params={"origin": "THR", "destination": "MHD", "date": D})
    assert r.status_code == 200
    j = r.json()
    assert j["flights"], "expected flights"
    assert all(s["ok"] for s in j["providers"].values())
    prices = [f["min_price"] for f in j["flights"]]
    assert prices == sorted(prices)
    f = max(j["flights"], key=lambda x: x["seller_count"])
    assert f["seller_count"] >= 2
    assert [o["price"] for o in f["offers"]] == sorted(o["price"] for o in f["offers"])
    assert f["min_price"] == f["offers"][0]["price"]
    assert len({x["id"] for x in j["flights"]}) == len(j["flights"])


def test_search_is_deterministic_and_second_call_is_cached(client):
    p = {"origin": "THR", "destination": "SYZ", "date": D}
    a, b = client.get("/api/search", params=p).json(), client.get("/api/search", params=p).json()
    assert a["flights"] == b["flights"]
    assert not any(s["cached"] for s in a["providers"].values())
    assert all(s["cached"] for s in b["providers"].values())


@pytest.mark.parametrize("p", [
    {"origin": "XXX", "destination": "MHD", "date": D},
    {"origin": "THR", "destination": "THR", "date": D},
    {"origin": "THR", "destination": "MHD", "date": "2020-01-01"},
    {"origin": "THR", "destination": "MHD", "date": "nope"},
    {"origin": "THR", "destination": "MHD", "date": D, "adults": 1, "infants": 2},
])
def test_validation(client, p):
    assert client.get("/api/search", params=p).status_code == 422


def test_history_and_airports(client):
    fid = client.get("/api/search", params={"origin": "THR", "destination": "MHD", "date": D}
                     ).json()["flights"][0]["id"]
    h = client.get(f"/api/flights/{fid}/history").json()
    assert len(h) >= 2
    assert client.get("/api/airports", params={"q": "مشهد"}).json()[0]["code"] == "MHD"


def test_alert_lifecycle(client):
    q = {"origin": "THR", "destination": "MHD", "date": D}
    cheapest = client.get("/api/search", params=q).json()["flights"][0]["min_price"]
    a = client.post("/api/alerts", json={**q, "target_price": cheapest, "contact": "09120000000"}).json()
    assert client.post("/api/alerts", json={**q, "target_price": 0, "contact": "x@y.z"}).status_code == 422
    assert asyncio.run(client.app.state.service.check_alerts()) == 1
    got = client.get("/api/alerts", params={"contact": "09120000000"}).json()
    assert got[0]["triggered_at"] and got[0]["last_price"] == cheapest
    assert client.delete(f"/api/alerts/{a['id']}").status_code == 204
    assert client.delete(f"/api/alerts/{a['id']}").status_code == 404


def test_failing_provider_does_not_break_search(tmp_path):
    app = create_app(str(tmp_path / "t.db"), alert_interval=0, watch_interval=0)

    class Boom:
        name = "boom"

        async def search(self, q):
            raise RuntimeError("down")

    app.state.service.providers.append(Boom())
    with TestClient(app) as c:
        j = c.get("/api/search", params={"origin": "THR", "destination": "MHD", "date": D}).json()
    assert j["providers"]["boom"]["ok"] is False and j["flights"]


def test_http_json_adapter():
    payload = {"data": {"flights": [
        {"airline": {"name": "ماهان", "code": "W5"}, "number": 1101, "departure": "2026-12-01T08:00:00",
         "arrival": "2026-12-01T09:30:00", "price": 2500000, "link": "https://s/1"},
        {"broken": True}]}}
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=payload))
    cfg = {"name": "s", "url": "https://s/search", "items_path": "data.flights",
           "params": {"from": "{origin}"},
           "map": {"airline": "airline.name", "airline_code": "airline.code", "flight_number": "number",
                   "departure": "departure", "arrival": "arrival", "price": "price", "url": "link"}}
    p = HttpJsonProvider(cfg, httpx.AsyncClient(transport=transport))
    fl = asyncio.run(p.search(SearchQuery(origin="THR", destination="MHD", date="2026-12-01")))
    assert len(fl) == 1 and fl[0].offers[0].price == 2500000 and fl[0].duration_minutes == 90


# ---------------- step 2: resilience
from app.providers.mock import MockProvider
from app.service import SearchService
from app.store import Store


class Flaky:
    """Fails the first `fail_times` calls (or always if None), then behaves like a real seller."""
    def __init__(self, name="flaky", fail_times=None):
        self.name, self.calls, self.fail_times = name, 0, fail_times
        self.inner = MockProvider(name)

    async def search(self, q):
        self.calls += 1
        if self.fail_times is None or self.calls <= self.fail_times:
            raise ConnectionError("boom")
        return await self.inner.search(q)


def _svc(tmp_path, providers, **kw):
    kw.setdefault("backoff", 0)
    return SearchService(providers, Store(str(tmp_path / "r.db")), **kw)


Q = SearchQuery(origin="THR", destination="MHD", date=D)


def test_retry_recovers(tmp_path):
    p = Flaky(fail_times=1)
    r = asyncio.run(_svc(tmp_path, [p], retries=1).search(Q))
    assert p.calls == 2 and r.providers["flaky"].ok and r.flights


def test_circuit_breaker_opens_and_skips_calls(tmp_path):
    p = Flaky()
    s = _svc(tmp_path, [p], retries=0, fail_threshold=2, cooldown=60)
    for _ in range(2):
        asyncio.run(s.search(Q))
    assert p.calls == 2 and asyncio.run(s.provider_status())["flaky"]["state"] == "open"
    r = asyncio.run(s.search(Q))
    assert p.calls == 2, "no call while the circuit is open"
    assert r.providers["flaky"].error == "circuit_open" and not r.providers["flaky"].ok


def test_stale_fallback_serves_last_good(tmp_path):
    p = Flaky(fail_times=0)  # healthy at first
    s = _svc(tmp_path, [p], retries=0, cache_ttl=0)
    first = asyncio.run(s.search(Q))
    p.fail_times = None  # now it dies
    second = asyncio.run(s.search(Q))
    st = second.providers["flaky"]
    assert st.ok and st.stale and st.error == "ConnectionError"
    assert [f.id for f in second.flights] == [f.id for f in first.flights]


def test_degraded_answer_is_not_cached(tmp_path):
    p = Flaky(fail_times=1)
    s = _svc(tmp_path, [p], retries=0, cache_ttl=60)
    assert not asyncio.run(s.search(Q)).providers["flaky"].ok
    assert asyncio.run(s.search(Q)).providers["flaky"].ok  # retried, not served from cache


def test_providers_status_endpoint(client):
    client.get("/api/search", params={"origin": "THR", "destination": "MHD", "date": D})
    j = client.get("/api/providers/status").json()
    assert len(j) == 4 and all(v["state"] == "closed" and v["last_ok"] for v in j.values())


# ---------------- step 3: notifications
import sqlite3
from app.models import AlertIn
from app.notify import SmtpNotifier, WebhookNotifier, build_notifiers


@pytest.mark.parametrize("raw,norm", [
    ("09121234567", "09121234567"), ("۰۹۱۲۱۲۳۴۵۶۷", "09121234567"), ("+98 912 123 4567", "09121234567"),
    ("0098-912-123-4567", "09121234567"), ("Me@Example.COM", "me@example.com")])
def test_contact_normalised(raw, norm):
    assert AlertIn(origin="THR", destination="MHD", date=D, target_price=1, contact=raw).contact == norm


@pytest.mark.parametrize("bad", ["12345", "abc", "0912", "a@b", "09121234567890"])
def test_contact_rejected(client, bad):
    r = client.post("/api/alerts", json={"origin": "THR", "destination": "MHD", "date": D,
                                         "target_price": 5, "contact": bad})
    assert r.status_code == 422


class Rec:
    name = "rec"

    def __init__(self, fail=0):
        self.sent, self.fail = [], fail

    def accepts(self, c):
        return True

    async def send(self, a, price):
        if self.fail:
            self.fail -= 1
            raise RuntimeError("gateway down")
        self.sent.append((a.id, price))


def test_alert_delivered_once_and_retried_on_failure(tmp_path):
    rec = Rec(fail=1)
    s = _svc(tmp_path, [MockProvider("a")], notifiers=[rec])
    first = asyncio.run(s.search(Q)).flights[0].min_price
    asyncio.run(s.store.add_alert(AlertIn(origin="THR", destination="MHD", date=D, target_price=first, contact="09121234567")))
    assert asyncio.run(s.check_alerts()) == 0 and rec.sent == []  # delivery failed
    a = asyncio.run(s.store.list_alerts())[0]
    assert a.triggered_at and not a.notified_at
    assert asyncio.run(s.check_alerts()) == 1 and rec.sent == [(a.id, first)]  # retried, same price
    assert asyncio.run(s.check_alerts()) == 0 and len(rec.sent) == 1  # never twice


def test_alert_not_triggered_above_target(tmp_path):
    rec = Rec()
    s = _svc(tmp_path, [MockProvider("a")], notifiers=[rec])
    asyncio.run(s.store.add_alert(AlertIn(origin="THR", destination="MHD", date=D, target_price=1000, contact="a@b.co")))
    assert asyncio.run(s.check_alerts()) == 0 and rec.sent == []
    assert asyncio.run(s.store.list_alerts())[0].last_price and not asyncio.run(s.store.list_alerts())[0].triggered_at


def test_webhook_notifier_payload():
    seen = {}

    def handler(req):
        seen.update(__import__("json").loads(req.content))
        return httpx.Response(200)

    n = WebhookNotifier("https://hook/x", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    from datetime import datetime
    a = __import__("app.models", fromlist=["Alert"]).Alert(id=7, origin="THR", destination="MHD", date=D,
        target_price=2_000_000, contact="09121234567", created=datetime.now())
    asyncio.run(n.send(a, 1_900_000))
    assert seen["alert_id"] == 7 and seen["price"] == 1_900_000 and "۱" not in seen["text"] and "1,900,000" in seen["text"]


def test_smtp_notifier_sends_only_to_emails(monkeypatch):
    sent = []

    class FakeSMTP:
        def __init__(self, host, port, timeout=None): sent.append(("connect", host, port))
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def starttls(self): sent.append("tls")
        def login(self, u, p): sent.append(("login", u))
        def send_message(self, m): sent.append(("msg", m["To"], m["Subject"]))

    monkeypatch.setattr("smtplib.SMTP", FakeSMTP)
    n = SmtpNotifier("smtp.x", 587, "u", "p", "from@x")
    assert n.accepts("a@b.co") and not n.accepts("09121234567")
    from datetime import datetime
    from app.models import Alert
    a = Alert(id=1, origin="THR", destination="MHD", date=D, target_price=1, contact="a@b.co", created=datetime.now())
    asyncio.run(n.send(a, 1))
    assert ("msg", "a@b.co", "ترب تیکت: کاهش قیمت بلیط") in sent and "tls" in sent


def test_build_notifiers_env(monkeypatch):
    monkeypatch.setenv("TORUB_NOTIFY", "console,webhook")
    monkeypatch.setenv("TORUB_WEBHOOK_URL", "https://h")
    assert [n.name for n in build_notifiers()] == ["console", "webhook"]
    monkeypatch.setenv("TORUB_NOTIFY", "pigeon")
    with pytest.raises(ValueError):
        build_notifiers()


def test_db_migration_adds_notified_at(tmp_path):
    p = str(tmp_path / "old.db")
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE alerts(id INTEGER PRIMARY KEY AUTOINCREMENT, origin TEXT, destination TEXT, date TEXT,"
              " target_price INTEGER, contact TEXT, flight_id TEXT, created TEXT, triggered_at TEXT, last_price INTEGER)")
    c.commit(); c.close()
    st = Store(p)
    asyncio.run(st.add_alert(AlertIn(origin="THR", destination="MHD", date=D, target_price=5, contact="a@b.co")))
    assert asyncio.run(st.list_alerts())[0].notified_at is None


# ---------------- step 4: watchlist
from datetime import datetime as _dt, timedelta as _td
from app.watchlist import parse_watchlist


def test_parse_watchlist():
    assert parse_watchlist(" thr-mhd, THR-SYZ,THR-MHD,bad,THR-THR,XXX-MHD,,") == [("THR", "MHD"), ("THR", "SYZ")]
    assert parse_watchlist("") == []


def test_snapshot_samples_every_day_and_records_history(tmp_path):
    s = _svc(tmp_path, [MockProvider("a"), MockProvider("b")])
    n = asyncio.run(s.snapshot_watchlist([("THR", "MHD"), ("THR", "SYZ")], days=3))
    assert n == 6 and s.last_snapshot["searches"] == 6
    tomorrow = (date.today() + _td(days=1)).isoformat()
    r = asyncio.run(s.search(SearchQuery(origin="THR", destination="MHD", date=tomorrow)))
    assert len(asyncio.run(s.store.history(r.flights[0].id))) >= 1


def test_snapshot_survives_failing_search(tmp_path):
    s = _svc(tmp_path, [Flaky()], retries=0)  # every seller fails; searches still "complete" (empty)
    assert asyncio.run(s.snapshot_watchlist([("THR", "MHD")], days=2)) == 2


def test_purge_old_history(tmp_path):
    st = Store(str(tmp_path / "p.db"))
    now = _dt(2026, 1, 1)
    asyncio.run(st.record("x", 100, now - _td(days=100)))
    asyncio.run(st.record("x", 110, now - _td(days=5)))
    assert asyncio.run(st.purge_history(90, now)) == 1
    assert [p.price for p in asyncio.run(st.history("x"))] == [110]


def test_watchlist_endpoint(client):
    j = client.get("/api/watchlist").json()
    assert "THR-MHD" in j["routes"] and j["days"] == 14


# ---------------- step 5: flexible dates
def test_calendar_endpoint(client):
    j = client.get("/api/calendar", params={"origin": "THR", "destination": "MHD", "date": D, "span": 3}).json()["days"]
    assert len(j) == 7 and [d["date"] for d in j] == sorted(d["date"] for d in j)
    assert all(d["min_price"] and d["flights"] for d in j)
    mid = client.get("/api/search", params={"origin": "THR", "destination": "MHD", "date": D}).json()
    assert j[3]["date"] == D and j[3]["min_price"] == mid["flights"][0]["min_price"]


def test_calendar_skips_past_days(client):
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    j = client.get("/api/calendar", params={"origin": "THR", "destination": "MHD", "date": tomorrow, "span": 3}).json()["days"]
    assert len(j) == 5 and j[0]["date"] == date.today().isoformat()


def test_calendar_validation(client):
    assert client.get("/api/calendar", params={"origin": "THR", "destination": "THR", "date": D}).status_code == 422
    assert client.get("/api/calendar", params={"origin": "THR", "destination": "MHD", "date": D, "span": 20}).status_code == 422



# ---------------- per-seller cache
class Counting:
    def __init__(self, name, fail=False, delay=0.0):
        self.name, self.fail, self.delay, self.calls = name, fail, delay, 0
        self.inner = MockProvider(name)

    async def search(self, q):
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise ConnectionError("down")
        return await self.inner.search(q)


def test_failing_seller_does_not_force_requery_of_healthy_one(tmp_path):
    good, bad = Counting("good"), Counting("bad", fail=True)
    s = _svc(tmp_path, [good, bad], retries=0, fail_threshold=99)
    for _ in range(3):
        r = asyncio.run(s.search(Q))
    assert good.calls == 1 and bad.calls == 3  # healthy seller served from its cache
    assert r.providers["good"].cached and not r.providers["bad"].ok and r.flights


def test_identical_concurrent_searches_share_one_call(tmp_path):
    slow = Counting("slow", delay=0.2)
    s = _svc(tmp_path, [slow])

    async def many():
        return await asyncio.gather(*(s.search(Q) for _ in range(5)))
    rs = asyncio.run(many())
    assert slow.calls == 1 and all(r.flights == rs[0].flights for r in rs)


def test_fresh_bypasses_cache_and_alerts_use_fresh(tmp_path):
    c = Counting("c")
    s = _svc(tmp_path, [c])
    asyncio.run(s.search(Q))
    asyncio.run(s.search(Q))
    assert c.calls == 1
    asyncio.run(s.search(Q, fresh=True))
    assert c.calls == 2
    asyncio.run(s.store.add_alert(AlertIn(origin=Q.origin, destination=Q.destination, date=Q.date, target_price=1, contact="a@b.co")))
    asyncio.run(s.check_alerts())
    assert c.calls == 3


def test_cache_ttl_expiry(tmp_path):
    c = Counting("c")
    s = _svc(tmp_path, [c], cache_ttl=0.05)
    asyncio.run(s.search(Q))
    import time as _t; _t.sleep(0.07)
    asyncio.run(s.search(Q))
    assert c.calls == 2


def test_cache_is_bounded(tmp_path):
    from app.cache import MemoryCache
    s = _svc(tmp_path, [Counting("c")], cache=MemoryCache(max_entries=5))
    for k in range(1, 12):
        asyncio.run(s.search(SearchQuery(origin="THR", destination="MHD", date=(date.today() + timedelta(days=k)).isoformat())))
    assert len(s.cache) <= 5
