"""Config-driven adapter for a seller exposing a JSON search endpoint.

Use it as the starting point for real sources. Verify the endpoint and the seller's
terms of use first; this module only maps JSON -> Flight and does not bypass anything.

Config entry (see providers.example.json):
  {"type": "http_json", "name": "...", "url": "https://.../search", "method": "GET",
   "params": {"from": "{origin}", "to": "{destination}", "date": "{date}"},
   "headers": {}, "items_path": "data.flights",
   "map": {"airline": "airline.name", "airline_code": "airline.code", "flight_number": "number",
           "departure": "departure", "arrival": "arrival", "price": "price", "url": "link"}}
"""
from __future__ import annotations

import httpx
from datetime import datetime

from ..models import Flight, Offer, SearchQuery
from .base import FlightProvider


def dig(obj, path: str, default=None):
    for part in path.split("."):
        if isinstance(obj, list):
            try:
                obj = obj[int(part)]
            except (ValueError, IndexError):
                return default
        elif isinstance(obj, dict) and part in obj:
            obj = obj[part]
        else:
            return default
    return obj


class HttpJsonProvider(FlightProvider):
    def __init__(self, cfg: dict, client: httpx.AsyncClient | None = None):
        self.cfg = cfg
        self.name = cfg["name"]
        self.client = client

    async def search(self, q: SearchQuery) -> list[Flight]:
        c = self.cfg
        fmt = q.model_dump()
        params = {k: str(v).format(**fmt) for k, v in c.get("params", {}).items()}
        client = self.client or httpx.AsyncClient(timeout=c.get("timeout", 8))
        try:
            if c.get("method", "GET").upper() == "POST":
                r = await client.post(c["url"], json=params, headers=c.get("headers"))
            else:
                r = await client.get(c["url"], params=params, headers=c.get("headers"))
            r.raise_for_status()
            data = r.json()
        finally:
            if not self.client:
                await client.aclose()

        m = c["map"]
        out = []
        for it in dig(data, c.get("items_path", ""), data) if c.get("items_path") else data:
            try:
                out.append(Flight(
                    airline=dig(it, m["airline"]), airline_code=dig(it, m["airline_code"]),
                    flight_number=str(dig(it, m["flight_number"])),
                    origin=q.origin, destination=q.destination,
                    departure=datetime.fromisoformat(dig(it, m["departure"])),
                    arrival=datetime.fromisoformat(dig(it, m["arrival"])),
                    offers=[Offer(seller=self.name, price=int(dig(it, m["price"])),
                                  url=dig(it, m["url"], c["url"]))],
                ))
            except (TypeError, ValueError, KeyError):
                continue  # skip malformed rows rather than failing the whole seller
        return out
