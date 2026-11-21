"""HR roster CSV -> one dict per employee record, values typed, nothing interpreted yet."""

import csv
from pathlib import Path

from northgate.ingest.common import clean_text, normalize_header, parse_date, parse_yes_no


def _int_or_none(value: str | None) -> int | None:
    text = clean_text(value)
    return int(text) if text else None


def parse_hr_roster(path: Path) -> list[dict]:
    rows = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        reader.fieldnames = [normalize_header(h) for h in reader.fieldnames or []]
        # Column names that carry a date ("sick_days_remaining_2026_10_01") are found by prefix,
        # so a roster exported on another date still loads.
        sick_col = next((h for h in reader.fieldnames if h.startswith("sick_days_remaining")), None)
        clinic_col = next((h for h in reader.fieldnames if h.startswith("clinic_day_used")), None)

        for line_no, raw in enumerate(reader, start=2):
            row = {k: clean_text(v) for k, v in raw.items()}
            if not row.get("employee_id"):
                continue
            rows.append(
                {
                    "employee_id": row["employee_id"],
                    "last_name": row.get("last_name"),
                    "first_name": row.get("first_name"),
                    "middle_initial": row.get("middle_initial"),
                    "job_class": row.get("job_class"),
                    "union_member": parse_yes_no(row.get("union_member")),
                    "local_member_no": row.get("local_member_no"),
                    "home_location": row.get("home_location"),
                    "department": row.get("department"),
                    "shift": (row.get("shift") or "").upper() or None,
                    "employment_type": (row.get("employment_type") or "").upper() or None,
                    "hire_date": parse_date(row.get("hire_date")),
                    "termination_date": parse_date(row.get("termination_date")),
                    "status": (row.get("status") or "").upper() or None,
                    "sick_days_remaining": _int_or_none(row.get(sick_col)) if sick_col else None,
                    "clinic_day_used": parse_yes_no(row.get(clinic_col)) if clinic_col else None,
                    "primary_language": row.get("primary_language"),
                    "source_ref": f"{path.name} line {line_no}",
                }
            )
    return rows
