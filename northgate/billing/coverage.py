"""Billable coverage: what one covered shift is worth, and whether an invoice already bills it.

Rules from docs/kpi_definitions.md and docs/backup_note_templates.md. Pure functions over rows.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from northgate.callouts.events import name_level
from northgate.callouts.rules import SHIFT_HOURS, shift_start

OVERTIME_MULTIPLIER = Decimal("1.5")
SHIFT_CODES = {"D": "day", "N": "night"}


def billable_amount(base_rate: Decimal, burden: Decimal, markup_pct: Decimal, overtime: bool) -> Decimal:
    """8 hours x base rate x (1.5 if overtime) x (1 + burden) x (1 + markup), rounded to the cent."""
    amount = (
        Decimal(SHIFT_HOURS)
        * base_rate
        * (OVERTIME_MULTIPLIER if overtime else 1)
        * (1 + burden)
        * (1 + Decimal(markup_pct) / 100)
    )
    return amount.quantize(Decimal("0.01"), ROUND_HALF_UP)


# --- matching invoice coverage lines to postings ------------------------------------------------

_REF = re.compile(r"\bref\s+(P-[\w-]+)", re.IGNORECASE)
_SHIFT = re.compile(r"\b(day|night)\b", re.IGNORECASE)


@dataclass
class LineMatch:
    posting_id: str | None
    method: str


def match_line(line: dict, building: str | None, coverage: list[dict], taken: set[str]) -> LineMatch:
    """Which posting an invoice coverage line bills.

    1. The posting reference printed on the line.
    2. Otherwise same building, service date and shift; then the replacement's name if the line
       names one; then the amount, if it equals exactly one candidate's billable amount.
    """
    text = line.get("description") or ""
    ref = _REF.search(text)
    if ref:
        return LineMatch(ref[1], "posting reference on the line")

    shift = _SHIFT.search(text)
    pool = [
        c
        for c in coverage
        if c["posting_id"] not in taken
        and c["building"] == building
        and c["shift_date"] == line.get("service_date")
        and (shift is None or c["shift"] == shift[1].lower())
    ]
    steps = ["building, date and shift"]
    named = [c for c in pool if name_level(text, c["covering_employee"]) >= 2]
    if named:
        pool, steps = named, [*steps, "replacement's name"]
    if len(pool) > 1:
        same_amount = [c for c in pool if c["billable_amount"] == line.get("amount")]
        if same_amount:
            pool, steps = same_amount, [*steps, "amount"]
    if len(pool) == 1:
        return LineMatch(pool[0]["posting_id"], " + ".join(steps))
    return LineMatch(None, f"{len(pool)} postings fit ({' + '.join(steps)})")


# --- time on site for Template A ----------------------------------------------------------------


def on_site(punches: list[dict], day: date, shift: str) -> tuple[datetime | None, datetime | None]:
    """First clock-in and last clock-out of one shift, from one employee's punches at the building.

    A clock-in counts if it is within 2 hours before to 4 hours after the shift start, a clock-out
    within 4 hours before to 3 hours after the shift end. This keeps a day shift's punches apart
    from an overtime night shift at the same building, and finds a night shift's clock-out after
    midnight.
    """
    start = shift_start(day, shift)
    end = start + timedelta(hours=SHIFT_HOURS)
    ins = [p["local_time"] for p in punches if p["event"] == "IN"
           and start - timedelta(hours=2) <= p["local_time"] <= start + timedelta(hours=4)]  # fmt: skip
    outs = [p["local_time"] for p in punches if p["event"] == "OUT"
            and end - timedelta(hours=4) <= p["local_time"] <= end + timedelta(hours=3)]  # fmt: skip
    return (min(ins) if ins else None), (max(outs) if outs else None)
