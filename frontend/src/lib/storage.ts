import type { Query, Trip } from "./types";

// Per-browser conveniences only; every read/write is guarded (private mode, blocked storage).
function read<T>(key: string, fallback: T): T {
  try { const v = localStorage.getItem(key); return v ? (JSON.parse(v) as T) : fallback; } catch { return fallback; }
}
function write(key: string, v: unknown) { try { localStorage.setItem(key, JSON.stringify(v)); } catch { /* ignore */ } }

export interface SavedTrip { trip: Trip; query: Query; saved: string }
const FAV = "tt.favorites", RECENT = "tt.recent", CONTACT = "tt.contact";

export const favorites = {
  all: () => read<SavedTrip[]>(FAV, []),
  has: (id: string) => read<SavedTrip[]>(FAV, []).some((f) => f.trip.id === id),
  toggle(trip: Trip, query: Query): boolean {
    const all = read<SavedTrip[]>(FAV, []);
    const i = all.findIndex((f) => f.trip.id === trip.id);
    if (i >= 0) { all.splice(i, 1); write(FAV, all); return false; }
    write(FAV, [{ trip, query, saved: new Date().toISOString() }, ...all].slice(0, 100));
    return true;
  },
  remove(id: string) { write(FAV, read<SavedTrip[]>(FAV, []).filter((f) => f.trip.id !== id)); },
};

export const recentSearches = {
  all: () => read<Query[]>(RECENT, []),
  add(q: Query) {
    const same = (a: Query) => a.mode === q.mode && a.origin === q.origin && a.destination === q.destination;
    write(RECENT, [q, ...read<Query[]>(RECENT, []).filter((a) => !same(a))].slice(0, 8));
  },
  clear() { write(RECENT, []); },
};

export const savedContact = { get: () => read<string>(CONTACT, ""), set: (c: string) => write(CONTACT, c) };
