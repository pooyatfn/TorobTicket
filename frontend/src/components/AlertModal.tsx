import { useEffect, useRef, useState } from "react";
import { createAlert } from "../lib/api";
import { toman } from "../lib/format";
import { tripTitle } from "../lib/modes";
import { savedContact } from "../lib/storage";
import type { Query, Trip } from "../lib/types";

export default function AlertModal({ trip, query, onClose }: { trip: Trip; query: Query; onClose: () => void }) {
  const [price, setPrice] = useState(String(Math.floor((trip.min_price * 0.9) / 10000) * 10000));
  const [contact, setContact] = useState(savedContact.get());
  const [state, setState] = useState<"idle" | "busy" | "done">("idle");
  const [err, setErr] = useState("");
  const first = useRef<HTMLInputElement>(null);
  useEffect(() => {
    first.current?.focus();
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);

  async function submit(e: React.FormEvent) {
    e.preventDefault(); setErr(""); setState("busy");
    try {
      const a = await createAlert({ mode: query.mode, origin: trip.origin, destination: trip.destination, date: query.date,
        target_price: +price, contact, flight_id: trip.id });
      savedContact.set(a.contact);
      setState("done");
    } catch (x) { setErr((x as Error).message); setState("idle"); }
  }
  return (
    <div className="backdrop" onClick={onClose}>
      <form className="modal" onClick={(e) => e.stopPropagation()} onSubmit={submit} role="dialog" aria-modal="true" aria-labelledby="alert-title">
        <h3 id="alert-title">خبرم کن وقتی ارزان شد</h3>
        {state === "done" ? <>
          <p>هشدار ثبت شد. وقتی قیمت به {toman(+price)} یا کمتر برسد پیام می‌دهیم. هشدارها را در «هشدارهای من» ببینید.</p>
          <button type="button" className="btn dark" onClick={onClose}>بستن</button>
        </> : <>
          <p className="muted">{tripTitle(trip)}، قیمت فعلی {toman(trip.min_price)}</p>
          <label className="field-label">قیمت هدف (تومان)
            <input ref={first} className="input" inputMode="numeric" required value={price} onChange={(e) => setPrice(e.target.value.replace(/\D/g, ""))} /></label>
          <label className="field-label">شماره موبایل یا ایمیل
            <input className="input" required minLength={3} value={contact} onChange={(e) => setContact(e.target.value)} dir="ltr" placeholder="09123456789" /></label>
          {err && <div className="form-error">{err}</div>}
          <div className="row"><button className="btn brand grow" disabled={state === "busy" || !+price}>ثبت هشدار</button>
            <button type="button" className="btn" onClick={onClose}>انصراف</button></div>
        </>}
      </form>
    </div>
  );
}
