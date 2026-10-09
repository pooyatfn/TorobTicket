"""MrBilit and FlyToday train adapters on real captured responses, and merging with Alibaba's trains."""
import asyncio
import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from app.models import SearchQuery
from app.providers import load_providers
from app.providers.alibaba_ground import AlibabaTrainProvider
from app.providers.flytoday import FlyTodayError, FlyTodayProvider
from app.providers.mrbilit import MrBilitProvider
from app.service import SearchService
from app.store import Store

FXD = Path(__file__).parent / "fixtures"
MB = json.loads((FXD / "mrbilit_train_thr_mhd.json").read_text(encoding="utf-8"))
FT = json.loads((FXD / "flytoday_train_thr_mhd.json").read_text(encoding="utf-8"))
AL = json.loads((FXD / "alibaba_ground_thr_mhd.json").read_text(encoding="utf-8"))
Q = SearchQuery(mode="train", origin="THR", destination="MHD", date="2026-10-20", adults=1)


def mb_client(seen=None, payload=None):
    def handler(req):
        if seen is not None:
            seen.append(req)
        if req.url.path.endswith("GetMinPrices"):
            return httpx.Response(200, json={"2026-10-20": "7600000", "2026-10-22": "0", "2026-10-21": "15200000"})
        return httpx.Response(200, json=payload or MB)
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def ft_client(seen=None, status=200, payload=None, text=None):
    def handler(req):
        if seen is not None:
            seen.append(req)
        if text is not None:
            return httpx.Response(status, text=text)
        return httpx.Response(status, json=payload or FT)
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_mrbilit_protocol_and_parse():
    seen = []
    fl = asyncio.run(MrBilitProvider(client=mb_client(seen)).search(Q))
    p = seen[0].url.params
    assert (p["from"], p["to"], p["date"], p["adultCount"]) == ("1", "191", "2026-10-20", "1")
    # sold-out classes (price 0) are skipped: 318 (one live class) and 370 remain
    assert sorted(f.flight_number for f in fl) == ["318", "370"]
    saba = next(f for f in fl if f.flight_number == "318")
    assert saba.offers[0].price == 760_000 and saba.seats_left == 297 and saba.offers[0].available
    assert saba.duration_minutes == 745 and saba.features[0] == "سالنی"
    assert saba.offers[0].url == "https://mrbilit.com/trains/tehran-mashhad?departureDate=1405-07-28"


def test_mrbilit_cheapest_and_unknown_station():
    p = MrBilitProvider(client=mb_client())
    r = asyncio.run(p.cheapest("THR", "MHD", date(2026, 10, 21), 1, 1))
    assert r == {"2026-10-20": 760_000, "2026-10-21": 1_520_000, "2026-10-22": None}
    assert asyncio.run(p.search(SearchQuery(mode="train", origin="THR", destination="KIH", date="2026-10-20"))) == []


def test_flytoday_protocol_and_parse():
    seen = []
    fl = asyncio.run(FlyTodayProvider(client=ft_client(seen)).search(Q))
    body = json.loads(seen[0].content)
    assert body["originDestination"] == [{"origin": 1, "destination": 191, "moveDate": "2026-10-20"}]
    assert body["tripType"] == "OneWay" and body["adultsCount"] == 1 and body["sexCode"] == 3
    assert len(fl) == 4
    ghadir = next(f for f in fl if f.flight_number == "580")
    assert not ghadir.offers[0].available and ghadir.airline == "ریل ترابر سبا"  # Arabic ي normalised
    saba = next(f for f in fl if f.flight_number == "318")
    assert saba.offers[0].price == 760_000 and saba.offers[0].available and saba.seats_left == 296
    assert "departureDate=2026-10-20" in saba.offers[0].url


def test_flytoday_captcha_fails_cleanly():
    p = FlyTodayProvider(client=ft_client(status=422, text='{"message":"Captcha is required"}'))
    with pytest.raises(FlyTodayError):
        asyncio.run(p.search(Q))


def test_three_sellers_merge_into_one_row_per_train(tmp_path):
    def alibaba_handler(req):
        return httpx.Response(200, json=AL["train_post"] if req.method == "POST" else AL["train_poll"])
    ali = AlibabaTrainProvider(client=httpx.AsyncClient(transport=httpx.MockTransport(alibaba_handler)), poll_interval=0)
    svc = SearchService([ali, MrBilitProvider(client=mb_client()), FlyTodayProvider(client=ft_client())],
                        Store(str(tmp_path / "t.db")))
    res = asyncio.run(svc.search(Q))
    by_no = {f.flight_number: f for f in res.flights}
    assert sorted(o.seller for o in by_no["318"].offers) == ["علی‌بابا", "فلای‌تودی", "مستربلیط"]
    assert sorted(o.seller for o in by_no["370"].offers) == ["علی‌بابا", "فلای‌تودی", "مستربلیط"]
    assert by_no["318"].seller_count == 3 and by_no["318"].min_price == 760_000
    assert len([f for f in res.flights if f.flight_number == "318"]) == 1


def test_load_providers_names(monkeypatch):
    monkeypatch.setenv("TORUB_PROVIDERS", "mrbilit,flytoday")
    monkeypatch.delenv("TORUB_PROVIDERS_CONFIG", raising=False)
    ps = load_providers()
    assert [(type(p).__name__, sorted(p.modes)) for p in ps] == [
        ("MrBilitFlightProvider", ["flight"]), ("MrBilitTrainProvider", ["train"]), ("MrBilitBusProvider", ["bus"]),
        ("FlyTodayFlightProvider", ["flight"]), ("FlyTodayTrainProvider", ["train"])]


# ---------------------------------------------------------------- flights and buses
MBF = json.loads((FXD / "mrbilit_flight_thr_mhd.json").read_text(encoding="utf-8"))
MBB = json.loads((FXD / "mrbilit_bus_thr_mhd.json").read_text(encoding="utf-8"))
FTF = json.loads((FXD / "flytoday_flight_thr_mhd.json").read_text(encoding="utf-8"))
FQ = SearchQuery(origin="THR", destination="MHD", date="2026-10-20", adults=2)
BQ = SearchQuery(mode="bus", origin="THR", destination="MHD", date="2026-10-20")


def json_client(payload, seen=None):
    def handler(req):
        if seen is not None:
            seen.append(req)
        return httpx.Response(200, json=payload)
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_mrbilit_flights_protocol_and_parse():
    from app.providers.mrbilit import MrBilitFlightProvider
    seen = []
    fl = asyncio.run(MrBilitFlightProvider(client=json_client(MBF, seen)).search(FQ))
    assert str(seen[0].url) == "https://flight.atighgasht.com/api/Flights"
    assert json.loads(seen[0].content)["Routes"] == [{"OriginCode": "THR", "DestinationCode": "MHD", "DepartureDate": "2026-10-20"}]
    assert json.loads(seen[0].content)["AdultCount"] == 2
    saha = next(f for f in fl if f.flight_number == "170")
    assert saha.airline == "ساها ایر" and saha.offers[0].price == 11_056_700 and saha.seats_left == 8
    assert saha.departure.tzinfo is None and saha.duration_minutes == 80   # offset stripped: Tehran local time
    assert saha.offers[0].baggage_kg == 20 and saha.offers[0].refundable
    mehr = next(f for f in fl if f.flight_number == "4200")
    assert not mehr.offers[0].refundable                                        # charter
    assert saha.offers[0].url == "https://mrbilit.com/flights/THR-MHD?departureDate=1405-07-28"


def test_flytoday_flights_protocol_and_parse():
    from app.providers.flytoday import FlyTodayFlightProvider
    seen = []
    fl = asyncio.run(FlyTodayFlightProvider(client=json_client(FTF, seen)).search(FQ))
    req = seen[0]
    assert req.url.path.endswith("/Flight/SplittedSearch") and req.url.params["pageSize"] == "100"
    body = json.loads(req.content)
    assert body["originDestinationInformations"][0]["departureDateTime"] == "2026-10-20" and body["adultCount"] == 2
    # IRZ170 is listed twice (two fare classes): one flight, cheapest fare
    irz = [f for f in fl if f.flight_number == "IRZ170"]
    assert len(irz) == 1 and irz[0].offers[0].price == 11_056_700 and irz[0].airline == "ساها ایر"
    assert len(fl) == 4 and irz[0].origin == "THR" and irz[0].departure.hour == 15
    cpn = next(f for f in fl if f.flight_number == "CPN24")
    assert cpn.offers[0].fare_class == "چارتر" and cpn.duration_minutes == 60
    assert "isDomestic=true" in irz[0].offers[0].url and "departure=thr,1" in irz[0].offers[0].url


def test_flight_sellers_merge_same_flight(tmp_path):
    from app.providers.flytoday import FlyTodayFlightProvider
    from app.providers.mrbilit import MrBilitFlightProvider
    svc = SearchService([MrBilitFlightProvider(client=json_client(MBF)), FlyTodayFlightProvider(client=json_client(FTF))],
                        Store(str(tmp_path / "f.db")))
    res = asyncio.run(svc.search(FQ))
    saha = [f for f in res.flights if f.departure.hour == 15]
    assert len(saha) == 1 and sorted(o.seller for o in saha[0].offers) == ["فلای‌تودی", "مستربلیط"]
    assert saha[0].seller_count == 2


def test_mrbilit_buses_protocol_and_parse():
    from app.providers.mrbilit import MrBilitBusProvider
    seen = []
    fl = asyncio.run(MrBilitBusProvider(client=json_client(MBB, seen)).search(BQ))
    assert json.loads(seen[0].content)["from"] == 11320000 and json.loads(seen[0].content)["to"] == 31310000
    assert len(fl) == 3 and all(f.mode == "bus" and f.arrival is None for f in fl)
    g = fl[0]
    assert g.offers[0].price == 1_315_500 and g.seats_left == 22 and "VIP" in g.features
    assert g.stops == ["سبزوار", "نیشابور"] and g.offers[0].fare_class == "VIP"
    assert not fl[2].offers[0].available
    assert g.offers[0].url == "https://mrbilit.com/buses/tehran-mashhad?departureDate=1405-07-28"
    assert MrBilitBusProvider().deep_link(SearchQuery(mode="bus", origin="THR", destination="IFN", date="2026-10-20")) \
        == "https://mrbilit.com/buses/tehran-esfahan?departureDate=1405-07-28"


def test_bus_sellers_merge_same_service(tmp_path):
    from app.providers.mrbilit import MrBilitBusProvider
    from app.providers.alibaba_ground import AlibabaBusProvider
    ali = AlibabaBusProvider(client=httpx.AsyncClient(transport=httpx.MockTransport(
        lambda req: httpx.Response(200, json=AL["bus"]))))
    svc = SearchService([ali, MrBilitBusProvider(client=json_client(MBB))], Store(str(tmp_path / "b.db")))
    res = asyncio.run(svc.search(BQ))
    first = next(f for f in res.flights if f.departure.hour == 6)
    assert sorted(o.seller for o in first.offers) == ["علی‌بابا", "مستربلیط"]
