"""Safarmarket.com — a flight metasearch: every flight comes with offers from several agencies.

Protocol (observed from safarmarket.com's own web client, 2026-10):
  Search (one request, ~5–7 s, no polling):
    POST https://safarmarket.com/api/flight/v3/search
      {"platform":"WEB_DESKTOP","limit":250,"compress":false,"productType":"LFLI","searchValidity":2,
       "searchFilter":{"sourceAirportCode","targetAirportCode","sourceIsCity","targetIsCity",
                       "leaveDate":"YYYY-MM-DD","returnDate":"","adultCount","childCount","infantCount",
                       "economy":true,"business":true}}
    -> {"code":200,"result":{"flights":[{"leave":{...},"providers":[{"title","price","url",...}]}]}}
  Cheapest per day (next ~31 days from today):
    GET https://safarmarket.com/api/flight/v3/calendar?org=THR&orgCity=true&dst=MHD&dstCity=true&dom=true
    -> {"cal":{"YYYY-MM-DD":{"minPrice","maxPrice"}}}
  Prices are in RIAL (we expose Toman). Each offer links to the agency's own booking page.

Note: Safarmarket's web client also sends a reCAPTCHA token and an X-Auth-Token header. The API currently
answers without them; this adapter does NOT fake, solve or work around them. If Safarmarket starts
requiring them, this seller will fail cleanly (circuit breaker) — the right fix then is a partner API.
Unofficial integration: respect Safarmarket's terms and keep the request rate low.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import date, datetime

import httpx

from ..models import Flight, Offer, SearchQuery, normalize_flight_number
from .base import FlightProvider

log = logging.getLogger("torobticket.safarmarket")

SITE = "https://safarmarket.com"
SEARCH = SITE + "/api/flight/v3/search"
CALENDAR = SITE + "/api/flight/v3/calendar"
VIA = "سفرمارکت"
# Codes that Safarmarket treats as a whole city (all its airports). Tehran: Mehrabad + IKA.
CITY_CODES = {"THR"}


class SafarmarketError(RuntimeError):
    pass


def _refundable(policies) -> bool:
    for p in policies or []:
        m = re.match(r"\s*(\d+)\s*%", str((p or {}).get("policy", "")))
        if m and int(m.group(1)) < 100:
            return True
    return False


def _baggage(bags) -> int | None:
    for b in bags or []:
        try:
            kg = int(float((b or {}).get("weightKg") or 0))
        except (TypeError, ValueError):
            continue
        if kg > 0:
            return kg
    return None


class SafarmarketProvider(FlightProvider):
    name = "سفرمارکت"  # used for status/caching; each offer carries the real agency as `seller`
    supports_cheapest = True
    min_interval = 3.0   # Safarmarket answers 429 when searched in bursts
    background = False   # never used by hourly sampling — only real user searches

    def __init__(self, client: httpx.AsyncClient | None = None, max_concurrency: int = 2):
        self._client = client
        self._sem = asyncio.Semaphore(max_concurrency)

    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=14, headers={
                "Accept": "application/json, */*",
                "User-Agent": os.getenv("TORUB_USER_AGENT", "Mozilla/5.0 (compatible; TorobTicket/0.2)"),
                "Origin": SITE, "Referer": SITE + "/",
            })
        return self._client

    async def search(self, q: SearchQuery) -> list[Flight]:
        body = {"platform": "WEB_DESKTOP", "uid": "", "limit": 250, "compress": False, "productType": "LFLI",
                "searchValidity": 2, "searchFilter": {
                    "sourceAirportCode": q.origin, "targetAirportCode": q.destination,
                    "sourceIsCity": q.origin in CITY_CODES, "targetIsCity": q.destination in CITY_CODES,
                    "leaveDate": q.date, "returnDate": "",
                    "adultCount": q.adults, "childCount": q.children, "infantCount": q.infants,
                    "economy": True, "business": True}}
        async with self._sem:
            r = await self.client().post(SEARCH, json=body)
            r.raise_for_status()
            data = r.json()
        if data.get("code") != 200 or not isinstance(data.get("result"), dict):
            raise SafarmarketError(f"search not accepted: code={data.get('code')!r} {data.get('message')!r}")
        return self.parse(data["result"].get("flights") or [], q)

    def parse(self, items: list, q: SearchQuery) -> list[Flight]:
        out: dict[tuple, Flight] = {}
        for it in items:
            if not isinstance(it, dict):
                continue
            try:
                leg = it["leave"]
                if leg.get("stopsCount") or not it.get("reservable", True):
                    continue  # connecting flights are not supported yet
                dep = datetime.fromisoformat(leg["departureTime"].replace(" ", "T"))
                arr = datetime.fromisoformat(leg["arrivalTime"].replace(" ", "T"))
                legs = leg.get("legs") or [{}]
                number = normalize_flight_number(leg["flightNo"])
                fare = "بیزینس" if str(it.get("flightClass", "")).upper() == "BUSINESS" else "اکونومی"
                offers = []
                for p in it.get("providers") or []:
                    if not isinstance(p, dict) or not p.get("reservable", True) or not p.get("capacity", 1):
                        continue
                    price = int(p.get("price") or 0) // 10  # rial -> toman
                    if price <= 0 or not p.get("url"):
                        continue
                    offers.append(Offer(
                        seller=p.get("title") or p.get("titleEn") or VIA, price=price, url=p["url"],
                        fare_class=fare, baggage_kg=_baggage(p.get("outBoundBaggages")),
                        refundable=_refundable(p.get("outBoundCancellationPolicies")), via=VIA))
                if not offers:
                    continue
                f = Flight(
                    airline=leg.get("airlineNameFa") or leg.get("airlineName") or leg.get("airlineCode", ""),
                    airline_code=leg.get("airlineCode", ""), flight_number=number,
                    origin=q.origin, destination=q.destination, departure=dep, arrival=arr,
                    aircraft=legs[0].get("airPlaneType"), offers=offers)
            except (KeyError, TypeError, ValueError, AttributeError) as e:
                log.debug("skipping malformed safarmarket item: %r", e)
                continue
            k = (number, dep)
            if k in out:  # same flight listed again (e.g. economy and business): pool the offers
                out[k].offers.extend(f.offers)
            else:
                out[k] = f
        return list(out.values())

    async def cheapest(self, origin, destination, center: date, back: int, fwd: int):
        async with self._sem:
            r = await self.client().get(CALENDAR, params={
                "org": origin, "orgCity": str(origin in CITY_CODES).lower(),
                "dst": destination, "dstCity": str(destination in CITY_CODES).lower(), "dom": "true"})
            r.raise_for_status()
            cal = (r.json() or {}).get("cal")
        if not isinstance(cal, dict):
            raise SafarmarketError("calendar: unexpected response")
        out: dict[str, int | None] = {}
        lo, hi = center.toordinal() - back, center.toordinal() + fwd
        for day, row in cal.items():
            try:
                if lo <= date.fromisoformat(day).toordinal() <= hi:
                    price = int((row or {}).get("minPrice") or 0) // 10
                    out[day] = price if price > 0 else None
            except (TypeError, ValueError):
                continue
        return out
