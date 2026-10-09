"""Alibaba.ir domestic flights.

Protocol (observed from alibaba.ir's own web client, 2026-10):
  1. POST https://ws.alibaba.ir/api/v1/flights/domestic/available
        {"origin","destination","departureDate":"YYYY-MM-DD","adult","child","infant"}
     -> {"result": {"requestId": "..."}, "success": true}
  2. GET  .../available/{requestId}   (poll until result.isCompleted)
     -> {"result": {"isCompleted": bool, "departing": [ {flight}, ... ]}}
  Cheapest price per day (used by the date strip, ~20 ms, one request for the whole range):
  3. POST https://ws.alibaba.ir/api/v2/flights/domestic/available/cheapest
        {"referenceDate":"YYYY-MM-DD","backwardDay":n,"forwardDay":m,"origin","destination"}
     -> {"result": [{"departureDateTime","adultPrice",...}, ...]}   one row per day,
        covering referenceDate-backwardDay .. referenceDate+forwardDay; adultPrice 0 = no flights.
        Verified to equal the minimum of a full search for the same day.
  Prices are in RIAL; we expose Toman (÷10). No login or cookies are needed.

This is an unofficial integration: it can break when Alibaba changes its site, and you are
responsible for complying with Alibaba's terms. Keep request volume low (see `max_concurrency`).
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, datetime

import httpx

from ..jalali import jalali_str
from ..models import Flight, Offer, SearchQuery
from .base import FlightProvider, poll_delay

log = logging.getLogger("torobticket.alibaba")

BASE = "https://ws.alibaba.ir/api/v1/flights/domestic/available"
CHEAPEST = "https://ws.alibaba.ir/api/v2/flights/domestic/available/cheapest"
SITE = "https://www.alibaba.ir"


class AlibabaError(RuntimeError):
    pass


class AlibabaProvider(FlightProvider):
    name = "علی‌بابا"
    supports_cheapest = True
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
                "Origin": SITE, "Referer": SITE + "/",
            })
        return self._client

    def deep_link(self, q: SearchQuery) -> str:
        return (f"{SITE}/flights/{q.origin}-{q.destination}?adult={q.adults}&child={q.children}"
                f"&infant={q.infants}&departing={jalali_str(date.fromisoformat(q.date))}")

    async def search(self, q: SearchQuery) -> list[Flight]:
        async with self._sem:
            c = self.client()
            r = await c.post(BASE, json={"origin": q.origin, "destination": q.destination,
                                         "departureDate": q.date, "adult": q.adults,
                                         "child": q.children, "infant": q.infants})
            r.raise_for_status()
            body = r.json()
            req_id = (body.get("result") or {}).get("requestId")
            if not body.get("success") or not req_id:
                raise AlibabaError(f"search not accepted: {body.get('error')!r}")

            loop = asyncio.get_running_loop()
            deadline = loop.time() + self.max_wait
            polls = 0
            result: dict = {}
            while True:
                r = await c.get(f"{BASE}/{req_id}")
                r.raise_for_status()
                result = r.json().get("result") or {}
                if result.get("isCompleted") or loop.time() + poll_delay(self.poll_interval, polls) > deadline:
                    break
                await asyncio.sleep(poll_delay(self.poll_interval, polls))
                polls += 1
            if not result.get("isCompleted"):
                log.info("alibaba %s-%s %s: returning partial results", q.origin, q.destination, q.date)
            return self.parse(result.get("departing") or [], q)

    async def cheapest(self, origin, destination, center, back, fwd):
        async with self._sem:
            r = await self.client().post(CHEAPEST, json={
                "referenceDate": center.isoformat(), "backwardDay": back, "forwardDay": fwd,
                "origin": origin, "destination": destination})
            r.raise_for_status()
            body = r.json()
        if not body.get("success") or not isinstance(body.get("result"), list):
            raise AlibabaError(f"cheapest not accepted: {body.get('error')!r}")
        out: dict[str, int | None] = {}
        for row in body["result"]:
            try:
                day = str(row["departureDateTime"])[:10]
                price = int(row.get("adultPrice") or 0) // 10
            except (KeyError, TypeError, ValueError):
                continue
            out[day] = price if price > 0 else None
        return out

    def parse(self, items: list[dict], q: SearchQuery) -> list[Flight]:
        link = self.deep_link(q)
        best: dict[tuple, Flight] = {}
        for it in items:
            if not isinstance(it, dict):
                continue
            try:
                if not it.get("isAllowedToBuy") or not it.get("seat") or it.get("hasConnection"):
                    continue  # sold out / not bookable / connecting (not supported yet)
                price = int(it["priceAdult"]) // 10  # rial -> toman
                if price <= 0:
                    continue
                f = Flight(
                    airline=it.get("airlineName") or it["airlineCode"], airline_code=it["airlineCode"],
                    flight_number=str(it["flightNumber"]).strip(),
                    origin=it.get("origin") or q.origin, destination=it.get("destination") or q.destination,
                    departure=datetime.fromisoformat(it["leaveDateTime"]),
                    arrival=datetime.fromisoformat(it["arrivalDateTime"]),
                    aircraft=it.get("aircraft"),
                    offers=[Offer(seller=self.name, price=price, url=link,
                                  fare_class=it.get("classTypeName") or "اکونومی",
                                  baggage_kg=it.get("maxAllowedBaggage"),
                                  refundable=bool(it.get("isRefundable")))],
                )
            except (KeyError, TypeError, ValueError) as e:
                log.debug("skipping malformed alibaba item: %r", e)
                continue
            # The same physical flight is often listed once per charter supplier: keep the cheapest.
            k = (f.airline_code, f.flight_number, f.departure)
            if k not in best or price < best[k].offers[0].price:
                best[k] = f
        return list(best.values())
