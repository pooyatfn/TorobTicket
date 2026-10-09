import { useEffect, useState } from "react";
import { ModeIcon } from "../components/Icons";
import { deleteAlert, listAlerts } from "../lib/api";
import { toman } from "../lib/format";
import { formatFull } from "../lib/jalali";
import { TICKET_LABEL } from "../lib/modes";
import { savedContact } from "../lib/storage";
import type { Alert } from "../lib/types";

export default function AlertsPage({ cityName }: { cityName: (c: string) => string }) {
  const [contact, setContact] = useState(savedContact.get());
  const [items, setItems] = useState<Alert[] | null>(null);
  const [err, setErr] = useState("");
  async function load(c: string) {
    setErr("");
    try { setItems(await listAlerts(c.trim())); savedContact.set(c.trim()); } catch (e) { setErr((e as Error).message); }
  }
  useEffect(() => { if (contact) load(contact); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <main className="wrap narrow">
      <h1 className="page-title">هشدارهای من</h1>
      <form className="panel row" onSubmit={(e) => { e.preventDefault(); load(contact); }}>
        <label className="field-label grow">شماره موبایل یا ایمیلی که با آن هشدار ساخته‌اید
          <input className="input" dir="ltr" value={contact} onChange={(e) => setContact(e.target.value)} placeholder="09123456789" required /></label>
        <button className="btn dark">نمایش هشدارها</button>
      </form>
      {err && <div className="notice error">{err}</div>}
      {items && items.length === 0 && <div className="empty"><b>هشداری با این شماره یا ایمیل نیست.</b><span>در صفحهٔ هر سفر روی آیکون زنگ بزنید تا وقتی ارزان شد خبرتان کنیم.</span></div>}
      <ul className="fav-list">
        {items?.map((a) => (
          <li key={a.id} className="panel fav">
            <ModeIcon mode={a.mode} />
            <div className="grow"><b>{TICKET_LABEL[a.mode]} {cityName(a.origin)} به {cityName(a.destination)}</b>
              <div className="muted small">{formatFull(new Date(a.date + "T12:00:00"))}، قیمت هدف {toman(a.target_price)}
                {a.last_price ? `، آخرین قیمت ${toman(a.last_price)}` : ""}</div></div>
            <span className={"tag " + (a.notified_at ? "ok" : a.triggered_at ? "hot" : "")}>{a.notified_at ? "خبر داده شد" : a.triggered_at ? "رسید به قیمت" : "در انتظار"}</span>
            <button type="button" className="link small" onClick={async () => { await deleteAlert(a.id); setItems((x) => x?.filter((y) => y.id !== a.id) ?? null); }}>حذف</button>
          </li>
        ))}
      </ul>
    </main>
  );
}
