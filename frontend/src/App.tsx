import { useEffect, useMemo, useState } from "react";
import Header, { Footer } from "./components/Header";
import SearchBox from "./components/SearchBox";
import { getCities } from "./lib/api";
import { num } from "./lib/format";
import { formatShort } from "./lib/jalali";
import { TICKET_LABEL } from "./lib/modes";
import { navigate, useLocation } from "./lib/router";
import { queryFromParams, searchUrl } from "./lib/query";
import AlertsPage from "./pages/AlertsPage";
import Favorites from "./pages/Favorites";
import Home from "./pages/Home";
import Results from "./pages/Results";
import TripPage from "./pages/TripPage";
import type { City, Query } from "./lib/types";

export default function App() {
  const { path, search } = useLocation();
  const params = useMemo(() => new URLSearchParams(search), [search]);
  const query: Query = useMemo(() => queryFromParams(params), [params]);
  const [names, setNames] = useState<Record<string, string>>({});
  useEffect(() => {
    // City names for every mode (bus/train cities are a subset of the full list).
    Promise.all((["flight", "bus"] as const).map((m) => getCities(m).catch(() => [] as City[])))
      .then((ls) => setNames(Object.fromEntries(ls.flat().map((c) => [c.code, c.name]))));
  }, []);
  const cityName = (c: string) => names[c] ?? c;

  const trip = path.match(/^\/trip\/([\w-]+)/);
  let page: React.ReactNode, title = "ترب تیکت | مقایسه قیمت بلیط هواپیما، قطار و اتوبوس";
  if (path === "/search") {
    page = <Results query={query} cityName={cityName} />;
    title = `${TICKET_LABEL[query.mode]} ${cityName(query.origin)} به ${cityName(query.destination)} | ترب تیکت`;
  } else if (trip) {
    page = <TripPage id={trip[1]} query={query} cityName={cityName} />;
    title = `${TICKET_LABEL[query.mode]} ${cityName(query.origin)} به ${cityName(query.destination)} | ترب تیکت`;
  } else if (path === "/favorites") page = <Favorites cityName={cityName} />;
  else if (path === "/alerts") page = <AlertsPage cityName={cityName} />;
  else page = <Home initial={query} />;
  useEffect(() => { document.title = title; }, [title]);

  const home = !(path === "/search" || trip || path === "/favorites" || path === "/alerts");
  return (
    <>
      {!home && (
        <Header mode={query.mode}>
          {(path === "/search" || trip) && <CompactSearch query={query} cityName={cityName} />}
        </Header>
      )}
      {home && <HomeTopBar />}
      {page}
      <Footer />
    </>
  );
}

/** Full search box on desktop; on phones a one-line summary that opens it (Torob-style). */
function CompactSearch({ query, cityName }: { query: Query; cityName: (c: string) => string }) {
  const [open, setOpen] = useState(false);
  useEffect(() => setOpen(false), [query]);
  return (
    <div className={"compact-search" + (open ? " open" : "")}>
      <button type="button" className="search-summary" aria-expanded={open} onClick={() => setOpen(!open)}>
        <span><b>{cityName(query.origin)} به {cityName(query.destination)}</b>
          <span className="muted small">{formatShort(new Date(query.date + "T12:00:00"))}{query.ret ? ` تا ${formatShort(new Date(query.ret + "T12:00:00"))}` : ""}، {num(query.adults + query.children + query.infants)} مسافر</span></span>
        <span className="link small">{open ? "بستن" : "تغییر جستجو"}</span>
      </button>
      <SearchBox query={query} onSearch={(q) => navigate(searchUrl(q))} />
    </div>
  );
}

function HomeTopBar() {
  return (
    <div className="home-top wrap wide">
      <a href="/favorites" onClick={(e) => { e.preventDefault(); navigate("/favorites"); }}>علاقه‌مندی‌ها</a>
      <a href="/alerts" onClick={(e) => { e.preventDefault(); navigate("/alerts"); }}>هشدارهای من</a>
    </div>
  );
}
