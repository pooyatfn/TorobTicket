import { useEffect, useRef, useState } from "react";
import type { City } from "../lib/types";

export default function CityInput({ label, value, cities, onChange }:
  { label: string; value: string; cities: City[]; onChange: (code: string) => void }) {
  const current = cities.find((a) => a.code === value);
  const [text, setText] = useState(current?.name ?? "");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => setText(current?.name ?? ""), [current?.name]);
  useEffect(() => {
    const h = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) { setOpen(false); setText(current?.name ?? ""); } };
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, [current?.name]);

  const q = text.trim();
  const shown = cities.filter((a) => !q || q === current?.name || a.name.includes(q) || a.code.toLowerCase().includes(q.toLowerCase()));
  const pick = (c: City) => { onChange(c.code); setText(c.name); setOpen(false); };

  return (
    <div className="field" ref={ref}>
      <label className="field-label">{label}</label>
      <input className="input" value={text} role="combobox" aria-expanded={open} aria-label={label}
        onFocus={(e) => { setOpen(true); setActive(0); e.target.select(); }}
        onChange={(e) => { setText(e.target.value); setOpen(true); setActive(0); }}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, shown.length - 1)); }
          if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
          if (e.key === "Enter" && open && shown[active]) { e.preventDefault(); pick(shown[active]); }
          if (e.key === "Escape") setOpen(false);
        }}
        placeholder="شهر را بنویسید" />
      {open && (
        <ul className="popover list" role="listbox">
          {shown.length === 0 && <li className="muted pad">شهری با این نام پیدا نشد</li>}
          {shown.map((a, i) => (
            <li key={a.code} role="option" aria-selected={i === active}>
              <button type="button" className={i === active ? "active" : ""} onMouseEnter={() => setActive(i)} onClick={() => pick(a)}>
                {a.name} <span className="muted">{a.code}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
