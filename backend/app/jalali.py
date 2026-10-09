"""Gregorian -> Jalali (Persian) date conversion (arithmetic algorithm, valid for 1900–2100)."""
from __future__ import annotations

from datetime import date

_G_DAYS = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]


def to_jalali(d: date) -> tuple[int, int, int]:
    gy2 = d.year + 1 if d.month > 2 else d.year
    days = (355666 + 365 * d.year + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400
            + d.day + _G_DAYS[d.month - 1])
    jy = -1595 + 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        return jy, 1 + days // 31, 1 + days % 31
    return jy, 7 + (days - 186) // 30, 1 + (days - 186) % 30


def jalali_str(d: date) -> str:
    y, m, dd = to_jalali(d)
    return f"{y:04d}-{m:02d}-{dd:02d}"
