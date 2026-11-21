"""What each screen shows, read from the tables the pipeline wrote.

Nothing here decides anything new: the board lists the facts for one building, day and shift, and
each KPI drill-down lists the records behind a figure that was already computed. Every record
carries its `source_ref`, so the interface can open the original line.
"""

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import Engine, select

from northgate import db
from northgate.billing.coverage import SHIFT_CODES, on_site
from northgate.billing.run import full_name
from northgate.callouts.events import name_level
from northgate.callouts.rules import WORKDAYS, shift_start
from northgate.kpis.operations import OVERTIME_HOURS_PER_SHIFT, OVERTIME_MULTIPLIER, weekdays
from northgate.kpis.run import aliases, rate_book
from northgate.resolve.employees import building_on


def run_info(engine: Engine) -> dict | None:
    rows = db.fetch(engine, db.run_info)
    return rows[-1] if rows else None


def _employee_row(e: dict) -> dict:
    return {"employee_id": e["employee_id"], "name": full_name(e), "job_class": e.get("job_class"),
            "employment_type": e.get("employment_type"), "source_ref": e["source_ref"]}  # fmt: skip


def _punches_for_day(engine: Engine, day: date) -> dict[str, list[dict]]:
    """Punches from the day before to the day after, by HR employee id, with their building."""
    badge = {x["source_id"]: x["employee_id"] for x in db.fetch(engine, db.employee_xref)
             if x["source"] == "badge" and x["employee_id"]}  # fmt: skip
    clock = aliases(engine, "time_clock_site")
    low = datetime.combine(day - timedelta(days=1), time.min)
    high = datetime.combine(day + timedelta(days=2), time.min)
    query = select(db.time_punches).where(db.time_punches.c.local_time.between(low, high))
    out: dict[str, list[dict]] = defaultdict(list)
    with engine.connect() as conn:
        for row in conn.execute(query):
            p = dict(row._mapping)
            if employee := badge.get(p["badge_no"]):
                out[employee].append({**p, "building": clock.get(p["site_raw"])})
    return out


def _times(punches: list[dict], building: str, day: date, shift: str) -> dict:
    clock_in, clock_out = on_site([p for p in punches if p["building"] == building], day, shift)
    refs = [
        p["source_ref"]
        for p in punches
        if p["building"] == building and p["local_time"] in (clock_in, clock_out)
    ]
    return {"clock_in": clock_in, "clock_out": clock_out, "punch_refs": refs}


# --- building view -------------------------------------------------------------------------------


def building_board(engine: Engine, building: str, day: date, shift: str) -> dict:
    """Who is assigned, who punched in and out, who is out and why, and who is covering."""
    terms = next((b for b in db.fetch(engine, db.buildings) if b["building"] == building), None)
    if terms is None:
        raise KeyError(building)
    contracted = terms["day_posts"] if shift == "day" else terms["night_posts"]
    board = {"building": building, "date": day, "shift": shift, "contracted": contracted,
             "scheduled_day": day.weekday() in WORKDAYS, "shift_start": shift_start(day, shift),
             "assigned": [], "covering": [], "unexpected": []}  # fmt: skip
    if not board["scheduled_day"]:
        board["summary"] = {"assigned": 0, "on_site": 0, "out": 0, "covered": 0, "open": 0}
        return board

    employees = {e["employee_id"]: e for e in db.fetch(engine, db.hr_employees)}
    assignments = db.fetch(engine, db.employee_assignments)
    punches = _punches_for_day(engine, day)
    site_building = aliases(engine, "dispatch_site")
    worker_employee = {x["source_id"]: x["employee_id"] for x in db.fetch(engine, db.employee_xref)
                       if x["source"] == "dispatch" and x["employee_id"]}  # fmt: skip
    absences = {e["employee_id"]: e for e in db.fetch(engine, db.callout_events)
                if e["outcome"] == "absence" and e["absence_date"] == day and e["employee_id"]}  # fmt: skip
    postings = [p for p in db.fetch(engine, db.dispatch_postings)
                if p["shift_date"] == day and site_building.get(p["site_id"]) == building
                and SHIFT_CODES.get((p["shift"] or "").upper()) == shift]  # fmt: skip

    seen = set()
    for emp_id, e in employees.items():
        a = building_on(assignments, emp_id, day)
        if not a or a["building"] != building or (a["shift"] or e.get("shift") or "").lower() != shift:
            continue
        seen.add(emp_id)
        row = {
            **_employee_row(e),
            **_times(punches.get(emp_id, []), building, day, shift),
            "assignment_basis": a["basis"],
        }
        absence = absences.get(emp_id)
        if absence:
            row.update(status="out", reason=absence["reason"], code=absence["code"], decision=absence["decision"],
                       callout_ref=absence["record_ref"], callout_source_ref=absence["source_ref"],
                       posting_id=absence["posting_id"])  # fmt: skip
        elif vacation := next(
            (p for p in postings if p["reason"] == "VACATION" and _names_match(p, e)), None
        ):
            row.update(status="out", reason="vacation", posting_id=vacation["posting_id"])
        elif row["clock_in"]:
            row.update(status="on_site")
        else:
            row.update(status="no_punch")
        board["assigned"].append(row)

    for p in postings:
        if (p["status"] or "").upper() == "CANCELLED":
            continue
        covering = employees.get(worker_employee.get(p["assigned_worker_id"] or "") or "")
        entry = {"posting_id": p["posting_id"], "reason": p["reason"], "status": p["status"],
                 "fill_type": p["fill_type"], "absent_as_posted": p["absent_employee_text"],
                 "source_ref": p["source_ref"], "covering": None}  # fmt: skip
        if covering:
            seen.add(covering["employee_id"])
            entry["covering"] = {**_employee_row(covering),
                                 **_times(punches.get(covering["employee_id"], []), building, day, shift)}  # fmt: skip
        board["covering"].append(entry)

    # Anyone else who clocked in here during this shift, with no assignment or posting explaining it.
    for emp_id, own in punches.items():
        if emp_id in seen or emp_id not in employees:
            continue
        times = _times(own, building, day, shift)
        if times["clock_in"] or times["clock_out"]:
            board["unexpected"].append({**_employee_row(employees[emp_id]), **times})

    assigned = board["assigned"]
    covered = [c for c in board["covering"] if (c["status"] or "").upper() == "FILLED"]
    out = [a for a in assigned if a["status"] == "out"]
    board["summary"] = {
        "assigned": len(assigned),
        "on_site": sum(1 for a in assigned if a["clock_in"]) + sum(
            1 for c in covered if c["covering"] and c["covering"]["clock_in"]),
        "out": len(out),
        "covered": len(covered),
        "open": sum(1 for c in board["covering"] if (c["status"] or "").upper() != "FILLED"),
    }  # fmt: skip
    return board


def _names_match(posting: dict, employee: dict) -> bool:
    return name_level(posting["absent_employee_text"], employee) >= 2


# --- KPI drill-down ------------------------------------------------------------------------------

METRICS = {
    "contracted_headcount": "Day posts plus night posts in the agreement in force at period end.",
    "active_headcount": "Permanent employees whose home building at period end is this building.",
    "headcount_variance": "Active headcount minus contracted headcount.",
    "scheduled_shifts": "Each weekday a permanent employee was employed, at their home building that day.",
    "callout_shifts": "Absences reported in the reception log or the managers' chat, one per employee and date.",
    "callout_rate": "Call-out shifts divided by scheduled shifts.",
    "fill_rate": "Filled postings divided by all postings in the dispatch app (cancelled excluded).",
    "overtime_hours": "8 hours for every coverage shift filled on overtime.",
    "overtime_dollars": "Overtime hours x the covering employee's base rate x 1.5 (wages only).",
    "revenue": "Every invoice line with this service period, any type, date or entity.",
    "labor_cost": "Every GL labor line of the building's department.",
    "gross_margin": "Revenue minus labor cost.",
    "gross_margin_pct": "Gross margin divided by revenue.",
    "unbilled_coverage_count": "Billable coverage shifts that are on no invoice.",
    "unbilled_coverage_dollars": "Billable amount of the coverage shifts that are on no invoice.",
}


def kpi_panel(engine: Engine) -> dict:
    with engine.connect() as conn:
        aging = [
            dict(r._mapping) for r in conn.execute(select(db.ar_open_items).order_by(db.ar_open_items.c.id))
        ]
    buckets: dict[str, Decimal] = defaultdict(Decimal)
    for item in aging:
        buckets[item["bucket"]] += item["open_amount"]
    return {"run": run_info(engine), "metrics": METRICS,
            "buildings": sorted(db.fetch(engine, db.kpis_by_building), key=lambda r: r["building"]),
            "ar_aging": [{"bucket": b, "open_amount": buckets.get(b, Decimal(0))}
                         for b in ("current", "1_30", "31_60", "61_90", "over_90")]}  # fmt: skip


def kpi_detail(engine: Engine, building: str, metric: str) -> dict:
    """The records behind one figure of the KPI panel."""
    if metric not in METRICS:
        raise KeyError(metric)
    kpi = next((k for k in db.fetch(engine, db.kpis_by_building) if k["building"] == building), None)
    run = run_info(engine)
    if kpi is None or run is None:
        raise KeyError(building)
    start, end = run["period_start"], run["period_end"]
    sections = []

    if metric in ("contracted_headcount", "headcount_variance"):
        sections.append(("Agreement terms", [r for r in db.fetch(engine, db.contract_buildings) if r["building"] == building]
                         + [r for r in db.fetch(engine, db.contract_changes) if r.get("building") == building]))  # fmt: skip
    if metric in ("active_headcount", "headcount_variance", "scheduled_shifts"):
        sections.append(("Employees", _headcount_rows(engine, building, start, end)))
    if metric in ("callout_shifts", "callout_rate"):
        sections.append(("Call-outs", [e for e in db.fetch(engine, db.callout_events)
                                       if e["outcome"] == "absence" and e["building"] == building]))  # fmt: skip
    if metric == "callout_rate":
        sections.append(("Employees", _headcount_rows(engine, building, start, end)))
    if metric == "fill_rate":
        sections.append(("Postings", _postings(engine, building, start, end, cancelled=False)))
    if metric in ("overtime_hours", "overtime_dollars"):
        sections.append(("Overtime coverage", _overtime_rows(engine, building, start, end)))
    if metric in ("revenue", "gross_margin", "gross_margin_pct"):
        sites = aliases(engine, "finance_site")
        sections.append(("Invoice lines", [r for r in db.fetch(engine, db.invoice_lines)
                                           if r["service_period"] == run["period"] and sites.get(r["site_name"]) == building]))  # fmt: skip
    if metric in ("labor_cost", "gross_margin", "gross_margin_pct"):
        depts = aliases(engine, "department")
        sections.append(
            (
                "GL labor lines",
                [r for r in db.fetch(engine, db.gl_lines) if depts.get(r["department"]) == building],
            )
        )
    if metric.startswith("unbilled_coverage"):
        sections.append(("Unbilled coverage", [c for c in db.fetch(engine, db.billable_coverage)
                                               if c["building"] == building and not c["billed"]]))  # fmt: skip

    return {"building": building, "metric": metric, "value": kpi[metric], "definition": METRICS[metric],
            "sections": [{"title": t, "records": rows} for t, rows in sections]}  # fmt: skip


def _headcount_rows(engine: Engine, building: str, start: date, end: date) -> list[dict]:
    assignments = db.fetch(engine, db.employee_assignments)
    days = weekdays(start, end)
    rows = []
    for e in db.fetch(engine, db.hr_employees):
        if (e.get("employment_type") or "").upper() != "PERMANENT":
            continue
        here = sum(
            1
            for d in days
            if (a := building_on(assignments, e["employee_id"], d)) and a["building"] == building
        )
        at_end = building_on(assignments, e["employee_id"], end)
        active = bool(at_end and at_end["building"] == building and e["hire_date"] and e["hire_date"] <= end
                      and not (e["termination_date"] and e["termination_date"] <= end))  # fmt: skip
        if here or active:
            rows.append({**_employee_row(e), "scheduled_shifts": here, "active_at_period_end": active,
                         "hire_date": e["hire_date"], "termination_date": e["termination_date"]})  # fmt: skip
    return sorted(rows, key=lambda r: r["name"])


def _postings(engine: Engine, building: str, start: date, end: date, cancelled: bool) -> list[dict]:
    sites = aliases(engine, "dispatch_site")
    return sorted(
        [{k: v for k, v in p.items() if k != "events"} for p in db.fetch(engine, db.dispatch_postings)
         if sites.get(p["site_id"]) == building and p["shift_date"] and start <= p["shift_date"] <= end
         and (cancelled or (p["status"] or "").upper() != "CANCELLED")],
        key=lambda p: (p["shift_date"], p["posting_id"]),
    )  # fmt: skip


def _overtime_rows(engine: Engine, building: str, start: date, end: date) -> list[dict]:
    employees = {e["employee_id"]: e for e in db.fetch(engine, db.hr_employees)}
    workers = {x["source_id"]: x["employee_id"] for x in db.fetch(engine, db.employee_xref)
               if x["source"] == "dispatch" and x["employee_id"]}  # fmt: skip
    rates = rate_book(engine)
    rows = []
    for p in _postings(engine, building, start, end, cancelled=False):
        if (p["status"] or "").upper() != "FILLED" or (p["fill_type"] or "").upper() != "OT":
            continue
        e = employees.get(workers.get(p["assigned_worker_id"] or "") or "")
        rate = rates.base_rate(e, p["shift_date"]) if e else None
        rows.append({**p, "covering_employee": full_name(e) if e else None, "base_rate": rate,
                     "overtime_hours": OVERTIME_HOURS_PER_SHIFT,
                     "overtime_dollars": OVERTIME_HOURS_PER_SHIFT * rate * OVERTIME_MULTIPLIER if rate else None})  # fmt: skip
    return rows


# --- source records ------------------------------------------------------------------------------


def find_records(engine: Engine, ref: str) -> list[dict]:
    """Every row, in any table, whose source_ref (or call-out record_ref) is `ref`."""
    found = []
    with engine.connect() as conn:
        for table in db.metadata.sorted_tables:
            for column in ("source_ref", "record_ref"):
                if column in table.c:
                    for row in conn.execute(select(table).where(table.c[column] == ref)):
                        found.append({"table": table.name, "record": dict(row._mapping)})
    return found
