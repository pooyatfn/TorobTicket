import { afterEach, describe, expect, it, vi } from "vitest";
import type { Query, SearchResponse } from "../lib/types";

class FakeES {
  static last: FakeES | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;
  constructor(public url: string) { FakeES.last = this; }
  close() { this.closed = true; }
  emit(r: Partial<SearchResponse>) { this.onmessage?.({ data: JSON.stringify(r) }); }
}

const q = (date: string): Query => ({ mode: "flight", origin: "THR", destination: "MHD", date, adults: 1, children: 0, infants: 0 });
const resp = (n: number, done: boolean, pending: string[] = []) =>
  ({ query: q("2030-01-01"), flights: Array(n).fill({}), providers: {}, done, pending }) as unknown as SearchResponse;

async function load() {
  vi.resetModules();
  vi.stubGlobal("EventSource", FakeES);
  return import("../lib/api");
}
afterEach(() => { vi.unstubAllGlobals(); FakeES.last = null; });

describe("searchLive", () => {
  it("passes on every streamed update and closes after the last one", async () => {
    const { searchLive } = await load();
    const got: SearchResponse[] = [];
    searchLive(q("2030-01-01"), (r) => got.push(r), () => {});
    const es = FakeES.last!;
    expect(es.url).toContain("/api/search/stream?");
    expect(es.url).not.toContain("ret=");
    es.emit(resp(2, false, ["slow"]));
    es.emit(resp(5, true));
    expect(got.map((r) => r.flights.length)).toEqual([2, 5]);
    expect(es.closed).toBe(true);
  });

  it("answers a repeated search from memory", async () => {
    const { searchLive } = await load();
    searchLive(q("2030-01-02"), () => {}, () => {});
    FakeES.last!.emit(resp(3, true));
    FakeES.last = null;
    const got = await new Promise<SearchResponse>((ok) => searchLive(q("2030-01-02"), ok, () => {}));
    expect(got.flights.length).toBe(3);
    expect(FakeES.last).toBeNull(); // no new request
  });

  it("falls back to a plain request and reports its error", async () => {
    const { searchLive } = await load();
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: "تاریخ گذشته است" }), { status: 422 })));
    const err = await new Promise<Error>((ok) => { searchLive(q("2030-01-03"), () => {}, ok); FakeES.last!.onerror!(); });
    expect(err.message).toBe("تاریخ گذشته است");
  });

  it("stops listening when cancelled", async () => {
    const { searchLive } = await load();
    const got: SearchResponse[] = [];
    const stop = searchLive(q("2030-01-04"), (r) => got.push(r), () => {});
    stop();
    FakeES.last!.emit(resp(1, true));
    expect(got).toEqual([]);
    expect(FakeES.last!.closed).toBe(true);
  });
});
