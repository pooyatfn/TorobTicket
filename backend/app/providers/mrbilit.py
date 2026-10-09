"""MrBilit.com (مستربلیط) trains.

Observed from mrbilit.com's own web client (2026-10), an open JSON API without login or tokens:
  Search:   GET https://train.mrbilit.com/api/GetAvailable/v2?from=1&to=191&date=2026-10-20&genderCode=3
                 &adultCount=1&childCount=0&infantCount=0&exclusive=false&availableStatus=Both
            -> {"trains":[{"trainNumber","departureTime","arrivalTime","corporationName",
                           "prices":[{"sellType","classes":[{"price","capacity","wagonName","compartmentType",
                                                             "isAvailable","features",...}]}]}]}
  Calendar: GET https://train.mrbilit.com/api/GetMinPrices?From=1&To=191&FromDate=..&ToDate=..&Capacity=1&GenderCode=3
            -> {"YYYY-MM-DD": "<cheapest price>"}   (days without a bookable seat are missing)
  Flights:  POST https://flight.atighgasht.com/api/Flights  (MrBilit's flight backend, no login or token)
              {"AdultCount","ChildCount","InfantCount","CabinClass":"All","Routes":[{"OriginCode","DestinationCode",
               "DepartureDate"}],"Baggage":true,"IncludeFlightsWithHigherCapacity":true}
            -> {"Flights":[{"Prices":[{"Capacity","PassengerFares":[{"PaxType":"ADL","TotalFare"}],"Baggage",...}],
                            "Segments":[{"Legs":[{"FlightNumber","Airline":{"PersianTitle"},"DepartureTime",...}]}]}]}
  Buses:    POST https://bus.mrbilit.ir/api/GetBusServices
              {"from":11320000,"to":31310000,"date":"2026-10-20","includeClosed":true,"includePromotions":true,
               "loadFromDbOnUnavailability":true,"includeUnderDevelopment":true}
            -> {"buses":[{"corporation","busType","departureTime","arrivalTime","price","capacity","fromTerminal",...}]}
            (the same numeric city codes as Alibaba's bus API, see cities.BUS_CODES)
Prices are in RIAL (we expose Toman); sold-out classes carry price 0 and are skipped.
`from`/`to` are MrBilit station ids (see STATIONS).
Unofficial integration: keep the request rate low and respect MrBilit's terms.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, datetime, timedelta

import httpx

from ..cities import BUS_CODES
from ..jalali import jalali_str
from ..models import Flight, Offer, SearchQuery, fa_text
from .base import FlightProvider

log = logging.getLogger("torobticket.mrbilit")

SITE = "https://mrbilit.com"
API = "https://train.mrbilit.com/api"
FLIGHTS = "https://flight.atighgasht.com/api/Flights"
BUSES = "https://bus.mrbilit.ir/api/GetBusServices"
# Our city code -> (MrBilit station id, url slug)
STATIONS = {
    "THR": (1, "tehran"), "MHD": (191, "mashhad"), "SYZ": (255, "shiraz"), "IFN": (21, "isfahan"),
    "TBZ": (55, "tabriz"), "AWZ": (25, "ahvaz"), "BND": (37, "bandar_abbas"), "KER": (167, "kerman"),
    "ZAH": (259, "zahedan"), "ADU": (452, "ardebil"), "OMH": (448, "urmia"), "SRY": (100, "sari"),
    "AZD": (219, "yazd"), "HDM": (117, "hamedan"), "RAS": (451, "rasht"),
}


# Bus pages are addressed by letter slugs that differ from the train ones for some cities (checked on the site)
BUS_SLUGS = {"IFN": "esfahan", "AWZ": "ahwaz", "ADU": "ardabil", "OMH": "orumieh", "KIH": "kish", "GSM": "qeshm",
             "KSH": "kermanshah", "BUZ": "bushehr"}


class MrBilitError(RuntimeError):
    pass


def _dt(v) -> datetime | None:
    try:
        return datetime.fromisoformat(str(v)) if v else None
    except ValueError:
        return None


class _MrBilitBase(FlightProvider):
    name = "مستربلیط"
    min_interval = 0.5

    def __init__(self, client: httpx.AsyncClient | None = None, max_concurrency: int = 3):
        self._client = client
        self._sem = asyncio.Semaphore(max_concurrency)

    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=12, headers={
                "Accept": "application/json, text/plain, */*",
                "User-Agent": os.getenv("TORUB_USER_AGENT", "Mozilla/5.0 (compatible; TorobTicket/0.2)"),
                "Origin": SITE, "Referer": SITE + "/"})
        return self._client


class MrBilitTrainProvider(_MrBilitBase):
    modes = frozenset({"train"})
    supports_cheapest = True

    def deep_link(self, q: SearchQuery) -> str:
        a, b = STATIONS.get(q.origin), STATIONS.get(q.destination)
        if not a or not b:
            return SITE + "/train-ticket"
        return f"{SITE}/trains/{a[1]}-{b[1]}?departureDate={jalali_str(date.fromisoformat(q.date))}"

    async def search(self, q: SearchQuery) -> list[Flight]:
        a, b = STATIONS.get(q.origin), STATIONS.get(q.destination)
        if not a or not b:
            return []
        async with self._sem:
            r = await self.client().get(f"{API}/GetAvailable/v2", params={
                "from": a[0], "to": b[0], "date": q.date, "genderCode": 3,
                "adultCount": max(1, q.adults), "childCount": q.children, "infantCount": q.infants,
                "exclusive": "false", "availableStatus": "Both"})
            r.raise_for_status()
            body = r.json()
        if not isinstance(body, dict) or not isinstance(body.get("trains"), list):
            raise MrBilitError("unexpected train response")
        return self.parse(body["trains"], q)

    async def cheapest(self, origin, destination, center, back, fwd):
        a, b = STATIONS.get(origin), STATIONS.get(destination)
        if not a or not b:
            return {}
        start, end = center - timedelta(days=back), center + timedelta(days=fwd)
        async with self._sem:
            r = await self.client().get(f"{API}/GetMinPrices", params={
                "From": a[0], "To": b[0], "FromDate": f"{start.isoformat()}T00:00:00.000Z",
                "ToDate": f"{end.isoformat()}T00:00:00.000Z", "Capacity": 1, "GenderCode": 3})
            r.raise_for_status()
            body = r.json()
        if not isinstance(body, dict):
            raise MrBilitError("unexpected calendar response")
        out: dict[str, int | None] = {}
        d = start
        while d <= end:
            out[d.isoformat()] = None
            d += timedelta(days=1)
        for day, v in body.items():
            try:
                price = int(float(v)) // 10
            except (TypeError, ValueError):
                continue
            if str(day)[:10] in out:
                out[str(day)[:10]] = price if price > 0 else None
        return out

    def parse(self, trains, q: SearchQuery) -> list[Flight]:
        link, out = self.deep_link(q), []
        for t in trains:
            if not isinstance(t, dict):
                continue
            dep, arr = _dt(t.get("departureTime")), _dt(t.get("arrivalTime"))
            if not dep:
                continue
            for group in t.get("prices") or []:
                for c in (group or {}).get("classes") or []:
                    try:
                        price = int(c.get("price") or 0) // 10
                        if price <= 0:
                            continue
                        seats = int(c.get("capacity") or 0)
                        comp = bool(c.get("isCompartment"))
                        cap = c.get("compartmentCapacity")
                        kind = f"کوپه {cap} نفره" if comp and cap else ("کوپه‌ای" if comp else "سالنی")
                        features = [kind]
                        if c.get("airConditioning"):
                            features.append("تهویه مطبوع")
                        if c.get("media"):
                            features.append("سیستم صوتی و تصویری")
                        features += [str(f) for f in (c.get("features") or []) if isinstance(f, str) and f not in features]
                        out.append(Flight(
                            mode="train", airline=str(t.get("corporationName") or t.get("providerName") or "").strip() or "قطار",
                            flight_number=str(t.get("trainNumber") or ""), origin=q.origin, destination=q.destination,
                            departure=dep, arrival=arr, aircraft=str(c.get("wagonName") or "").strip() or None,
                            seats_left=seats, features=features,
                            offers=[Offer(seller=self.name, price=price, url=link, fare_class=kind,
                                          available=bool(c.get("isAvailable")) and seats > 0)]))
                    except (KeyError, TypeError, ValueError) as e:
                        log.debug("skipping malformed train row: %r", e)
        return out


MrBilitProvider = MrBilitTrainProvider  # the original name


def _naive(v) -> datetime | None:
    """MrBilit flights carry +03:30; the rest of the app uses Tehran local time without an offset."""
    d = _dt(v)
    return d.replace(tzinfo=None) if d else None


class MrBilitFlightProvider(_MrBilitBase):
    modes = frozenset({"flight"})

    def deep_link(self, q: SearchQuery) -> str:
        return f"{SITE}/flights/{q.origin}-{q.destination}?departureDate={jalali_str(date.fromisoformat(q.date))}"

    async def search(self, q: SearchQuery) -> list[Flight]:
        async with self._sem:
            r = await self.client().post(FLIGHTS, json={
                "AdultCount": max(1, q.adults), "ChildCount": q.children, "InfantCount": q.infants,
                "CabinClass": "All", "Routes": [{"OriginCode": q.origin, "DestinationCode": q.destination,
                                                 "DepartureDate": q.date}],
                "Baggage": True, "IncludeFlightsWithHigherCapacity": True})
            r.raise_for_status()
            body = r.json()
        if not isinstance(body, dict) or not isinstance(body.get("Flights"), list):
            raise MrBilitError("unexpected flight response")
        return self.parse(body["Flights"], q)

    def parse(self, items, q: SearchQuery) -> list[Flight]:
        link, out = self.deep_link(q), []
        for it in items:
            try:
                segs = [s for s in it["Segments"]]
                legs = [leg for s in segs for leg in s["Legs"]]
                if len(legs) != 1 or legs[0].get("Stops"):
                    continue  # connecting flights are not supported yet
                leg = legs[0]
                dep, arr = _naive(leg["DepartureTime"]), _naive(leg.get("ArrivalTime"))
                if not dep:
                    continue
                best = None
                for p in it.get("Prices") or []:
                    fares = {f.get("PaxType"): f.get("TotalFare") for f in p.get("PassengerFares") or []}
                    price = int(fares.get("ADL") or 0) // 10
                    seats = int(p.get("Capacity") or 0)
                    if price <= 0 or seats <= 0:
                        continue
                    if best is None or price < best[0]:
                        best = (price, seats, p)
                if not best:
                    continue
                price, seats, p = best
                air = leg.get("Airline") or {}
                bag = p.get("Baggage")
                charter = bool(p.get("IsCharter"))
                out.append(Flight(
                    airline=fa_text(air.get("PersianTitle") or air.get("EnglishTitle")) or str(leg.get("AirlineCode") or ""),
                    airline_code=str(leg.get("AirlineCode") or ""), flight_number=str(leg.get("FlightNumber") or "").strip(),
                    origin=leg.get("OriginCode") or q.origin, destination=leg.get("DestinationCode") or q.destination,
                    departure=dep, arrival=arr, aircraft=(leg.get("AirCraft") or {}).get("ShortTitle"),
                    seats_left=seats, logo=air.get("Logo"),
                    origin_terminal=leg.get("DepartureTerminal") or None,
                    destination_terminal=leg.get("ArrivalTerminal") or None,
                    offers=[Offer(seller=self.name, price=price, url=link,
                                  fare_class=p.get("CabinClassDisplayName") or "اکونومی",
                                  baggage_kg=int(bag) if isinstance(bag, (int, float)) and p.get("BaggageType") == "KG" else None,
                                  refundable=bool(p.get("CancellationTernEntities")) and not charter)]))
            except (KeyError, TypeError, ValueError) as e:
                log.debug("skipping malformed flight row: %r", e)
        return out


class MrBilitBusProvider(_MrBilitBase):
    modes = frozenset({"bus"})

    def deep_link(self, q: SearchQuery) -> str:
        a = BUS_SLUGS.get(q.origin) or (STATIONS.get(q.origin) or (0, ""))[1]
        b = BUS_SLUGS.get(q.destination) or (STATIONS.get(q.destination) or (0, ""))[1]
        if not a or not b:
            return SITE + "/bus-ticket"
        return f"{SITE}/buses/{a}-{b}?departureDate={jalali_str(date.fromisoformat(q.date))}"

    async def search(self, q: SearchQuery) -> list[Flight]:
        org, dst = BUS_CODES.get(q.origin), BUS_CODES.get(q.destination)
        if not org or not dst:
            return []
        async with self._sem:
            r = await self.client().post(BUSES, json={
                "from": int(org), "to": int(dst), "date": q.date, "includeClosed": True, "includePromotions": True,
                "loadFromDbOnUnavailability": True, "includeUnderDevelopment": True})
            r.raise_for_status()
            body = r.json()
        if not isinstance(body, dict) or not isinstance(body.get("buses"), list):
            raise MrBilitError("unexpected bus response")
        return self.parse(body["buses"], q)

    def parse(self, items, q: SearchQuery) -> list[Flight]:
        link, out = self.deep_link(q), []
        for it in items:
            if not isinstance(it, dict) or it.get("isCar") or it.get("isExclusive"):
                continue
            try:
                price = int(it.get("price") or 0) // 10
                dep = _dt(it["departureTime"])
                if price <= 0 or not dep:
                    continue
                seats = int(it.get("capacity") or 0)
                bus_type = " ".join(str(it.get("busType") or "").split()) or None
                features = [str(f) for f in (it.get("features") or []) if isinstance(f, str)]
                vip = bool(it.get("isVIP"))
                if vip and "VIP" not in features:
                    features.insert(0, "VIP")
                out.append(Flight(
                    mode="bus", airline=" ".join(str(it.get("corporation") or "").split()) or "اتوبوس",
                    airline_code=str(it.get("companyCode") or ""), origin=q.origin, destination=q.destination,
                    departure=dep, arrival=None, aircraft=bus_type, seats_left=seats, features=features,
                    origin_terminal=it.get("fromTerminal"),
                    stops=[s for s in (it.get("intermediateDestinations") or []) if isinstance(s, str)],
                    offers=[Offer(seller=self.name, price=price, url=link, fare_class="VIP" if vip else "معمولی",
                                  refundable=True, available=seats > 0 and it.get("reservable", True) is not False)]))
            except (KeyError, TypeError, ValueError) as e:
                log.debug("skipping malformed bus row: %r", e)
        return out
