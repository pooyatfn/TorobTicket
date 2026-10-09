import { ModeIcon } from "./Icons";
import { MODE_LABEL, MODES } from "../lib/modes";
import type { Mode } from "../lib/types";

export default function ModeTabs({ mode, onChange, size = "md" }: { mode: Mode; onChange: (m: Mode) => void; size?: "md" | "lg" }) {
  return (
    <div className={`mode-tabs ${size}`} role="tablist" aria-label="نوع سفر">
      {MODES.map((m) => (
        <button key={m} type="button" role="tab" aria-selected={m === mode} className={m === mode ? "on" : ""} onClick={() => onChange(m)}>
          <ModeIcon mode={m} size={size === "lg" ? 22 : 18} /><span>{MODE_LABEL[m]}</span>
        </button>
      ))}
    </div>
  );
}
