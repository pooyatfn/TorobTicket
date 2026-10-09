import { useEffect, useState } from "react";
import { Logo, ModeIcon } from "../components/Icons";
import ModeTabs from "../components/ModeTabs";
import SearchBox from "../components/SearchBox";
import { getPopular } from "../lib/api";
import { formatShort } from "../lib/jalali";
import { MODE_LABEL, TICKET_LABEL } from "../lib/modes";
import { navigate, linkProps } from "../lib/router";
import { searchUrl } from "../lib/query";
import { recentSearches } from "../lib/storage";
import type { Mode, Popular, Query } from "../lib/types";
import { tomorrow } from "../lib/format";

export default function Home({ initial }: { initial: Query }) {
  const [q, setQ] = useState<Query>(initial);
  const [popular, setPopular] = useState<Popular[]>([]);
  const [recent, setRecent] = useState(() => recentSearches.all());
  useEffect(() => setQ(initial), [initial]);
  useEffect(() => { getPopular(q.mode).then(setPopular).catch(() => setPopular([])); }, [q.mode]);
  const setMode = (mode: Mode) => { setQ({ ...q, mode }); history.replaceState(null, "", `/?mode=${mode}`); };
  const go = (next: Query) => navigate(searchUrl(next));

  return (
    <main className="home">
      <div className="home-hero">
        <div className="home-mark"><Logo size={56} /><h1>ترب <b>تیکت</b></h1></div>
        <p className="home-sub">قیمت بلیط هواپیما، قطار و اتوبوس را از چند سایت یک‌جا ببینید و ارزان‌ترین را بخرید.</p>
        <ModeTabs mode={q.mode} onChange={setMode} size="lg" />
        <div className="home-search"><SearchBox query={q} onSearch={go} /></div>
      </div>

      <section className="home-block" aria-labelledby="pop-title">
        <h2 id="pop-title">{TICKET_LABEL[q.mode]} مسیرهای پرطرفدار</h2>
        <div className="route-grid">
          {popular.map((p) => {
            const to: Query = { ...q, origin: p.origin, destination: p.destination, date: tomorrow() };
            return (
              <a key={p.origin + p.destination} className="route-card" {...linkProps(searchUrl(to))}>
                <ModeIcon mode={q.mode} /><span><b>{p.origin_name}</b> به <b>{p.destination_name}</b></span>
                <span className="muted small">فردا</span>
              </a>
            );
          })}
        </div>
      </section>

      {recent.length > 0 && (
        <section className="home-block" aria-labelledby="recent-title">
          <div className="row between"><h2 id="recent-title">جستجوهای اخیر شما</h2>
            <button type="button" className="link small" onClick={() => { recentSearches.clear(); setRecent([]); }}>پاک کردن</button></div>
          <div className="chips">
            {recent.map((r, i) => (
              <a key={i} className="chip" {...linkProps(searchUrl(r))}>
                <ModeIcon mode={r.mode} size={16} />{MODE_LABEL[r.mode]} {r.origin} ← {r.destination}، {formatShort(new Date(r.date + "T12:00:00"))}
              </a>
            ))}
          </div>
        </section>
      )}
    </main>
  );
}
