import { useState } from "react";
import { ModeIcon } from "../components/Icons";
import { hhmm, toman } from "../lib/format";
import { formatFull } from "../lib/jalali";
import { TICKET_LABEL, tripTitle } from "../lib/modes";
import { linkProps } from "../lib/router";
import { tripUrl } from "../lib/query";
import { favorites } from "../lib/storage";

export default function Favorites({ cityName }: { cityName: (c: string) => string }) {
  const [items, setItems] = useState(() => favorites.all());
  const today = new Date().toISOString().slice(0, 10);
  return (
    <main className="wrap narrow">
      <h1 className="page-title">علاقه‌مندی‌ها</h1>
      {items.length === 0 && <div className="empty"><b>هنوز سفری ذخیره نکرده‌اید.</b><span>روی آیکون قلب کنار هر سفر بزنید تا این‌جا بماند.</span>
        <a className="btn dark small" {...linkProps("/")}>جستجوی سفر</a></div>}
      <ul className="fav-list">
        {items.map(({ trip, query, saved }) => {
          const past = query.date < today;
          return (
            <li key={trip.id} className={"panel fav" + (past ? " past" : "")}>
              <ModeIcon mode={trip.mode} />
              <a className="grow" {...linkProps(tripUrl(trip.id, query))}>
                <b>{TICKET_LABEL[trip.mode]} {cityName(trip.origin)} به {cityName(trip.destination)}</b>
                <div className="muted small">{tripTitle(trip)}، {formatFull(new Date(query.date + "T12:00:00"))}، ساعت {hhmm(trip.departure)}</div>
              </a>
              <div className="fav-price"><span className="muted small">{past ? "تاریخ گذشته" : "قیمت هنگام ذخیره"}</span><b>{toman(trip.min_price)}</b></div>
              <button type="button" className="link small" onClick={() => { favorites.remove(trip.id); setItems(favorites.all()); }}
                aria-label={`حذف ${tripTitle(trip)} از علاقه‌مندی‌ها`} title={`ذخیره‌شده در ${new Date(saved).toLocaleDateString("fa-IR")}`}>حذف</button>
            </li>
          );
        })}
      </ul>
    </main>
  );
}
