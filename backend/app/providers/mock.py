"""Deterministic demo data. Seller names are fictional."""
from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta

from ..models import Flight, Offer, SearchQuery
from .base import FlightProvider

AIRLINES = [
    ("ایران‌ایر", "IR", "Airbus A320"), ("ماهان", "W5", "Airbus A310"),
    ("آسمان", "EP", "ATR 72"), ("کاسپین", "IV", "MD-83"),
    ("ایران‌ایرتور", "B9", "Boeing 737"), ("قشم‌ایر", "QB", "Fokker 100"),
    ("زاگرس", "ZV", "Boeing 737"), ("وارش", "VR", "Airbus A320"),
]
SELLERS = ["آژانس نمونه الف", "آژانس نمونه ب", "آژانس نمونه ج", "آژانس نمونه د"]


def _rng(*parts: str) -> random.Random:
    return random.Random(int(hashlib.sha256("|".join(parts).encode()).hexdigest()[:12], 16))


RAIL = [("رجا", "سالنی ۴ ستاره", ["سالنی", "تهویه مطبوع"]), ("فدک", "کوپه ۴ نفره ۵ ستاره", ["کوپه 4 نفره", "تهویه مطبوع", "پذیرایی رایگان"]),
        ("ریل ترابر سبا", "کوپه ۶ نفره ۳ ستاره", ["کوپه 6 نفره", "تهویه مطبوع"]), ("بن ریل", "کوپه ۴ نفره ۴ ستاره", ["کوپه 4 نفره", "تهویه مطبوع", "سیستم صوتی و تصویری"])]
BUS_CO = [("تعاونی نمونه ۱", "VIP ۲۵ نفره تخت‌شو", ["VIP", "صندلی تخت‌شو"]), ("تعاونی نمونه ۲", "مارال ۳ محوره", ["اتوبوس مارال"]),
          ("تعاونی نمونه ۳", "VIP ۲۹ نفره با شارژر", ["VIP", "شارژر اختصاصی"]), ("تعاونی نمونه ۴", "معمولی ۴۴ نفره", [])]


class MockProvider(FlightProvider):
    modes = frozenset({"flight", "train", "bus"})

    def __init__(self, name: str, base_markup: float = 0.0):
        self.name = name
        self.markup = base_markup

    async def search(self, q: SearchQuery) -> list[Flight]:
        if q.mode != "flight":
            return self._ground(q)
        return self._flights(q)

    def _ground(self, q: SearchQuery) -> list[Flight]:
        """Demo trains/buses: only the first demo seller sells ground transport (like real life: one agency)."""
        sched = _rng(q.mode, q.origin, q.destination, q.date)
        if _rng(self.name).random() < 0.5 and self.name != SELLERS[0]:
            return []
        day = datetime.fromisoformat(q.date)
        hours = 6 + _rng(*sorted([q.origin, q.destination])).randint(2, 10) * (2 if q.mode == "train" else 1)
        out = []
        for i in range(sched.randint(6, 12)):
            co, vehicle, feats = sched.choice(RAIL if q.mode == "train" else BUS_CO)
            dep = day + timedelta(hours=sched.randint(0, 22), minutes=sched.choice([0, 15, 30, 45]))
            base = (hours * (120_000 if q.mode == "train" else 90_000) + sched.randint(0, 400_000)) // 10_000 * 10_000
            seats = sched.choice([0, 3, 12, 25, 40]) if q.mode == "bus" else sched.choice([0, 8, 30, 120])
            price = int(base * (1 + self.markup)) // 1000 * 1000
            out.append(Flight(
                mode=q.mode, airline=co, flight_number=str(sched.randint(100, 999)) if q.mode == "train" else "",
                origin=q.origin, destination=q.destination, departure=dep,
                arrival=dep + timedelta(hours=hours) if q.mode == "train" else None,
                aircraft=vehicle, seats_left=seats, features=list(feats),
                origin_terminal="پایانه جنوب" if q.mode == "bus" else None,
                offers=[Offer(seller=self.name, price=price, url=f"https://example.com/{q.mode}/{i}",
                              fare_class=feats[0] if feats else "معمولی", refundable=sched.random() < 0.7,
                              available=seats > 0)]))
        return out

    def _flights(self, q: SearchQuery) -> list[Flight]:
        # The flight schedule is shared by all mock sellers (same seed); prices differ per seller.
        sched = _rng(q.origin, q.destination, q.date)
        day = datetime.fromisoformat(q.date)
        distance = 40 + _rng(*sorted([q.origin, q.destination])).randint(0, 90)  # minutes
        flights = []
        for i in range(sched.randint(8, 13)):
            al_name, al_code, ac = sched.choice(AIRLINES)
            dep = day + timedelta(hours=6, minutes=sched.randrange(0, 16 * 60, 5))
            arr = dep + timedelta(minutes=distance + sched.randint(-5, 15))
            base = (distance * 28_000 + sched.randint(0, 600_000)) // 10_000 * 10_000
            num = str(sched.randint(100, 9999))
            if sched.random() < 0.15:  # not every seller lists every flight
                if _rng(self.name, num).random() < 0.5:
                    continue
            pr = _rng(self.name, q.date, al_code, num)
            price = int(base * (1 + self.markup + pr.uniform(-0.04, 0.08))) // 1000 * 1000
            flights.append(Flight(
                airline=al_name, airline_code=al_code, flight_number=num,
                origin=q.origin, destination=q.destination, departure=dep, arrival=arr, aircraft=ac,
                offers=[Offer(
                    seller=self.name, price=price,
                    url=f"https://example.com/{self.name}/{al_code}{num}",
                    fare_class=pr.choice(["اکونومی", "اکونومی", "بیزینس"]),
                    baggage_kg=pr.choice([20, 20, 30]), refundable=pr.random() < 0.5,
                )],
            ))
        return flights
