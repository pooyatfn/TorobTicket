from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass
from datetime import date as _date, timedelta, datetime
from typing import AsyncIterator

import httpx
from pydantic import TypeAdapter

from .cache import Cache, MemoryCache
from .notify import ConsoleNotifier, Notifier
from .models import Flight, FlightOut, ProviderStatus, SearchQuery, SearchResponse
from .providers.base import FlightProvider

log = logging.getLogger("torobticket")

FLIGHTS = TypeAdapter(list[Flight])
TRIP = TypeAdapter(dict)


def flight_id(f: Flight) -> str:
    return hashlib.sha1(f.key.encode()).hexdigest()[:12]


@dataclass
class ProviderState:
    """Per-process counters shown on /api/providers/status. The breaker itself lives in the cache."""
    last_ok: float | None = None  # wall clock
    last_error: str | None = None
    total_calls: int = 0
    total_failures: int = 0


class RateLimited(Exception):
    def __init__(self, retry_after: float):
        super().__init__(f"rate limited, retry after {retry_after:.0f}s")
        self.retry_after = retry_after


def _retry_after(resp: httpx.Response, default: float = 60.0) -> float:
    try:
        v = float(resp.headers.get("Retry-After", ""))
        return max(1.0, min(v, 900.0))
    except ValueError:
        return default


class SearchService:
    """Queries every seller in parallel and merges their answers into one row per trip.

    Cache keys (all in `cache`, shared between processes when it is Redis):
      s:<seller>:<query hash>  one seller's answer: fresh for `cache_ttl`, served instantly and
                               refreshed in the background up to `swr_ttl`, used as a labelled
                               fallback when the seller fails up to `stale_ttl`
      l:<same>                 lease: one process fetches, the others wait for its answer
      b:<seller> / f:<seller>  circuit breaker: open-until time / consecutive failures
      p:<seller>               next request slot (min_interval between requests to a seller)
      t:<trip id>              recently returned trips, for trip pages and shared links
      c:<route/date/span>      date-strip prices
    """

    def __init__(self, providers: list[FlightProvider], store, timeout: float = 10.0,
                 cache_ttl: float = 60.0, retries: int = 1, backoff: float = 0.2,
                 fail_threshold: int = 3, cooldown: float = 60.0, stale_ttl: float = 900.0,
                 notifiers: list[Notifier] | None = None, cache: Cache | None = None,
                 swr_ttl: float = 0.0, trip_ttl: float = 6 * 3600, write_behind: bool = False):
        self.notifiers = notifiers if notifiers is not None else [ConsoleNotifier()]
        self.providers, self.store, self.timeout = providers, store, timeout
        self.cache: Cache = cache if cache is not None else MemoryCache()
        self.cache_ttl, self.swr_ttl, self.stale_ttl = cache_ttl, swr_ttl, stale_ttl
        self.trip_ttl, self.write_behind = trip_ttl, write_behind
        self.retries, self.backoff = retries, backoff
        self.fail_threshold, self.cooldown = fail_threshold, cooldown
        self.stats: dict[str, ProviderState] = {}
        self.last_snapshot: dict = {}
        self._inflight: dict[str, asyncio.Task] = {}
        self._bg: set[asyncio.Task] = set()

    # ---- background tasks
    def _spawn(self, coro) -> asyncio.Task:
        t = asyncio.create_task(coro)
        self._bg.add(t)

        def done(t: asyncio.Task):
            self._bg.discard(t)
            if not t.cancelled() and t.exception():
                log.warning("background task failed: %r", t.exception())
        t.add_done_callback(done)
        return t

    async def drain(self):
        """Wait for background work (history writes, cache refreshes) to finish."""
        while self._bg:
            await asyncio.gather(*list(self._bg), return_exceptions=True)

    # ---- per-seller cache
    def _key(self, p: FlightProvider, q: SearchQuery) -> str:
        return f"s:{p.name}:{hashlib.sha1(q.model_dump_json().encode()).hexdigest()[:20]}"

    async def _cached(self, key: str) -> tuple[float, list[Flight]] | None:
        raw = await self.cache.get(key)
        if not raw:
            return None
        t, _, body = raw.partition(b"\n")
        try:
            return time.time() - float(t), FLIGHTS.validate_json(body)
        except ValueError:  # written by an incompatible version
            return None

    async def _save(self, key: str, flights: list[Flight]):
        ttl = max(self.cache_ttl, self.swr_ttl, self.stale_ttl)
        await self.cache.set(key, f"{time.time():.3f}\n".encode() + FLIGHTS.dump_json(flights), ttl)

    async def _fallback(self, key: str, t0: float, err: str):
        ms = int((time.monotonic() - t0) * 1000)
        hit = await self._cached(key)
        if hit and hit[0] < self.stale_ttl:
            return hit[1], ProviderStatus(ok=True, ms=ms, count=len(hit[1]), error=err, stale=True, age=int(hit[0]))
        return [], ProviderStatus(ok=False, ms=ms, count=0, error=err)

    async def _one(self, p: FlightProvider, q: SearchQuery, fresh: bool = False):
        key = self._key(p, q)
        if not fresh:
            hit = await self._cached(key)
            if hit:
                age, fl = hit
                if age < self.cache_ttl:
                    return p.name, fl, ProviderStatus(ok=True, ms=0, count=len(fl), cached=True, age=int(age))
                if age < self.swr_ttl:  # serve now, refresh for the next visitor
                    self._start(p, q, key)
                    return p.name, fl, ProviderStatus(ok=True, ms=0, count=len(fl), cached=True, age=int(age),
                                                      refreshing=True)
        # shield: a visitor who leaves must not cancel a search others are waiting for (or that warms the cache)
        return await asyncio.shield(self._start(p, q, key))

    def _start(self, p: FlightProvider, q: SearchQuery, key: str) -> asyncio.Task:
        """One fetch per key per process; concurrent identical searches share it."""
        task = self._inflight.get(key)
        if task is None:
            task = self._spawn(self._leased(p, q, key, time.monotonic()))
            self._inflight[key] = task
            task.add_done_callback(lambda t: self._inflight.pop(key, None) if self._inflight.get(key) is t else None)
        return task

    async def _leased(self, p: FlightProvider, q: SearchQuery, key: str, t0: float):
        """Across processes: whoever takes the lease calls the seller, the others wait for its answer."""
        lease = "l:" + key
        if not await self.cache.add(lease, b"1", self.timeout + 5):
            deadline = t0 + self.timeout + 1
            while time.monotonic() < deadline:
                await asyncio.sleep(0.1)
                hit = await self._cached(key)
                if hit and hit[0] <= time.monotonic() - t0 + 0.5:  # written after we started waiting
                    return p.name, hit[1], ProviderStatus(ok=True, ms=int((time.monotonic() - t0) * 1000),
                                                          count=len(hit[1]), cached=True, age=int(hit[0]))
                if await self.cache.get(lease) is None:
                    break  # the other process gave up; try ourselves (the shared breaker still applies)
        try:
            return await self._call(p, q, key, t0)
        finally:
            await self.cache.delete(lease)

    # ---- pacing, breaker, retries
    async def _pace(self, p: FlightProvider):
        """Wait for this seller's next request slot (min_interval between request starts, all processes)."""
        interval = getattr(p, "min_interval", 0.0)
        if interval:
            wait = await self.cache.next_slot("p:" + p.name, interval)
            if wait > 0:
                await asyncio.sleep(wait)

    async def _guarded(self, p: FlightProvider, coro_fn):
        """Pace the request and translate HTTP 429 into RateLimited."""
        await self._pace(p)
        try:
            return await asyncio.wait_for(coro_fn(), self.timeout)
        except httpx.HTTPStatusError as e:
            if e.response is not None and e.response.status_code == 429:
                raise RateLimited(_retry_after(e.response)) from e
            raise

    async def _open_until(self, name: str) -> float:
        raw = await self.cache.get("b:" + name)
        return float(raw) if raw else 0.0

    async def _open(self, name: str, seconds: float):
        until = max(await self._open_until(name), time.time() + seconds)
        await self.cache.set("b:" + name, repr(until).encode(), until - time.time())

    async def _rate_limited(self, p: FlightProvider, e: RateLimited):
        self.stats.setdefault(p.name, ProviderState()).last_error = "RateLimited"
        await self._open(p.name, e.retry_after)
        log.warning("provider %s is rate limiting us; pausing it for %.0fs", p.name, e.retry_after)

    async def _call(self, p: FlightProvider, q: SearchQuery, key: str, t0: float):
        st = self.stats.setdefault(p.name, ProviderState())
        if await self._open_until(p.name) > time.time():  # circuit open: don't hammer a failing seller
            fl, status = await self._fallback(key, t0, "circuit_open")
            return p.name, fl, status
        st.total_calls += 1
        err = "Error"
        for attempt in range(self.retries + 1):
            try:
                flights = await self._guarded(p, lambda: p.search(q))
                st.last_ok, st.last_error = time.time(), None
                await self._save(key, flights)
                await self.cache.delete("f:" + p.name)
                return p.name, flights, ProviderStatus(ok=True, ms=int((time.monotonic() - t0) * 1000),
                                                       count=len(flights))
            except RateLimited as e:  # never retry into a rate limit: back off for Retry-After instead
                st.total_failures += 1
                await self._rate_limited(p, e)
                fl, status = await self._fallback(key, t0, "RateLimited")
                return p.name, fl, status
            except Exception as e:  # one failing seller must not break the page
                err = type(e).__name__
                log.warning("provider %s failed (attempt %d): %r", p.name, attempt + 1, e)
                client_error = isinstance(e, httpx.HTTPStatusError) and e.response is not None \
                    and 400 <= e.response.status_code < 500
                if client_error:
                    break  # a 4xx won't fix itself on an immediate retry
                if attempt < self.retries:
                    await asyncio.sleep(self.backoff)
        st.total_failures += 1
        st.last_error = err
        if await self.cache.incr("f:" + p.name, self.cooldown * 5) >= self.fail_threshold:
            await self._open(p.name, self.cooldown)
            await self.cache.delete("f:" + p.name)
            log.error("provider %s circuit opened for %ss", p.name, self.cooldown)
        fl, status = await self._fallback(key, t0, err)
        return p.name, fl, status

    async def provider_status(self) -> dict:
        names = [p.name for p in self.providers]
        opens = await self.cache.get_many(["b:" + n for n in names])
        fails = await self.cache.get_many(["f:" + n for n in names])
        now, out = time.time(), {}
        for n, o, f in zip(names, opens, fails):
            until = float(o) if o else 0.0
            out[n] = {"state": "open" if until > now else "closed", "consecutive_failures": int(f or 0),
                      **vars(self.stats.get(n, ProviderState())), "retry_in": max(0, round(until - now))}
        return out

    # ---- search
    def _merge(self, q: SearchQuery, results: dict, order: list[str], pending: list[str]):
        merged: dict[str, Flight] = {}
        for name in order:
            if name not in results:
                continue
            for f in results[name][0]:
                cur = merged.get(f.key)
                if cur is None:
                    cur = merged[f.key] = f.model_copy(update={"offers": []})
                cur.offers.extend(f.offers)

        out, rows = [], []
        for f in merged.values():
            if not f.offers:
                continue
            # One offer per seller per trip (the same agency can arrive via two marketplaces): keep the cheapest,
            # preferring offers that can actually be bought.
            best: dict[str, object] = {}
            for o in f.offers:
                cur = best.get(o.seller)
                if cur is None or (o.available, -o.price) > (cur.available, -cur.price):
                    best[o.seller] = o
            f.offers = sorted(best.values(), key=lambda o: (not o.available, o.price))
            f.id = flight_id(f)
            buyable = [o for o in f.offers if o.available]
            min_price = (buyable or f.offers)[0].price
            if buyable:
                rows.append((f.id, min_price))
            out.append(FlightOut(**f.model_dump(), duration_min=f.duration_minutes, min_price=min_price,
                                 seller_count=len(buyable) or len(f.offers), available=bool(buyable)))
        out.sort(key=lambda x: (not x.available, x.min_price, x.departure))
        statuses = {n: results[n][1] for n in order if n in results}
        return SearchResponse(query=q, flights=out, providers=statuses, pending=pending, done=not pending), rows

    async def search_stream(self, q: SearchQuery, fresh: bool = False,
                            providers: list[FlightProvider] | None = None,
                            progressive: bool = True) -> AsyncIterator[SearchResponse]:
        """Yield the merged answer each time more sellers have answered; the last one has done=True.

        The search runs in its own task: if the visitor leaves, it still finishes, warms the cache
        and records price history.
        """
        sellers = [p for p in (providers or self.providers) if q.mode in getattr(p, "modes", {"flight"})]
        queue: asyncio.Queue = asyncio.Queue()
        self._spawn(self._run(q, fresh, sellers, queue, progressive))
        while True:
            item = await queue.get()
            if isinstance(item, BaseException):
                raise item
            yield item
            if item.done:
                return

    async def _run(self, q, fresh, sellers, queue: asyncio.Queue, progressive: bool):
        try:
            order = [p.name for p in sellers]
            tasks = {asyncio.create_task(self._one(p, q, fresh)): p.name for p in sellers}
            results: dict[str, tuple] = {}
            pending = set(tasks)
            while pending:
                done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                if pending:  # sellers answering within a few ms of each other go out together
                    more, pending = await asyncio.wait(pending, timeout=0.02)
                    done |= more
                for t in done:
                    name, fl, st = t.result()
                    results[name] = (fl, st)
                if progressive and pending:
                    resp, _ = self._merge(q, results, order, sorted(tasks[t] for t in pending))
                    await self._remember(resp)
                    queue.put_nowait(resp)
            resp, rows = self._merge(q, results, order, [])
            await self._remember(resp)
            if self.write_behind:  # answer first, write history after
                queue.put_nowait(resp)
                await self._record(rows)
            else:
                await self._record(rows)
                queue.put_nowait(resp)
        except asyncio.CancelledError:
            queue.put_nowait(asyncio.CancelledError())
            raise
        except Exception as e:
            log.exception("search %s failed", q)
            queue.put_nowait(e)

    async def search(self, q: SearchQuery, fresh: bool = False,
                     providers: list[FlightProvider] | None = None) -> SearchResponse:
        """Search every seller (each answer cached per seller) and merge the offers."""
        last = None
        async for r in self.search_stream(q, fresh, providers, progressive=False):
            last = r
        return last

    async def _record(self, rows):
        if not rows:
            return
        try:
            await self.store.record_many(rows)
        except Exception:  # history is a nice-to-have; never fail a search over it
            log.exception("could not record price history")

    async def _remember(self, resp: SearchResponse):
        """Keep returned trips so a trip page can be opened or shared by id."""
        qj = resp.query.model_dump_json().encode()
        await self.cache.set_many({"t:" + t.id: b'{"trip":' + t.model_dump_json().encode() + b',"query":' + qj + b"}"
                                   for t in resp.flights}, self.trip_ttl)

    async def get_trip_raw(self, trip_id: str) -> bytes | None:
        return await self.cache.get("t:" + trip_id)

    async def get_trip(self, trip_id: str) -> tuple[FlightOut, SearchQuery] | None:
        raw = await self.get_trip_raw(trip_id)
        if not raw:
            return None
        d = TRIP.validate_json(raw)
        return FlightOut.model_validate(d["trip"]), SearchQuery.model_validate(d["query"])

    # ---- background sampling
    async def snapshot_watchlist(self, routes: list[tuple[str, str]], days: int = 14,
                                 concurrency: int = 3, history_days: int = 90) -> int:
        """Search every watched route for each of the next `days` days so price history is sampled
        regularly (searching records the cheapest price per flight). Returns #searches done."""
        sem = asyncio.Semaphore(concurrency)  # be polite to the sellers
        bg = [p for p in self.providers if getattr(p, "background", True)]  # rate-limited sellers serve users only
        if not bg:
            self.last_snapshot = {"at": datetime.now().isoformat(timespec="seconds"), "routes": len(routes),
                                  "searches": 0, "purged_points": 0, "note": "no background-capable sellers"}
            return 0
        today = _date.today()
        done = 0

        async def one(o: str, d: str, day: _date):
            nonlocal done
            async with sem:
                try:
                    await self.search(SearchQuery(origin=o, destination=d, date=day.isoformat()), providers=bg)
                    done += 1
                except Exception as e:
                    log.warning("snapshot %s-%s %s failed: %r", o, d, day, e)

        await asyncio.gather(*(one(o, d, today + timedelta(days=k))
                               for o, d in routes for k in range(1, days + 1)))
        purged = await self.store.purge_history(history_days)
        self.last_snapshot = {"at": datetime.now().isoformat(timespec="seconds"), "routes": len(routes),
                              "searches": done, "purged_points": purged}
        log.info("watchlist snapshot: %s", self.last_snapshot)
        return done

    async def calendar(self, q: SearchQuery, span: int = 3, concurrency: int = 3,
                       ttl: float = 300.0) -> list[dict]:
        """Cheapest price for each day in [date-span, date+span] (past days skipped).

        Sellers with a bulk "cheapest per day" API answer in one request; the others are searched
        day by day. The cheapest price across sellers wins. Results are cached for `ttl` seconds.
        """
        center, today = _date.fromisoformat(q.date), _date.today()
        days = [center + timedelta(days=k) for k in range(-span, span + 1) if center + timedelta(days=k) >= today]
        key = f"c:{q.mode}:{q.origin}:{q.destination}:{q.date}:{span}"
        raw = await self.cache.get(key)
        if raw:
            return TypeAdapter(list[dict]).validate_json(raw)

        best: dict[str, int | None] = {d.isoformat(): None for d in days}
        counts: dict[str, int | None] = {d.isoformat(): None for d in days}
        sem = asyncio.Semaphore(concurrency)

        def take(day: str, price: int | None):
            if day in best and price is not None and (best[day] is None or price < best[day]):
                best[day] = price

        async def day_by_day(p: FlightProvider):
            async def one(d: _date):
                async with sem:
                    _, flights, st = await self._one(p, q.model_copy(update={"date": d.isoformat()}))
                prices = [o.price for f in flights for o in f.offers if o.available]
                if st.ok and prices:
                    take(d.isoformat(), min(prices))
                    counts[d.isoformat()] = (counts[d.isoformat()] or 0) + len(flights)
            await asyncio.gather(*(one(d) for d in days))

        async def via(p: FlightProvider):
            if getattr(p, "supports_cheapest", False) and await self._open_until(p.name) <= time.time():
                try:
                    back = (center - days[0]).days if days else 0
                    res = await self._guarded(p, lambda: p.cheapest(q.origin, q.destination, center, back, span))
                    for day, price in res.items():
                        take(day, price)
                    return
                except RateLimited as e:  # don't make it worse by searching 7 days instead
                    await self._rate_limited(p, e)
                    return
                except Exception as e:  # fall back to searching each day
                    log.warning("cheapest-per-day from %s failed, searching day by day: %r", p.name, e)
                    if not getattr(p, "background", True):
                        return  # don't turn one failed request into seven searches on a rate-limited seller
            await day_by_day(p)

        if days:
            await asyncio.gather(*(via(p) for p in self.providers if q.mode in getattr(p, "modes", {"flight"})))
        out = [{"date": d, "min_price": best[d], "flights": counts[d]} for d in sorted(best)]
        await self.cache.set(key, TypeAdapter(list[dict]).dump_json(out), ttl)
        return out

    # ---- alerts
    async def _notify(self, a, price: int) -> bool:
        """True if at least one notifier that accepts this contact delivered the message."""
        sent = False
        for n in self.notifiers:
            if not n.accepts(a.contact):
                continue
            try:
                await n.send(a, price)
                sent = True
            except Exception as e:
                log.warning("notifier %s failed for alert %s: %r", n.name, a.id, e)
        return sent

    async def check_alerts(self) -> int:
        """Trigger alerts whose price reached the target and deliver them exactly once.

        A triggered alert whose delivery failed is retried on the next run (at its trigger price)
        without searching again. Returns the number of alerts delivered in this run.
        """
        n = 0
        for a in await self.store.list_alerts(pending=True):
            if a.triggered_at and a.last_price is not None:
                price = a.last_price
            else:
                r = await self.search(SearchQuery(mode=a.mode, origin=a.origin, destination=a.destination,
                                                  date=a.date), fresh=True)
                cands = [f for f in r.flights if f.available and (not a.flight_id or f.id == a.flight_id)]
                if not cands:
                    continue
                price = min(f.min_price for f in cands)
                hit = price <= a.target_price
                await self.store.mark_alert(a.id, price, hit)
                if not hit:
                    continue
            if await self._notify(a, price):
                await self.store.mark_notified(a.id)
                n += 1
        return n
