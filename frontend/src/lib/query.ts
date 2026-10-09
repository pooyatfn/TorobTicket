import { tomorrow } from "./format";
import type { Mode, Query } from "./types";

const ISO = /^\d{4}-\d{2}-\d{2}$/;

export function queryFromParams(p: URLSearchParams, fallbackMode: Mode = "flight"): Query {
  const mode = (["flight", "train", "bus"].includes(p.get("mode") ?? "") ? p.get("mode") : fallbackMode) as Mode;
  const date = p.get("date") ?? tomorrow();
  const ret = p.get("return") ?? "";
  const q: Query = {
    mode, origin: p.get("origin") ?? "THR", destination: p.get("destination") ?? "MHD", date,
    adults: Math.max(1, +(p.get("adults") ?? 1) || 1), children: Math.max(0, +(p.get("children") ?? 0) || 0),
    infants: Math.max(0, +(p.get("infants") ?? 0) || 0),
  };
  if (ISO.test(ret) && ret >= date) q.ret = ret; // a return before departure is ignored
  return q;
}

/** URL query string; the return date travels as `return=`. */
export function queryString(q: Query): string {
  const { ret, ...rest } = q;
  const p = new URLSearchParams(Object.entries(rest).map(([k, v]) => [k, String(v)]));
  if (ret) p.set("return", ret);
  return p.toString();
}
export const searchUrl = (q: Query) => "/search?" + queryString(q);
export const tripUrl = (id: string, q: Query) => `/trip/${id}?` + queryString(oneWay(q));

export const oneWay = (q: Query): Query => { const { ret: _ret, ...rest } = q; return rest; };

/** Round trip = two one-way searches: [outbound, return (reversed route on the return date)]. */
export function legQueries(q: Query): Query[] {
  const out = oneWay(q);
  if (!q.ret) return [out];
  return [out, { ...out, origin: q.destination, destination: q.origin, date: q.ret }];
}

/** Change one leg's date, keeping the round trip valid (return never before departure). */
export function withLegDate(q: Query, leg: number, date: string): Query {
  if (leg === 0) return { ...q, date, ...(q.ret && q.ret < date ? { ret: date } : {}) };
  return { ...q, ret: date < q.date ? q.date : date };
}
