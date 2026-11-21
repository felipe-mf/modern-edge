"""Writers for the files in ./output. Each writes from the database, so the files always match it."""

import csv
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
