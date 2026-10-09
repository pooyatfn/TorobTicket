from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Mode = Literal["flight", "train", "bus"]
MODES: tuple[str, ...] = ("flight", "train", "bus")


def normalize_flight_number(raw: str) -> str:
    """'IS4303' -> '4303', 'B98006' -> '8006', 'NV2628' -> '2628', '0450' -> '450', '4200' -> '4200'."""
    s = re.sub(r"[\s\-]", "", str(raw)).upper()
    if s[:1].isalpha() and len(s) > 2:
        s = s[2:]  # drop the 2-character IATA airline designator (it may contain a digit, e.g. B9, A7)
    digits = re.sub(r"\D", "", s)
    return digits.lstrip("0") or digits or s


_LETTERS = {"ي": "ی", "ك": "ک", "ة": "ه", "ۀ": "ه", "أ": "ا", "إ": "ا", "ؤ": "و"}
_DISPLAY = str.maketrans(_LETTERS)
_ARABIC = str.maketrans({**_LETTERS, "\u200c": ""})


def fa_text(raw) -> str:
    """Display form of a Persian label: Arabic letter variants -> Persian, single spaces."""
    return " ".join(str(raw or "").translate(_DISPLAY).split())


def norm_text(raw) -> str:
    """Compare Persian labels across sellers: Arabic/Persian letter variants, spacing, punctuation."""
    s = str(raw or "").translate(_ARABIC)
    return re.sub(r"[\s\-_()（）،,.:]+", "", s).lower()


class Offer(BaseModel):
    seller: str
    price: int = Field(description="Price per adult in Toman")
    url: str
    fare_class: str = "اکونومی"
    baggage_kg: int | None = None
    refundable: bool = False
    via: str | None = None  # marketplace the offer came through (e.g. سفرمارکت), shown next to the seller
    available: bool = True  # False = listed but sold out


class Flight(BaseModel):
    """One bookable trip: a flight, a train (one wagon class) or a bus departure.

    Field names come from the flight-only first version; for trains/buses `airline` is the operator,
    `flight_number` the train number (empty for buses) and `aircraft` the wagon / bus type.
    """
    id: str = ""
    mode: Mode = "flight"
    airline: str
    airline_code: str = ""
    flight_number: str = ""
    origin: str
    destination: str
    departure: datetime
    arrival: datetime | None = None  # buses don't publish an arrival time
    aircraft: str | None = None
    seats_left: int | None = None
    features: list[str] = []
    origin_terminal: str | None = None
    destination_terminal: str | None = None
    stops: list[str] = []  # intermediate / drop-off points (buses)
    logo: str | None = None
    rating: float | None = None
    offers: list[Offer] = []

    @property
    def duration_minutes(self) -> int | None:
        if not self.arrival:
            return None
        return int((self.arrival - self.departure).total_seconds() // 60)

    @property
    def key(self) -> str:
        """Identity of the physical trip across sellers.

        Flights: sellers spell airlines differently (Alibaba "SR 4303" / Safarmarket "IS4303"), so match on
        route + numeric flight number + departure minute. Trains: number + wagon class. Buses: operator + type.
        """
        route = f"{self.mode}|{self.origin}-{self.destination}|{self.departure.isoformat(timespec='minutes')}"
        if self.mode == "flight":
            return f"{route}|{normalize_flight_number(self.flight_number)}"
        if self.mode == "train":
            return f"{route}|{self.flight_number}|{norm_text(self.aircraft)}"
        return f"{route}|{norm_text(self.airline)}|{norm_text(self.aircraft)}"


class FlightOut(Flight):
    duration_min: int | None
    min_price: int
    seller_count: int
    available: bool = True


class SearchQuery(BaseModel):
    mode: Mode = "flight"
    origin: str
    destination: str
    date: str  # YYYY-MM-DD (Gregorian; the UI converts from Jalali)
    adults: int = 1
    children: int = 0
    infants: int = 0


class ProviderStatus(BaseModel):
    ok: bool
    ms: int
    count: int
    error: str | None = None
    stale: bool = False  # served from the last good answer because the live call failed
    cached: bool = False  # served from this seller's cache (no call made)
    age: int | None = None  # seconds since this seller's answer was fetched, when served from cache
    refreshing: bool = False  # a cached answer was served and a fresh one is being fetched in the background


class SearchResponse(BaseModel):
    query: SearchQuery
    flights: list[FlightOut]
    providers: dict[str, ProviderStatus]
    pending: list[str] = []  # sellers still searching (streamed responses only)
    done: bool = True  # false while more sellers are on the way (streamed responses only)


class PricePoint(BaseModel):
    ts: datetime
    price: int


class AlertIn(BaseModel):
    mode: Mode = "flight"
    origin: str
    destination: str
    date: str
    target_price: int = Field(gt=0)
    contact: str = Field(min_length=3, description="Iranian mobile (09xxxxxxxxx) or e-mail")
    flight_id: str | None = None

    @field_validator("contact")
    @classmethod
    def _contact(cls, v: str) -> str:
        v = v.strip().translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
        if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", v):
            return v.lower()
        phone = re.sub(r"[\s\-()]", "", v)
        phone = re.sub(r"^(\+98|0098|98)", "0", phone)
        if re.fullmatch(r"09\d{9}", phone):
            return phone
        raise ValueError("شماره موبایل یا ایمیل معتبر نیست")


class Alert(AlertIn):
    id: int
    created: datetime
    triggered_at: datetime | None = None
    notified_at: datetime | None = None
    last_price: int | None = None
