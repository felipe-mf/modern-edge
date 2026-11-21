"""Operations labor budget spreadsheet.

Loaded for reference and cross-checks only: the data guide says nobody has maintained it since
the administrator left, so it is never a source of truth for headcount or rates.
"""

from pathlib import Path

import openpyxl

from northgate.ingest.common import clean_text, normalize_header, parse_amount

REQUIRED_COLUMNS = {"building", "employee"}


def parse_labor_budget(path: Path) -> list[dict]:
    rows = []
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    for sheet in workbook.worksheets:
        header = None
        for row_no, values in enumerate(sheet.iter_rows(values_only=True), start=1):
            if header is None:
                names = [normalize_header(v) for v in values]
                if REQUIRED_COLUMNS <= set(names):
                    header = names
                continue
            row = dict(zip(header, values))
            if not clean_text(row.get("employee")):
                continue
            rows.append(
                {
                    "building": clean_text(row.get("building")),
                    "position": clean_text(row.get("position")),
                    "employee_name": clean_text(row.get("employee")),
                    "shift": clean_text(row.get("shift")),
                    "status": clean_text(row.get("status")),
                    "weekly_hours": parse_amount(row.get("wkly_hrs")),
                    "rate": parse_amount(row.get("rate")),
                    "source_ref": f"{path.name} [{sheet.title}] row {row_no}",
                }
            )
    workbook.close()
    return rows
