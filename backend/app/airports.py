"""Backwards-compatible view of flight cities (see cities.py)."""
from .cities import NAMES, codes
from .cities import search as _search

CODES = codes("flight")


def search(q: str):
    return [{"code": c["code"], "name": c["name"]} for c in _search(q, "flight")]
