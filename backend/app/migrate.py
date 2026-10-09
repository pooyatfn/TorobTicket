"""Copy price history and alerts from an SQLite file into Postgres (one-off, when upgrading).

    docker compose run --rm app python -m app.migrate /data/torobticket.db

Uses TORUB_DATABASE_URL. Safe to run twice: it refuses to copy into a database that already has data
unless --force is given.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sqlite3
from datetime import datetime

from .store import PgStore


async def migrate(sqlite_path: str, url: str, force: bool = False) -> tuple[int, int]:
    src = sqlite3.connect(sqlite_path)
    src.row_factory = sqlite3.Row
    pg = PgStore(url)
    pool = await pg.pool()
    try:
        if not force and (await pool.fetchval("SELECT count(*) FROM history")
                          or await pool.fetchval("SELECT count(*) FROM alerts")):
            raise SystemExit("Postgres already has data; use --force to copy anyway")
        ts = lambda v: datetime.fromisoformat(v) if v else None  # noqa: E731
        hist = [(r["flight_id"], ts(r["ts"]), r["price"]) for r in src.execute("SELECT * FROM history")]
        cols = {r["name"] for r in src.execute("PRAGMA table_info(alerts)")}
        alerts = [(r["id"], r["mode"] if "mode" in cols else "flight", r["origin"], r["destination"], r["date"],
                   r["target_price"], r["contact"], r["flight_id"], ts(r["created"]), ts(r["triggered_at"]),
                   r["last_price"], ts(r["notified_at"]) if "notified_at" in cols else None)
                  for r in src.execute("SELECT * FROM alerts")]
        async with pool.acquire() as c, c.transaction():
            await c.copy_records_to_table("history", records=hist, columns=["flight_id", "ts", "price"])
            await c.copy_records_to_table("alerts", records=alerts, columns=[
                "id", "mode", "origin", "destination", "date", "target_price", "contact", "flight_id",
                "created", "triggered_at", "last_price", "notified_at"])
            # keep new alert ids after the copied ones
            await c.execute("SELECT setval(pg_get_serial_sequence('alerts','id'), GREATEST((SELECT max(id) FROM alerts), 1))")
        return len(hist), len(alerts)
    finally:
        src.close()
        await pg.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sqlite_path")
    ap.add_argument("--url", default=os.getenv("TORUB_DATABASE_URL"))
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    if not a.url:
        raise SystemExit("set TORUB_DATABASE_URL or pass --url")
    h, n = asyncio.run(migrate(a.sqlite_path, a.url, a.force))
    print(f"copied {h} price points and {n} alerts")


if __name__ == "__main__":
    main()
