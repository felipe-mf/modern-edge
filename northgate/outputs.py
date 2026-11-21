"""Writers for the files in ./output. Each writes from the database, so the files always match it."""

import csv
from datetime import date
from pathlib import Path

from sqlalchemy import Engine, select

from northgate import db

EXCEPTION_COLUMNS = ["source", "record_ref", "issue", "action_taken", "confidence"]


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_exceptions(engine: Engine, output_dir: Path) -> int:
    with engine.connect() as conn:
        rows = [dict(r._mapping) for r in conn.execute(select(db.exceptions).order_by(db.exceptions.c.id))]
    write_csv(output_dir / "exceptions.csv", EXCEPTION_COLUMNS, rows)
    return len(rows)


PAYROLL_COLUMNS = [
    "source", "source_ref", "employee_id", "date", "code", "decision", "submission_id", "final_status", "reason",
]  # fmt: skip


def write_payroll_submissions(engine: Engine, output_dir: Path) -> int:
    """One row per absence decided on (written or held). Duplicates and non-absences are not
    absences; they are listed in exceptions.csv instead."""
    rows = []
    for e in sorted(
        db.fetch(engine, db.callout_events), key=lambda e: (e["absence_date"] or date.max, e["id"])
    ):
        if e["outcome"] not in ("absence", "unreadable"):
            continue
        held = e["decision"] != "written"
        reason = "; ".join(r for r in (e["code_reason"], e["hold_reason"] if held else None) if r)
        rows.append({
            "source": e["source"],
            "source_ref": e["source_ref"],
            "employee_id": e["payroll_id"],
            "date": e["absence_date"],
            "code": e["code"],
            "decision": e["decision"],
            "submission_id": e["submission_id"],
            "final_status": None if held else e["final_status"],
            "reason": reason,
        })  # fmt: skip
    write_csv(output_dir / "payroll_submissions.csv", PAYROLL_COLUMNS, rows)
    return len(rows)
