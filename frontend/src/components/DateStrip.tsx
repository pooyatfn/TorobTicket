import { useEffect, useState } from "react";
import { getCalendar } from "../lib/api";
import { shortToman } from "../lib/format";
import { formatShort } from "../lib/jalali";
import type { CalendarDay, Query } from "../lib/types";

const wd = new Intl.DateTimeFormat("fa-IR", { weekday: "short" });

/** Cheapest price for the days around the searched date; click a day to search it. */
export default function DateStrip({ query, onPick, busy }: { query: Query; onPick: (date: string) => void; busy: boolean }) {
  const [days, setDays] = useState<CalendarDay[] | null>(null);
  const { mode, origin, destination, date } = query;

  useEffect(() => {
    let live = true;
    setDays(null);
    getCalendar({ mode, origin, destination, date }).then((r) => live && setDays(r.days)).catch(() => live && setDays([]));
    return () => { live = false; };
  }, [mode, origin, destination, date]);

  if (days && days.length === 0) return null;
  const prices = (days ?? []).map((d) => d.min_price).filter((p): p is number => p != null);
  const best = prices.length ? Math.min(...prices) : null;

  return (
    <nav className="datestrip" aria-label="قیمت روزهای اطراف">
      {(days ?? Array.from({ length: 7 }, () => null)).map((d, i) => d ? (
        <button key={d.date} type="button" disabled={busy || d.date === date} aria-current={d.date === date ? "date" : undefined}
          className={(d.date === date ? "on " : "") + (d.min_price != null && d.min_price === best ? "best" : "")}
          onClick={() => onPick(d.date)}>
          <span className="small muted">{wd.format(new Date(d.date + "T12:00:00"))}</span>
          <b>{formatShort(new Date(d.date + "T12:00:00"))}</b>
          <span className="small price">{d.min_price != null ? shortToman(d.min_price) : "—"}</span>
        </button>
      ) : <div key={i} className="cell skeleton" />)}
    </nav>
  );
}
