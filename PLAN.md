# Torob Ticket — Implementation Plan

Goal: a "Torob Ticket" feature for torob.com that searches domestic flights across
several sellers (agencies), lists each flight once, and shows every seller's price
Torob-style (cheapest first, "go to seller" button), with filters, price history and alerts.

## Decisions
- Backend: Python FastAPI. Frontend: React + Vite + TypeScript, Persian, RTL, Jalali dates.
- Data: pluggable providers. A seller = one `FlightProvider`. Shipped: `mock` (default,
  deterministic realistic data) and `http_json` (config-driven adapter for real sources).
  Real Iranian sources (Alibaba, Flightio, Safarmarket, ...) have no public documented API;
  each needs a small adapter written/verified against its live responses and terms of use.
- Storage: SQLite (stdlib) for price history + alerts. No ORM, no extra infra.

## Architecture
```
React SPA ──/api──▶ FastAPI
                     ├─ routes: /airports, /search, /flights/{id}/history, /alerts
                     ├─ SearchService: fan out to providers concurrently (timeout per
                     │    provider), merge offers of the same physical flight, rank
                     ├─ PriceStore (SQLite): snapshots of min price per flight/day, alerts
                     └─ providers/: base.py, mock.py, http_json.py, registry
```
Merging key: airline + flight number + departure datetime. Each merged Flight has
`offers[]` (seller, price IRR/Toman, deep link, fare class) sorted ascending.

## API
- `GET /api/airports?q=` autocomplete (Persian + code)
- `GET /api/search?origin=THR&destination=MHD&date=2026-10-20&adults=1&children=0&infants=0`
  → `{flights:[...], providers:{name:{ok,ms,count,error}}}`
- `GET /api/flights/{id}/history` → price points
- `POST/GET/DELETE /api/alerts` — price-drop alert (flight search + target price + contact)
- Filters/sorting are client-side on the returned list (price, time, airline, seller, class).

## UI (Torob style)
Search bar (origin/destination swap, Jalali date picker, passengers) → results page:
right filter sidebar (RTL), sort tabs (cheapest / earliest / fastest), flight cards with
lowest price + "N فروشنده", expandable seller list, price history chart, alert modal.

## Milestones
1. Backend core + mock provider + tests  2. Frontend  3. Real adapters per source
4. Scheduled price snapshots + alert notifier (SMS/push) 5. Torob integration (embed as route/module)

---
# Roadmap (v0.2) — ALL STEPS DONE (40 backend + 12 frontend tests)

| # | Step | Why | Done when |
|---|------|-----|-----------|
| 1 | Fix Docker import error | Container crashed: non-root user could not read copied files | `chmod -R a+rX` in image; reproduced + verified |
| 2 | Provider resilience | Real sellers are slow/flaky; one bad seller must not hurt the page | Retry, circuit breaker, stale fallback, `/api/providers/status`; tests |
| 3 | Alert notifications | Alerts only logged; users need to actually be told | Notifier interface (console, webhook, SMTP), dedupe, contact validation; tests |
| 4 | Watchlist snapshots | Price history is only real if prices are sampled regularly | Background job samples configured routes/days; tests |
| 5 | Flexible dates strip | Torob-style "cheapest nearby day" is the main way people save money | `/api/calendar` + clickable strip in UI; tests |
| 6 | Quality + delivery | Keep it from regressing | Vitest (Jalali, filters), GitHub Actions CI, dev compose with hot reload |

Out of scope until real sources exist: scraping adapters, payments/booking, user accounts.

---
# Flightio integration — status (2026-10-09)

Blocked on Flightio, not on us: every domestic `POST /bff/FlightSearch` currently answers
`500 {"error":"خطای سمت سرور"}` — including the exact request flightio.com's own page sends.
Input validation works (bad city code → `400 "کد شهر ارسالی معتبر نمی باشد"`), so the service is up
but its flight search backend is failing. Retry when Flightio's own site shows results again.

What is already known (observed from flightio.com's web client):
- Results page (also the "go to seller" link):
  `https://flightio.com/flight/search/THR-MHD?depart=2026-10-20&adult=1&child=0&infant=0&flightType=1&cabinType=1`
- Step 1: `POST https://flightio.com/bff/FlightSearch`, JSON body
  `{"adult":1,"child":0,"infant":0,"source":"THR","sourceLabel":"THR","dest":"MHD","destLabel":"MHD",
    "depart":"2026-10-20","flightType":1,"tripMode":1,"cabinType":1,"isExtraInfoRequested":false}`
  (flightType 1 = domestic, 2 = international; tripMode 1 = one way) → returns a search id.
- Step 2: `GET https://flightio.com/bff/FlightSearch?id={id}&isReturnExtraInfo=false` → results
  (response shape still to be captured).
- Headers the site sends: `Accept-Language: fa_IR`, `f-lang: fa`, `app-type: desktop-browser`.

---
# v0.3 — done
- Trains and buses (Alibaba), Torob-style UI redesign, favourites, my alerts, dark mode.
- Safarmarket 429 handling: per-seller pacing, Retry-After pause, no background sampling on rate-limited sellers.
- Round trips (رفت و برگشت): two one-way searches in parallel, outbound/return tabs, total bar.
- GitHub README with screenshots and diagrams (`docs/images/`).

---
# v0.4: done
- PostgreSQL (asyncpg) for price history and alerts; SQLite kept for development. `python -m app.migrate` copies old SQLite data.
- Redis shared cache: seller answers, trip pages, circuit breaker, request pacing, cross-process single-flight, job leases.
- Several API worker processes (compose: 2), background jobs run in one process at a time.
- Faster answers: streamed results per seller (SSE), stale-while-revalidate, write-behind history in one statement,
  quicker polling for Alibaba, gzip, immutable asset caching. Benchmark in README → Performance.

---
# v0.5: done
- MrBilit (trains, plus a one-request price calendar) and FlyToday (trains) added as sellers, built from their own web clients' requests.
- Trains from Alibaba, MrBilit and FlyToday merge into one row per train and wagon class. The merge key now ignores
  Arabic/Persian letter variants (ي/ی), spacing and punctuation in wagon names.
- Neither seller needs login or tokens today. FlyToday has a search-captcha mode that is switched off; if it is switched on
  the seller fails cleanly (no solving or bypass).
- MrBilit flights and buses, FlyToday flights. FlyToday buses: endpoint known (`POST /api/gateway/V1/Bus/Search`, stations
  `0001` Tehran / `0006` Mashhad) but the request body could not be worked out, so it is not integrated.
- Broken buy links fixed: Alibaba has no page for `IKA` (removed) and Yazd is `AZD`, not `YZD`; Alibaba bus pages use numeric city codes.
- "Cheapest so far" bar above the results.
