import asyncio
import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from app.models import SearchQuery, normalize_flight_number
from app.providers.alibaba import AlibabaProvider
from app.providers.safarmarket import SafarmarketError, SafarmarketProvider
from app.service import SearchService
from app.store import Store

FIX = Path(__file__).parent / "fixtures"
SM = json.loads((FIX / "safarmarket_thr_syz.json").read_text(encoding="utf-8"))
AB = json.loads((FIX / "alibaba_thr_syz.json").read_text(encoding="utf-8"))
Q = SearchQuery(origin="THR", destination="SYZ", date="2026-10-20", adults=2, children=1, infants=0)


def sm_client(search=SM["search"], calendar=SM["calendar"], seen=None):
    def handler(req: httpx.Request):
        if seen is not None:
            seen.append(req)
        return httpx.Response(200, json=search if req.method == "POST" else calendar)
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def ab_client():
    polls = [AB["poll2"]]

    def handler(req):
        return httpx.Response(200, json=AB["post"] if req.method == "POST" else polls[0])
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.parametrize("raw,norm", [("IS4303", "4303"), ("B98006", "8006"), ("A78626", "8626"), ("NV2628", "2628"),
                                      ("ME4200", "4200"), ("4200", "4200"), ("IR0450", "450"), ("W5 1101", "1101")])
def test_normalize_flight_number(raw, norm):
    assert normalize_flight_number(raw) == norm


def test_request_body_and_no_bot_protection_headers_faked():
    seen = []
    asyncio.run(SafarmarketProvider(client=sm_client(seen=seen)).search(Q))
    req = seen[0]
    assert str(req.url) == "https://safarmarket.com/api/flight/v3/search"
    body = json.loads(req.content)
    assert body["searchFilter"] == {"sourceAirportCode": "THR", "targetAirportCode": "SYZ", "sourceIsCity": True,
                                    "targetIsCity": False, "leaveDate": "2026-10-20", "returnDate": "",
                                    "adultCount": 2, "childCount": 1, "infantCount": 0, "economy": True, "business": True}
    assert "recaptcha" not in {k.lower() for k in req.headers} and "x-auth-token" not in {k.lower() for k in req.headers}
    assert "IPInfo" not in body


def test_parse_real_response():
    fl = asyncio.run(SafarmarketProvider(client=sm_client()).search(Q))
    by = {f.flight_number: f for f in fl}
    # 7 rows -> connecting (IR450) and fully sold-out (QB1234) dropped; B9 8006 economy+business pooled
    assert sorted(by) == ["2628", "3790", "4303", "8006"]
    nv = by["2628"]
    assert nv.airline == "کارون" and nv.departure.isoformat() == "2026-10-20T20:20:00" and nv.duration_minutes == 60
    assert [(o.seller, o.price, o.via) for o in nv.offers] == [("قاصدک24", 11_568_780, "سفرمارکت"),
                                                              ("اسنپ تریپ", 11_636_352, "سفرمارکت")]
    gh = nv.offers[0]
    assert gh.url.startswith("https://ghasedak24.com/") and gh.baggage_kg == 20 and gh.refundable
    assert not nv.offers[1].refundable  # no policy published -> not claimed refundable
    b9 = by["8006"]
    assert len(b9.offers) == 3 and {o.fare_class for o in b9.offers} == {"اکونومی", "بیزینس"}


def test_rejected_search_raises():
    p = SafarmarketProvider(client=sm_client(search={"code": 429, "message": "too many", "result": None}))
    with pytest.raises(SafarmarketError):
        asyncio.run(p.search(Q))


def test_calendar_range_and_empty_days():
    seen = []
    p = SafarmarketProvider(client=sm_client(seen=seen))
    res = asyncio.run(p.cheapest("THR", "SYZ", date(2026, 10, 20), 1, 1))
    assert res == {"2026-10-19": 9_500_009, "2026-10-20": 11_568_780, "2026-10-21": None}
    assert seen[0].url.params["org"] == "THR" and seen[0].url.params["orgCity"] == "true"
    assert seen[0].url.params["dstCity"] == "false"


def test_merges_with_alibaba_on_real_data(tmp_path):
    """Same route/date from both real samples: SR4303 vs IS4303, NV2628, EP3790 must merge into one row each."""
    s = SearchService([AlibabaProvider(client=ab_client(), poll_interval=0),
                       SafarmarketProvider(client=sm_client())], Store(str(tmp_path / "m.db")))
    r = asyncio.run(s.search(Q))
    by = {normalize_flight_number(f.flight_number): f for f in r.flights}
    assert sorted(by) == ["2628", "3790", "4303", "8006", "8626"]  # 8006 only on SM, 8626 only on Alibaba
    nv = by["2628"]
    assert [o.seller for o in nv.offers] == ["قاصدک24", "اسنپ تریپ", "علی‌بابا"]
    assert nv.min_price == 11_568_780 and nv.seller_count == 3
    assert by["4303"].seller_count == 3 and by["8626"].seller_count == 1
    assert all(st.ok for st in r.providers.values())
    # cheapest-first ordering across all flights
    assert [f.min_price for f in r.flights] == sorted(f.min_price for f in r.flights)


def test_same_agency_twice_on_a_flight_keeps_cheapest(tmp_path):
    s = SearchService([SafarmarketProvider(client=sm_client())], Store(str(tmp_path / "d.db")))
    r = asyncio.run(s.search(Q))
    b9 = next(f for f in r.flights if normalize_flight_number(f.flight_number) == "8006")
    assert [o.seller for o in b9.offers] == ["اسنپ تریپ", "قاصدک24"]  # snapptrip economy kept, business dropped
    assert b9.offers[0].price == 11_817_410


def test_calendar_combines_both_bulk_sellers(tmp_path):
    from datetime import timedelta
    center = date.today() + timedelta(days=5)
    cal = {"cal": {(center + timedelta(days=k)).isoformat(): {"minPrice": 100_000_000 + k} for k in range(-3, 4)}}
    ali = {"result": [{"departureDateTime": (center + timedelta(days=k)).isoformat() + "T08:00:00",
                       "adultPrice": 99_000_000 if k == 0 else 200_000_000} for k in range(-3, 4)], "success": True}
    a = AlibabaProvider(client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=ali))))
    sm = SafarmarketProvider(client=sm_client(calendar=cal))
    s = SearchService([a, sm], Store(str(tmp_path / "c.db")))
    out = asyncio.run(s.calendar(SearchQuery(origin="THR", destination="SYZ", date=center.isoformat()), 3))
    prices = {d["date"]: d["min_price"] for d in out}
    assert prices[center.isoformat()] == 9_900_000  # Alibaba cheaper that day
    assert prices[(center + timedelta(days=1)).isoformat()] == 10_000_000 + 0  # Safarmarket (100,000,001 rial)


# ---------------- rate limiting (429)
import time as _time
from datetime import timedelta
from app.models import SearchQuery as _SQ


class Limited:
    """A seller that answers 429 like Safarmarket under load."""
    name, supports_cheapest, background, min_interval = "lim", True, False, 0.0

    def __init__(self, retry_after="30"):
        self.calls, self.cheap_calls, self.retry_after = 0, 0, retry_after

    def _429(self):
        req = httpx.Request("POST", "https://x/search")
        headers = {"Retry-After": self.retry_after} if self.retry_after else {}
        resp = httpx.Response(429, request=req, headers=headers)
        raise httpx.HTTPStatusError("Client error '429 '", request=req, response=resp)

    async def search(self, q):
        self.calls += 1
        self._429()

    async def cheapest(self, *a):
        self.cheap_calls += 1
        self._429()


def _q(days=6):
    return _SQ(origin="THR", destination="MHD", date=(date.today() + timedelta(days=days)).isoformat())


def test_429_is_not_retried_and_pauses_the_seller(tmp_path):
    lim = Limited("30")
    s = SearchService([lim], Store(str(tmp_path / "r.db")), retries=2, backoff=0)
    r = asyncio.run(s.search(_q()))
    assert lim.calls == 1  # no immediate retry into a rate limit
    assert r.providers["lim"].error == "RateLimited" and not r.providers["lim"].ok
    st = asyncio.run(s.provider_status())["lim"]
    assert st["state"] == "open" and 25 <= st["retry_in"] <= 30
    asyncio.run(s.search(_q(7)))  # different query: still paused, no call made
    assert lim.calls == 1


def test_429_without_retry_after_uses_default(tmp_path):
    lim = Limited(None)
    s = SearchService([lim], Store(str(tmp_path / "r.db")))
    asyncio.run(s.search(_q()))
    assert asyncio.run(s.provider_status())["lim"]["retry_in"] >= 55


def test_429_serves_last_good_answer_when_available(tmp_path):
    p = SafarmarketProvider(client=sm_client())
    p.min_interval = 0
    s = SearchService([p], Store(str(tmp_path / "r.db")), cache_ttl=0)
    first = asyncio.run(s.search(Q))
    req = httpx.Request("POST", "https://x")
    p._client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(429, request=req)))
    second = asyncio.run(s.search(Q))
    st = second.providers["سفرمارکت"]
    assert st.ok and st.stale and st.error == "RateLimited" and len(second.flights) == len(first.flights)


def test_calendar_429_does_not_fan_out_into_daily_searches(tmp_path):
    lim = Limited("20")
    s = SearchService([lim], Store(str(tmp_path / "r.db")))
    asyncio.run(s.calendar(_q(10), 3))
    assert lim.cheap_calls == 1 and lim.calls == 0


def test_requests_are_spaced_per_seller(tmp_path):
    p = SafarmarketProvider(client=sm_client())
    p.min_interval = 0.2
    s = SearchService([p], Store(str(tmp_path / "r.db")), cache_ttl=0)
    t = _time.monotonic()

    async def three():
        await asyncio.gather(*(s.search(_SQ(origin="THR", destination="SYZ", date=f"2026-10-2{k}")) for k in range(3)))
    asyncio.run(three())
    assert _time.monotonic() - t >= 0.4  # 3 requests -> at least 2 intervals


def test_background_sampling_skips_rate_limited_sellers(tmp_path):
    from app.providers.mock import MockProvider
    sm = SafarmarketProvider(client=sm_client())
    calls = []
    orig = sm.search

    async def spy(q):
        calls.append(q)
        return await orig(q)
    sm.search = spy
    s = SearchService([MockProvider("demo"), sm], Store(str(tmp_path / "w.db")))
    assert asyncio.run(s.snapshot_watchlist([("THR", "MHD")], days=2)) == 2
    assert calls == []
