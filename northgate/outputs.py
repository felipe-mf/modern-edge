"""Writers for the files in ./output. Each writes from the database, so the files always match it."""

import csv
from datetime import date
from pathlib import Path

from sqlalchemy import Engine, select

from northgate import db

EXCEPTION_COLUMNS = ["source", "record_ref", "issue", "action_taken", "confidence"]

# The written log: the rules for every kind of conflict, with what they met in the provided dataset.
DECISIONS_LOG = Path(__file__).resolve().parents[1] / "docs" / "decisions_log.md"


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


def write_decisions_log(engine: Engine, output_dir: Path, period: str, written: Path = DECISIONS_LOG) -> int:
    """output/decisions_log.md: the written log, then the conflicts this run actually met.

    The written part explains each rule and cites the provided dataset as evidence. The appended part
    comes from the exceptions table, grouped by area, so on any dataset the log lists every conflict
    the run resolved or flagged and what it did. Returns how many it listed.
    """
    rows = sorted(db.fetch(engine, db.exceptions), key=lambda r: r["id"])
    by_area: dict[str, list[dict]] = {}
    for r in rows:
        by_area.setdefault(r["source"].split(":")[0], []).append(r)

    lines = [
        written.read_text(encoding="utf-8").rstrip(),
        "",
        f"## Conflicts found in this run ({period})",
        "",
        (
            f"Written by the pipeline from `exceptions.csv`: {len(rows)} records it could not resolve or "
            "chose to flag, each with what it did and how sure it is."
        ),
    ]
    for area, items in by_area.items():
        lines += ["", f"### {area.replace('_', ' ').capitalize()} ({len(items)})", ""]
        lines += [
            f"- `{r['record_ref']}`: {r['issue']} → {r['action_taken']} ({r['confidence']})" for r in items
        ]
    if not rows:
        lines += ["", "None."]

    path = output_dir / "decisions_log.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(rows)
