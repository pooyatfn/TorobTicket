from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import date as _date
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import airports, cities
from .cache import build_cache
from .models import MODES, Alert, AlertIn, PricePoint, SearchQuery, SearchResponse
from .notify import build_notifiers
from .providers import is_demo, load_providers
from .service import SearchService
from .store import open_store
from .watchlist import DEFAULT, parse_watchlist

log = logging.getLogger("torobticket")

JSON = "application/json"


class ImmutableStatic(StaticFiles):
    """Vite puts a content hash in every asset name, so browsers may keep them for a year."""

    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        if resp.status_code == 200:
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return resp


def create_app(db_path: str | None = None, alert_interval: float | None = None,
               watch_interval: float | None = None, redis_url: str | None = None) -> FastAPI:
    # Storage: Postgres when TORUB_DATABASE_URL is set, otherwise an SQLite file.
    target = db_path or os.getenv("TORUB_DATABASE_URL") or os.getenv("TORUB_DB", "torobticket.db")
    redis_url = redis_url if redis_url is not None else os.getenv("TORUB_REDIS_URL", "")
    providers = load_providers()
    # Fake back-filled history only for the fictional demo sellers, never for real data.
    store = open_store(target, demo_history=is_demo(providers), pool_size=int(os.getenv("TORUB_DB_POOL", "10")))
    cache = build_cache(redis_url or None, os.getenv("TORUB_REDIS_PREFIX", "tt:"))
    service = SearchService(
        providers, store, cache=cache,
        timeout=float(os.getenv("TORUB_PROVIDER_TIMEOUT", "15")),
        cache_ttl=float(os.getenv("TORUB_CACHE_TTL", "60")),
        swr_ttl=float(os.getenv("TORUB_SWR_TTL", "300")),
        stale_ttl=float(os.getenv("TORUB_STALE_TTL", "900")),
        trip_ttl=float(os.getenv("TORUB_TRIP_TTL", "21600")),
        retries=int(os.getenv("TORUB_PROVIDER_RETRIES", "1")),
        fail_threshold=int(os.getenv("TORUB_BREAKER_THRESHOLD", "3")),
        cooldown=float(os.getenv("TORUB_BREAKER_COOLDOWN", "60")),
        notifiers=build_notifiers(),
        write_behind=True,
    )
    interval = alert_interval if alert_interval is not None else float(os.getenv("TORUB_ALERT_INTERVAL", "600"))

    routes = parse_watchlist(os.getenv("TORUB_WATCHLIST", DEFAULT))
    watch_days = int(os.getenv("TORUB_WATCH_DAYS", "14"))
    watch_interval = watch_interval if watch_interval is not None else float(os.getenv("TORUB_WATCH_INTERVAL", "3600"))
    history_days = int(os.getenv("TORUB_HISTORY_DAYS", "90"))
    me = f"{os.uname().nodename}:{os.getpid()}".encode()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # With several processes, each job runs in one of them per period: the first to take the lease.
        async def alert_loop():
            while True:
                await asyncio.sleep(interval)
                try:
                    if await cache.add("leader:alerts", me, interval * 0.9):
                        await service.check_alerts()
                except Exception:
                    log.exception("alert check failed")

        async def watch_loop():
            await asyncio.sleep(5)  # let the server come up first
            while True:
                try:
                    if await cache.add("leader:watchlist", me, watch_interval * 0.9):
                        await service.snapshot_watchlist(routes, watch_days, history_days=history_days)
                except Exception:
                    log.exception("watchlist snapshot failed")
                await asyncio.sleep(watch_interval)

        if store.kind == "sqlite" and cache.kind == "redis":
            log.warning("Redis is shared but SQLite is not: run one process, or set TORUB_DATABASE_URL")
        log.info("storage: %s, cache: %s", store.kind, cache.kind)
        tasks = []
        if interval > 0:
            tasks.append(asyncio.create_task(alert_loop()))
        if watch_interval > 0 and routes:
            tasks.append(asyncio.create_task(watch_loop()))
        yield
        for t in tasks:
            t.cancel()
        try:
            await asyncio.wait_for(service.drain(), 5)  # finish pending history writes
        except Exception:
            pass
        await store.close()
        await cache.close()

    app = FastAPI(title="Torob Ticket", lifespan=lifespan)
    app.state.service, app.state.store, app.state.cache = service, store, cache
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    # Search answers are repetitive JSON and shrink ~10x. Server-sent events are never compressed.
    app.add_middleware(GZipMiddleware, minimum_size=1024)

    @app.get("/api/health")
    async def health(deep: bool = False):
        out = {"status": "ok", "store": store.kind, "cache": cache.kind}
        if deep:  # also check the database and Redis (used by the compose healthcheck)
            out["store_ok"], out["cache_ok"] = await store.ping(), await cache.ping()
            if not (out["store_ok"] and out["cache_ok"]):
                return JSONResponse(out, 503)
        return out

    @app.get("/api/providers/status")
    async def providers_status():
        return await service.provider_status()

    @app.get("/api/watchlist")
    def watchlist():
        return {"routes": [f"{o}-{d}" for o, d in routes], "days": watch_days,
                "interval_s": watch_interval, "last_snapshot": service.last_snapshot}

    @app.get("/api/airports")
    def get_airports(q: str = ""):
        return airports.search(q)

    def validated(origin: str, destination: str, date: str, adults: int, children: int, infants: int,
                  mode: str = "flight"):
        if mode not in MODES:
            raise HTTPException(422, "نوع سفر نامعتبر است")
        origin, destination = origin.upper(), destination.upper()
        allowed = cities.codes(mode)
        if origin not in allowed or destination not in allowed:
            raise HTTPException(422, "شهر انتخاب‌شده برای این نوع سفر پشتیبانی نمی‌شود" if mode != "flight"
                                else "فرودگاه نامعتبر است")
        if origin == destination:
            raise HTTPException(422, "مبدأ و مقصد نباید یکسان باشند")
        try:
            d = _date.fromisoformat(date)
        except ValueError:
            raise HTTPException(422, "date must be YYYY-MM-DD")
        if d < _date.today():
            raise HTTPException(422, "تاریخ گذشته است")
        if infants > adults:
            raise HTTPException(422, "تعداد نوزاد نمی‌تواند از بزرگسال بیشتر باشد")
        return SearchQuery(mode=mode, origin=origin, destination=destination, date=date,
                           adults=adults, children=children, infants=infants)

    @app.get("/api/cities")
    def get_cities(mode: str = "flight", q: str = ""):
        if mode not in MODES:
            raise HTTPException(422, "نوع سفر نامعتبر است")
        return cities.search(q, mode)

    @app.get("/api/popular")
    def popular(mode: str = "flight"):
        return [{"origin": o, "destination": d, "origin_name": cities.NAMES[o], "destination_name": cities.NAMES[d]}
                for o, d in cities.POPULAR.get(mode, [])]

    @app.get("/api/search", response_model=SearchResponse)
    async def search(origin: str, destination: str, date: str, adults: int = Query(1, ge=1, le=9),
                     children: int = Query(0, ge=0, le=8), infants: int = Query(0, ge=0, le=4),
                     mode: str = "flight"):
        r = await service.search(validated(origin, destination, date, adults, children, infants, mode))
        # Already a validated model: serialise once in Rust instead of FastAPI validating it again.
        return Response(r.model_dump_json(), media_type=JSON)

    @app.get("/api/search/stream", response_model=SearchResponse,
             responses={200: {"content": {"text/event-stream": {}}}})
    async def search_stream(request: Request, origin: str, destination: str, date: str,
                            adults: int = Query(1, ge=1, le=9), children: int = Query(0, ge=0, le=8),
                            infants: int = Query(0, ge=0, le=4), mode: str = "flight"):
        """Server-sent events: one `data:` line with the merged results each time more sellers have
        answered, so the page can show the fast sellers without waiting for the slowest one.
        The last event has `done: true`."""
        q = validated(origin, destination, date, adults, children, infants, mode)

        async def events():
            async for r in service.search_stream(q):
                yield b"data: " + r.model_dump_json().encode() + b"\n\n"

        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/calendar")
    async def calendar(origin: str, destination: str, date: str, span: int = Query(3, ge=1, le=7),
                       mode: str = "flight"):
        q = validated(origin, destination, date, 1, 0, 0, mode)
        return {"days": await service.calendar(q, span)}

    @app.get("/api/trips/{tid}")
    async def trip(tid: str):
        raw = await service.get_trip_raw(tid)
        if not raw:
            raise HTTPException(404, "این سفر در جستجوهای اخیر نیست؛ دوباره جستجو کنید")
        return Response(raw, media_type=JSON)  # stored as {"trip": …, "query": …}

    @app.get("/api/trips/{tid}/history", response_model=list[PricePoint])
    async def trip_history(tid: str):
        return await store.history(tid)

    @app.get("/api/flights/{fid}/history", response_model=list[PricePoint])
    async def history(fid: str):
        return await store.history(fid)

    @app.post("/api/alerts", response_model=Alert, status_code=201)
    async def add_alert(a: AlertIn):
        validated(a.origin, a.destination, a.date, 1, 0, 0, a.mode)
        return await store.add_alert(a)

    @app.get("/api/alerts", response_model=list[Alert])
    async def list_alerts(contact: str | None = None):
        return await store.list_alerts(contact)

    @app.delete("/api/alerts/{aid}", status_code=204)
    async def del_alert(aid: int):
        if not await store.delete_alert(aid):
            raise HTTPException(404)

    # Serve the built SPA if present (production); in dev Vite proxies /api here.
    dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if dist.exists():
        app.mount("/assets", ImmutableStatic(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            # Client-side routes (/search, /trip/..., /favorites, /alerts) all load index.html.
            if path.startswith("api/"):
                raise HTTPException(404)
            f = (dist / path).resolve()
            if path and f.is_file() and dist in f.parents:
                return FileResponse(f)
            return FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache"})
    return app


app = create_app()
