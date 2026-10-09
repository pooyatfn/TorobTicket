const fa = new Intl.NumberFormat("fa-IR");
const faDigits = (s: string) => s.replace(/\d/g, (d) => "۰۱۲۳۴۵۶۷۸۹"[+d]);
export const num = (n: number) => fa.format(n);
export const toman = (n: number) => `${fa.format(n)} تومان`;
export const hhmm = (iso: string) => faDigits(iso.slice(11, 16));
export const hour = (iso: string) => +iso.slice(11, 13);
export const duration = (m: number) => `${num(Math.floor(m / 60))} ساعت${m % 60 ? ` و ${num(m % 60)} دقیقه` : ""}`;
export const iso = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
export const tomorrow = () => { const t = new Date(); t.setDate(t.getDate() + 1); return iso(t); };
/** "۶۵٫۵ میلیون" style short price for tight spaces (date strip). */
export const shortToman = (n: number) =>
  n >= 1_000_000 ? `${new Intl.NumberFormat("fa-IR", { maximumFractionDigits: 2 }).format(n / 1_000_000)} میلیون`
    : `${num(Math.round(n / 1000))} هزار`;
export const faNum = faDigits;
