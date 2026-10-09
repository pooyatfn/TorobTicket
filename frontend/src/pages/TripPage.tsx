import { useEffect, useMemo, useState } from "react";
import AlertModal from "../components/AlertModal";
import { BellIcon, HeartIcon, ShareIcon } from "../components/Icons";
import PriceChart from "../components/PriceChart";
import { Carrier, Times } from "../components/TripCard";
import { ApiError, getHistory, getTrip, search } from "../lib/api";
import { duration, faNum, hhmm, num, toman } from "../lib/format";
import { formatFull } from "../lib/jalali";
import { CARRIER_LABEL, TICKET_LABEL, VEHICLE_LABEL, tripTitle } from "../lib/modes";
import { linkProps, navigate } from "../lib/router";
import { searchUrl, tripUrl } from "../lib/query";
import { favorites } from "../lib/storage";
import type { PricePoint, Query, Trip } from "../lib/types";

export default function TripPage({ id, query, cityName }: { id: string; query: Query; cityName: (c: string) => string }) {
  const [trip, setTrip] = useState<Trip | null>(null);
  const [siblings, setSiblings] = useState<Trip[]>([]);
  const [hist, setHist] = useState<PricePoint[] | null>(null);
  const [err, setErr] = useState("");
  const [fav, setFav] = useState(() => favorites.has(id));
  const [alert, setAlert] = useState(false);
  const [shared, setShared] = useState("");
  const [onlyRefundable, setOnlyRefundable] = useState(false);

  useEffect(() => {
    let live = true;
    setTrip(null); setErr(""); setHist(null);
    // Fast path: the server remembers recent trips. Otherwise (shared link, restart) search again by the URL query.
    getTrip(id).then((r) => live && setTrip(r.trip)).catch(async (e) => {
      if (!(e instanceof ApiError) || e.status !== 404) { if (live) setErr((e as Error).message); return; }
      try {
        const r = await search(query);
        const t = r.flights.find((f) => f.id === id);
        if (live) t ? setTrip(t) : setErr("این سفر دیگر در نتایج نیست؛ شاید ظرفیتش تمام شده یا زمانش تغییر کرده.");
      } catch (x) { if (live) setErr((x as Error).message); }
    });
    search(query).then((r) => live && setSiblings(r.flights.filter((f) => f.id !== id && f.available))).catch(() => {});
    getHistory(id).then((h) => live && setHist(h)).catch(() => live && setHist([]));
    return () => { live = false; };
  }, [id, query]);

  const offers = useMemo(() => (trip?.offers ?? []).filter((o) => !onlyRefundable || o.refundable), [trip, onlyRefundable]);
  const similar = useMemo(() => !trip ? [] : siblings.slice().sort((a, b) =>
    Math.abs(+new Date(a.departure) - +new Date(trip.departure)) - Math.abs(+new Date(b.departure) - +new Date(trip.departure))).slice(0, 4),
  [siblings, trip]);

  async function share() {
    const url = location.origin + tripUrl(id, query);
    try {
      if (navigator.share) { await navigator.share({ title: document.title, url }); return; }
      await navigator.clipboard.writeText(url); setShared("لینک کپی شد");
    } catch { setShared(url); }
    setTimeout(() => setShared(""), 3000);
  }

  const route = `${cityName(query.origin)} به ${cityName(query.destination)}`;
  const crumbs = (
    <nav className="crumbs" aria-label="مسیر"><a {...linkProps(`/?mode=${query.mode}`)}>ترب تیکت</a><span>›</span>
      <a {...linkProps(searchUrl(query))}>{TICKET_LABEL[query.mode]} {route}</a>{trip && <><span>›</span><span>{tripTitle(trip)}</span></>}</nav>
  );
  if (err) return <main className="wrap">{crumbs}<div className="empty"><b>{err}</b>
    <a className="btn dark small" {...linkProps(searchUrl(query))}>دیدن سفرهای این روز</a></div></main>;
  if (!trip) return <main className="wrap">{crumbs}<div className="trip-page"><div className="panel skeleton tall" /><div className="panel skeleton tall" /></div></main>;

  const best = trip.offers.find((o) => o.available);
  const specs: [string, string | null | undefined][] = [
    [CARRIER_LABEL[trip.mode], trip.airline],
    [trip.mode === "train" ? "شماره قطار" : trip.mode === "flight" ? "شماره پرواز" : null as never, trip.flight_number ? `${trip.airline_code} ${faNum(trip.flight_number)}`.trim() : null],
    [VEHICLE_LABEL[trip.mode], trip.aircraft],
    ["تاریخ", formatFull(new Date(query.date + "T12:00:00"))],
    ["ساعت حرکت", hhmm(trip.departure)],
    ["ساعت رسیدن", trip.arrival ? hhmm(trip.arrival) : null],
    ["مدت سفر", trip.duration_min != null ? duration(trip.duration_min) : null],
    ["پایانه مبدأ", trip.origin_terminal], ["پایانه مقصد", trip.destination_terminal],
    ["توقف‌های بین‌راهی", trip.stops.length ? trip.stops.join("، ") : null],
    ["صندلی خالی", trip.seats_left != null ? (trip.seats_left > 0 ? num(trip.seats_left) : "تکمیل") : null],
    ["امکانات", trip.features.length ? trip.features.join("، ") : null],
    ["بار مجاز", best?.baggage_kg ? `${num(best.baggage_kg)} کیلوگرم` : null],
  ];

  return (
    <main className="wrap">
      {crumbs}
      <div className="trip-page">
        <div className="col-main">
          <section className="panel trip-hero">
            <div className="hero-head">
              <Carrier trip={trip} size={56} />
              <div className="grow">
                <h1>{TICKET_LABEL[trip.mode]} {route}</h1>
                <div className="muted">{tripTitle(trip)}{trip.aircraft && trip.mode !== "train" ? `، ${trip.aircraft}` : ""}</div>
              </div>
            </div>
            <Times trip={trip} />
            <div className="hero-buy">
              {best ? (
                <a className="cta" href={best.url} target="_blank" rel="noopener noreferrer sponsored">
                  <span>خرید از {best.seller}{best.via ? ` (از طریق ${best.via})` : ""}</span>
                  <b>{toman(best.price)}</b>
                  {trip.seller_count > 1 && <em>ارزان‌ترین</em>}
                </a>
              ) : <div className="cta off">این سفر تکمیل ظرفیت شده است</div>}
              <div className="hero-icons">
                <button type="button" className="icon-btn" onClick={() => setAlert(true)} aria-label="هشدار کاهش قیمت"><BellIcon /></button>
                <button type="button" className={"icon-btn" + (fav ? " on" : "")} aria-pressed={fav}
                  aria-label={fav ? "حذف از علاقه‌مندی‌ها" : "افزودن به علاقه‌مندی‌ها"} onClick={() => setFav(favorites.toggle(trip, query))}><HeartIcon filled={fav} /></button>
                <button type="button" className="icon-btn" onClick={share} aria-label="اشتراک‌گذاری"><ShareIcon /></button>
                {shared && <span className="muted small" role="status">{shared}</span>}
                <span className="grow" />
                {trip.seller_count > 1 && <span className="muted small">{num(trip.seller_count)} فروشنده</span>}
              </div>
            </div>
          </section>

          <section className="panel" aria-labelledby="sellers-title">
            <div className="row between"><h2 id="sellers-title">فروشنده‌ها</h2>
              <button type="button" className={"chip toggle" + (onlyRefundable ? " on" : "")} aria-pressed={onlyRefundable}
                onClick={() => setOnlyRefundable(!onlyRefundable)}>فقط قابل استرداد</button></div>
            <ul className="sellers">
              {offers.map((o, i) => (
                <li key={o.seller} className={o.available ? "" : "sold"}>
                  <div className="s-name"><b>{o.seller}</b>{i === 0 && o.available && trip.offers.length > 1 && <span className="badge">ارزان‌ترین</span>}
                    <div className="muted small">{[o.fare_class, o.baggage_kg ? `بار ${num(o.baggage_kg)} کیلو` : "", o.refundable ? "قابل استرداد" : "غیرقابل استرداد", o.via ? `از طریق ${o.via}` : ""].filter(Boolean).join("، ")}</div></div>
                  <div className="s-price"><b>{o.available ? toman(o.price) : "ناموجود"}</b>
                    {o.available && best && o.price > best.price && <span className="muted small">{toman(o.price - best.price)} گران‌تر</span>}</div>
                  <a className={"btn small " + (o.available ? "brand" : "")} href={o.url} target="_blank" rel="noopener noreferrer sponsored">خرید از سایت فروشنده</a>
                </li>
              ))}
              {offers.length === 0 && <li className="muted">فروشنده‌ای با این شرط نیست.</li>}
            </ul>
          </section>

          {similar.length > 0 && (
            <section className="panel" aria-labelledby="similar-title">
              <h2 id="similar-title">سفرهای دیگر همین روز</h2>
              <div className="similar">
                {similar.map((s) => (
                  <a key={s.id} className="sim" {...linkProps(tripUrl(s.id, query))} onClick={(e) => { e.preventDefault(); navigate(tripUrl(s.id, query)); }}>
                    <b>{hhmm(s.departure)}</b><span className="clamp">{tripTitle(s)}</span><span className="price">{toman(s.min_price)}</span>
                  </a>
                ))}
              </div>
            </section>
          )}
        </div>

        <aside className="col-side">
          <section className="panel" aria-labelledby="hist-title">
            <h2 id="hist-title">تغییرات قیمت</h2>
            {hist ? <PriceChart points={hist} /> : <div className="skeleton chart-sk" />}
          </section>
          <section className="panel" aria-labelledby="spec-title">
            <h2 id="spec-title">مشخصات سفر</h2>
            <dl className="specs">{specs.filter(([k, v]) => k && v).map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>
          </section>
        </aside>
      </div>
      {alert && <AlertModal trip={trip} query={query} onClose={() => setAlert(false)} />}
    </main>
  );
}
