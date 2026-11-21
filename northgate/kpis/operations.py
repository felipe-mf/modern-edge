"""Operations KPIs, implemented exactly as docs/kpi_definitions.md words them.

Inputs are plain rows from the database, so each rule can be read and tested on its own.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from northgate.rates import RateBook
from northgate.resolve.employees import building_on

OVERTIME_HOURS_PER_SHIFT = Decimal(8)
OVERTIME_MULTIPLIER = Decimal("1.5")


def weekdays(start: date, end: date) -> list[date]:
    """Monday to Friday, both ends included. The KPI scope has no holiday calendar."""
    days, day = [], start
    while day <= end:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


def _is_permanent(employee: dict) -> bool:
    return (employee.get("employment_type") or "").upper() == "PERMANENT"


def active_headcount(employees: list[dict], assignments: list[dict], as_of: date) -> Counter:
    """Permanent employees whose home building on `as_of` is the building, hired on or before that
    date and not terminated by then."""
    counts: Counter = Counter()
    for e in employees:
        if not _is_permanent(e) or e.get("hire_date") is None or e["hire_date"] > as_of:
            continue
        if e.get("termination_date") is not None and e["termination_date"] <= as_of:
            continue
        assignment = building_on(assignments, e["employee_id"], as_of)
        if assignment and assignment["building"]:
            counts[assignment["building"]] += 1
    return counts


def scheduled_shifts(employees: list[dict], assignments: list[dict], start: date, end: date) -> Counter:
    """For every permanent employee, each weekday they were employed, at their home building that day.

    Employment runs from hire date through termination date, both included; the assignment rows
    carry exactly that range (see resolve/employees.py).
    """
    counts: Counter = Counter()
    permanent = {e["employee_id"] for e in employees if _is_permanent(e)}
    for day in weekdays(start, end):
        for employee_id in permanent:
            assignment = building_on(assignments, employee_id, day)
            if assignment and assignment["building"]:
                counts[assignment["building"]] += 1
    return counts


@dataclass
class CoverageResult:
    postings: Counter = field(default_factory=Counter)
    filled: Counter = field(default_factory=Counter)
    overtime_hours: defaultdict = field(default_factory=lambda: defaultdict(Decimal))
    overtime_dollars: defaultdict = field(default_factory=lambda: defaultdict(Decimal))
    issues: list[tuple[str, str]] = field(default_factory=list)  # (posting ref, issue)


def coverage_kpis(
    postings: list[dict],
    site_to_building: dict[str, str],
    worker_to_employee: dict[str, str],
    employees_by_id: dict[str, dict],
    rate_book: RateBook,
    start: date,
    end: date,
) -> CoverageResult:
    """Fill rate inputs and overtime, from the dispatch postings of the period.

    Fill rate counts call-out and vacation postings and excludes cancelled ones. Each posting filled
    on overtime adds 8 hours at the building where the shift was worked, paid at the covering
    employee's own base rate x 1.5 (wages only, no burden).
    """
    result = CoverageResult()
    for p in postings:
        if p["shift_date"] is None or not start <= p["shift_date"] <= end:
            continue
        if (p["status"] or "").upper() == "CANCELLED":
            continue
        building = site_to_building.get(p["site_id"])
        if building is None:
            result.issues.append((p["source_ref"], f"site {p['site_id']} is not a client building"))
            continue
        result.postings[building] += 1
        if (p["status"] or "").upper() != "FILLED":
            continue
        result.filled[building] += 1

        if (p["fill_type"] or "").upper() != "OT":
            continue
        result.overtime_hours[building] += OVERTIME_HOURS_PER_SHIFT
        employee = employees_by_id.get(worker_to_employee.get(p["assigned_worker_id"] or "") or "")
        rate = rate_book.base_rate(employee, p["shift_date"]) if employee else None
        if rate is None:
            result.issues.append(
                (
                    p["source_ref"],
                    (
                        f"no base rate for covering worker {p['assigned_worker_id']}; "
                        "overtime hours counted, dollars not"
                    ),
                )
            )
            continue
        result.overtime_dollars[building] += OVERTIME_HOURS_PER_SHIFT * rate * OVERTIME_MULTIPLIER
    return result
