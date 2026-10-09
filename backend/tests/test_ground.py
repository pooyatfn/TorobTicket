"""Trains and buses: Alibaba adapters (real captured rows), mode routing, availability, new endpoints."""
import asyncio
import json
from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models import SearchQuery
from app.providers.alibaba import AlibabaProvider
from app.providers.alibaba_ground import AlibabaBusProvider, AlibabaTrainProvider
from app.providers.mock import MockProvider
from app.service import SearchService
from app.store import Store

FX = json.loads((Path(__file__).parent / "fixtures" / "alibaba_ground_thr_mhd.json").read_text(encoding="utf-8"))
TQ = SearchQuery(mode="train", origin="THR", destination="MHD", date="2026-10-20", adults=2)
BQ = SearchQuery(mode="bus", origin="THR", destination="MHD", date="2026-10-20", adults=1, children=1)
D = (date.today() + timedelta(days=5)).isoformat()


def client_for(seen=None):
    def handler(req):
        if seen is not None:
            seen.append(req)
        if "/bus/" in req.url.path:
            return httpx.Response(200, json=FX["bus"])
        return httpx.Response(200, json=FX["train_post"] if req.method == "POST" else FX["train_poll"])
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_train_protocol_and_parse():
    seen = []
    fl = asyncio.run(AlibabaTrainProvider(client=client_for(seen), poll_interval=0).search(TQ))
    assert json.loads(seen[0].content) == {"departureDate": "2026-10-20", "origin": "THR", "destination": "MHD",
                                           "passengerCount": 2, "isExclusiveCompartment": False, "ticketType": "Family"}
    assert seen[1].url.path.endswith("/eyJGcm9tIjoxLCJUbyI6MTkx")
    assert len(fl) == 4 and all(f.mode == "train" for f in fl)
    saba = next(f for f in fl if f.flight_number == "318")
    assert saba.airline == "رجا" and saba.offers[0].price == 760_000 and saba.duration_minutes == 745
    assert saba.features[0] == "سالنی" and "تهویه مطبوع" in saba.features and saba.seats_left == 312
    ghadir = next(f for f in fl if f.flight_number == "580")
    assert not ghadir.offers[0].available and ghadir.features[0] == "کوپه 4 نفره"
    iran = next(f for f in fl if f.flight_number == "468")
    assert "پذیرایی رایگان" in iran.features and not iran.offers[0].refundable
    assert iran.offers[0].url == ("https://www.alibaba.ir/train/THR-MHD?adult=2&child=0&infant=0&departing=1405-07-28"
                                  "&ticketType=Family&isExclusive=false")


def test_bus_protocol_and_parse():
    seen = []
    fl = asyncio.run(AlibabaBusProvider(client=client_for(seen)).search(BQ))
    p = seen[0].url.params
    assert (p["orginCityCode"], p["destinationCityCode"], p["requestDate"], p["passengerCount"]) == \
           ("11320000", "31310000", "2026-10-20", "2")
    assert len(fl) == 4 and all(f.mode == "bus" and f.arrival is None for f in fl)
    g = fl[0]
    assert g.airline == "شرکت گیتی نورد تعاونى شماره 12 - پایانه جنوب"  # whitespace normalised
    assert g.offers[0].price == 1_315_500 and g.seats_left == 22 and g.stops[-1] == "مشهد (خراسان )"
    assert {"VIP", "صندلی تخت‌شو", "شارژر اختصاصی"} <= set(g.features)
    assert g.origin_terminal == "تهران پایانه جنوب" and g.logo.endswith("T12.jpg")
    assert "اتوبوس مارال" in fl[1].features and fl[2].rating == 4.5
    assert not fl[3].offers[0].available
    assert g.offers[0].url == "https://www.alibaba.ir/bus/11320000-31310000?departing=1405-07-28"


def test_bus_unknown_city_returns_nothing_without_calling():
    seen = []
    q = BQ.model_copy(update={"origin": "IKA"})
    assert asyncio.run(AlibabaBusProvider(client=client_for(seen)).search(q)) == [] and seen == []


def test_service_routes_by_mode_and_sorts_sold_out_last(tmp_path):
    fl, tr, bu = (AlibabaProvider(client=client_for()), AlibabaTrainProvider(client=client_for(), poll_interval=0),
                  AlibabaBusProvider(client=client_for()))
    for p in (fl, tr, bu):
        p.min_interval = 0
    called = []
    orig = fl.search

    async def spy(q):
        called.append(q)
        return await orig(q)
    fl.search = spy
    s = SearchService([fl, tr, bu], Store(str(tmp_path / "g.db")))
    r = asyncio.run(s.search(TQ))
    assert called == [] and len(r.flights) == 4 and list(r.providers) == ["علی‌بابا"]
    assert [f.available for f in r.flights] == [True, True, True, False]
    assert r.flights[0].min_price == 760_000 and r.flights[-1].flight_number == "580"
    assert r.flights[-1].seller_count == 1 and r.flights[-1].min_price == 1_283_950
    rb = asyncio.run(s.search(BQ))
    assert len(rb.flights) == 4 and rb.flights[-1].available is False and rb.flights[0].duration_min is None
    # recently seen trips can be opened by id
    assert asyncio.run(s.get_trip(r.flights[0].id))[0].flight_number == "318"


def test_trip_keys_distinguish_wagon_classes():
    fl = asyncio.run(AlibabaTrainProvider(client=client_for(), poll_interval=0).search(TQ))
    assert len({f.key for f in fl}) == 4


def test_mock_generates_ground_trips():
    m = MockProvider("آژانس نمونه الف")
    for mode in ("train", "bus"):
        fl = asyncio.run(m.search(SearchQuery(mode=mode, origin="THR", destination="MHD", date=D)))
        assert fl and all(f.mode == mode and f.offers for f in fl)
        assert any(not f.offers[0].available for f in fl) or all(f.seats_left for f in fl)


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(str(tmp_path / "t.db"), alert_interval=0, watch_interval=0)) as c:
        yield c


def test_cities_endpoint_per_mode(client):
    train = {c["code"] for c in client.get("/api/cities", params={"mode": "train"}).json()}
    assert "MHD" in train and "KIH" not in train and "AZD" not in train
    bus = client.get("/api/cities", params={"mode": "bus", "q": "یزد"}).json()
    assert bus == [{"code": "AZD", "name": "یزد", "modes": ["flight", "bus"]}]
    assert client.get("/api/cities", params={"mode": "boat"}).status_code == 422
    pop = client.get("/api/popular", params={"mode": "train"}).json()
    assert pop[0] == {"origin": "THR", "destination": "MHD", "origin_name": "تهران", "destination_name": "مشهد"}


def test_search_validation_per_mode(client):
    assert client.get("/api/search", params={"mode": "train", "origin": "THR", "destination": "KIH", "date": D}).status_code == 422
    assert client.get("/api/search", params={"mode": "rocket", "origin": "THR", "destination": "MHD", "date": D}).status_code == 422
    r = client.get("/api/search", params={"mode": "bus", "origin": "THR", "destination": "MHD", "date": D})
    assert r.status_code == 200 and r.json()["flights"] and r.json()["query"]["mode"] == "bus"


def test_trip_endpoint_and_history(client):
    j = client.get("/api/search", params={"mode": "train", "origin": "THR", "destination": "MHD", "date": D}).json()
    tid = j["flights"][0]["id"]
    t = client.get(f"/api/trips/{tid}").json()
    assert t["trip"]["id"] == tid and t["query"]["mode"] == "train"
    assert client.get("/api/trips/nope").status_code == 404
    assert isinstance(client.get(f"/api/trips/{tid}/history").json(), list)


def test_calendar_and_alert_for_bus(client):
    days = client.get("/api/calendar", params={"mode": "bus", "origin": "THR", "destination": "MHD", "date": D}).json()["days"]
    assert len(days) == 7 and any(d["min_price"] for d in days)
    a = client.post("/api/alerts", json={"mode": "bus", "origin": "THR", "destination": "MHD", "date": D,
                                         "target_price": 1, "contact": "09121234567"})
    assert a.status_code == 201 and a.json()["mode"] == "bus"
    bad = client.post("/api/alerts", json={"mode": "train", "origin": "THR", "destination": "KIH", "date": D,
                                           "target_price": 1, "contact": "09121234567"})
    assert bad.status_code == 422


def test_alert_mode_migration(tmp_path):
    import sqlite3
    from app.models import AlertIn
    p = str(tmp_path / "old.db")
    c = sqlite3.connect(p)
    c.execute("CREATE TABLE alerts(id INTEGER PRIMARY KEY AUTOINCREMENT, origin TEXT, destination TEXT, date TEXT,"
              " target_price INTEGER, contact TEXT, flight_id TEXT, created TEXT, triggered_at TEXT, last_price INTEGER,"
              " notified_at TEXT)")
    c.execute("INSERT INTO alerts(origin,destination,date,target_price,contact,created) VALUES('THR','MHD','2030-01-01',5,'a@b.co','2026-01-01T00:00:00')")
    c.commit(); c.close()
    st = Store(p)
    assert asyncio.run(st.list_alerts())[0].mode == "flight"
    asyncio.run(st.add_alert(AlertIn(mode="train", origin="THR", destination="MHD", date="2030-01-01", target_price=5, contact="a@b.co")))
    assert {a.mode for a in asyncio.run(st.list_alerts())} == {"flight", "train"}


def test_spa_fallback(tmp_path, monkeypatch):
    import app.main as m
    dist = tmp_path / "frontend" / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>spa</html>")
    (dist / "assets" / "a.js").write_text("x")
    (dist / "favicon.svg").write_text("<svg/>")
    fake = tmp_path / "backend" / "app" / "main.py"
    monkeypatch.setattr(m, "__file__", str(fake))
    with TestClient(m.create_app(str(tmp_path / "s.db"), alert_interval=0, watch_interval=0)) as c:
        assert c.get("/search?mode=train").text == "<html>spa</html>"
        assert c.get("/trip/abc").text == "<html>spa</html>"
        assert c.get("/assets/a.js").text == "x" and c.get("/favicon.svg").text == "<svg/>"
        assert c.get("/api/nope").status_code == 404
        assert c.get("/../../etc/passwd").text == "<html>spa</html>"


def test_alibaba_links_use_codes_its_site_serves():
    """Verified against alibaba.ir (2026-10): flights need IATA codes (no IKA, Yazd is AZD); bus pages are
    addressed by the numeric city code (letter slugs exist for only a few cities); trains by our city code."""
    from app.cities import CITIES
    from app.providers.alibaba import AlibabaProvider
    codes = {c[0] for c in CITIES}
    assert "IKA" not in codes and "YZD" not in codes and "AZD" in codes
    day = "2026-10-20"
    f = AlibabaProvider().deep_link(SearchQuery(origin="THR", destination="AZD", date=day))
    assert f == "https://www.alibaba.ir/flights/THR-AZD?adult=1&child=0&infant=0&departing=1405-07-28"
    b = AlibabaBusProvider().deep_link(SearchQuery(mode="bus", origin="THR", destination="BND", date=day))
    assert b == "https://www.alibaba.ir/bus/11320000-64310000?departing=1405-07-28"
    assert AlibabaBusProvider().deep_link(SearchQuery(mode="bus", origin="THR", destination="XXX", date=day)) \
        == "https://www.alibaba.ir/bus-ticket"
