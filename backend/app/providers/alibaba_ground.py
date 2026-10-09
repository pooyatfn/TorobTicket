"""Alibaba.ir trains and buses.

Observed from alibaba.ir's own web client (2026-10):
  Train: POST https://ws.alibaba.ir/api/v2/train/available
           {"departureDate","origin","destination","passengerCount","isExclusiveCompartment":false,"ticketType":"Family"}
         -> {"result":{"requestId"}};  GET .../available/{requestId} -> {"result":{"departing":[...],"isCompleted"}}
         Prices ("cost") in RIAL; "seat" = seats left (0 = sold out); one row per train + wagon class.
  Bus:   GET https://ws.alibaba.ir/api/v2/bus/available?orginCityCode=11320000&destinationCityCode=31310000
           &requestDate=YYYY-MM-DD&passengerCount=N&serviceType=Bus
         -> {"result":{"availableList":[...]}}  (numeric city codes: see cities.BUS_CODES)
         Prices in RIAL; no arrival time is published.
Unofficial integration — see alibaba.py for the caveats.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, datetime

import httpx

from ..cities import BUS_CODES
from ..jalali import jalali_str
from ..models import Flight, Offer, SearchQuery
from .alibaba import AlibabaError
from .base import FlightProvider, poll_delay

log = logging.getLogger("torobticket.alibaba")
SITE = "https://www.alibaba.ir"
TRAIN = "https://ws.alibaba.ir/api/v2/train/available"
BUS = "https://ws.alibaba.ir/api/v2/bus/available"


class _AlibabaBase(FlightProvider):
    name = "علی‌بابا"
    min_interval = 0.5

    def __init__(self, client: httpx.AsyncClient | None = None, poll_interval: float = 1.0,
                 max_wait: float = 8.0, max_concurrency: int = 2):
        self._client = client
        self.poll_interval, self.max_wait = poll_interval, max_wait
        self._sem = asyncio.Semaphore(max_concurrency)

    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=10, headers={
                "Accept": "application/json, text/plain, */*",
                "User-Agent": os.getenv("TORUB_USER_AGENT", "Mozilla/5.0 (compatible; TorobTicket/0.2)"),
                "Origin": SITE, "Referer": SITE + "/"})
        return self._client


def _dt(v) -> datetime | None:
    try:
        return datetime.fromisoformat(str(v)) if v else None
    except ValueError:
        return None


class AlibabaTrainProvider(_AlibabaBase):
    modes = frozenset({"train"})

    def deep_link(self, q: SearchQuery) -> str:
        return (f"{SITE}/train/{q.origin}-{q.destination}?adult={q.adults}&child={q.children}&infant={q.infants}"
                f"&departing={jalali_str(date.fromisoformat(q.date))}&ticketType=Family&isExclusive=false")

    async def search(self, q: SearchQuery) -> list[Flight]:
        async with self._sem:
            c = self.client()
            r = await c.post(TRAIN, json={"departureDate": q.date, "origin": q.origin, "destination": q.destination,
                                          "passengerCount": max(1, q.adults + q.children),
                                          "isExclusiveCompartment": False, "ticketType": "Family"})
            r.raise_for_status()
            body = r.json()
            req_id = (body.get("result") or {}).get("requestId")
            if not body.get("success", True) or not req_id:
                raise AlibabaError(f"train search not accepted: {body.get('error')!r}")
            loop = asyncio.get_running_loop()
            deadline = loop.time() + self.max_wait
            polls = 0
            while True:
                r = await c.get(f"{TRAIN}/{req_id}")
                r.raise_for_status()
                res = r.json().get("result") or {}
                if res.get("isCompleted", True) or loop.time() + poll_delay(self.poll_interval, polls) > deadline:
                    break
                await asyncio.sleep(poll_delay(self.poll_interval, polls))
                polls += 1
        return self.parse(res.get("departing") or [], q)

    def parse(self, items, q: SearchQuery) -> list[Flight]:
        link, out = self.deep_link(q), []
        for it in items:
            if not isinstance(it, dict):
                continue
            try:
                price = int(it.get("cost") or it.get("fullPrice") or 0) // 10
                dep, arr = _dt(it["departureDateTime"]), _dt(it.get("arrivalDateTime"))
                if price <= 0 or not dep:
                    continue
                seats = int(it.get("seat") or 0)
                comp = bool(it.get("isCompartment"))
                cap = it.get("compartmentCapacity")
                features = [f"کوپه {cap} نفره" if comp and cap else ("کوپه‌ای" if comp else "سالنی")]
                if it.get("hasAirCondition"):
                    features.append("تهویه مطبوع")
                if it.get("hasMedia"):
                    features.append("سیستم صوتی و تصویری")
                if it.get("hasFreeFood"):
                    features.append("پذیرایی رایگان")
                out.append(Flight(
                    mode="train", airline=(it.get("companyName") or "").strip() or "قطار",
                    flight_number=str(it.get("trainNumber") or ""), origin=q.origin, destination=q.destination,
                    departure=dep, arrival=arr, aircraft=(it.get("wagonName") or "").strip() or None,
                    seats_left=seats, features=features,
                    offers=[Offer(seller=self.name, price=price, url=link,
                                  fare_class=features[0], refundable=not it.get("nonRefundable"),
                                  available=seats > 0)]))
            except (KeyError, TypeError, ValueError) as e:
                log.debug("skipping malformed train row: %r", e)
        return out


BUS_FEATURES = [("vip", "VIP"), ("وی آی پی", "VIP"), ("تخت", "صندلی تخت‌شو"), ("شارژ", "شارژر اختصاصی"),
                ("2+1", "چیدمان ۲+۱"), ("مارال", "اتوبوس مارال"), ("تهویه", "تهویه مطبوع")]


class AlibabaBusProvider(_AlibabaBase):
    modes = frozenset({"bus"})

    def deep_link(self, q: SearchQuery) -> str:
        # Alibaba's bus pages are addressed by its numeric city code (its own letter slugs exist for only a few cities)
        org, dst = BUS_CODES.get(q.origin), BUS_CODES.get(q.destination)
        if not org or not dst:
            return SITE + "/bus-ticket"
        return f"{SITE}/bus/{org}-{dst}?departing={jalali_str(date.fromisoformat(q.date))}"

    async def search(self, q: SearchQuery) -> list[Flight]:
        org, dst = BUS_CODES.get(q.origin), BUS_CODES.get(q.destination)
        if not org or not dst:
            return []
        async with self._sem:
            r = await self.client().get(BUS, params={
                "orginCityCode": org, "destinationCityCode": dst, "requestDate": q.date,
                "passengerCount": max(1, q.adults + q.children), "serviceType": "Bus"})
            r.raise_for_status()
            body = r.json()
        if body.get("success") is False:
            raise AlibabaError(f"bus search not accepted: {body.get('error')!r}")
        return self.parse(((body.get("result") or {}).get("availableList")) or [], q)

    def parse(self, items, q: SearchQuery) -> list[Flight]:
        link, out = self.deep_link(q), []
        for it in items:
            if not isinstance(it, dict):
                continue
            try:
                price = int(it.get("price") or 0) // 10
                dep = _dt(it["departureDateTime"])
                if price <= 0 or not dep:
                    continue
                bus_type = " ".join(str(it.get("busType") or "").split()) or None
                low = (bus_type or "").lower()
                features = []
                for needle, label in BUS_FEATURES:
                    if needle in low and label not in features:
                        features.append(label)
                seats = int(it.get("availableSeats") or 0)
                rate = it.get("rate")
                out.append(Flight(
                    mode="bus", airline=" ".join(str(it.get("companyName") or "").split()) or "اتوبوس",
                    airline_code=str(it.get("companyCode") or ""), origin=q.origin, destination=q.destination,
                    departure=dep, arrival=None, aircraft=bus_type, seats_left=seats, features=features,
                    origin_terminal=it.get("orginTerminal"), destination_terminal=it.get("destinationTerminal"),
                    stops=[s for s in (it.get("droppingPoints") or []) if isinstance(s, str)],
                    logo=it.get("logoPath"), rating=float(rate) if rate else None,
                    offers=[Offer(seller=self.name, price=price, url=link, fare_class="VIP" if "VIP" in features else "معمولی",
                                  refundable=bool(it.get("isRefundable")), available=seats > 0)]))
            except (KeyError, TypeError, ValueError) as e:
                log.debug("skipping malformed bus row: %r", e)
        return out
