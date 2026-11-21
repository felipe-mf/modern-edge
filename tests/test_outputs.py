"""output/decisions_log.md: the written log plus the conflicts of the run (invented data)."""

from sqlalchemy import create_engine

from northgate import db, outputs


def test_decisions_log_appends_this_runs_conflicts_by_area(tmp_path):
    engine = create_engine("sqlite://")
    db.metadata.create_all(engine)
    db.insert_rows(engine, db.exceptions, [
        {"source": "building:time_clock_site", "record_ref": "S-9", "issue": "no name match",
         "action_taken": "excluded from building figures", "confidence": "low"},
        {"source": "employee:dispatch", "record_ref": "W-1 'Ana Silva'", "issue": "number not in HR",
         "action_taken": "linked to E1", "confidence": "medium"},
        {"source": "building:dispatch_site", "record_ref": "DS-2", "issue": "inactive in source",
         "action_taken": "link used", "confidence": "high"},
    ])  # fmt: skip
    written = tmp_path / "written.md"
    written.write_text("# Decisions log\n\n**D-01.** A rule.\n", encoding="utf-8")

    listed = outputs.write_decisions_log(engine, tmp_path / "out", "2025-03", written)

    text = (tmp_path / "out" / "decisions_log.md").read_text(encoding="utf-8")
    assert listed == 3
    assert text.startswith("# Decisions log\n\n**D-01.** A rule.\n\n## Conflicts found in this run (2025-03)")
    assert "### Building (2)" in text and "### Employee (1)" in text
    assert "- `S-9`: no name match → excluded from building figures (low)" in text
    assert text.index("S-9") < text.index("DS-2")  # in the order the run logged them


def test_decisions_log_says_so_when_the_run_found_nothing(tmp_path):
    engine = create_engine("sqlite://")
    db.metadata.create_all(engine)
    written = tmp_path / "written.md"
    written.write_text("# Decisions log\n", encoding="utf-8")

    assert outputs.write_decisions_log(engine, tmp_path, "2025-03", written) == 0
    assert (tmp_path / "decisions_log.md").read_text(encoding="utf-8").endswith("None.\n")


def test_the_written_log_ships_with_the_code():
    assert outputs.DECISIONS_LOG.is_file()
