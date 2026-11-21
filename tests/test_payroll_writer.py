"""Exactly-once payroll writes against a fake payroll that misbehaves like the real one can."""

from datetime import date, datetime

import httpx
import pytest

from northgate import db
from northgate.payroll.writer import PayrollWriter


class FakePayroll:
    """Stores submissions in memory. `script` lists what each POST does:
    'ok' = store and answer 202; '503' = answer 503, store nothing;
    'ghost' = store it but answer 503 (the answer is lost); 'timeout' = store it, then time out;
    '422' = reject."""

    def __init__(self, script=()):
        self.script = list(script)
        self.rows: list[dict] = []
        self.posts = 0

    def _store(self, payload):
        row = {**payload, "submission_id": f"SUB-{len(self.rows) + 1}", "status": "RECEIVED"}
        self.rows.append(row)
        return row

    def find_absences(self, employee_id, day):
        return [r for r in self.rows if r["employee_id"] == employee_id and r["date"] == day]

    def get_absence(self, submission_id):
        row = next(r for r in self.rows if r["submission_id"] == submission_id)
        if row["status"] == "RECEIVED":
            row["status"] = "POSTED"
        return row

    def create_absence(self, payload):
        self.posts += 1
        action = self.script.pop(0) if self.script else "ok"
        request = httpx.Request("POST", "http://payroll/v1/absences")
        if action == "ok":
            row = self._store(payload)
            return httpx.Response(202, json={"submission_id": row["submission_id"], "status": "RECEIVED"},
                                  request=request)  # fmt: skip
        if action == "ghost":
            self._store(payload)
            return httpx.Response(503, request=request)
        if action == "timeout":
            self._store(payload)
            raise httpx.ReadTimeout("timed out", request=request)
        if action == "422":
            return httpx.Response(422, json={"detail": {"error": "PERIOD_CLOSED"}}, request=request)
        return httpx.Response(503, request=request)

    def void_absence(self, submission_id):
        row = next(r for r in self.rows if r["submission_id"] == submission_id)
        row["status"] = "VOIDED"
        return httpx.Response(200, request=httpx.Request("DELETE", "http://payroll"))

    def active(self):
        return [r for r in self.rows if r["status"] != "VOIDED"]


EVENT = {"payroll_id": 101, "absence_date": date(2025, 3, 5), "code": "SKP", "source": "reception_log",
         "source_ref": "7", "record_ref": "log row 7", "contact_at": datetime(2025, 3, 5, 9, 0)}  # fmt: skip


@pytest.fixture
def engine(monkeypatch):
    """The writer's audit and ledger calls are recorded in memory instead of a database."""
    monkeypatch.setattr(db, "insert_rows", lambda engine, table, rows: len(list(rows)))
    monkeypatch.setattr(PayrollWriter, "_ledger", lambda self, *args, **kwargs: None)


def _writer(payroll, engine, dry_run=False):
    return PayrollWriter(payroll, engine, dry_run, sleep=lambda s: None, settle_seconds=0)


def test_writes_once(engine):
    payroll = FakePayroll()
    result = _writer(payroll, engine).write(EVENT)
    assert result["decision"] == "written" and len(payroll.active()) == 1


def test_rerun_adopts_instead_of_writing_again(engine):
    payroll = FakePayroll()
    _writer(payroll, engine).write(EVENT)
    again = _writer(payroll, engine).write(EVENT)
    assert payroll.posts == 1
    assert again["submission_id"] == "SUB-1"


def test_503_is_retried_after_checking(engine):
    payroll = FakePayroll(["503", "503", "ok"])
    assert _writer(payroll, engine).write(EVENT)["decision"] == "written"
    assert len(payroll.active()) == 1 and payroll.posts == 3


@pytest.mark.parametrize("failure", ["ghost", "timeout"])
def test_lost_answer_is_not_written_twice(engine, failure):
    payroll = FakePayroll([failure])
    result = _writer(payroll, engine).write(EVENT)
    assert result["submission_id"] == "SUB-1"
    assert payroll.posts == 1 and len(payroll.active()) == 1


def test_existing_duplicates_are_voided_keeping_one(engine):
    payroll = FakePayroll()
    payroll._store({"employee_id": 101, "date": "2025-03-05", "code": "SKP"})
    payroll._store({"employee_id": 101, "date": "2025-03-05", "code": "SKP"})
    result = _writer(payroll, engine).write(EVENT)
    assert payroll.posts == 0
    assert [r["submission_id"] for r in payroll.active()] == [result["submission_id"]]


def test_a_different_code_in_payroll_is_held_not_overwritten(engine):
    payroll = FakePayroll()
    payroll._store({"employee_id": 101, "date": "2025-03-05", "code": "PER"})
    result = _writer(payroll, engine).write(EVENT)
    assert result["decision"] == "held_for_review" and payroll.posts == 0


def test_validation_error_is_held(engine):
    result = _writer(FakePayroll(["422"]), engine).write(EVENT)
    assert result["decision"] == "held_for_review" and "PERIOD_CLOSED" in result["hold_reason"]


def test_payroll_down_is_held_without_writing(engine):
    payroll = FakePayroll(["503"] * 10)
    result = _writer(payroll, engine).write(EVENT)
    assert result["decision"] == "held_for_review" and not payroll.active()


def test_dry_run_never_writes(engine):
    payroll = FakePayroll()
    result = _writer(payroll, engine, dry_run=True).write(EVENT)
    assert result["final_status"] == "DRY_RUN" and payroll.posts == 0


def test_settle_reads_final_status_and_voids_late_duplicates(engine):
    payroll = FakePayroll()
    writer = _writer(payroll, engine)
    event = {**EVENT, **writer.write(EVENT)}
    payroll._store({"employee_id": 101, "date": "2025-03-05", "code": "SKP"})  # a copy that appears later
    status = writer.settle([event])
    assert status == {"SUB-1": "POSTED"}
    assert [r["submission_id"] for r in payroll.active()] == ["SUB-1"]
