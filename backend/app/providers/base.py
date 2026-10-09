from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from ..models import Flight, SearchQuery


class FlightProvider(ABC):
    """One seller/source. Returns flights each carrying exactly the offer(s) it sells."""

    name: str
    # Politeness: minimum seconds between the start of two requests to this seller (enforced by the service).
    min_interval: float = 0.0
    # Whether background jobs (hourly watchlist sampling) may use this seller. Sellers that rate-limit
    # aggressively are reserved for real user searches.
    background: bool = True
    # Travel modes this seller answers for ("flight", "train", "bus").
    modes: frozenset = frozenset({"flight"})

    @abstractmethod
    async def search(self, q: SearchQuery) -> list[Flight]: ...

    # Optional fast path for the date strip. Sellers that can answer "cheapest adult price per day"
    # in one request set this True and implement `cheapest`; others are searched day by day.
    supports_cheapest: bool = False

    async def cheapest(self, origin: str, destination: str, center: date, back: int,
                       fwd: int) -> dict[str, int | None]:
        """{'YYYY-MM-DD': toman or None (no flights)} for center-back .. center+fwd."""
        raise NotImplementedError


def poll_delay(interval: float, n: int) -> float:
    """Delay before poll n+1 of a start-then-poll search: 0.25 s, 0.4 s, then every 0.5 s (never more
    than `interval`). Most searches finish in 1–2 s; fixed 1 s steps added up to a second of waiting."""
    return min(interval, 0.25 * 1.6 ** n, 0.5)
