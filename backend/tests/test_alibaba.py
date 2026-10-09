import asyncio
import json
from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest

from app.jalali import jalali_str, to_jalali
from app.models import SearchQuery
from app.providers import is_demo, load_providers
from app.providers.alibaba import AlibabaError, AlibabaProvider

FX = json.loads((Path(__file__).parent / "fixtures" / "alibaba_thr_syz.json").read_text(encoding="utf-8"))
Q = SearchQuery(origin="THR", destination="SYZ", date="2026-10-20", adults=2, children=1, infants=0)


def fake(post=FX["post"], polls=(FX["poll1"], FX["poll2"]), seen=None):
    polls = list(polls)

    def handler(req: httpx.Request):
        if seen is not None:
            seen.append((req.method, str(req.url), req.content and json.loads(req.content)))
        if req.method == "POST":
            return httpx.Response(200, json=post)
        return httpx.Response(200, json=polls.pop(0) if len(polls) > 1 else polls[0])
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def run(p, q=Q):
    return asyncio.run(p.search(q))


@pytest.mark.parametrize("g,j", [("2026-10-17", "1405-07-25"), ("2026-10-18", "1405-07-26"), ("2026-10-08", "1405-07-16"),
                                 ("2026-03-21", "1405-01-01"), ("2025-03-20", "1403-12-30"), ("2025-03-21", "1404-01-01")])
def test_jalali_known_dates(g, j):
    assert jalali_str(date.fromisoformat(g)) == j


def test_search_protocol_and_parsing():
    seen = []
    p = AlibabaProvider(client=fake(seen=seen), poll_interval=0)
    fl = run(p)
    # protocol: one POST with the query, then polling the requestId until complete
    assert seen[0][0] == "POST" and seen[0][2] == {"origin": "THR", "destination": "SYZ", "departureDate": "2026-10-20",
                                                    "adult": 2, "child": 1, "infant": 0}
    assert [m for m, *_ in seen] == ["POST", "GET", "GET"] and seen[1][1].endswith("/GE4DQNRQG42DQ")
    # 8 raw rows -> 2 sold out dropped, NV2628 listed 3x collapsed to its cheapest -> 4 flights
    assert len(fl) == 4
    nv = next(f for f in fl if f.flight_number == "2628")
    assert nv.offers[0].price == 11_758_500 and nv.arrival.hour == 21  # rial -> toman, cheapest copy kept
    sj = next(f for f in fl if f.airline_code == "SJ")
    assert sj.airline == "آساجت" and sj.offers[0].baggage_kg == 15 and sj.duration_minutes == 75
    o = fl[0].offers[0]
    assert o.seller == "علی‌بابا" and o.url == ("https://www.alibaba.ir/flights/THR-SYZ?adult=2&child=1&infant=0"
                                                 "&departing=1405-07-28")


def test_partial_results_when_never_completes():
    p = AlibabaProvider(client=fake(polls=(FX["poll1"],)), poll_interval=0.01, max_wait=0.05)
    assert len(run(p)) == 3


def test_rejected_search_raises():
    p = AlibabaProvider(client=fake(post={"result": None, "success": False, "error": {"message": "x"}}), poll_interval=0)
    with pytest.raises(AlibabaError):
        run(p)


def test_http_error_raises():
    c = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    with pytest.raises(httpx.HTTPStatusError):
        run(AlibabaProvider(client=c, poll_interval=0))


def test_malformed_rows_are_skipped():
    bad = {"result": {"isCompleted": True, "departing": [{"airlineCode": "IR"}, None.__class__.__name__,
                                                          FX["poll2"]["result"]["departing"][1]]}}
    p = AlibabaProvider(client=fake(polls=(bad,)), poll_interval=0)
    fl = run(p)
    assert [f.flight_number for f in fl] == ["4303"]


def test_provider_selection(monkeypatch):
    monkeypatch.delenv("TORUB_PROVIDERS_CONFIG", raising=False)
    monkeypatch.setenv("TORUB_PROVIDERS", "alibaba")
    ps = load_providers()
    assert [p.name for p in ps] == ["علی‌بابا"] * 3 and not is_demo(ps)
    assert [sorted(p.modes) for p in ps] == [["flight"], ["train"], ["bus"]]
    monkeypatch.setenv("TORUB_PROVIDERS", "demo")
    assert is_demo(load_providers())
    monkeypatch.setenv("TORUB_PROVIDERS", "nope")
    with pytest.raises(ValueError):
        load_providers()


def test_alibaba_through_search_service(tmp_path):
    from app.service import SearchService
    from app.store import Store
    s = SearchService([AlibabaProvider(client=fake(), poll_interval=0)], Store(str(tmp_path / "a.db")))
    r = asyncio.run(s.search(Q))
    assert r.providers["علی‌بابا"].ok and r.flights[0].min_price == 11_758_500
    assert len(asyncio.run(s.store.history(r.flights[0].id))) == 1  # real provider: no fake back-filled history


# ---------------- cheapest per day (date strip fast path)
CHEAP = {"result": [  # shape of a real /v2/.../cheapest response; adultPrice in rial, 0 = no flights
    {"adultPrice": 117585000, "childPrice": 117585000, "infantPrice": 17085000, "departureDateTime": "2026-10-20T20:20:00",
     "arrivalTime": "2026-10-20T21:20:00", "capacity": 9, "airline": "NV", "systemKey": "R", "isCompleted": True},
    {"adultPrice": 118174100, "departureDateTime": "2026-10-21T05:10:00", "capacity": 7, "airline": "B9", "isCompleted": True},
    {"adultPrice": 0, "departureDateTime": "2026-10-22T00:00:00", "capacity": 0, "isCompleted": True},
    {"broken": True}], "success": True, "error": None}


def test_alibaba_cheapest_request_and_parse():
    seen = []

    def handler(req):
        seen.append((str(req.url), json.loads(req.content)))
        return httpx.Response(200, json=CHEAP)
    p = AlibabaProvider(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    res = asyncio.run(p.cheapest("THR", "SYZ", date(2026, 10, 21), 1, 1))
    assert seen == [("https://ws.alibaba.ir/api/v2/flights/domestic/available/cheapest",
                     {"referenceDate": "2026-10-21", "backwardDay": 1, "forwardDay": 1, "origin": "THR", "destination": "SYZ"})]
    assert res == {"2026-10-20": 11_758_500, "2026-10-21": 11_817_410, "2026-10-22": None}


def test_alibaba_cheapest_rejected():
    c = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"result": None, "success": False})))
    with pytest.raises(AlibabaError):
        asyncio.run(AlibabaProvider(client=c).cheapest("THR", "SYZ", date(2026, 10, 21), 1, 1))


# ---- service.calendar with bulk-capable and day-by-day sellers
from app.providers.base import FlightProvider
from app.providers.mock import MockProvider
from app.service import SearchService
from app.store import Store


class Bulk(FlightProvider):
    name = "bulk"
    supports_cheapest = True

    def __init__(self, prices=None, fail=False):
        self.prices, self.fail, self.cheap_calls, self.search_calls = prices or {}, fail, [], 0

    async def search(self, q):
        self.search_calls += 1
        return await MockProvider("bulk").search(q)

    async def cheapest(self, origin, destination, center, back, fwd):
        self.cheap_calls.append((center.isoformat(), back, fwd))
        if self.fail:
            raise ConnectionError("down")
        return {d: p for d, p in self.prices.items()}


def _days(center: date, span=3):
    return [(center + timedelta(days=k)).isoformat() for k in range(-span, span + 1)]


C = date.today() + timedelta(days=10)


def _q(d=C):
    return SearchQuery(origin="THR", destination="MHD", date=d.isoformat())


def test_calendar_uses_one_bulk_call_instead_of_seven_searches(tmp_path):
    days = _days(C)
    b = Bulk({d: 1_000_000 + i for i, d in enumerate(days)} | {days[2]: None})
    s = SearchService([b], Store(str(tmp_path / "c.db")), backoff=0)
    out = asyncio.run(s.calendar(_q(), 3))
    assert b.cheap_calls == [(C.isoformat(), 3, 3)] and b.search_calls == 0
    assert [d["date"] for d in out] == days
    assert out[0]["min_price"] == 1_000_000 and out[2]["min_price"] is None


def test_calendar_mixes_bulk_and_day_by_day_and_takes_minimum(tmp_path):
    days = _days(C)
    b = Bulk({d: 1 for d in days[:3]})  # absurdly cheap on the first 3 days only
    s = SearchService([b, MockProvider("demo")], Store(str(tmp_path / "c.db")), backoff=0)
    out = asyncio.run(s.calendar(_q(), 3))
    assert [d["min_price"] for d in out[:3]] == [1, 1, 1]
    assert all(d["min_price"] and d["min_price"] > 1 for d in out[3:])  # filled by the demo seller
    assert b.search_calls == 0


def test_calendar_falls_back_when_bulk_fails(tmp_path):
    b = Bulk(fail=True)
    s = SearchService([b], Store(str(tmp_path / "c.db")), backoff=0, retries=0)
    out = asyncio.run(s.calendar(_q(), 3))
    assert len(b.cheap_calls) == 1 and b.search_calls == 7 and all(d["min_price"] for d in out)


def test_calendar_is_cached(tmp_path):
    b = Bulk({d: 5 for d in _days(C)})
    s = SearchService([b], Store(str(tmp_path / "c.db")))
    asyncio.run(s.calendar(_q(), 3))
    asyncio.run(s.calendar(_q(), 3))
    assert len(b.cheap_calls) == 1


def test_calendar_near_today_asks_only_for_future_days(tmp_path):
    b = Bulk({})
    s = SearchService([b], Store(str(tmp_path / "c.db")))
    tomorrow = date.today() + timedelta(days=1)
    out = asyncio.run(s.calendar(_q(tomorrow), 3))
    assert b.cheap_calls == [(tomorrow.isoformat(), 1, 3)] and out[0]["date"] == date.today().isoformat()
