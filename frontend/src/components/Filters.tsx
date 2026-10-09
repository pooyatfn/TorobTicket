import { useEffect, useState } from "react";
import { ChevronIcon } from "./Icons";
import { num } from "../lib/format";
import { CARRIER_LABEL } from "../lib/modes";
import type { Mode, Trip } from "../lib/types";

export interface FilterState {
  priceMin: number | null; priceMax: number | null;
  times: Set<string>; carriers: Set<string>; sellers: Set<string>; classes: Set<string>;
  features: Set<string>; terminals: Set<string>; refundable: boolean; availableOnly: boolean;
}
export const emptyFilters = (): FilterState => ({
  priceMin: null, priceMax: null, times: new Set(), carriers: new Set(), sellers: new Set(), classes: new Set(),
  features: new Set(), terminals: new Set(), refundable: false, availableOnly: true,
});
export const activeCount = (f: FilterState) =>
  (f.priceMin != null || f.priceMax != null ? 1 : 0) + f.times.size + f.carriers.size + f.sellers.size + f.classes.size +
  f.features.size + f.terminals.size + (f.refundable ? 1 : 0);

export const TIME_SLOTS: Record<string, [string, number, number]> = {
  night: ["بامداد", 0, 6], morning: ["صبح", 6, 12], noon: ["بعدازظهر", 12, 18], evening: ["شب", 18, 24],
};

export function applyFilters(trips: Trip[], f: FilterState): Trip[] {
  return trips.filter((t) => {
    if (f.availableOnly && !t.available) return false;
    if (f.carriers.size && !f.carriers.has(t.airline)) return false;
    if (f.terminals.size && !f.terminals.has(t.origin_terminal ?? "")) return false;
    if (f.features.size && ![...f.features].every((x) => t.features.includes(x))) return false;
    if (f.times.size) {
      const h = +t.departure.slice(11, 13);
      if (![...f.times].some((k) => h >= TIME_SLOTS[k][1] && h < TIME_SLOTS[k][2])) return false;
    }
    // Offer-level filters: a trip stays if at least one remaining offer passes all of them.
    return t.offers.some((o) =>
      (!f.availableOnly || o.available) &&
      (!f.sellers.size || f.sellers.has(o.seller)) &&
      (!f.classes.size || f.classes.has(o.fare_class)) &&
      (!f.refundable || o.refundable) &&
      (f.priceMin == null || o.price >= f.priceMin) &&
      (f.priceMax == null || o.price <= f.priceMax));
  });
}

function Section({ title, children, open: initial = true }: { title: string; children: React.ReactNode; open?: boolean }) {
  const [open, setOpen] = useState(initial);
  return (
    <section className="f-section">
      <button type="button" className="f-head" aria-expanded={open} onClick={() => setOpen(!open)}>
        <b>{title}</b><span className={open ? "chev open" : "chev"}><ChevronIcon /></span>
      </button>
      {open && <div className="f-body">{children}</div>}
    </section>
  );
}

function CheckList({ items, sel, toggle, searchable }: { items: [string, string, number][]; sel: Set<string>; toggle: (k: string) => void; searchable?: string }) {
  const [q, setQ] = useState("");
  const [all, setAll] = useState(false);
  const shown = items.filter(([, l]) => !q || l.includes(q));
  const list = all || q ? shown : shown.slice(0, 6);
  return (
    <>
      {searchable && items.length > 6 && <input className="input sm" placeholder={searchable} value={q} onChange={(e) => setQ(e.target.value)} />}
      {list.map(([k, label, count]) => (
        <label key={k} className="check"><input type="checkbox" checked={sel.has(k)} onChange={() => toggle(k)} />
          <span className="grow">{label}</span><span className="muted small">{num(count)}</span></label>
      ))}
      {!q && shown.length > 6 && <button type="button" className="link small" onClick={() => setAll(!all)}>{all ? "نمایش کمتر" : `نمایش ${num(shown.length - 6)} مورد دیگر`}</button>}
      {list.length === 0 && <div className="muted small">موردی نیست</div>}
    </>
  );
}

const tally = (vals: string[]): [string, string, number][] => {
  const m = new Map<string, number>();
  vals.filter(Boolean).forEach((v) => m.set(v, (m.get(v) ?? 0) + 1));
  return [...m.entries()].sort((a, b) => b[1] - a[1]).map(([k, n]) => [k, k, n]);
};

export default function Filters({ trips, state, set, mode, onClose }:
  { trips: Trip[]; state: FilterState; set: (s: FilterState) => void; mode: Mode; onClose?: () => void }) {
  const [from, setFrom] = useState(state.priceMin?.toString() ?? "");
  const [to, setTo] = useState(state.priceMax?.toString() ?? "");
  useEffect(() => { setFrom(state.priceMin?.toString() ?? ""); setTo(state.priceMax?.toString() ?? ""); }, [state.priceMin, state.priceMax]);
  const toggle = (key: "times" | "carriers" | "sellers" | "classes" | "features" | "terminals") => (k: string) => {
    const s = new Set(state[key]); s.has(k) ? s.delete(k) : s.add(k); set({ ...state, [key]: s });
  };
  const prices = trips.flatMap((t) => t.offers.map((o) => o.price));
  const lo = prices.length ? Math.min(...prices) : 0, hi = prices.length ? Math.max(...prices) : 0;
  const digits = (v: string) => v.replace(/[۰-۹]/g, (d) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(d))).replace(/\D/g, "");

  const timeItems = Object.entries(TIME_SLOTS).map(([k, [label, a, b]]) =>
    [k, `${label} (${num(a)} تا ${num(b)})`, trips.filter((t) => +t.departure.slice(11, 13) >= a && +t.departure.slice(11, 13) < b).length] as [string, string, number]);
  const classes = tally(trips.flatMap((t) => [...new Set(t.offers.map((o) => o.fare_class))]));
  const features = tally(trips.flatMap((t) => t.features)).filter(([k]) => !classes.some(([c]) => c === k));
  const terminals = tally(trips.map((t) => t.origin_terminal ?? ""));

  return (
    <aside className="filters" aria-label="فیلترها">
      <div className="filters-head">
        <b>فیلترها</b>
        <span className="grow" />
        {activeCount(state) > 0 && <button type="button" className="link" onClick={() => set({ ...state, ...emptyFilters(), availableOnly: state.availableOnly })}>حذف همه</button>}
        {onClose && <button type="button" className="btn small" onClick={onClose}>نمایش نتایج</button>}
      </div>
      <Section title="قیمت">
        <div className="price-range">
          <label>از<input className="input sm" inputMode="numeric" value={from} placeholder={num(lo)} onChange={(e) => setFrom(digits(e.target.value))} />تومان</label>
          <label>تا<input className="input sm" inputMode="numeric" value={to} placeholder={num(hi)} onChange={(e) => setTo(digits(e.target.value))} />تومان</label>
        </div>
        {prices.length > 0 && <div className="muted small">از {num(lo)} تا {num(hi)} تومان</div>}
        <div className="row">
          <button type="button" className="btn dark small grow" onClick={() => set({ ...state, priceMin: from ? +from : null, priceMax: to ? +to : null })}>اعمال فیلتر</button>
          <button type="button" className="btn small" onClick={() => { setFrom(""); setTo(""); set({ ...state, priceMin: null, priceMax: null }); }}>حذف</button>
        </div>
      </Section>
      <Section title="ساعت حرکت"><CheckList items={timeItems} sel={state.times} toggle={toggle("times")} /></Section>
      <Section title={CARRIER_LABEL[mode]}><CheckList items={tally(trips.map((t) => t.airline))} sel={state.carriers} toggle={toggle("carriers")} searchable="جستجوی نام" /></Section>
      {classes.length > 1 && <Section title={mode === "flight" ? "کلاس پروازی" : mode === "train" ? "نوع واگن" : "نوع اتوبوس"}><CheckList items={classes} sel={state.classes} toggle={toggle("classes")} /></Section>}
      {features.length > 0 && <Section title="امکانات"><CheckList items={features} sel={state.features} toggle={toggle("features")} /></Section>}
      {mode === "bus" && terminals.length > 1 && <Section title="پایانه مبدأ"><CheckList items={terminals} sel={state.terminals} toggle={toggle("terminals")} /></Section>}
      <Section title="فروشنده" open={false}><CheckList items={tally(trips.flatMap((t) => t.offers.map((o) => o.seller)))} sel={state.sellers} toggle={toggle("sellers")} searchable="جستجوی فروشنده" /></Section>
    </aside>
  );
}
