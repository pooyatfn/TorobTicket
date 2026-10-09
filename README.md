<p align="center">
  <img src="docs/images/logo.svg" width="72" alt="" />
</p>

<h1 align="center">Torob Ticket · ترب تیکت</h1>

<p align="center">
  Compare <b>flight, train and bus</b> ticket prices from several Iranian sellers on one page, in Torob's style.<br/>
  One row per trip, every seller's price on the trip page, round trips, price history and price-drop alerts.
</p>

<p align="center">
  <img alt="Python 3.13" src="https://img.shields.io/badge/python-3.13-1e293b?logo=python&logoColor=white">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-backend-1e293b?logo=fastapi&logoColor=white">
  <img alt="React 18" src="https://img.shields.io/badge/React_18-Vite-1e293b?logo=react&logoColor=white">
  <img alt="PostgreSQL" src="https://img.shields.io/badge/PostgreSQL-17-1e293b?logo=postgresql&logoColor=white">
  <img alt="Redis" src="https://img.shields.io/badge/Redis-7-1e293b?logo=redis&logoColor=white">
  <img alt="Docker" src="https://img.shields.io/badge/docker-compose-1e293b?logo=docker&logoColor=white">
  <img alt="Tests" src="https://img.shields.io/badge/tests-123_backend_%2B_21_frontend-15803d">
</p>

<p align="center">
  <img src="docs/images/results.png" alt="Flight results for Tehran to Mashhad: filters on the right, date strip with the cheapest price per day, trip cards with price and number of sellers" width="900" />
</p>

---

## Contents

- [Screenshots](#screenshots)
- [Features](#features)
- [Quick start](#quick-start)
- [How it works](#how-it-works)
- [Performance](#performance)
- [Sellers](#sellers)
- [Project structure](#project-structure)
- [API](#api)
- [Configuration](#configuration)
- [Development and tests](#development-and-tests)
- [Roadmap](#roadmap)
- [Notes and limits](#notes-and-limits)

## Screenshots

<table>
  <tr>
    <td width="50%"><img src="docs/images/home.png" alt="Home page: flight, train and bus tabs, one-way or round trip, search box and popular routes" /><br/><sub><b>Home</b>: pick flight, train or bus, one-way or round trip.</sub></td>
    <td width="50%"><img src="docs/images/round-trip.png" alt="Round trip results: outbound and return tabs, a selected trip, and a bar at the bottom with both picks and the total price" /><br/><sub><b>Round trip</b>: pick the outbound, then the return; the bar shows the total.</sub></td>
  </tr>
  <tr>
    <td><img src="docs/images/trip.png" alt="Trip page: red buy-from-cheapest button, list of sellers with prices, price history chart and trip details" /><br/><sub><b>Trip page</b>: cheapest seller first, every other seller, price history, details.</sub></td>
    <td><img src="docs/images/bus.png" alt="Bus results with bus type, terminals, seats-left warnings and sold-out trips" /><br/><sub><b>Buses</b>: bus type, terminal, stops and seats left.</sub></td>
  </tr>
  <tr>
    <td><img src="docs/images/train-dark.png" alt="Train results in dark mode showing compartment type and facilities" /><br/><sub><b>Trains</b> in dark mode: compartment type and facilities.</sub></td>
    <td align="center"><img src="docs/images/mobile.png" alt="Mobile layout of a round trip search with a collapsed search summary" width="260" /><br/><sub><b>Mobile</b>: collapsed search, filter drawer, sticky total bar.</sub></td>
  </tr>
</table>

## Features

**Search**
- Flights, trains and buses, one-way or **round trip** (رفت و برگشت)
- Jalali date picker; a date strip with the cheapest price for the days around your date
- Shareable URLs for every search and trip page

**Results**, in Torob's layout
- Filters: price range, departure time, airline / rail company / bus company, class, wagon or bus type, facilities, terminal, seller, refundable
- "Only available" toggle (sold-out trips are kept but hidden), six sort orders
- The same flight from different sellers is merged into one row, with "from X تومان in N sellers"

**Trip page**, like a Torob product page
- Big "buy from the cheapest seller" button, then every seller with price difference, class, baggage and refund policy
- Price history chart with an average line; trip details; other trips that day
- Favourite, share and **price-drop alert** (SMS/e-mail via webhook or SMTP)

**Built to be polite to sellers**
- Per-seller cache, shared in-flight requests, a minimum gap between requests, `429 Retry-After` handling, circuit breaker and stale-but-labelled fallback, all shared between processes through Redis

**Fast**
- Results stream in as each seller answers, so the quick sellers show up without waiting for the slowest one
- Repeat searches come from the shared cache; slightly older answers are shown instantly and refreshed in the background
- Gzip-compressed answers and long-lived caching of the app's static files

## Quick start

```bash
git clone <this repo> && cd TorobTicket
docker compose up --build
```

Open **http://localhost:8000**. The API docs are at `/docs`.

`docker-compose.yml` uses the real sellers (`TORUB_PROVIDERS=alibaba,safarmarket,mrbilit,flytoday`), which need a network that can reach Iranian sites. To try it anywhere, use demo data:

```bash
TORUB_PROVIDERS=demo docker compose up --build   # or edit the value in docker-compose.yml
```

Compose starts the app (2 worker processes), **PostgreSQL 17** for price history and alerts (volume `pg-data`), and **Redis 7** as the shared cache. Set `POSTGRES_PASSWORD` and `WEB_CONCURRENCY` in your environment or an `.env` file to change the defaults.

**Upgrading from the SQLite version?** Your old price history and alerts are still on the `torobticket-data` volume. Copy them into Postgres once:

```bash
docker compose run --rm app python -m app.migrate /data/torobticket.db
```

## How it works

<p align="center"><img src="docs/images/architecture.svg" alt="Architecture: the browser talks to several FastAPI processes, which use SearchService (Redis shared cache, shared calls, pacing, retries, streamed merge) to query seller adapters for Alibaba flights, trains and buses, Safarmarket and demo data; PostgreSQL stores price history and alerts; background jobs run in one process at a time, sample prices and send alert notifications" width="100%" /></p>

FastAPI serves both the API and the built React app. Several worker processes can run side by side: they share Postgres for data and Redis for everything else (seller answers, trip pages, circuit breaker, request pacing, and the lease that lets only one process run each background job). Without `TORUB_DATABASE_URL` and `TORUB_REDIS_URL` the app falls back to an SQLite file and an in-memory cache, for development and single-process use.

Each seller is a small adapter with one method, `search(query) → trips`, plus an optional `cheapest(...)` that returns the cheapest price per day in one request for the date strip.

<p align="center"><img src="docs/images/search-flow.svg" alt="Search flow: results stream to the page as each seller answers. For every seller in parallel, use a cached answer (refreshing it in the background when older than 60 seconds) or join a running identical search in any process; skip a paused seller and show its last good answer; otherwise wait for the seller's request slot and call it. A 429 pauses the seller without retrying. Results are merged into one row per physical trip with one offer per seller" width="100%" /></p>

Sellers write flight numbers differently (Alibaba `SR 4303`, Safarmarket `IS4303`), so flights are matched on route + flight number without the airline prefix + departure minute. Trains are matched per wagon class, buses per operator and bus type.

<p align="center"><img src="docs/images/round-trip.svg" alt="Round trip: one URL with a return date becomes two one-way searches run in parallel; you pick the outbound, the page switches to the return, and a total bar shows the combined price" width="100%" /></p>

## Performance

Measured with two simulated sellers, a fast one (1.3 s, like Alibaba) and a slow one (6 s, like Safarmarket), comparing the previous version (SQLite, in-process cache) with this one (Postgres, Redis):

| | Before | Now |
|---|---|---|
| First results on screen | 6.0 s (waits for the slowest seller) | **1.4 s** (streamed as each seller answers) |
| Same search after the 60 s fresh window | 6.0 s (searched again) | **7 ms** (shown at once, refreshed in the background) |
| Same search within 60 s | 7 ms | 10 ms (now shared by every process) |
| Server time per search, sellers excluded | 24.7 ms median | **10.4 ms** (history written after answering, in one statement) |
| Answer size on the wire | 7.2 KB | **1.1 KB** (gzip) |

The Alibaba adapters also poll for results sooner (after 0.25 s and 0.4 s instead of every second), and the app's JS and CSS are cached by browsers for a year because their file names change on every build.

How fresh answers are, per seller:

- **0–60 s old** (`TORUB_CACHE_TTL`): served from the cache.
- **60 s–5 min** (`TORUB_SWR_TTL`): served at once, and a fresh search runs in the background for the next visitor; the page shows how old the prices are.
- **Seller failing or rate-limited:** its last answer up to 15 min old (`TORUB_STALE_TTL`), labelled as possibly outdated.

## Sellers

| Seller | Modes | How it is queried | Notes |
|---|---|---|---|
| **Alibaba** (`alibaba`) | ✈️ 🚆 🚌 | flights and trains: start a search, poll until complete; buses: one GET | cheapest-per-day endpoint for flights; prices converted from rial to toman |
| **Safarmarket** (`safarmarket`) | ✈️ | one POST, about 5–7 s | a metasearch: each flight brings offers from several agencies, each with its own booking link |
| **MrBilit** (`mrbilit`) | ✈️ 🚆 🚌 | one request per search, no login; trains also have a one-request price calendar | open JSON APIs; the same trains, flights and buses as Alibaba, so they merge into one row |
| **FlyToday** (`flytoday`) | ✈️ 🚆 | one request per search, no login | its search-captcha mode is off today; if it is switched on the seller fails cleanly (no bypass). Buses are not integrated yet |
| **Demo** (`demo`) | ✈️ 🚆 🚌 | generated locally | fictional sellers, deterministic prices, no network |
| Flightio | ✈️ | planned | request format known; blocked on their search service, see [PLAN.md](PLAN.md) |

The page shows the cheapest price above the list. While sellers are still answering it is labelled "cheapest so far" and can drop when a slower seller arrives.

Every adapter was built from the requests the seller's own website makes, and is tested against real responses saved in `backend/tests/fixtures/`.

**Train cities:** THR, MHD, SYZ, IFN, TBZ, AWZ, BND, KER, ZAH, ADU, OMH, SRY. Bus city codes are in `backend/app/cities.py`.

**Adding a seller:** implement `FlightProvider.search()` in `backend/app/providers/`, set `modes`, `min_interval` and `background`, and register it in `providers/__init__.py`. For a plain JSON API, the config-driven `http_json` adapter may be enough (see `backend/providers.example.json`).

## Project structure

<p align="center"><img src="docs/images/structure.svg" alt="Project structure: backend/app with main, service, models, cities, store, notify, cache and one provider module per seller; frontend/src with pages, components, lib and tests; Dockerfile and compose files at the root" width="100%" /></p>

## API

| Endpoint | What it does |
|---|---|
| `GET /api/search?mode=&origin=&destination=&date=&adults=&children=&infants=` | trips for one direction; each lists every seller's offer, cheapest first |
| `GET /api/search/stream?…` (same parameters) | server-sent events: the merged answer each time more sellers have answered; the last one has `done: true` |
| `GET /api/calendar?mode=&origin=&destination=&date=&span=` | cheapest price for the days around a date |
| `GET /api/trips/{id}` | a recently returned trip (shared trip links) |
| `GET /api/trips/{id}/history` | price history of a trip |
| `GET /api/cities?mode=&q=` · `GET /api/popular?mode=` | cities served per mode · popular routes |
| `POST /api/alerts` · `GET /api/alerts?contact=` · `DELETE /api/alerts/{id}` | price-drop alerts (contact: Iranian mobile or e-mail) |
| `GET /api/providers/status` | per-seller health: circuit state, failures, last success, retry-in |
| `GET /api/watchlist` · `GET /api/health[?deep=true]` | background sampling status · liveness (`deep` also checks Postgres and Redis) |

Round trips are two searches, the outbound route on `date` and the reversed route on the return date, streamed in parallel.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `TORUB_PROVIDERS` | `demo` | sellers: `alibaba`, `safarmarket`, `mrbilit`, `flytoday`, `demo` (comma separated) |
| `TORUB_PROVIDERS_CONFIG` | – | JSON file of sellers; overrides `TORUB_PROVIDERS` |
| `TORUB_DATABASE_URL` | – | `postgresql://user:pass@host:5432/db`; set by compose. Without it, the SQLite file below is used |
| `TORUB_DB` | `torobticket.db` | SQLite file when there is no `TORUB_DATABASE_URL` |
| `TORUB_DB_POOL` | `10` | Postgres connections per process |
| `TORUB_REDIS_URL` | – | `redis://host:6379/0`; set by compose. Without it, each process has its own in-memory cache |
| `TORUB_REDIS_PREFIX` | `tt:` | prefix for every Redis key, so one Redis can serve several deployments |
| `WEB_CONCURRENCY` | `1` (`2` in compose) | worker processes; use more than one only with Postgres and Redis |
| `TORUB_CACHE_TTL` | `60` | seconds a seller's answer is served as fresh |
| `TORUB_SWR_TTL` | `300` | up to this age, a cached answer is shown at once and refreshed in the background |
| `TORUB_STALE_TTL` | `900` | how old a fallback answer may be when a seller fails |
| `TORUB_TRIP_TTL` | `21600` | how long trip pages stay openable by id |
| `TORUB_PROVIDER_TIMEOUT` / `TORUB_PROVIDER_RETRIES` | `15` / `1` | per-seller timeout (s) and retries |
| `TORUB_BREAKER_THRESHOLD` / `TORUB_BREAKER_COOLDOWN` | `3` / `60` | failures before a seller is skipped, and for how long (s) |
| `TORUB_ALERT_INTERVAL` | `600` | how often alerts are checked (s); `0` disables |
| `TORUB_NOTIFY` | `console` | `console`, `webhook`, `smtp` (comma separated) |
| `TORUB_WEBHOOK_URL` | – | POST target for alerts (SMS gateway, Telegram bot, n8n…) |
| `TORUB_SMTP_HOST` `_PORT` `_USER` `_PASSWORD` `_FROM` `_TLS` | – / `587` / – / – / – / `1` | e-mail delivery |
| `TORUB_WATCHLIST` | `THR-MHD,THR-SYZ,THR-IFN,THR-KIH,MHD-THR` | routes sampled in the background for price history |
| `TORUB_WATCH_DAYS` / `TORUB_WATCH_INTERVAL` | `14` / `3600` | days ahead per route; how often (s), `0` disables |
| `TORUB_HISTORY_DAYS` | `90` | how long price history is kept |
| `TORUB_USER_AGENT` | `Mozilla/5.0 (compatible; TorobTicket/0.2)` | User-Agent sent to sellers |

## Development and tests

```bash
# backend: http://localhost:8000
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
TORUB_PROVIDERS=demo uvicorn app.main:app --reload

# frontend: http://localhost:5173 (proxies /api to :8000)
cd frontend && npm install && npm run dev

# or both with hot reload in containers
docker compose -f docker-compose.dev.yml up
```

```bash
cd backend && pytest        # adapters on real captured responses, cache, 429, merge, streaming, API
cd frontend && npm test     # 21 tests: Jalali calendar, filters, URLs, round-trip legs, streaming client
```

Without Postgres and Redis, 113 backend tests run and 10 are skipped. To run all 123, point the tests at a throwaway database and Redis:

```bash
docker run -d --name tt-pg -e POSTGRES_USER=torob -e POSTGRES_PASSWORD=torob -e POSTGRES_DB=torob_test -p 5432:5432 postgres:17-alpine
docker run -d --name tt-redis -p 6379:6379 redis:7-alpine
TORUB_TEST_DATABASE_URL=postgresql://torob:torob@localhost:5432/torob_test \
TORUB_TEST_REDIS_URL=redis://localhost:6379/15 pytest
```

A GitHub Actions workflow is included at `ci/github-ci.yml`. Move it to `.github/workflows/ci.yml` to enable it; it runs both test suites (the backend one against Postgres and Redis services), builds the image and smoke-tests it.

## Roadmap

- [x] Flights from Alibaba and Safarmarket, merged per flight
- [x] Trains and buses
- [x] Round trips
- [x] Price history, alerts, favourites
- [ ] Flightio (waiting on their search service; details in [PLAN.md](PLAN.md))
- [x] Postgres and Redis, several worker processes, streamed results
- [ ] Multi-leg and international flights

## Notes and limits

- **Torob Ticket compares prices; it does not sell tickets.** Every "buy" button opens the seller's own site, where prices may have changed.
- **The seller integrations are unofficial.** They use the same JSON endpoints as the sellers' own websites, can break when those sites change, and following each seller's terms is your responsibility. Requests are cached, spaced and rate-limit aware.
- Safarmarket's website also sends a reCAPTCHA token. Its API currently answers without it; this project does not fake or work around it. If Safarmarket starts requiring it, that seller shows as unavailable and the rest keep working.
- Several app processes or containers can run against one Postgres and one Redis. Without them (SQLite and the in-memory cache), run a single process.
- Prices are per adult. Round-trip totals multiply by adults + children and leave out infant fares.
