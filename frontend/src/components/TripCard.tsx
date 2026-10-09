import { useState } from "react";
import { BellIcon, HeartIcon, ModeIcon } from "./Icons";
import { duration, faNum, hhmm, num, toman } from "../lib/format";
import { linkProps } from "../lib/router";
import { tripUrl } from "../lib/query";
import { favorites } from "../lib/storage";
import type { Query, Trip } from "../lib/types";

export function Carrier({ trip, size = 40 }: { trip: Trip; size?: number }) {
  const [broken, setBroken] = useState(false);
  return trip.logo && !broken
    ? <img className="carrier-logo" src={trip.logo} alt="" width={size} height={size} onError={() => setBroken(true)} />
    : <span className="carrier-logo initial" style={{ width: size, height: size }} aria-hidden="true">{trip.airline.trim().slice(0, 1) || <ModeIcon mode={trip.mode} />}</span>;
}

export function Times({ trip }: { trip: Trip }) {
  return (
    <div className="times">
      <div className="t-end"><b>{hhmm(trip.departure)}</b><span className="muted small">{trip.origin_terminal ?? trip.origin}</span></div>
      <div className="t-line">
        <span className="muted small">{trip.duration_min != null ? duration(trip.duration_min) : ""}</span>
        <i aria-hidden="true" />
        <span className="muted small">{trip.mode === "flight" ? "بدون توقف"
          : trip.stops.length > 1 ? `از مسیر ${trip.stops.slice(0, -1).join("، ")}` : trip.mode === "bus" ? "مستقیم" : ""}</span>
      </div>
      <div className="t-end"><b>{trip.arrival ? hhmm(trip.arrival) : "—"}</b><span className="muted small">{trip.destination_terminal ?? trip.destination}</span></div>
    </div>
  );
}

export interface SelectProps { selected: boolean; label: string; onSelect: () => void }

export default function TripCard({ trip, query, onAlert, select }: { trip: Trip; query: Query; onAlert: (t: Trip) => void; select?: SelectProps }) {
  const [fav, setFav] = useState(() => favorites.has(trip.id));
  const lowSeats = trip.available && trip.seats_left != null && trip.seats_left > 0 && trip.seats_left <= 5;
  const name = trip.mode === "train" ? `قطار ${faNum(trip.flight_number)}، ${trip.airline}` : trip.mode === "flight" ? `${trip.airline} ${faNum(trip.flight_number)}` : trip.airline;
  return (
    <article className={"trip" + (trip.available ? "" : " sold") + (select?.selected ? " picked" : "")}>
      <a className="trip-main" {...linkProps(tripUrl(trip.id, query))} aria-label={`جزئیات ${name}`}>
        <div className="trip-carrier">
          <Carrier trip={trip} />
          <div><b className="clamp">{name}</b>
            <div className="muted small clamp">{trip.aircraft}</div></div>
        </div>
        <Times trip={trip} />
        <div className="trip-tags">
          {trip.features.slice(0, 3).map((f) => <span key={f} className="tag">{f}</span>)}
          {!trip.available && <span className="tag warn">تکمیل ظرفیت</span>}
          {lowSeats && <span className="tag hot">فقط {num(trip.seats_left!)} صندلی</span>}
        </div>
        <div className="trip-price">
          {trip.available ? <><span className="muted small">{trip.seller_count > 1 ? "از" : ""}</span><b>{toman(trip.min_price)}</b>
            <span className="muted small">در {num(trip.seller_count)} فروشنده</span></>
            : <span className="muted">ناموجود</span>}
        </div>
      </a>
      {select && trip.available && (
        <div className="trip-select">
          <button type="button" className={"btn small " + (select.selected ? "dark" : "brand")} aria-pressed={select.selected} onClick={select.onSelect}>
            {select.selected ? "انتخاب شد ✓" : select.label}</button>
        </div>
      )}
      <div className="trip-actions">
        <button type="button" className={"icon-btn" + (fav ? " on" : "")} aria-pressed={fav} aria-label={fav ? "حذف از علاقه‌مندی‌ها" : "افزودن به علاقه‌مندی‌ها"}
          onClick={() => setFav(favorites.toggle(trip, query))}><HeartIcon filled={fav} /></button>
        <button type="button" className="icon-btn" aria-label="هشدار کاهش قیمت" onClick={() => onAlert(trip)}><BellIcon /></button>
      </div>
    </article>
  );
}
