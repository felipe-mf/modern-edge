"""KPI rules on small synthetic data (invented, not client data)."""

from datetime import date
from decimal import Decimal

from northgate.kpis.financial import ar_aging, bucket_for, labor_cost_by_building, revenue_by_building
from northgate.kpis.operations import active_headcount, coverage_kpis, scheduled_shifts, weekdays
from northgate.rates import RateBook, pay_schedule

MARCH_START, MARCH_END = date(2025, 3, 1), date(2025, 3, 31)  # 21 weekdays


def _employee(
    employee_id, *, kind="PERMANENT", hired=date(2020, 1, 1), terminated=None, union=True, job="Cleaner"
):
    return {
        "employee_id": employee_id,
        "employment_type": kind,
        "hire_date": hired,
        "termination_date": terminated,
        "union_member": union,
        "job_class": job,
    }


def _assignment(employee_id, building, start, end=None):
    return {"employee_id": employee_id, "building": building, "start_date": start, "end_date": end}


def test_weekdays_skip_weekends():
    assert len(weekdays(MARCH_START, MARCH_END)) == 21
    assert weekdays(date(2025, 3, 7), date(2025, 3, 10)) == [date(2025, 3, 7), date(2025, 3, 10)]


EMPLOYEES = [
    _employee("A"),  # all month at North
    _employee("B", terminated=date(2025, 3, 5)),  # leaves after 3 weekdays (3, 4, 5)
    _employee("C", hired=date(2025, 3, 24)),  # joins for the last 6 weekdays
    _employee("D"),  # transfers North -> South on the 17th
    _employee("F", kind="FLOATER"),  # floaters are never counted
]
ASSIGNMENTS = [
    _assignment("A", "North", date(2020, 1, 1)),
    _assignment("B", "North", date(2020, 1, 1), date(2025, 3, 5)),
    _assignment("C", "South", date(2025, 3, 24)),
    _assignment("D", "North", date(2020, 1, 1), date(2025, 3, 16)),
    _assignment("D", "South", date(2025, 3, 17)),
    _assignment("F", None, date(2020, 1, 1)),
]


def test_active_headcount_at_period_end():
    assert active_headcount(EMPLOYEES, ASSIGNMENTS, MARCH_END) == {"North": 1, "South": 2}


def test_scheduled_shifts_follow_employment_dates_and_transfers():
    counts = scheduled_shifts(EMPLOYEES, ASSIGNMENTS, MARCH_START, MARCH_END)
    # North: A 21 + B 3 + D 10 (Mar 3-14); South: C 6 + D 11 (Mar 17-31)
    assert counts == {"North": 34, "South": 17}


RATES = RateBook(
    rates=[
        {
            "schedule": "union",
            "classification": "Cleaner",
            "effective_date": date(2024, 1, 1),
            "hourly_rate": 20,
        },
        {
            "schedule": "union",
            "classification": "Cleaner",
            "effective_date": date(2025, 1, 1),
            "hourly_rate": 22,
        },
        {
            "schedule": "non_union",
            "classification": "Cleaner",
            "effective_date": date(2025, 1, 1),
            "hourly_rate": 18,
        },
    ],
    burden_pct={"union": Decimal(30), "non_union": Decimal(15)},
)


def test_rate_book_uses_schedule_and_effective_date():
    union, temp = _employee("U"), _employee("T", kind="TEMP", union=True)
    assert RATES.base_rate(union, date(2025, 3, 3)) == Decimal(22)
    assert RATES.base_rate(union, date(2024, 6, 3)) == Decimal(20)
    assert pay_schedule(temp) == "non_union"  # temporary staff are outside the bargaining unit
    assert RATES.base_rate(temp, date(2025, 3, 3)) == Decimal(18)
    assert RATES.burden(temp) == Decimal("0.15")


def _posting(pid, site, status, fill_type=None, worker=None, day=date(2025, 3, 10)):
    return {
        "posting_id": pid,
        "site_id": site,
        "status": status,
        "fill_type": fill_type,
        "assigned_worker_id": worker,
        "shift_date": day,
        "source_ref": pid,
    }


def test_fill_rate_and_overtime():
    postings = [
        _posting("P1", "S1", "FILLED", "OT", "W1"),
        _posting("P2", "S1", "FILLED", "STANDARD", "W1"),
        _posting("P3", "S1", "EXPIRED"),
        _posting("P4", "S1", "CANCELLED"),  # excluded from fill rate
        _posting("P5", "S1", "FILLED", "OT", "W1", day=date(2025, 4, 1)),  # outside the period
    ]
    result = coverage_kpis(
        postings, {"S1": "North"}, {"W1": "A"}, {"A": EMPLOYEES[0]}, RATES, MARCH_START, MARCH_END
    )
    assert (result.filled["North"], result.postings["North"]) == (2, 3)
    assert result.overtime_hours["North"] == Decimal(8)
    assert result.overtime_dollars["North"] == Decimal(8) * Decimal(22) * Decimal("1.5")  # no burden


def test_revenue_includes_every_line_type_of_the_service_period():
    lines = [
        {"service_period": "2025-03", "site_name": "North Twr", "amount": Decimal(1000), "source_ref": "1"},
        {"service_period": "2025-03", "site_name": "North Twr", "amount": Decimal(-100), "source_ref": "2"},
        {"service_period": "2025-02", "site_name": "North Twr", "amount": Decimal(999), "source_ref": "3"},
        {"service_period": "2025-03", "site_name": "Unknown", "amount": Decimal(5), "source_ref": "4"},
    ]
    revenue, unattributed = revenue_by_building(lines, {"North Twr": "North"}, "2025-03")
    assert revenue == {"North": Decimal(900)}
    assert [line["source_ref"] for line in unattributed] == ["4"]


def test_labor_cost_sums_every_account_of_the_department():
    gl = [
        {"department": "100", "amount": Decimal(500)},
        {"department": "100", "amount": Decimal(50)},
        {"department": "900", "amount": Decimal(7)},
    ]
    cost, unattributed = labor_cost_by_building(gl, {"100": "North"})
    assert cost == {"North": Decimal(550)}
    assert len(unattributed) == 1


def test_ar_buckets_boundaries():
    assert [bucket_for(d) for d in (-5, 0, 1, 30, 31, 60, 61, 90, 91)] == [
        "current",
        "current",
        "1_30",
        "1_30",
        "31_60",
        "31_60",
        "61_90",
        "61_90",
        "over_90",
    ]


def _ar(doc_type, doc_no, amount, doc_date, due=None, apply_to=None):
    return {
        "doc_type": doc_type,
        "doc_no": doc_no,
        "amount": Decimal(amount),
        "doc_date": doc_date,
        "due_date": due,
        "apply_to": apply_to,
        "source_ref": doc_no,
    }


def test_ar_aging_partial_payment_credit_memo_and_future_documents():
    as_of = MARCH_END
    items = [
        _ar("INV", "I1", "1000", date(2025, 2, 1), due=date(2025, 3, 3)),  # 28 days past due
        _ar("PMT", "P1", "-400", date(2025, 3, 10), apply_to="I1"),  # partial payment
        _ar("INV", "I2", "500", date(2025, 1, 1), due=date(2025, 1, 31)),  # paid in full
        _ar("PMT", "P2", "-500", date(2025, 2, 15), apply_to="I2"),
        _ar("CM", "C1", "-200", date(2025, 3, 20)),  # aged from its own date: 11 days
        _ar("INV", "I3", "300", date(2024, 11, 1), due=date(2024, 12, 1)),  # 120 days
        _ar("INV", "I4", "800", date(2025, 3, 31), due=date(2025, 4, 30)),  # not yet due
        _ar("INV", "I5", "999", date(2025, 4, 2), due=date(2025, 5, 2)),  # after as-of: ignored
    ]
    result = ar_aging(items, as_of)
    assert result.buckets == {
        "current": Decimal(800),
        "1_30": Decimal(600) + Decimal(-200),
        "31_60": Decimal(0),
        "61_90": Decimal(0),
        "over_90": Decimal(300),
    }
    assert result.issues == []


def test_ar_payment_for_unknown_invoice_is_reported():
    items = [_ar("PMT", "P9", "-50", date(2025, 3, 1), apply_to="NOPE")]
    result = ar_aging(items, MARCH_END)
    assert result.buckets["1_30"] == Decimal(-50)
    assert len(result.issues) == 1
