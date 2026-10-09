from __future__ import annotations

import logging

from .airports import CODES

log = logging.getLogger("torobticket")
DEFAULT = "THR-MHD,THR-SYZ,THR-IFN,THR-KIH,MHD-THR"


def parse_watchlist(text: str) -> list[tuple[str, str]]:
    """'THR-MHD, thr-syz' -> [('THR','MHD'), ('THR','SYZ')]; invalid or duplicate entries are skipped."""
    out: list[tuple[str, str]] = []
    for item in (text or "").split(","):
        item = item.strip().upper()
        if not item:
            continue
        parts = item.split("-")
        if len(parts) != 2 or parts[0] == parts[1] or not set(parts) <= CODES:
            log.warning("ignoring invalid watchlist entry %r", item)
            continue
        if (parts[0], parts[1]) not in out:
            out.append((parts[0], parts[1]))
    return out
