"""Price history and alerts.

Two implementations with the same async interface:
- `PgStore`   PostgreSQL through an asyncpg pool. Use it in production and whenever more than
              one app process runs.
- `Store`     SQLite in one file, for development, tests and single-process setups. Calls run in
              a worker thread so they never block the event loop.

`open_store()` picks one from a database URL or file path.
"""
from __future__ import annotations

import asyncio
import random
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from typing import Iterable

from .models import Alert, AlertIn, PricePoint

DEDUPE = timedelta(hours=1)  # the same price for the same trip is stored at most once an hour


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _demo_backfill(fid: str, price: int, now: datetime) -> list[tuple[str, datetime, int]]:
    rnd = random.Random(fid)
    return [(fid, now - timedelta(days=d), int(price * (1 + rnd.uniform(-0.12, 0.15))) // 1000 * 1000)
            for d in range(14, 0, -1)]


class Store:
    """SQLite store."""

    kind = "sqlite"

    def __init__(self, path: str, demo_history: bool = False):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        self.demo_history = demo_history
        with self.lock, self.db:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.executescript("""
            CREATE TABLE IF NOT EXISTS history(flight_id TEXT, ts TEXT, price INTEGER);
            CREATE INDEX IF NOT EXISTS h_idx ON history(flight_id, ts);
            CREATE INDEX IF NOT EXISTS h_ts ON history(ts);
            CREATE TABLE IF NOT EXISTS alerts(
              id INTEGER PRIMARY KEY AUTOINCREMENT, origin TEXT, destination TEXT, date TEXT,
              target_price INTEGER, contact TEXT, flight_id TEXT, created TEXT,
              triggered_at TEXT, last_price INTEGER);
            CREATE INDEX IF NOT EXISTS a_contact ON alerts(contact);
            """)
            cols = {r["name"] for r in self.db.execute("PRAGMA table_info(alerts)")}
            if "notified_at" not in cols:  # migrate DBs created before notifications existed
                self.db.execute("ALTER TABLE alerts ADD COLUMN notified_at TEXT")
            if "mode" not in cols:  # migrate DBs created before trains/buses existed
                self.db.execute("ALTER TABLE alerts ADD COLUMN mode TEXT NOT NULL DEFAULT 'flight'")

    async def _run(self, fn, *args):
        return await asyncio.to_thread(fn, *args)

    async def ping(self) -> bool:
        return True

    async def close(self):
        self.db.close()

    # ---- price history
    def _record_many(self, rows: list[tuple[str, int]], now: datetime) -> int:
        n = 0
        with self.lock, self.db:
            for fid, price in rows:
                last = self.db.execute(
                    "SELECT ts, price FROM history WHERE flight_id=? ORDER BY ts DESC LIMIT 1", (fid,)).fetchone()
                if last is None and self.demo_history:
                    self.db.executemany("INSERT INTO history VALUES(?,?,?)",
                                        [(f, t.isoformat(), p) for f, t, p in _demo_backfill(fid, price, now)])
                elif last and last["price"] == price and now - datetime.fromisoformat(last["ts"]) < DEDUPE:
                    continue
                self.db.execute("INSERT INTO history VALUES(?,?,?)", (fid, now.isoformat(), price))
                n += 1
        return n

    async def record_many(self, rows: Iterable[tuple[str, int]], now: datetime | None = None) -> int:
        """Store the cheapest price of many trips at once. Returns how many points were added."""
        rows = list(rows)
        return await self._run(self._record_many, rows, now or _utcnow()) if rows else 0

    async def record(self, flight_id: str, price: int, now: datetime | None = None):
        await self.record_many([(flight_id, price)], now)

    def _history(self, fid: str) -> list[PricePoint]:
        with self.lock:
            rows = self.db.execute("SELECT ts, price FROM history WHERE flight_id=? ORDER BY ts", (fid,)).fetchall()
        return [PricePoint(ts=datetime.fromisoformat(r["ts"]), price=r["price"]) for r in rows]

    async def history(self, flight_id: str) -> list[PricePoint]:
        return await self._run(self._history, flight_id)

    def _purge(self, cutoff: datetime) -> int:
        with self.lock, self.db:
            return self.db.execute("DELETE FROM history WHERE ts < ?", (cutoff.isoformat(),)).rowcount

    async def purge_history(self, keep_days: int, now: datetime | None = None) -> int:
        return await self._run(self._purge, (now or _utcnow()) - timedelta(days=keep_days))

    # ---- alerts
    @staticmethod
    def _alert(r: sqlite3.Row) -> Alert:
        d = dict(r)
        d["created"] = datetime.fromisoformat(d["created"])
        for k in ("triggered_at", "notified_at"):
            d[k] = datetime.fromisoformat(d[k]) if d[k] else None
        return Alert(**d)

    def _add_alert(self, a: AlertIn) -> Alert:
        with self.lock, self.db:
            cur = self.db.execute(
                "INSERT INTO alerts(mode,origin,destination,date,target_price,contact,flight_id,created)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (a.mode, a.origin, a.destination, a.date, a.target_price, a.contact, a.flight_id,
                 _utcnow().isoformat()))
            row = self.db.execute("SELECT * FROM alerts WHERE id=?", (cur.lastrowid,)).fetchone()
        return self._alert(row)

    async def add_alert(self, a: AlertIn) -> Alert:
        return await self._run(self._add_alert, a)

    def _list(self, contact: str | None, pending: bool) -> list[Alert]:
        where = []
        if contact:
            where.append("contact=?")
        if pending:
            where.append("notified_at IS NULL")
        sql = "SELECT * FROM alerts" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY id DESC"
        with self.lock:
            rows = self.db.execute(sql, (contact,) if contact else ()).fetchall()
        return [self._alert(r) for r in rows]

    async def list_alerts(self, contact: str | None = None, pending: bool = False) -> list[Alert]:
        return await self._run(self._list, contact, pending)

    def _delete(self, alert_id: int) -> bool:
        with self.lock, self.db:
            return self.db.execute("DELETE FROM alerts WHERE id=?", (alert_id,)).rowcount > 0

    async def delete_alert(self, alert_id: int) -> bool:
        return await self._run(self._delete, alert_id)

    def _mark(self, alert_id: int, price: int, triggered: bool):
        with self.lock, self.db:
            self.db.execute("UPDATE alerts SET last_price=?, triggered_at=COALESCE(triggered_at, ?) WHERE id=?",
                            (price, _utcnow().isoformat() if triggered else None, alert_id))

    async def mark_alert(self, alert_id: int, price: int, triggered: bool):
        await self._run(self._mark, alert_id, price, triggered)

    def _notified(self, alert_id: int):
        with self.lock, self.db:
            self.db.execute("UPDATE alerts SET notified_at=? WHERE id=?", (_utcnow().isoformat(), alert_id))

    async def mark_notified(self, alert_id: int):
        await self._run(self._notified, alert_id)


SqliteStore = Store

PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS history(
  flight_id TEXT NOT NULL,
  ts        TIMESTAMP NOT NULL,
  price     BIGINT NOT NULL);
CREATE INDEX IF NOT EXISTS history_trip_ts ON history(flight_id, ts DESC);
CREATE INDEX IF NOT EXISTS history_ts_brin ON history USING brin(ts);
CREATE TABLE IF NOT EXISTS alerts(
  id           BIGSERIAL PRIMARY KEY,
  mode         TEXT NOT NULL DEFAULT 'flight',
  origin       TEXT NOT NULL,
  destination  TEXT NOT NULL,
  date         TEXT NOT NULL,
  target_price BIGINT NOT NULL,
  contact      TEXT NOT NULL,
  flight_id    TEXT,
  created      TIMESTAMP NOT NULL,
  triggered_at TIMESTAMP,
  last_price   BIGINT,
  notified_at  TIMESTAMP);
CREATE INDEX IF NOT EXISTS alerts_contact ON alerts(contact);
CREATE INDEX IF NOT EXISTS alerts_pending ON alerts(id) WHERE notified_at IS NULL;
"""

# One statement for a whole search: insert each trip's price unless its latest point already has
# that price and is less than an hour old. Uses the (flight_id, ts DESC) index once per trip.
PG_RECORD = """
INSERT INTO history(flight_id, ts, price)
SELECT x.fid, $3::timestamp, x.price
FROM unnest($1::text[], $2::bigint[]) AS x(fid, price)
LEFT JOIN LATERAL (
  SELECT h.ts, h.price FROM history h WHERE h.flight_id = x.fid ORDER BY h.ts DESC LIMIT 1
) last ON true
WHERE last.ts IS NULL OR last.price <> x.price OR last.ts < $3::timestamp - interval '1 hour'
"""


class PgStore:
    """PostgreSQL store (asyncpg). The pool is opened on first use, on the running event loop."""

    kind = "postgres"

    def __init__(self, url: str, demo_history: bool = False, min_size: int = 1, max_size: int = 10):
        self.url, self.demo_history = url, demo_history
        self.min_size, self.max_size = min_size, max_size
        self._pool = None
        self._lock: asyncio.Lock | None = None

    async def pool(self):
        if self._pool is None:
            self._lock = self._lock or asyncio.Lock()
            async with self._lock:
                if self._pool is None:
                    import asyncpg  # optional dependency

                    pool = await asyncpg.create_pool(self.url, min_size=self.min_size, max_size=self.max_size,
                                                     command_timeout=10)
                    async with pool.acquire() as c, c.transaction():
                        # Several processes may start at once; let one create the schema.
                        await c.execute("SELECT pg_advisory_xact_lock(7274801)")
                        await c.execute(PG_SCHEMA)
                    self._pool = pool
        return self._pool

    async def ping(self) -> bool:
        try:
            p = await self.pool()
            return await p.fetchval("SELECT 1") == 1
        except Exception:
            return False

    async def close(self):
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    # ---- price history
    async def record_many(self, rows: Iterable[tuple[str, int]], now: datetime | None = None) -> int:
        best: dict[str, int] = {}
        for fid, price in rows:  # unique ids so one statement never sees the same trip twice
            best[fid] = min(price, best.get(fid, price))
        if not best:
            return 0
        now = now or _utcnow()
        p = await self.pool()
        async with p.acquire() as c, c.transaction():
            if self.demo_history:
                known = {r["flight_id"] for r in await c.fetch(
                    "SELECT DISTINCT flight_id FROM history WHERE flight_id = ANY($1::text[])", list(best))}
                fill = [row for fid, price in best.items() if fid not in known
                        for row in _demo_backfill(fid, price, now)]
                if fill:
                    await c.executemany("INSERT INTO history(flight_id, ts, price) VALUES($1,$2,$3)", fill)
            status = await c.execute(PG_RECORD, list(best), list(best.values()), now)
        return int(status.split()[-1])

    async def record(self, flight_id: str, price: int, now: datetime | None = None):
        await self.record_many([(flight_id, price)], now)

    async def history(self, flight_id: str) -> list[PricePoint]:
        p = await self.pool()
        rows = await p.fetch("SELECT ts, price FROM history WHERE flight_id=$1 ORDER BY ts", flight_id)
        return [PricePoint(ts=r["ts"], price=r["price"]) for r in rows]

    async def purge_history(self, keep_days: int, now: datetime | None = None) -> int:
        p = await self.pool()
        status = await p.execute("DELETE FROM history WHERE ts < $1",
                                 (now or _utcnow()) - timedelta(days=keep_days))
        return int(status.split()[-1])

    # ---- alerts
    @staticmethod
    def _alert(r) -> Alert:
        return Alert(**dict(r))

    async def add_alert(self, a: AlertIn) -> Alert:
        p = await self.pool()
        r = await p.fetchrow(
            "INSERT INTO alerts(mode,origin,destination,date,target_price,contact,flight_id,created)"
            " VALUES($1,$2,$3,$4,$5,$6,$7,$8) RETURNING *",
            a.mode, a.origin, a.destination, a.date, a.target_price, a.contact, a.flight_id, _utcnow())
        return self._alert(r)

    async def list_alerts(self, contact: str | None = None, pending: bool = False) -> list[Alert]:
        where, args = [], []
        if contact:
            args.append(contact)
            where.append(f"contact=${len(args)}")
        if pending:
            where.append("notified_at IS NULL")
        p = await self.pool()
        rows = await p.fetch("SELECT * FROM alerts" + (" WHERE " + " AND ".join(where) if where else "")
                             + " ORDER BY id DESC", *args)
        return [self._alert(r) for r in rows]

    async def delete_alert(self, alert_id: int) -> bool:
        p = await self.pool()
        return (await p.execute("DELETE FROM alerts WHERE id=$1", alert_id)) != "DELETE 0"

    async def mark_alert(self, alert_id: int, price: int, triggered: bool):
        p = await self.pool()
        await p.execute("UPDATE alerts SET last_price=$1, triggered_at=COALESCE(triggered_at, $2) WHERE id=$3",
                        price, _utcnow() if triggered else None, alert_id)

    async def mark_notified(self, alert_id: int):
        p = await self.pool()
        await p.execute("UPDATE alerts SET notified_at=$1 WHERE id=$2", _utcnow(), alert_id)


def open_store(target: str, demo_history: bool = False, pool_size: int = 10):
    """`postgres://…` / `postgresql://…` → PgStore, anything else is an SQLite file path."""
    if target.startswith(("postgres://", "postgresql://")):
        return PgStore(target, demo_history, max_size=pool_size)
    return Store(target, demo_history)
