// Jalali (Persian) calendar helpers built on Intl, so no hand-rolled conversion tables.
const parts = new Intl.DateTimeFormat("en-US-u-ca-persian-nu-latn", { year: "numeric", month: "numeric", day: "numeric" });
const monthName = new Intl.DateTimeFormat("fa-IR-u-ca-persian", { month: "long" });
const fullFmt = new Intl.DateTimeFormat("fa-IR-u-ca-persian", { weekday: "long", year: "numeric", month: "long", day: "numeric" });
const shortFmt = new Intl.DateTimeFormat("fa-IR-u-ca-persian", { month: "long", day: "numeric" });

export interface J { y: number; m: number; d: number }

export function toJalali(d: Date): J {
  const p = Object.fromEntries(parts.formatToParts(d).map((x) => [x.type, x.value]));
  return { y: +p.year, m: +p.month, d: +p.day };
}

export const formatFull = (d: Date) => {
  const p = Object.fromEntries(fullFmt.formatToParts(d).map((x) => [x.type, x.value]));
  return `${p.weekday}، ${p.day} ${p.month} ${p.year}`; // fixed order regardless of ICU locale data
};
export const formatShort = (d: Date) => shortFmt.format(d);
const wdFmt = new Intl.DateTimeFormat("fa-IR-u-ca-persian", { weekday: "long" });
/** "چهارشنبه ۲۲ مهر" — for inputs where the year is obvious and space is tight. */
export const formatMedium = (d: Date) => `${wdFmt.format(d)} ${shortFmt.format(d)}`;
export const jMonthName = (d: Date) => monthName.format(d) + " " + new Intl.NumberFormat("fa-IR", { useGrouping: false }).format(toJalali(d).y);

/** Gregorian Date at noon for a Jalali y/m/d (day 1..31). */
export function fromJalali(y: number, m: number, d: number): Date {
  const nowruz = new Date(y + 621, 2, 21, 12);
  const offset = m <= 6 ? (m - 1) * 31 : 186 + (m - 7) * 30;
  const g = new Date(nowruz.getTime());
  g.setDate(g.getDate() + offset + d - 1);
  // Nowruz can fall on Mar 20/21/22 — correct by scanning ±3 days.
  for (let k = -3; k <= 3; k++) {
    const t = new Date(g.getTime()); t.setDate(t.getDate() + k);
    const j = toJalali(t);
    if (j.y === y && j.m === m && j.d === d) return t;
  }
  return g;
}

export function monthGrid(y: number, m: number): (Date | null)[] {
  const first = fromJalali(y, m, 1);
  const cells: (Date | null)[] = Array((first.getDay() + 1) % 7).fill(null); // week starts Saturday
  for (let d = 1; d <= 31; d++) {
    const t = new Date(first.getTime()); t.setDate(t.getDate() + d - 1);
    const j = toJalali(t);
    if (j.m !== m) break;
    cells.push(t);
  }
  return cells;
}

export const nextMonth = ({ y, m }: { y: number; m: number }, delta: number) => {
  const i = y * 12 + (m - 1) + delta;
  return { y: Math.floor(i / 12), m: (i % 12) + 1 };
};
export const WEEKDAYS = ["ش", "ی", "د", "س", "چ", "پ", "ج"];
