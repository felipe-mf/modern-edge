"""Compute the KPI panel and AR aging from the resolved tables and write them to ./output.

Call-out shifts come from the call-out step and unbilled coverage from the billing step. Until those
steps have run, their columns (and the call-out rate) are left blank rather than written as zero.
"""

import logging
from collections import Counter
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from sqlalchemy import Engine

from northgate import db, outputs
from northgate.kpis.financial import AR_BUCKETS, ar_aging, labor_cost_by_building, revenue_by_building
from northgate.kpis.operations import active_headcount, coverage_kpis, scheduled_shifts
from northgate.rates import RateBook

log = logging.getLogger(__name__)

KPI_COLUMNS = [
    "building",
    "contracted_headcount",
    "active_headcount",
    "headcount_variance",
    "scheduled_shifts",
    "callout_shifts",
    "callout_rate",
    "fill_rate",
    "overtime_hours",
    "overtime_dollars",
    "revenue",
    "labor_cost",
    "gross_margin",
    "gross_margin_pct",
    "unbilled_coverage_count",
    "unbilled_coverage_dollars",
]


def money(value: Decimal | None) -> Decimal | None:
    return None if value is None else Decimal(value).quantize(Decimal("0.01"), ROUND_HALF_UP)


def ratio(numerator: Decimal | int | None, denominator: Decimal | int | None) -> Decimal | None:
    if numerator is None or not denominator:
        return None
    return (Decimal(numerator) / Decimal(denominator)).quantize(Decimal("0.0001"), ROUND_HALF_UP)


def aliases(engine: Engine, source: str) -> dict[str, str]:
    return {
        a["alias"]: a["building"]
        for a in db.fetch(engine, db.building_aliases)
        if a["source"] == source and a["building"]
    }


def rate_book(engine: Engine) -> RateBook:
    burden = {b["schedule"]: b["burden_pct"] for b in db.fetch(engine, db.labor_burden)}
    return RateBook(db.fetch(engine, db.wage_rates), burden)


def run_kpis(
    engine: Engine,
    output_dir: Path,
    period: str,
    start: date,
    end: date,
    callout_shifts: Counter | None = None,
    unbilled: dict[str, tuple[int, Decimal]] | None = None,
) -> None:
    buildings = db.fetch(engine, db.buildings)
    employees = db.fetch(engine, db.hr_employees)
    assignments = db.fetch(engine, db.employee_assignments)
    worker_to_employee = {
        x["source_id"]: x["employee_id"]
        for x in db.fetch(engine, db.employee_xref)
        if x["source"] == "dispatch" and x["employee_id"]
    }

    active = active_headcount(employees, assignments, end)
    scheduled = scheduled_shifts(employees, assignments, start, end)
    coverage = coverage_kpis(
        db.fetch(engine, db.dispatch_postings),
        aliases(engine, "dispatch_site"),
        worker_to_employee,
        {e["employee_id"]: e for e in employees},
        rate_book(engine),
        start,
        end,
    )
    for ref, issue in coverage.issues:
        db.add_exception(engine, "kpi:dispatch", ref, issue, "excluded from the affected KPI", "medium")

    revenue, unbilled_lines = revenue_by_building(
        db.fetch(engine, db.invoice_lines), aliases(engine, "finance_site"), period
    )
    for line in unbilled_lines:
        db.add_exception(
            engine,
            "kpi:revenue",
            line["source_ref"],
            f"invoice line for site {line['site_name']!r} matches no building",
            "excluded from building revenue",
            "medium",
        )
    labor, _ = labor_cost_by_building(db.fetch(engine, db.gl_lines), aliases(engine, "department"))

    rows = []
    for b in sorted(buildings, key=lambda b: b["building"]):
        name = b["building"]
        contracted = (b["day_posts"] or 0) + (b["night_posts"] or 0)
        callouts = callout_shifts.get(name, 0) if callout_shifts is not None else None
        building_revenue = money(revenue.get(name, Decimal(0)))
        building_labor = money(labor.get(name, Decimal(0)))
        margin = building_revenue - building_labor
        unbilled_count, unbilled_dollars = (unbilled or {}).get(name, (0, Decimal(0)))
        rows.append(
            {
                "building": name,
                "contracted_headcount": contracted,
                "active_headcount": active.get(name, 0),
                "headcount_variance": active.get(name, 0) - contracted,
                "scheduled_shifts": scheduled.get(name, 0),
                "callout_shifts": callouts,
                "callout_rate": ratio(callouts, scheduled.get(name, 0)),
                "fill_rate": ratio(coverage.filled.get(name, 0), coverage.postings.get(name, 0)),
                "overtime_hours": money(coverage.overtime_hours.get(name, Decimal(0))),
                "overtime_dollars": money(coverage.overtime_dollars.get(name, Decimal(0))),
                "revenue": building_revenue,
                "labor_cost": building_labor,
                "gross_margin": margin,
                "gross_margin_pct": ratio(margin, building_revenue),
                "unbilled_coverage_count": unbilled_count if unbilled is not None else None,
                "unbilled_coverage_dollars": money(unbilled_dollars) if unbilled is not None else None,
            }
        )
    db.insert_rows(engine, db.kpis_by_building, rows)
    outputs.write_csv(output_dir / "kpis_by_building.csv", KPI_COLUMNS, rows)

    aging = ar_aging(db.fetch(engine, db.ar_items), end)
    for ref, issue in aging.issues:
        db.add_exception(engine, "kpi:ar", ref, issue, "aged as described", "medium")
    db.insert_rows(
        engine,
        db.ar_open_items,
        [
            {
                k: item.get(k)
                for k in (
                    "entity",
                    "customer_no",
                    "doc_type",
                    "doc_no",
                    "doc_date",
                    "due_date",
                    "open_amount",
                    "days_past_due",
                    "bucket",
                    "source_ref",
                )
            }
            for item in aging.items
        ],
    )
    outputs.write_csv(
        output_dir / "ar_aging.csv",
        ["bucket", "open_amount"],
        [{"bucket": b, "open_amount": money(aging.buckets[b])} for b in AR_BUCKETS],
    )
    log.info(
        "KPIs written for %d buildings; AR open total %s",
        len(rows),
        money(sum(aging.buckets.values(), Decimal(0))),
    )
