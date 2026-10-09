"""Cities/terminals per travel mode.

Codes are IATA-style city codes shared by all modes. `bus` is Alibaba's bus city code (looked up live
from ws.alibaba.ir/api/v1/bus/stations, 2026-10); `train` marks cities Alibaba's train search accepts.
"""
from __future__ import annotations

# code, Persian name, English name, has airport, has train, Alibaba bus city code
CITIES = [
    ("THR", "تهران", "Tehran", True, True, "11320000"),
    ("MHD", "مشهد", "Mashhad", True, True, "31310000"),
    ("SYZ", "شیراز", "Shiraz", True, True, "41310000"),
    ("IFN", "اصفهان", "Isfahan", True, True, "21310000"),
    ("TBZ", "تبریز", "Tabriz", True, True, "26310000"),
    ("AWZ", "اهواز", "Ahvaz", True, True, "36310000"),
    ("KIH", "کیش", "Kish", True, False, "64334000"),
    ("GSM", "قشم", "Qeshm", True, False, "64370000"),
    ("BND", "بندرعباس", "Bandar Abbas", True, True, "64310000"),
    ("RAS", "رشت", "Rasht", True, False, "54310000"),
    ("KER", "کرمان", "Kerman", True, True, "45310000"),
    ("ZAH", "زاهدان", "Zahedan", True, True, "61310000"),
    ("ADU", "اردبیل", "Ardabil", True, True, "91310000"),
    ("OMH", "ارومیه", "Urmia", True, True, "57310000"),
    ("KSH", "کرمانشاه", "Kermanshah", True, False, "71310000"),
    ("BUZ", "بوشهر", "Bushehr", True, False, "95310000"),
    ("SRY", "ساری", "Sari", True, True, "16310000"),
    ("AZD", "یزد", "Yazd", True, False, "93310000"),
    ("HDM", "همدان", "Hamedan", True, False, "75310000"),
]

NAMES = {c[0]: c[1] for c in CITIES}
BUS_CODES = {c[0]: c[5] for c in CITIES if c[5]}
_MODE_CODES = {
    "flight": {c[0] for c in CITIES if c[3]},
    "train": {c[0] for c in CITIES if c[4]},
    "bus": set(BUS_CODES),
}

# Shown on the home page per mode.
POPULAR = {
    "flight": [("THR", "MHD"), ("THR", "KIH"), ("THR", "SYZ"), ("MHD", "THR"), ("THR", "IFN"), ("THR", "BND")],
    "train": [("THR", "MHD"), ("THR", "SYZ"), ("THR", "IFN"), ("THR", "TBZ"), ("MHD", "THR"), ("THR", "SRY")],
    "bus": [("THR", "MHD"), ("THR", "IFN"), ("THR", "SYZ"), ("THR", "TBZ"), ("THR", "RAS"), ("IFN", "SYZ")],
}


def codes(mode: str = "flight") -> set[str]:
    return _MODE_CODES.get(mode, set())


def search(q: str = "", mode: str = "flight") -> list[dict]:
    q = (q or "").strip().lower()
    allowed = codes(mode)
    return [{"code": c, "name": n, "modes": [m for m in ("flight", "train", "bus") if c in _MODE_CODES[m]]}
            for c, n, en, *_ in CITIES
            if c in allowed and (not q or q in c.lower() or q in n or q in en.lower())]
