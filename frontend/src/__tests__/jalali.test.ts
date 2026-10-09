import { describe, expect, it } from "vitest";
import { formatFull, fromJalali, monthGrid, nextMonth, toJalali } from "../lib/jalali";

const g = (y: number, m: number, d: number) => new Date(y, m - 1, d, 12);

describe("jalali", () => {
  it("converts known dates", () => {
    expect(toJalali(g(2026, 10, 8))).toEqual({ y: 1405, m: 7, d: 16 });
    expect(toJalali(g(2026, 3, 21))).toEqual({ y: 1405, m: 1, d: 1 }); // Nowruz 1405
    expect(toJalali(g(2025, 3, 21))).toEqual({ y: 1404, m: 1, d: 1 });
    expect(toJalali(g(2025, 3, 20))).toEqual({ y: 1403, m: 12, d: 30 }); // 1403 is a leap year
  });

  it("round-trips every day of two years", () => {
    for (let t = g(2025, 1, 1).getTime(); t < g(2027, 1, 1).getTime(); t += 86_400_000) {
      const d = new Date(t);
      const j = toJalali(d);
      const back = fromJalali(j.y, j.m, j.d);
      expect(`${back.getFullYear()}-${back.getMonth()}-${back.getDate()}`).toBe(`${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`);
    }
  });

  it("builds month grids with Saturday-first padding", () => {
    const count = (y: number, m: number) => monthGrid(y, m).filter(Boolean).length;
    expect([count(1405, 1), count(1405, 6), count(1405, 7), count(1405, 11)]).toEqual([31, 31, 30, 30]);
    expect([count(1404, 12), count(1403, 12)]).toEqual([29, 30]);
    // 1 Mehr 1405 = Wed 23 Sep 2026 -> Saturday-first index 4
    expect(monthGrid(1405, 7).findIndex(Boolean)).toBe(4);
  });

  it("navigates months across year boundaries", () => {
    expect(nextMonth({ y: 1405, m: 12 }, 1)).toEqual({ y: 1406, m: 1 });
    expect(nextMonth({ y: 1405, m: 1 }, -1)).toEqual({ y: 1404, m: 12 });
  });

  it("formats with a fixed word order", () => {
    expect(formatFull(g(2026, 10, 9))).toBe("جمعه، ۱۷ مهر ۱۴۰۵");
  });
});
