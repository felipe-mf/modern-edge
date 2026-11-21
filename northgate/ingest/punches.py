"""Time clock exports -> one common punch schema.

The clock vendor changed the export layout mid-month (new column names, event names and an ISO
timestamp with UTC offset). Layouts are recognised by their header, not by file name, and both
are mapped to the same columns:

    badge_no, employee_name, site_raw, event (IN / OUT / MEAL_START / MEAL_END),
    local_time (wall-clock time at the building, no zone), utc_offset_min, device

The clock records the building's wall-clock time, so local_time is kept exactly as written. The
offset, when the file has one, is kept separately so it can be cross-checked later.
"""

import csv
from datetime import datetime
from pathlib import Path

from northgate.ingest.common import clean_text, normalize_header

# canonical column -> header names seen in the exports (normalised)
COLUMN_ALIASES = {
    "badge_no": ("badge_no", "empbadge", "badge"),
    "employee_name": ("employee_name", "name"),
    "site_raw": ("site", "sitecode", "site_code"),
    "event": ("punch_type", "event"),
    "time": ("punch_time", "timestamp"),
    "device": ("device_id", "terminal"),
}

EVENT_ALIASES = {
    "IN": "IN",
    "CLOCK_IN": "IN",
    "OUT": "OUT",
    "CLOCK_OUT": "OUT",
    "MEAL_START": "MEAL_START",
    "BREAK_OUT": "MEAL_START",  # old layout: leaving for the meal break
    "MEAL_END": "MEAL_END",
    "BREAK_IN": "MEAL_END",  # old layout: back from the meal break
}

LOCAL_TIME_FORMATS = ("%m/%d/%Y %H:%M", "%m/%d/%Y %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S")


def is_punch_file(header: list[str]) -> bool:
    names = {normalize_header(h) for h in header}
    return all(any(alias in names for alias in aliases) for aliases in COLUMN_ALIASES.values())


def is_site_code_file(header: list[str]) -> bool:
    names = {normalize_header(h) for h in header}
    return {"sitecode", "sitename"} <= names


def parse_punch_time(text: str) -> tuple[datetime, int | None]:
    """Return (local wall-clock time, UTC offset in minutes or None)."""
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        stamp = None
    if stamp is not None:
        offset = stamp.utcoffset()
        return stamp.replace(tzinfo=None), (int(offset.total_seconds() // 60) if offset is not None else None)
    for fmt in LOCAL_TIME_FORMATS:
        try:
            return datetime.strptime(text, fmt), None
        except ValueError:
            continue
    raise ValueError(f"Unrecognised punch time: {text!r}")


def parse_punches(path: Path) -> tuple[list[dict], list[str]]:
    """Returns (punches, issues). Rows that cannot be read become issues, not crashes."""
    rows, issues = [], []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle)
        header = [normalize_header(h) for h in next(reader)]
        column = {
            canonical: next(header.index(a) for a in aliases if a in header)
            for canonical, aliases in COLUMN_ALIASES.items()
        }
        for line_no, values in enumerate(reader, start=2):
            if not any(v.strip() for v in values):
                continue
            ref = f"{path.name} line {line_no}"
            raw_event = (clean_text(values[column["event"]]) or "").upper()
            event = EVENT_ALIASES.get(raw_event)
            try:
                local_time, offset = parse_punch_time(clean_text(values[column["time"]]) or "")
            except ValueError as exc:
                issues.append(f"{ref}: {exc}")
                continue
            if event is None:
                issues.append(f"{ref}: unknown punch event {raw_event!r}")
                continue
            rows.append(
                {
                    "badge_no": clean_text(values[column["badge_no"]]),
                    "employee_name": clean_text(values[column["employee_name"]]),
                    "site_raw": clean_text(values[column["site_raw"]]),
                    "event": event,
                    "local_time": local_time,
                    "utc_offset_min": offset,
                    "device": clean_text(values[column["device"]]),
                    "source_ref": ref,
                }
            )
    return rows, issues


def parse_site_codes(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        reader.fieldnames = [normalize_header(h) for h in reader.fieldnames or []]
        return [
            {
                "site_code": clean_text(r.get("sitecode")),
                "site_name": clean_text(r.get("sitename")),
                "status": (clean_text(r.get("status")) or "").upper() or None,
                "source_ref": f"{path.name} line {n}",
            }
            for n, r in enumerate(reader, start=2)
            if clean_text(r.get("sitecode"))
        ]


def read_header(path: Path) -> list[str]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return next(csv.reader(handle), [])
