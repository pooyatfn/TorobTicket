import type { Alert, CalendarDay, City, Mode, Popular, PricePoint, Query, SearchResponse, Trip } from "./types";

export class ApiError extends Error { constructor(msg: string, public status: number) { super(msg); } }

async function j<T>(r: Response): Promise<T> {
  if (!r.ok) {
    let msg = `خطا (${r.status})`;
    try {
      const b = await r.json();
      if (typeof b.detail === "string") msg = b.detail;
      else if (Array.isArray(b.detail) && b.detail[0]?.msg) msg = String(b.detail[0].msg).replace(/^Value error, /, "");
    } catch { /* ignore */ }
    throw new ApiError(msg, r.status);
  }
  return r.status === 204 ? (undefined as T) : r.json();
}
const qs = (o: Record<string, string | number>) => new URLSearchParams(Object.entries(o).map(([k, v]) => [k, String(v)])).toString();

export const getCities = (mode: Mode) => fetch(`/api/cities?mode=${mode}`).then(j<City[]>);
export const getPopular = (mode: Mode) => fetch(`/api/popular?mode=${mode}`).then(j<Popular[]>);
const searchQs = ({ ret: _ret, ...q }: Query) => qs({ ...q });
export const search = (q: Query) => fetch("/api/search?" + searchQs(q)).then(j<SearchResponse>);

// Finished searches are kept for a minute, so going back to a results page is instant.
const MEMO_MS = 60_000;
const memo = new Map<string, { at: number; data: SearchResponse }>();
const remember = (key: string, data: SearchResponse) => {
  memo.set(key, { at: Date.now(), data });
  if (memo.size > 30) memo.delete(memo.keys().next().value!);
};

/**
 * Search and get the results as each seller answers: `onData` is called with the merged list
 * after every seller (the last call has `done: true`). Uses server-sent events and falls back to
 * one plain request. Returns a function that stops listening.
 */
export function searchLive(q: Query, onData: (r: SearchResponse) => void, onError: (e: Error) => void): () => void {
  const key = searchQs(q);
  const hit = memo.get(key);
  let stopped = false;
  if (hit && Date.now() - hit.at < MEMO_MS) {
    queueMicrotask(() => !stopped && onData(hit.data));
    return () => { stopped = true; };
  }
  const plain = () => search(q).then((r) => { remember(key, r); if (!stopped) onData(r); })
    .catch((e) => !stopped && onError(e as Error));
  if (typeof EventSource === "undefined") { plain(); return () => { stopped = true; }; }

  const es = new EventSource("/api/search/stream?" + key);
  es.onmessage = (ev) => {
    if (stopped) return;
    const r = JSON.parse(ev.data) as SearchResponse;
    if (r.done !== false) { es.close(); remember(key, r); }
    onData(r);
  };
  // A validation error (422) or a dropped connection: ask once more without streaming, which also
  // returns the error message. The server finished or cached the work, so this is quick.
  es.onerror = () => { es.close(); if (!stopped) plain(); };
  return () => { stopped = true; es.close(); };
}
export const getCalendar = (q: Pick<Query, "mode" | "origin" | "destination" | "date">) =>
  fetch("/api/calendar?" + qs({ ...q, span: 3 })).then(j<{ days: CalendarDay[] }>);
export const getTrip = (id: string) => fetch(`/api/trips/${id}`).then(j<{ trip: Trip; query: Query }>);
export const getHistory = (id: string) => fetch(`/api/trips/${id}/history`).then(j<PricePoint[]>);
export const createAlert = (a: Omit<Alert, "id" | "created" | "triggered_at" | "notified_at" | "last_price" | "flight_id"> & { flight_id?: string }) =>
  fetch("/api/alerts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(a) }).then(j<Alert>);
export const listAlerts = (contact: string) => fetch("/api/alerts?" + qs({ contact })).then(j<Alert[]>);
export const deleteAlert = (id: number) => fetch(`/api/alerts/${id}`, { method: "DELETE" }).then(j<void>);
