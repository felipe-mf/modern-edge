"""Parser tests on small synthetic inputs (written for the tests, not copied from client data)."""

from datetime import date, datetime
from decimal import Decimal

import openpyxl

from northgate.ingest.callouts import parse_callout_log, parse_chat_export
from northgate.ingest.common import parse_amount, parse_date
from northgate.ingest.hr import parse_hr_roster
from northgate.ingest.punches import is_punch_file, parse_punches
from northgate.ingest.run import current_assignment
from northgate.parsers.finance_reports import parse_gl_labor, parse_invoice_register, parse_open_receivables


def test_parse_amount_formats():
    assert parse_amount("1,234.50") == Decimal("1234.50")
    assert parse_amount("(1,250.00)") == Decimal("-1250.00")
    assert parse_amount("980.10-") == Decimal("-980.10")
    assert parse_amount("$21.00") == Decimal("21.00")
    assert parse_amount("") is None


def test_parse_date_formats():
    assert parse_date("2025-03-04") == date(2025, 3, 4)
    assert parse_date("03/04/2025") == date(2025, 3, 4)
    assert parse_date("03/04/25") == date(2025, 3, 4)
    assert parse_date("04-MAR-25") == date(2025, 3, 4)


INVOICE_REGISTER = """ACME SERVICES LLC
INVOICE REGISTER     PERIOD: 2025-03     RUN: 04/01/25 06:00

Invoice,Inv Date,Cust No,Customer,Svc Period,Site,Ln,Type,Svc Date,Description,Amount
A-1,03/31/25,C-9,Client One,2025-03,Site A,1,CONTRACT,,"Monthly fee, March","10,000.00"
A-2,03/10/25,C-9,Client One,2025-03,Site A,1,COVERAGE,03/05/25,Coverage 03/05 Day (ref X-1),250.25
CM-3,03/20/25,C-9,Client One,2025-03,Site A,1,CREDIT,03/06/25,Service credit,"(500.00)"
,,,,,,,,,REPORT TOTAL,"9,750.25"
"""


def test_invoice_register_reads_lines_and_ties_to_total():
    report = parse_invoice_register(INVOICE_REGISTER, "ACM")
    assert [r["amount"] for r in report.rows] == [Decimal("10000.00"), Decimal("250.25"), Decimal("-500.00")]
    assert report.rows[1]["service_date"] == date(2025, 3, 5)
    assert report.rows[0]["description"] == "Monthly fee, March"
    assert report.issues == []


def test_invoice_register_flags_total_mismatch():
    broken = INVOICE_REGISTER.replace('"9,750.25"', '"9,999.99"')
    assert parse_invoice_register(broken, "ACM").issues


AR_OPEN = """ENTITY|CUST_NO|CUST_NAME|DOC_TYPE|DOC_NO|APPLY_TO|DOC_DATE|DUE_DATE|AMOUNT
ACM|C-9|Client One|INV|A-1||31-JAN-25|02-MAR-25|1000.00
ACM|C-9|Client One|PMT|P-1|A-1|10-MAR-25||400.00-
ACM|C-9|Client One|CM|CM-3||20-MAR-25||500.00-
*** END OF REPORT *** 3 RECORDS AS OF 31-MAR-25
"""


def test_open_receivables_signs_dates_and_trailer():
    report = parse_open_receivables(AR_OPEN, "ACM")
    assert [r["amount"] for r in report.rows] == [Decimal("1000.00"), Decimal("-400.00"), Decimal("-500.00")]
    assert report.rows[1]["apply_to"] == "A-1"
    assert report.rows[2]["due_date"] is None
    assert report.as_of == date(2025, 3, 31)
    assert report.issues == []


def test_open_receivables_flags_record_count_mismatch():
    assert parse_open_receivables(AR_OPEN.replace("3 RECORDS", "4 RECORDS"), "ACM").issues


GL_LABOR = """
                   ACME SERVICES LLC                                  PAGE   1
PERIOD 2025-03

DEPT  ACCT  ACCOUNT NAME                        WK ENDING           AMOUNT
----  ----  ----------------------------------  ----------  --------------
710   5100  WAGES - STRAIGHT TIME               03/07/25          1,000.00
710   5110  WAGES - OVERTIME PREMIUM            03/07/25             50.00
            DEPT 710 TOTAL                                        1,050.00

\f
                   ACME SERVICES LLC                                  PAGE   2
DEPT  ACCT  ACCOUNT NAME                        WK ENDING           AMOUNT
----  ----  ----------------------------------  ----------  --------------
720   5100  WAGES - STRAIGHT TIME               03/07/25            200.00
            DEPT 720 TOTAL                                          200.00

            ENTITY TOTAL                                          1,250.00
*** END OF REPORT ***
"""


def test_gl_labor_across_pages_ties_to_totals():
    report = parse_gl_labor(GL_LABOR, "ACM")
    assert len(report.rows) == 3
    assert {r["department"] for r in report.rows} == {"710", "720"}
    assert report.rows[1]["account_name"] == "WAGES - OVERTIME PREMIUM"
    assert report.issues == []


def test_gl_labor_flags_dropped_line():
    assert parse_gl_labor(GL_LABOR.replace("710   5110", "XXX   5110"), "ACM").issues


def test_hr_roster_types_and_dated_columns(tmp_path):
    path = tmp_path / "roster.csv"
    path.write_text(
        "employee_id,last_name,first_name,union_member,hire_date,termination_date,status,"
        "sick_days_remaining_2025_03_01,clinic_day_used_2025\n"
        "E1,DOE,Jane,Y,2024-01-15,,ACTIVE,3,N\n"
    )
    [row] = parse_hr_roster(path)
    assert row["union_member"] is True
    assert row["hire_date"] == date(2024, 1, 15)
    assert row["termination_date"] is None
    assert row["sick_days_remaining"] == 3
    assert row["clinic_day_used"] is False


def test_punch_layouts_map_to_one_schema(tmp_path):
    old = tmp_path / "old.csv"
    old.write_text(
        "badge_no,employee_name,site,punch_type,punch_time,device_id\n"
        '0000007,"DOE, JANE",SITE A,IN,03/03/2025 06:55,D1\n'
        '0000007,"DOE, JANE",SITE A,BREAK_OUT,03/03/2025 11:00,D1\n'
    )
    new = tmp_path / "new.csv"
    new.write_text(
        "EmpBadge,Name,SiteCode,Event,Timestamp,Terminal\n"
        "7,Jane Doe,S-1,CLOCK_OUT,2025-03-04T00:05:00-05:00,T1\n"
        "7,Jane Doe,S-1,TELEPORT,2025-03-04T00:06:00-05:00,T1\n"
    )
    old_rows, old_issues = parse_punches(old)
    new_rows, new_issues = parse_punches(new)

    assert [r["event"] for r in old_rows] == ["IN", "MEAL_START"]
    assert old_rows[0]["local_time"] == datetime(2025, 3, 3, 6, 55) and old_rows[0]["utc_offset_min"] is None
    assert new_rows[0]["event"] == "OUT"
    assert new_rows[0]["local_time"] == datetime(2025, 3, 4, 0, 5) and new_rows[0]["utc_offset_min"] == -300
    assert old_issues == [] and len(new_issues) == 1  # unknown event is reported, not dropped silently
    assert is_punch_file(["EmpBadge", "Name", "SiteCode", "Event", "Timestamp", "Terminal"])


def test_callout_log_finds_header_below_banner(tmp_path):
    path = tmp_path / "log.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["Call log"])
    sheet.append(["Date", "Time", "Channel", "VM Received", "Caller", "Message"])
    sheet.append(["03/03/2025", "08:40 AM", "Voicemail", "03/02 22:10", "Jane D.", "Sick tomorrow"])
    sheet.append([None, None, None, None, None, None])
    workbook.save(path)

    rows, issues = parse_callout_log(path)
    assert issues == []
    assert len(rows) == 1
    assert rows[0]["logged_at"] == datetime(2025, 3, 3, 8, 40)
    assert rows[0]["vm_received_raw"] == "03/02 22:10"
    assert rows[0]["caller"] == "Jane D."


def test_chat_export_messages_system_lines_and_continuations(tmp_path):
    path = tmp_path / "chat.txt"
    path.write_text(
        "[03/01/25, 7:00:00 AM] Messages are encrypted.\n"
        "[03/03/25, 9:15:00 PM] Ana Lima: Jane is out tonight\n"
        "at Site A\n",
        encoding="utf-8",
    )
    system, message = parse_chat_export(path)
    assert system["author"] is None
    assert message["author"] == "Ana Lima"
    assert message["sent_at_local"] == datetime(2025, 3, 3, 21, 15)
    assert message["text"] == "Jane is out tonight\nat Site A"


def test_current_assignment_replays_unassign():
    events = [
        {"type": "POSTED", "at": "2025-03-03T10:00:00Z"},
        {"type": "ASSIGNED", "at": "2025-03-03T10:05:00Z", "worker_id": "W-1", "fill_type": "OT"},
        {"type": "UNASSIGNED", "at": "2025-03-03T10:20:00Z", "worker_id": "W-1"},
        {"type": "ASSIGNED", "at": "2025-03-03T10:30:00Z", "worker_id": "W-2", "fill_type": "STANDARD"},
    ]
    assert current_assignment(events) == ("W-2", "STANDARD")
    assert current_assignment(events[:3]) == (None, None)
