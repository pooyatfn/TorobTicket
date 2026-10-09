import { useEffect, useRef, useState } from "react";
import { WEEKDAYS, formatFull, formatMedium, jMonthName, monthGrid, nextMonth, toJalali } from "../lib/jalali";
import { iso } from "../lib/format";

export default function DatePicker({ value, onChange, label = "تاریخ رفت", min, placeholder = "انتخاب تاریخ", onClear }: {
  value: string; onChange: (iso: string) => void; label?: string; min?: string; placeholder?: string; onClear?: () => void;
}) {
  const sel = value ? new Date(value + "T12:00:00") : null;
  const [open, setOpen] = useState(false);
  const start = sel ?? (min ? new Date(min + "T12:00:00") : new Date());
  const [view, setView] = useState(() => { const j = toJalali(start); return { y: j.y, m: j.m }; });
  const ref = useRef<HTMLDivElement>(null);
  const today = new Date(); today.setHours(12, 0, 0, 0);
  const todayIso = iso(today);
  const floor = min && min > todayIso ? min : todayIso;

  useEffect(() => {
    const h = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);
  useEffect(() => { if (open) { const j = toJalali(start); setView({ y: j.y, m: j.m }); } }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  const grid = monthGrid(view.y, view.m);
  const firstOfMonth = grid.find(Boolean) as Date;

  return (
    <div className="field datepicker" ref={ref}>
      <label className="field-label">{label}</label>
      <div className="date-input">
        <button type="button" className={"input" + (sel ? "" : " placeholder")} aria-haspopup="dialog" aria-expanded={open}
          aria-label={`${label}: ${sel ? formatFull(sel) : placeholder}`} onClick={() => setOpen(!open)}>{sel ? formatMedium(sel) : placeholder}</button>
        {sel && onClear && <button type="button" className="clear" aria-label={`حذف ${label}`} onClick={onClear}>×</button>}
      </div>
      {open && (
        <div className="popover calendar" role="dialog" aria-label={label}>
          <div className="cal-head">
            <button type="button" aria-label="ماه بعد" onClick={() => setView(nextMonth(view, 1))}>‹</button>
            <strong>{jMonthName(firstOfMonth)}</strong>
            <button type="button" aria-label="ماه قبل" onClick={() => setView(nextMonth(view, -1))}>›</button>
          </div>
          <div className="cal-grid">
            {WEEKDAYS.map((w) => <span key={w} className="cal-wd">{w}</span>)}
            {grid.map((d, i) => d ? (
              <button type="button" key={i} disabled={iso(d) < floor}
                className={"cal-day" + (iso(d) === value ? " sel" : "") + (iso(d) === todayIso ? " today" : "") +
                  (min && iso(d) === min && iso(d) !== value ? " anchor" : "")}
                onClick={() => { onChange(iso(d)); setOpen(false); }}>
                {new Intl.NumberFormat("fa-IR").format(toJalali(d).d)}
              </button>
            ) : <span key={i} />)}
          </div>
        </div>
      )}
    </div>
  );
}
