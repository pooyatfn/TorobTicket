import { useEffect, useMemo, useState } from "react";
import AlertModal from "../components/AlertModal";
import DateStrip from "../components/DateStrip";
import Filters, { FilterState, activeCount, applyFilters, emptyFilters } from "../components/Filters";
import { FilterIcon } from "../components/Icons";
import TripCard from "../components/TripCard";
import { searchLive } from "../lib/api";
import { hhmm, num, toman } from "../lib/format";
import { formatFull, formatShort } from "../lib/jalali";
import { TICKET_LABEL, tripTitle } from "../lib/modes";
import { linkProps, navigate } from "../lib/router";
import { legQueries, searchUrl, tripUrl, withLegDate } from "../lib/query";
import { recentSearches } from "../lib/storage";
import type { Query, SearchResponse, Trip } from "../lib/types";

type Sort = "cheapest" | "expensive" | "earliest" | "latest" | "fastest" | "sellers";
const SORTS: [Sort, string][] = [["cheapest", "ارزان‌ترین"], ["expensive", "گران‌ترین"], ["earliest", "زودترین حرکت"],
  ["latest", "دیرترین حرکت"], ["fastest", "کوتاه‌ترین سفر"], ["sellers", "بیشترین فروشنده"]];
const BY: Record<Sort, (a: Trip, b: Trip) => number> = {
  cheapest: (a, b) => a.min_price - b.min_price, expensive: (a, b) => b.min_price - a.min_price,
  earliest: (a, b) => a.departure.localeCompare(b.departure), latest: (a, b) => b.departure.localeCompare(a.departure),
  fastest: (a, b) => (a.duration_min ?? 1e9) - (b.duration_min ?? 1e9), sellers: (a, b) => b.seller_count - a.seller_count,
};
/** `loading`: nothing to show yet. `pending`: sellers still searching while the first answers are shown. */
interface Leg { data: SearchResponse | null; loading: boolean; error: string; pending: string[] }
const EMPTY: Leg = { data: null, loading: true, error: "", pending: [] };
const LEG_LABEL = ["رفت", "برگشت"];

export default function Results({ query, cityName }: { query: Query; cityName: (c: string) => string }) {
  const legs = useMemo(() => legQueries(query), [query]);
  const round = legs.length === 2;
  const [state, setState] = useState<Leg[]>([]);
  const [active, setActive] = useState(0);
  const [picked, setPicked] = useState<(Trip | null)[]>([null, null]);
  const [sort, setSort] = useState<Sort>("cheapest");
  const [filters, setFilters] = useState<FilterState[]>([emptyFilters(), emptyFilters()]);
  const [drawer, setDrawer] = useState(false);
  const [alertFor, setAlertFor] = useState<{ trip: Trip; q: Query } | null>(null);

  // One search per leg, in parallel. A leg keeps its results if only the other leg's date changed.
  const legKeys = legs.map((l) => JSON.stringify(l));
  useEffect(() => { recentSearches.add(query); }, [query]);
  useEffect(() => {
    setState(legs.map(() => EMPTY));
    setFilters([emptyFilters(), emptyFilters()]);
    const set = (i: number, leg: Leg) => setState((s) => s.map((x, j) => j === i ? leg : x));
    // Results appear as soon as the first seller answers; slower sellers are merged in as they arrive.
    const stops = legs.map((lq, i) => searchLive(lq,
      (data) => set(i, { data, loading: false, error: "", pending: data.done === false ? data.pending ?? [] : [] }),
      (e) => set(i, { data: null, loading: false, error: e.message, pending: [] })));
    return () => stops.forEach((stop) => stop());
  }, legKeys); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { setPicked([null, null]); setActive(0); }, [query.mode, query.origin, query.destination]);
  useEffect(() => { setPicked((p) => [legs[0] && p[0]?.departure.startsWith(legs[0].date) ? p[0] : null,
    legs[1] && p[1]?.departure.startsWith(legs[1].date) ? p[1] : null]); }, legKeys); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (!round) setActive(0); }, [round]);

  const leg = state[active] ?? EMPTY;
  const partial = leg.pending.length > 0;
  const lq = legs[active] ?? legs[0];
  const f = filters[active];
  const setF = (nf: FilterState) => setFilters((all) => all.map((x, i) => i === active ? nf : x));
  const shown = useMemo(() => (leg.data ? applyFilters(leg.data.flights, f).slice().sort((a, b) =>
    a.available === b.available ? BY[sort](a, b) : a.available ? -1 : 1) : []), [leg.data, f, sort]);
  const providers = leg.data ? Object.entries(leg.data.providers) : [];
  const down = providers.filter(([, s]) => !s.ok).map(([n]) => n);
  const stale = providers.filter(([, s]) => s.stale).map(([n]) => n);
  // Cheapest price over everything that has arrived (ignores filters): it can still drop while sellers are pending.
  const bestTrip = leg.data ? leg.data.flights.filter((t) => t.available).sort((a, b) => a.min_price - b.min_price)[0] : undefined;
  const bestOffer = bestTrip?.offers.find((o) => o.available);
  const soldOut = leg.data ? leg.data.flights.filter((t) => !t.available).length : 0;
  const route = `${cityName(query.origin)} به ${cityName(query.destination)}`;
  const chip = (on: boolean, label: string, flip: () => void) =>
    <button type="button" className={"chip toggle" + (on ? " on" : "")} aria-pressed={on} onClick={flip}>{label}</button>;
  const pick = (t: Trip) => {
    const next = picked.map((p, i) => i === active ? (p?.id === t.id ? null : t) : p);
    setPicked(next);
    if (active === 0 && round && next[0] && !next[1]) { setActive(1); window.scrollTo({ top: 0 }); }
  };
  const pax = query.adults + query.children;
  const total = picked[0] && picked[1] ? (picked[0].min_price + picked[1].min_price) * pax : null;

  return (
    <main className={"wrap results" + (round ? " has-bar" : "")}>
      <nav className="crumbs" aria-label="مسیر"><a {...linkProps(`/?mode=${query.mode}`)}>ترب تیکت</a>
        <span>›</span><span>{TICKET_LABEL[query.mode]}</span><span>›</span><span>{route}{round ? " (رفت و برگشت)" : ""}</span></nav>
      <h1 className="page-title">{TICKET_LABEL[query.mode]} {route}{round ? " — رفت و برگشت" : ""}
        <span className="muted"> — {formatFull(new Date(query.date + "T12:00:00"))}{round ? ` تا ${formatFull(new Date(query.ret + "T12:00:00"))}` : ""}</span></h1>

      {round && (
        <div className="leg-tabs" role="tablist" aria-label="مسیر رفت یا برگشت">
          {legs.map((l, i) => (
            <button key={i} type="button" role="tab" aria-selected={active === i} className={active === i ? "on" : ""} onClick={() => setActive(i)}>
              <span className="leg-step">{LEG_LABEL[i]}</span>
              <b>{cityName(l.origin)} به {cityName(l.destination)}</b>
              <span className="muted small">{formatShort(new Date(l.date + "T12:00:00"))}
                {picked[i] ? `، ${hhmm(picked[i]!.departure)} انتخاب شد` : state[i]?.loading || state[i]?.pending.length ? "، در حال جستجو" : state[i]?.data ? `، ${num(state[i]!.data!.flights.filter((t) => t.available).length)} سفر` : ""}</span>
            </button>
          ))}
        </div>
      )}

      <DateStrip query={lq} busy={leg.loading} onPick={(date) => navigate(searchUrl(withLegDate(query, active, date)))} />
      {leg.error && <div className="notice error" role="alert">{leg.error}</div>}
      {down.length > 0 && !leg.loading && !partial && <div className="notice warn">نتایج {down.join("، ")} الان در دسترس نیست؛ فهرست زیر ممکن است کامل نباشد.</div>}
      {partial && <div className="notice progress" role="status"><span className="spinner" aria-hidden="true" />
        در حال گرفتن قیمت از {leg.pending.join("، ")}؛ فهرست با رسیدن قیمت‌ها کامل می‌شود.</div>}
      {stale.length > 0 && !leg.loading && <div className="notice warn">قیمت‌های {stale.join("، ")} ممکن است چند دقیقه قدیمی باشند.</div>}

      {bestTrip && bestOffer && !leg.loading && (
        <div className={"best-bar" + (partial ? " partial" : "")} role="status" aria-live="polite">
          <span className="best-label">{partial ? "ارزان‌ترین تا این‌جا" : "ارزان‌ترین قیمت"}</span>
          <b className="best-price">{toman(bestTrip.min_price)}</b>
          <span className="muted small">{bestOffer.seller} · {hhmm(bestTrip.departure)}{bestTrip.seller_count > 1 ? ` · ${num(bestTrip.seller_count)} فروشنده` : ""}</span>
          {partial && <span className="muted small">؛ ممکن است با رسیدن {leg.pending.join("، ")} ارزان‌تر شود</span>}
        </div>
      )}

      <div className="layout">
        {leg.data && leg.data.flights.length > 0 && (
          <div className={"filters-wrap" + (drawer ? " open" : "")}>
            <Filters key={active} trips={leg.data.flights} state={f} set={setF} mode={query.mode} onClose={drawer ? () => setDrawer(false) : undefined} />
          </div>
        )}
        <section className="results-main" aria-busy={leg.loading || partial}>
          <div className="toolbar">
            <button type="button" className="btn small filters-btn" onClick={() => setDrawer(true)}>
              <FilterIcon />فیلترها{activeCount(f) ? ` (${num(activeCount(f))})` : ""}</button>
            {chip(f.availableOnly, "فقط موجودها", () => setF({ ...f, availableOnly: !f.availableOnly }))}
            {chip(f.refundable, "قابل استرداد", () => setF({ ...f, refundable: !f.refundable }))}
            <span className="grow" />
            <label className="sort">مرتب‌سازی
              <select value={sort} onChange={(e) => setSort(e.target.value as Sort)}>
                {SORTS.filter(([k]) => k !== "fastest" || query.mode !== "bus").map(([k, l]) => <option key={k} value={k}>{l}</option>)}
              </select></label>
          </div>
          {!leg.loading && leg.data && <p className="muted small count">{num(shown.length)} سفر{partial ? " تا این‌جا" : ""}{soldOut > 0 && f.availableOnly ? `، ${num(soldOut)} سفر تکمیل‌ظرفیت پنهان است` : ""}</p>}
          {(leg.loading || (partial && !leg.data?.flights.length)) && [0, 1, 2, 3].map((i) => <div key={i} className="trip skeleton" />)}
          {!leg.loading && !partial && leg.data && leg.data.flights.length === 0 &&
            <div className="empty"><b>برای این روز سفری پیدا نشد.</b><span>روز دیگری را از نوار بالا انتخاب کنید یا مسیر را عوض کنید.</span></div>}
          {!leg.loading && leg.data && leg.data.flights.length > 0 && shown.length === 0 &&
            <div className="empty"><b>هیچ سفری با این فیلترها نیست.</b>
              <button type="button" className="btn small" onClick={() => setF({ ...emptyFilters(), availableOnly: false })}>حذف فیلترها</button></div>}
          {!leg.loading && shown.map((t) => (
            <TripCard key={t.id} trip={t} query={lq} onAlert={(trip) => setAlertFor({ trip, q: lq })}
              select={round ? { selected: picked[active]?.id === t.id, label: active === 0 ? "انتخاب رفت" : "انتخاب برگشت", onSelect: () => pick(t) } : undefined} />
          ))}
        </section>
      </div>

      {round && (
        <aside className="rt-bar" aria-label="سفر انتخاب‌شده">
          <div className="wrap rt-inner">
            {legs.map((l, i) => (
              <div key={i} className={"rt-slot" + (picked[i] ? " full" : "")}>
                <span className="muted small">{LEG_LABEL[i]}، {formatShort(new Date(l.date + "T12:00:00"))}</span>
                {picked[i] ? (
                  <a {...linkProps(tripUrl(picked[i]!.id, l))}><b className="clamp">{hhmm(picked[i]!.departure)} {tripTitle(picked[i]!)}</b>
                    <span className="small">{toman(picked[i]!.min_price)}</span></a>
                ) : <button type="button" className="link" onClick={() => setActive(i)}>{`${LEG_LABEL[i]} را انتخاب کنید`}</button>}
              </div>
            ))}
            <div className="rt-total">
              {total != null ? <><span className="muted small">جمع برای {num(pax)} مسافر</span><b>{toman(total)}</b></>
                : <span className="muted small">بعد از انتخاب رفت و برگشت، جمع قیمت این‌جا نمایش داده می‌شود</span>}
            </div>
          </div>
        </aside>
      )}
      {alertFor && <AlertModal trip={alertFor.trip} query={alertFor.q} onClose={() => setAlertFor(null)} />}
    </main>
  );
}
