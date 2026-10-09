import { useEffect, useState } from "react";
import CityInput from "./CityInput";
import DatePicker from "./DatePicker";
import { SearchIcon, SwapIcon } from "./Icons";
import { getCities } from "../lib/api";
import { num } from "../lib/format";
import type { City, Query } from "../lib/types";

function Stepper({ label, hint, v, min, max, set }: { label: string; hint: string; v: number; min: number; max: number; set: (n: number) => void }) {
  return (
    <div className="stepper">
      <div><b>{label}</b><div className="muted small">{hint}</div></div>
      <div className="ctl">
        <button type="button" aria-label={`افزایش ${label}`} disabled={v >= max} onClick={() => set(v + 1)}>+</button>
        <span>{num(v)}</span>
        <button type="button" aria-label={`کاهش ${label}`} disabled={v <= min} onClick={() => set(v - 1)}>−</button>
      </div>
    </div>
  );
}

const cityCache: Partial<Record<string, City[]>> = {};

/** Origin / destination / date / passengers for the active mode. */
export default function SearchBox({ query, onSearch, busy }: { query: Query; onSearch: (q: Query) => void; busy?: boolean }) {
  const [q, setQ] = useState(query);
  const [cities, setCities] = useState<City[]>(cityCache[query.mode] ?? []);
  const [pax, setPax] = useState(false);
  useEffect(() => setQ(query), [query]);
  useEffect(() => {
    let live = true;
    if (cityCache[q.mode]) { setCities(cityCache[q.mode]!); return; }
    getCities(q.mode).then((c) => { cityCache[q.mode] = c; if (live) setCities(c); }).catch(() => live && setCities([]));
    return () => { live = false; };
  }, [q.mode]);

  const total = q.adults + q.children + q.infants;
  const round = q.ret !== undefined;
  const setDepart = (date: string) => setQ({ ...q, date, ...(q.ret && q.ret < date ? { ret: date } : {}) });
  const same = q.origin === q.destination;
  const unsupported = cities.length > 0 && (!cities.some((c) => c.code === q.origin) || !cities.some((c) => c.code === q.destination));

  return (
    <form className={"searchbox" + (round ? " round" : "")}
      onSubmit={(e) => { e.preventDefault(); if (!same && !unsupported && !(round && !q.ret)) onSearch(q); }}>
      <div className="trip-type" role="radiogroup" aria-label="نوع بلیط">
        <button type="button" role="radio" aria-checked={!round} className={!round ? "on" : ""}
          onClick={() => { const { ret: _r, ...rest } = q; setQ(rest); }}>یک‌طرفه</button>
        <button type="button" role="radio" aria-checked={round} className={round ? "on" : ""}
          onClick={() => setQ({ ...q, ret: q.ret ?? "" })}>رفت و برگشت</button>
      </div>
      <CityInput label="مبدأ" value={q.origin} cities={cities} onChange={(origin) => setQ({ ...q, origin })} />
      <button type="button" className="swap" aria-label="جابه‌جایی مبدأ و مقصد"
        onClick={() => setQ({ ...q, origin: q.destination, destination: q.origin })}><SwapIcon /></button>
      <CityInput label="مقصد" value={q.destination} cities={cities} onChange={(destination) => setQ({ ...q, destination })} />
      <DatePicker value={q.date} onChange={setDepart} />
      {round && <DatePicker label="تاریخ برگشت" value={q.ret ?? ""} min={q.date} placeholder="انتخاب تاریخ برگشت"
        onChange={(ret) => setQ({ ...q, ret })} onClear={() => setQ({ ...q, ret: "" })} />}
      <div className="field">
        <label className="field-label">مسافران</label>
        <button type="button" className="input" aria-expanded={pax} onClick={() => setPax(!pax)}>{num(total)} مسافر</button>
        {pax && (
          <div className="popover pax">
            <Stepper label="بزرگسال" hint="۱۲ سال به بالا" v={q.adults} min={1} max={9}
              set={(adults) => setQ({ ...q, adults, infants: Math.min(q.infants, adults) })} />
            <Stepper label="کودک" hint="۲ تا ۱۲ سال" v={q.children} min={0} max={8} set={(children) => setQ({ ...q, children })} />
            <Stepper label="نوزاد" hint="زیر ۲ سال" v={q.infants} min={0} max={q.adults} set={(infants) => setQ({ ...q, infants })} />
            <button type="button" className="btn dark small" onClick={() => setPax(false)}>تأیید</button>
          </div>
        )}
      </div>
      <button className="btn brand search-go" disabled={busy || same || unsupported || (round && !q.ret)} aria-label="جستجو">
        <SearchIcon /><span>جستجو</span>
      </button>
      {round && !q.ret && !same && <div className="form-hint">تاریخ برگشت را انتخاب کنید.</div>}
      {same && <div className="form-error">مبدأ و مقصد یکسان است؛ یکی را تغییر دهید.</div>}
      {unsupported && !same && <div className="form-error">این مسیر برای این نوع سفر در دسترس نیست؛ شهر دیگری انتخاب کنید.</div>}
    </form>
  );
}
