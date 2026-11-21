"""API views and review actions on a tiny in-memory database (invented data)."""

from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine

from northgate import db
from northgate.api import review, views
from northgate.callouts.run import REVIEW

DAY = date(2025, 3, 5)  # a Wednesday


@pytest.fixture
def engine():
    engine = create_engine("sqlite://")
    db.metadata.create_all(engine)

    def ins(table, *rows):
        """Fill required text columns the test does not care about (source_ref, method...)."""
        required = [
            c.name for c in table.columns if not c.nullable and not c.primary_key and c.server_default is None
        ]
        db.insert_rows(engine, table, [{**{c: "test" for c in required}, **row} for row in rows])

    ins(db.run_info, {"period": "2025-03", "period_start": date(2025, 3, 1), "period_end": date(2025, 3, 31),
                      "payroll_dry_run": True})  # fmt: skip
    ins(db.buildings, {"building": "North", "day_posts": 1, "night_posts": 2, "coverage_billable": False})
    person = {
        "union_member": True,
        "employment_type": "PERMANENT",
        "shift": "NIGHT",
        "hire_date": date(2020, 1, 1),
    }
    ins(db.hr_employees,
        {**person, "employee_id": "E1", "first_name": "Ana", "last_name": "SILVA", "source_ref": "hr 1"},
        {**person, "employee_id": "E2", "first_name": "Rui", "last_name": "COSTA", "source_ref": "hr 2"},
        {**person, "employee_id": "E3", "first_name": "Eva", "last_name": "LIMA", "employment_type": "FLOATER",
         "shift": "FLEX", "source_ref": "hr 3"})  # fmt: skip
    ins(db.employee_assignments,
        {"employee_id": "E1", "building": "North", "shift": "NIGHT", "basis": "HR"},
        {"employee_id": "E2", "building": "North", "shift": "NIGHT", "basis": "HR"},
        {"employee_id": "E3", "building": None, "shift": "FLEX", "basis": "HR"})  # fmt: skip
    ins(db.building_aliases,
        {"source": "dispatch_site", "alias": "S1", "building": "North", "method": "t", "confidence": "high"},
        {"source": "time_clock_site", "alias": "NORTH", "building": "North", "method": "t", "confidence": "high"})  # fmt: skip
    ins(db.employee_xref,
        *[{"source": "badge", "source_id": f"B{i}", "employee_id": f"E{i}", "method": "t", "confidence": "high"}
          for i in (1, 2, 3)],
        {"source": "dispatch", "source_id": "W3", "employee_id": "E3", "method": "t", "confidence": "high"})  # fmt: skip
    punch = lambda badge, event, when: {
        "badge_no": badge,
        "site_raw": "NORTH",
        "event": event,
        "local_time": when,
        "source_ref": f"punch {badge} {event}",
    }
    ins(db.time_punches,
        punch("B1", "IN", datetime(2025, 3, 5, 15, 55)), punch("B1", "OUT", datetime(2025, 3, 6, 0, 2)),
        punch("B3", "IN", datetime(2025, 3, 5, 16, 1)))  # fmt: skip
    ins(db.dispatch_postings, {"posting_id": "P-1", "site_id": "S1", "shift_date": DAY, "shift": "N",
                               "reason": "CALLOUT", "absent_employee_text": "Rui Costa", "status": "FILLED",
                               "assigned_worker_id": "W3", "fill_type": "STANDARD", "source_ref": "posting P-1"})  # fmt: skip
    ins(db.callout_events,
        {"source": "reception_log", "source_ref": "7", "record_ref": "log row 7", "outcome": "absence",
         "reason": "own_illness", "employee_id": "E2", "payroll_id": None, "absence_date": DAY,
         "building": "North", "shift": "night", "code": "SKP", "decision": REVIEW,
         "hold_reason": "employee has no payroll record", "posting_id": "P-1"})  # fmt: skip
    ins(db.kpis_by_building, {"building": "North", "callout_shifts": 1})
    ins(
        db.exceptions,
        {"source": "x", "record_ref": "r", "issue": "i", "action_taken": "a", "confidence": "low"},
    )
    return engine


def test_board_shows_present_absent_and_covering(engine):
    board = views.building_board(engine, "North", DAY, "night")
    status = {a["name"]: a["status"] for a in board["assigned"]}
    assert status == {"Ana Silva": "on_site", "Rui Costa": "out"}
    assert board["covering"][0]["covering"]["name"] == "Eva Lima"
    assert board["summary"] == {"assigned": 2, "on_site": 2, "out": 1, "covered": 1, "open": 0}
    assert board["contracted"] == 2


def test_board_weekend_has_no_shift(engine):
    assert views.building_board(engine, "North", date(2025, 3, 8), "night")["scheduled_day"] is False


def test_kpi_detail_lists_the_records_behind_the_number(engine):
    detail = views.kpi_detail(engine, "North", "callout_shifts")
    assert detail["value"] == 1
    assert [r["source_ref"] for r in detail["sections"][0]["records"]] == ["7"]
    with pytest.raises(KeyError):
        views.kpi_detail(engine, "North", "made_up_metric")


def test_records_found_by_source_ref(engine):
    assert [r["table"] for r in views.find_records(engine, "posting P-1")] == ["dispatch_postings"]


def test_absence_without_payroll_id_cannot_be_approved_but_can_be_dismissed(engine):
    settings = type("S", (), {"output_dir": None})()
    with pytest.raises(ValueError, match="payroll_id"):
        review.approve_absence(engine, settings, 1, None)
    dismissed = review.dismiss_absence(engine, settings, 1, "not ours")
    assert dismissed["hold_reason"].startswith("dismissed by reviewer (not ours)")
    queue = review.review_queue(engine)
    assert queue["absences"][0]["review"]["action"] == "dismiss"


def test_exception_acknowledge(engine):
    key = review.review_queue(engine)["exceptions"][0]["item_key"]
    review.acknowledge_exception(engine, key, "acknowledge", None)
    assert review.review_queue(engine)["exceptions"][0]["review"]["action"] == "acknowledge"
    with pytest.raises(KeyError):
        review.acknowledge_exception(engine, "nope", "acknowledge", None)


def test_panel_ar_aging_has_all_buckets(engine):
    db.insert_rows(
        engine, db.ar_open_items, [{"bucket": "1_30", "open_amount": Decimal("10.00"), "source_ref": "a"}]
    )
    panel = views.kpi_panel(engine)
    assert [b["bucket"] for b in panel["ar_aging"]] == ["current", "1_30", "31_60", "61_90", "over_90"]
    assert panel["ar_aging"][1]["open_amount"] == Decimal("10.00")
