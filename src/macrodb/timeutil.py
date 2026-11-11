from __future__ import annotations

import calendar
import re
from datetime import date, datetime

_Q = re.compile(r"^(\d{4})-?Q([1-4])$")
_W = re.compile(r"^(\d{4})-?W(\d{2})$")


def parse_obs_date(s: str | None) -> date | None:
    """Parse the date representations used by the supported providers into the period START date.
    Accepts YYYY-MM-DD, YYYY-MM, YYYY, YYYY-Qn, YYYY-Wnn, YYYYMMDD. Returns None if unparseable."""
    if s is None:
        return None
    s = s.strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            return date.fromisoformat(s)
        if re.fullmatch(r"\d{8}", s):
            return datetime.strptime(s, "%Y%m%d").date()
        if re.fullmatch(r"\d{4}-\d{2}", s):
            return date(int(s[:4]), int(s[5:7]), 1)
        if re.fullmatch(r"\d{4}", s):
            return date(int(s), 1, 1)
        m = _Q.match(s)
        if m:
            return date(int(m[1]), 3 * (int(m[2]) - 1) + 1, 1)
        m = _W.match(s)
        if m:
            return date.fromisocalendar(int(m[1]), int(m[2]), 1)
    except ValueError:
        return None
    return None


def period_end(d: date, freq: str) -> date:
    """Last calendar day of the period that starts at/contains `d` for the frequency."""
    if freq == "D":
        return d
    if freq == "W":
        return d
    if freq == "M":
        return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])
    if freq == "Q":
        m = 3 * ((d.month - 1) // 3) + 3
        return date(d.year, m, calendar.monthrange(d.year, m)[1])
    if freq == "A":
        return date(d.year, 12, 31)
    raise ValueError(freq)


def period_start(d: date, freq: str) -> date:
    if freq in ("D", "W"):
        return d
    if freq == "M":
        return date(d.year, d.month, 1)
    if freq == "Q":
        return date(d.year, 3 * ((d.month - 1) // 3) + 1, 1)
    if freq == "A":
        return date(d.year, 1, 1)
    raise ValueError(freq)


def is_aligned(d: date, freq: str) -> bool:
    """Does `d` sit at the start or end of a period of this frequency? (D/W always True.)"""
    if freq in ("D", "W"):
        return True
    return d == period_start(d, freq) or d == period_end(d, freq)
