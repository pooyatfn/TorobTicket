import { describe, expect, it } from "vitest";
import { applyFilters, emptyFilters, type FilterState } from "../components/Filters";
import { duration, hhmm, shortToman, toman } from "../lib/format";
import { queryFromParams, searchUrl } from "../lib/query";
import type { Trip } from "../lib/types";

const t = (id: string, airline: string, dep: string, offers: [string, number, boolean?, boolean?, string?][], extra: Partial<Trip> = {}): Trip => ({
  id, mode: "flight", airline, airline_code: "XX", flight_number: id, origin: "THR", destination: "MHD",
  departure: `2026-10-20T${dep}:00`, arrival: `2026-10-20T${dep}:00`, aircraft: null, seats_left: null, features: [],
  origin_terminal: null, destination_terminal: null, stops: [], logo: null, rating: null, duration_min: 90,
  offers: offers.map(([seller, price, refundable, available, fare]) => ({ seller, price, url: "#", fare_class: fare ?? "اکونومی",
    baggage_kg: null, refundable: !!refundable, available: available ?? true })),
  min_price: Math.min(...offers.map((o) => o[1])), seller_count: offers.length, available: offers.some((o) => o[3] ?? true), ...extra,
});
const trips = [
  t("1", "ماهان", "07:00", [["A", 1_000_000], ["B", 1_200_000, true]], { features: ["VIP"] }),
  t("2", "آسمان", "13:30", [["A", 2_000_000, false, true, "بیزینس"]]),
  t("3", "ماهان", "22:15", [["B", 1_500_000, true]], { origin_terminal: "پایانه جنوب" }),
  t("4", "زاگرس", "09:00", [["A", 900_000, true, false]]),
];
const ids = (f: Partial<FilterState>) => applyFilters(trips, { ...emptyFilters(), ...f }).map((x) => x.id);

describe("applyFilters", () => {
  it("hides sold-out trips by default", () => expect(ids({})).toEqual(["1", "2", "3"]));
  it("shows them when 'only available' is off", () => expect(ids({ availableOnly: false })).toEqual(["1", "2", "3", "4"]));
  it("filters by carrier", () => expect(ids({ carriers: new Set(["ماهان"]) })).toEqual(["1", "3"]));
  it("filters by departure slot", () => expect(ids({ times: new Set(["morning", "evening"]) })).toEqual(["1", "3"]));
  it("price range applies to remaining offers", () => {
    expect(ids({ priceMax: 1_100_000 })).toEqual(["1"]);
    expect(ids({ priceMin: 1_400_000 })).toEqual(["2", "3"]);
    expect(ids({ priceMax: 1_100_000, sellers: new Set(["B"]) })).toEqual([]);
  });
  it("seller, class, feature, terminal and refundable filters", () => {
    expect(ids({ sellers: new Set(["B"]) })).toEqual(["1", "3"]);
    expect(ids({ classes: new Set(["بیزینس"]) })).toEqual(["2"]);
    expect(ids({ features: new Set(["VIP"]) })).toEqual(["1"]);
    expect(ids({ terminals: new Set(["پایانه جنوب"]) })).toEqual(["3"]);
    expect(ids({ refundable: true })).toEqual(["1", "3"]);
  });
});

describe("format", () => {
  it("formats Persian numbers, times and durations", () => {
    expect(toman(1_250_000)).toBe("۱٬۲۵۰٬۰۰۰ تومان");
    expect(hhmm("2026-10-20T07:05:00")).toBe("۰۷:۰۵");
    expect(duration(125)).toBe("۲ ساعت و ۵ دقیقه");
    expect(shortToman(6_550_000)).toBe("۶٫۵۵ میلیون");
    expect(shortToman(760_000)).toBe("۷۶۰ هزار");
  });
});

describe("query URLs", () => {
  it("round-trips through the URL and rejects unknown modes", () => {
    const q = queryFromParams(new URLSearchParams("mode=train&origin=THR&destination=MHD&date=2026-10-20&adults=2"));
    expect(q).toEqual({ mode: "train", origin: "THR", destination: "MHD", date: "2026-10-20", adults: 2, children: 0, infants: 0 });
    expect(queryFromParams(new URLSearchParams(searchUrl(q).split("?")[1]))).toEqual(q);
    expect(queryFromParams(new URLSearchParams("mode=boat")).mode).toBe("flight");
  });
});

import { legQueries, queryString, withLegDate } from "../lib/query";

describe("round trip", () => {
  const base = "mode=bus&origin=THR&destination=MHD&date=2026-10-20&adults=1";
  it("parses return= and ignores a return before departure", () => {
    expect(queryFromParams(new URLSearchParams(base + "&return=2026-10-25")).ret).toBe("2026-10-25");
    expect(queryFromParams(new URLSearchParams(base + "&return=2026-10-19")).ret).toBeUndefined();
    expect(queryFromParams(new URLSearchParams(base + "&return=garbage")).ret).toBeUndefined();
  });
  it("splits into an outbound and a reversed return leg", () => {
    const q = queryFromParams(new URLSearchParams(base + "&return=2026-10-25"));
    const [out, back] = legQueries(q);
    expect(out).toMatchObject({ origin: "THR", destination: "MHD", date: "2026-10-20" });
    expect(back).toMatchObject({ origin: "MHD", destination: "THR", date: "2026-10-25", mode: "bus" });
    expect(out.ret).toBeUndefined();
    expect(back.ret).toBeUndefined();
    expect(legQueries({ ...q, ret: undefined })).toHaveLength(1);
  });
  it("keeps the return on or after departure when a leg's date changes", () => {
    const q = queryFromParams(new URLSearchParams(base + "&return=2026-10-22"));
    expect(withLegDate(q, 0, "2026-10-24")).toMatchObject({ date: "2026-10-24", ret: "2026-10-24" });
    expect(withLegDate(q, 0, "2026-10-21")).toMatchObject({ date: "2026-10-21", ret: "2026-10-22" });
    expect(withLegDate(q, 1, "2026-10-18")).toMatchObject({ date: "2026-10-20", ret: "2026-10-20" });
  });
  it("puts the return date in the URL as return=", () => {
    const q = queryFromParams(new URLSearchParams(base + "&return=2026-10-25"));
    expect(queryString(q)).toContain("return=2026-10-25");
    expect(queryString(q)).not.toContain("ret=");
  });
});
