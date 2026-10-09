import { num, toman } from "../lib/format";
import { formatShort } from "../lib/jalali";
import type { PricePoint } from "../lib/types";

/** Daily cheapest price with an average line, like Torob's "لیست تغییرات قیمت". */
export default function PriceChart({ points }: { points: PricePoint[] }) {
  const byDay = new Map<string, number>();
  for (const p of points) { const d = p.ts.slice(0, 10); byDay.set(d, Math.min(byDay.get(d) ?? Infinity, p.price)); }
  const days = [...byDay.entries()].sort(([a], [b]) => a.localeCompare(b));
  if (days.length < 2) return <p className="muted small">برای این سفر هنوز سابقهٔ قیمت کافی ثبت نشده. هر بار که قیمت عوض شود این‌جا اضافه می‌شود.</p>;
  const W = 340, H = 150, PX = 8, PY = 14;
  const ps = days.map(([, p]) => p);
  const lo = Math.min(...ps), hi = Math.max(...ps), span = hi - lo || 1;
  const avg = Math.round(ps.reduce((a, b) => a + b, 0) / ps.length);
  const x = (i: number) => W - PX - (i * (W - 2 * PX)) / (days.length - 1); // RTL: newest on the left
  const y = (v: number) => H - PY - ((v - lo) / span) * (H - 2 * PY);
  const d = days.map(([, p], i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p).toFixed(1)}`).join(" ");
  const last = ps[ps.length - 1], first = ps[0];
  const change = Math.round(((last - first) / first) * 100);
  return (
    <figure className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="نمودار تغییرات قیمت">
        <line x1={PX} x2={W - PX} y1={y(avg)} y2={y(avg)} className="avg" />
        <path d={d} fill="none" className="line" />
        {days.map(([day, p], i) => <circle key={day} cx={x(i)} cy={y(p)} r="3" className="dot"><title>{formatShort(new Date(day + "T12:00:00"))}: {toman(p)}</title></circle>)}
      </svg>
      <div className="legend small"><span><i className="sw line" />کمترین قیمت روز</span><span><i className="sw avg" />میانگین</span></div>
      <figcaption className="small">
        <div>کمترین: <b>{toman(lo)}</b></div><div>بیشترین: <b>{toman(hi)}</b></div>
        <div>تغییر از {formatShort(new Date(days[0][0] + "T12:00:00"))}: <b className={change > 0 ? "up" : change < 0 ? "down" : ""}>{change > 0 ? "+" : ""}{num(change)}٪</b></div>
      </figcaption>
    </figure>
  );
}
