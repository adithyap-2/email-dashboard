"""Lenient parsing of the free-text dates business users type into the
engagement sheet — e.g. "20th July", "15th july", "1st Aug", "29th July".

The sheet almost never includes a year, so we resolve each date to the
occurrence closest to `today` (within a ~6-month window either side). That
keeps "20th July" anchored to the current cycle regardless of the calendar
year the dashboard runs in. Anything we can't confidently read as a date
(e.g. "Not specific", "1-2 months", "week of 6th-10th July") returns None and
is simply excluded from follow-up categorisation.
"""

from __future__ import annotations

import os
import re
from datetime import date, datetime


def reference_today() -> date:
    """The 'today' the dashboard reasons about. Defaults to the real system
    date; set DASHBOARD_TODAY=YYYY-MM-DD to pin it for deterministic demos or
    when replaying historical data through n8n."""
    override = os.environ.get("DASHBOARD_TODAY", "").strip()
    if override:
        try:
            return date.fromisoformat(override)
        except ValueError:
            pass
    return date.today()

_MONTHS = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}

# "20th July", "July 20", "20 Jul", "1st aug" — day + month in either order.
_DAY_MONTH = re.compile(
    r"\b(\d{1,2})\s*(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\b", re.IGNORECASE
)
_MONTH_DAY = re.compile(
    r"\b([A-Za-z]{3,9})\s+(\d{1,2})\s*(?:st|nd|rd|th)?\b", re.IGNORECASE
)


def parse_fuzzy_date(raw: object, today: date | None = None) -> date | None:
    """Best-effort parse of a free-text date cell. Returns None if no confident
    single date can be extracted."""
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw

    text = str(raw).strip()
    if not text:
        return None

    today = today or date.today()

    low = text.lower()
    # "week of ...", "1-2 months", "next month" etc. are horizon estimates,
    # not a specific due date — skip them.
    if "week" in low or "month" in low:
        return None
    # Ranges like "6th-10th July" or "6-10 July" are ambiguous windows — skip.
    if re.search(r"\d\s*(?:st|nd|rd|th)?\s*[-–]\s*\d", text):
        return None

    day = month = None
    m = _DAY_MONTH.search(text)
    if m and m.group(2).lower() in _MONTHS:
        day, month = int(m.group(1)), _MONTHS[m.group(2).lower()]
    else:
        m = _MONTH_DAY.search(text)
        if m and m.group(1).lower() in _MONTHS:
            month, day = _MONTHS[m.group(1).lower()], int(m.group(2))

    if not day or not month or not (1 <= day <= 31):
        return None

    # No year in the source — pick the occurrence nearest to today.
    best: date | None = None
    for year in (today.year - 1, today.year, today.year + 1):
        try:
            cand = date(year, month, day)
        except ValueError:
            continue
        if best is None or abs((cand - today).days) < abs((best - today).days):
            best = cand
    return best