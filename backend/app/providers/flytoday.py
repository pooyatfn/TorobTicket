"""FlyToday.ir (فلای‌تودی) trains.

Observed from flytoday.ir's own web client (2026-10):
  Search: POST https://www.flytoday.ir/api/gateway/V2/DomesticRails/Search
            {"sexCode":3,"adultsCount":1,"childCount":0,"infantCount":0,"isExclusive":false,"tripType":"OneWay",
             "originDestination":[{"origin":1,"destination":191,"moveDate":"2026-10-20"}]}
          -> {"itinerariesList":[{"itineraries":[{"trainNumber","wagonName","railCompanyName","moveDate",
                                                   "arrivalDate","remainingSeats","price","isCompartment",...}]}]}
  `origin`/`destination` are station ids (the same ids as MrBilit's, see mrbilit.STATIONS).
  Prices are in RIAL (we expose Toman); one row per train + wagon class; remainingSeats 0 = sold out.

  Flights: POST https://www.flytoday.ir/api/gateway/v1/Flight/SplittedSearch?sortBy=Cheapest&pageNumber=1&pageSize=100
            {"pricingSourceType":0,"adultCount":1,"childCount":0,"infantCount":0,
             "travelPreference":{"cabinType":"Y","maxStopsQuantity":"All","airTripType":"OneWay"},
             "originDestinationInformations":[{"originLocationCode":"THR","originType":"City",
               "destinationLocationCode":"MHD","destinationType":"City","departureDateTime":"2026-10-20"}],"isJalali":true}
          -> {"pricedItineraries":[{"airItineraryPricingInfo":{"itinTotalFare":{"totalFare"}},
               "originDestinationOptions":[{"flightSegments":[{"flightNumber":"IRZ170","departureDateTime",...}]}]}]}
          (one entry per fare class; the same flight can appear several times).
The site's client has a "search captcha" mode that is switched off today. This adapter does NOT fake, solve or
work around it: if FlyToday starts demanding it (HTTP 400/422 mentioning a captcha), the seller fails cleanly
and the circuit breaker takes over.
Unofficial integration: keep the request rate low and respect FlyToday's terms.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime

import httpx

from ..models import Flight, Offer, SearchQuery, fa_text
from .base import FlightProvider
from .mrbilit import STATIONS

log = logging.getLogger("torobticket.flytoday")

SITE = "https://www.flytoday.ir"
SEARCH = SITE + "/api/gateway/V2/DomesticRails/Search"


class FlyTodayError(RuntimeError):
    pass


def _dt(v) -> datetime | None:
    try:
        return datetime.fromisoformat(str(v)) if v else None
    except ValueError:
        return None


class _FlyTodayBase(FlightProvider):
    name = "فلای‌تودی"
    min_interval = 0.7

    def __init__(self, client: httpx.AsyncClient | None = None, max_concurrency: int = 2):
        self._client = client
        self._sem = asyncio.Semaphore(max_concurrency)

    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=15, headers={
                "Accept": "application/json, text/plain, */*",
                "User-Agent": os.getenv("TORUB_USER_AGENT", "Mozilla/5.0 (compatible; TorobTicket/0.2)"),
                "Origin": SITE, "Referer": SITE + "/"})
        return self._client


class FlyTodayTrainProvider(_FlyTodayBase):
    modes = frozenset({"train"})

    def deep_link(self, q: SearchQuery) -> str:
        a, b = STATIONS.get(q.origin), STATIONS.get(q.destination)
        if not a or not b:
            return SITE + "/train"
        return (f"{SITE}/train/{a[1].replace('_', '')}-{b[1].replace('_', '')}?origin={a[0]}&destination={b[0]}"
                f"&departureDate={q.date}&adt={max(1, q.adults)}&chd={q.children}&inf={q.infants}&genderType=3")

    async def search(self, q: SearchQuery) -> list[Flight]:
        a, b = STATIONS.get(q.origin), STATIONS.get(q.destination)
        if not a or not b:
            return []
        async with self._sem:
            r = await self.client().post(SEARCH, json={
                "sexCode": 3, "adultsCount": max(1, q.adults), "childCount": q.children,
                "infantCount": q.infants, "isExclusive": False, "tripType": "OneWay",
                "originDestination": [{"origin": a[0], "destination": b[0], "moveDate": q.date}]})
            if r.status_code in (400, 422) and "captcha" in r.text.lower():
                raise FlyTodayError("FlyToday now requires a captcha for train search; not supported")
            r.raise_for_status()
            body = r.json()
        if not isinstance(body, dict) or not isinstance(body.get("itinerariesList"), list):
            raise FlyTodayError("unexpected train response")
        return self.parse(body, q)

    def parse(self, body: dict, q: SearchQuery) -> list[Flight]:
        link, out = self.deep_link(q), []
        for group in body.get("itinerariesList") or []:
            for it in (group or {}).get("itineraries") or []:
                if not isinstance(it, dict):
                    continue
                try:
                    price = int(it.get("finalPrice") or it.get("price") or 0) // 10
                    dep, arr = _dt(it["moveDate"]), _dt(it.get("arrivalDate"))
                    if price <= 0 or not dep or it.get("isExclusive"):
                        continue
                    seats = int(it.get("remainingSeats") or 0)
                    comp = bool(it.get("isCompartment"))
                    cap = it.get("compartmentCapacity")
                    kind = f"کوپه {cap} نفره" if comp and cap else ("کوپه‌ای" if comp else "سالنی")
                    features = [kind]
                    if it.get("hasMedia"):
                        features.append("سیستم صوتی و تصویری")
                    if it.get("hasFood"):
                        features.append("پذیرایی")
                    out.append(Flight(
                        mode="train", airline=fa_text(it.get("railCompanyName")) or "قطار",
                        flight_number=str(it.get("trainNumber") or ""), origin=q.origin, destination=q.destination,
                        departure=dep, arrival=arr, aircraft=fa_text(it.get("wagonName")) or None,
                        seats_left=seats, features=features,
                        offers=[Offer(seller=self.name, price=price, url=link, fare_class=kind,
                                      available=seats > 0 and it.get("isCapacityEnough", True) is not False)]))
                except (KeyError, TypeError, ValueError) as e:
                    log.debug("skipping malformed train row: %r", e)
        return out


FlyTodayProvider = FlyTodayTrainProvider  # the original name

FLIGHTS = SITE + "/api/gateway/v1/Flight/SplittedSearch"
# FlyToday names airlines in English only; show the Persian name when this seller is the only one with the flight.
AIRLINES_FA = {"IRZ": "ساها ایر", "SH": "ساها ایر", "MEH": "هواپیمایی مهر", "CPN": "کاسپین", "IS": "سپهران",
               "VRH": "وارش", "W5": "ماهان", "IR": "ایران ایر", "EP": "آسمان", "QB": "قشم ایر", "ZV": "زاگرس",
               "Y9": "کیش ایر", "NV": "نسیم ایر", "HH": "تابان", "A1": "آتا", "B9": "ایران ایرتور",
               "AXV": "آوا ایر", "I3": "آتا"}


class FlyTodayFlightProvider(_FlyTodayBase):
    modes = frozenset({"flight"})

    def deep_link(self, q: SearchQuery) -> str:
        return (f"{SITE}/flight/search?departure={q.origin.lower()},1&arrival={q.destination.lower()},1"
                f"&departureDate={q.date}&adt={max(1, q.adults)}&chd={q.children}&inf={q.infants}&cabin=1&isDomestic=true")

    async def search(self, q: SearchQuery) -> list[Flight]:
        async with self._sem:
            r = await self.client().post(FLIGHTS, params={"sortBy": "Cheapest", "pageNumber": 1, "pageSize": 100}, json={
                "pricingSourceType": 0, "adultCount": max(1, q.adults), "childCount": q.children,
                "infantCount": q.infants,
                "travelPreference": {"cabinType": "Y", "maxStopsQuantity": "All", "airTripType": "OneWay"},
                "originDestinationInformations": [{
                    "originLocationCode": q.origin, "originType": "City",
                    "destinationLocationCode": q.destination, "destinationType": "City",
                    "departureDateTime": q.date}],
                "isJalali": True})
            if r.status_code in (400, 422) and "captcha" in r.text.lower():
                raise FlyTodayError("FlyToday now requires a captcha for flight search; not supported")
            r.raise_for_status()
            body = r.json()
        if not isinstance(body, dict) or not isinstance(body.get("pricedItineraries"), list):
            raise FlyTodayError("unexpected flight response")
        return self.parse(body, q)

    def parse(self, body: dict, q: SearchQuery) -> list[Flight]:
        link = self.deep_link(q)
        names = {a.get("iata"): a.get("nameLocal") or a.get("name")
                 for a in ((body.get("additionalData") or {}).get("airlines") or []) if isinstance(a, dict)}
        best: dict[tuple, Flight] = {}
        for it in body.get("pricedItineraries") or []:
            try:
                opts = it["originDestinationOptions"]
                segs = [s for o in opts for s in o["flightSegments"]]
                if it.get("isClosed") or len(segs) != 1 or segs[0].get("stopQuantity"):
                    continue  # closed / connecting (not supported yet)
                s = segs[0]
                adt = next((b for b in it["airItineraryPricingInfo"]["ptcFareBreakdown"]
                            if (b.get("passengerTypeQuantity") or {}).get("passengerType") == "Adt"), None)
                fare = (adt or {}).get("passengerFare", {}).get("totalFare") or \
                    it["airItineraryPricingInfo"]["itinTotalFare"]["totalFare"]
                price, seats = int(fare) // 10, int(s.get("seatsRemaining") or 0)
                if price <= 0 or seats <= 0:
                    continue
                code = str(s.get("marketingAirlineCode") or it.get("validatingAirlineCode") or "")
                op = s.get("operatingAirline") or {}
                bag = "".join(ch for ch in str(s.get("baggage") or "").split("KG")[0] if ch.isdigit()) if "KG" in str(s.get("baggage") or "") else ""
                f = Flight(
                    airline=AIRLINES_FA.get(code) or names.get(code) or code, airline_code=code,
                    flight_number=str(s.get("flightNumber") or "").strip(),
                    origin=str(s["departureAirportLocationCode"]).upper(),
                    destination=str(s["arrivalAirportLocationCode"]).upper(),
                    departure=datetime.fromisoformat(s["departureDateTime"]),
                    arrival=datetime.fromisoformat(s["arrivalDateTime"]),
                    aircraft=op.get("equipmentName") or op.get("equipment"), seats_left=seats,
                    offers=[Offer(seller=self.name, price=price, url=link,
                                  fare_class="چارتر" if it.get("isCharter") else "اکونومی",
                                  baggage_kg=int(bag) if bag else None, refundable=not it.get("isCharter"))])
            except (KeyError, TypeError, ValueError, StopIteration) as e:
                log.debug("skipping malformed flight row: %r", e)
                continue
            k = (f.airline_code, f.flight_number, f.departure)
            if k not in best or price < best[k].offers[0].price:
                best[k] = f  # the same flight is listed once per fare class: keep the cheapest
        return list(best.values())
