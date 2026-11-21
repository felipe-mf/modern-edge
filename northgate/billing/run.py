"""Billing step: backup notes and unbilled coverage for cost-plus buildings.

1. Billable coverage = filled call-out and vacation postings at buildings whose agreement makes
   coverage billable. Each gets its amount and a backup note in the template its client requires.
2. Every coverage line on the invoices is matched to a posting; billable postings with no line are
   unbilled coverage (a KPI). Lines with no posting, or billed at a different amount, are exceptions.
"""

import logging
import shutil
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import Engine

from northgate import db
from northgate.billing.coverage import SHIFT_CODES, billable_amount, match_line, on_site
from northgate.billing.notes import TEMPLATES
from northgate.callouts.events import name_level
from northgate.kpis.run import aliases, rate_book
from northgate.resolve.employees import building_on

log = logging.getLogger(__name__)


def full_name(employee: dict) -> str:
    """HR keeps last names in capitals: 'Teuta', 'BERISHA' -> 'Teuta Berisha'."""
    return f"{(employee.get('first_name') or '').title()} {(employee.get('last_name') or '').title()}".strip()


def _absent_employee(posting, building, employees, assignments, callout_link) -> dict | None:
    """The employee the posting covers: the call-out matched to it, else the name on the posting
    among the people assigned to that building that day."""
    if posting["posting_id"] in callout_link:
        return callout_link[posting["posting_id"]]
    here = [e for e in employees
            if (a := building_on(assignments, e["employee_id"], posting["shift_date"])) and a["building"] == building]  # fmt: skip
    scored = [(name_level(posting["absent_employee_text"], e), e) for e in here]
    best = max((s for s, _ in scored), default=0)
    found = [e for s, e in scored if s == best and s > 0]
    return found[0] if len(found) == 1 else None


def run_billing(engine: Engine, output_dir: Path, start: date, end: date) -> dict[str, tuple[int, Decimal]]:
    """Writes backup notes and the billable_coverage table. Returns unbilled (count, dollars) per building."""
    buildings = {b["building"]: b for b in db.fetch(engine, db.buildings)}
    employees = db.fetch(engine, db.hr_employees)
    by_id = {e["employee_id"]: e for e in employees}
    assignments = db.fetch(engine, db.employee_assignments)
    rates = rate_book(engine)
    site_building = aliases(engine, "dispatch_site")
    clock_building = aliases(engine, "time_clock_site")
    worker_employee = {x["source_id"]: x["employee_id"] for x in db.fetch(engine, db.employee_xref)
                       if x["source"] == "dispatch" and x["employee_id"]}  # fmt: skip
    badge_employee = {x["source_id"]: x["employee_id"] for x in db.fetch(engine, db.employee_xref)
                      if x["source"] == "badge" and x["employee_id"]}  # fmt: skip
    callout_link = {e["posting_id"]: by_id[e["employee_id"]] for e in db.fetch(engine, db.callout_events)
                    if e["posting_id"] and e["employee_id"] and e["outcome"] == "absence"}  # fmt: skip

    punches_by_employee: dict[str, list[dict]] = defaultdict(list)
    for p in db.fetch(engine, db.time_punches):
        if (emp := badge_employee.get(p["badge_no"])) and p["local_time"]:
            punches_by_employee[emp].append({**p, "building": clock_building.get(p["site_raw"])})

    def flag(ref: str, issue: str, action: str, confidence: str = "high") -> None:
        db.add_exception(engine, "billing", ref, issue, action, confidence)

    coverage: list[dict] = []
    for p in db.fetch(engine, db.dispatch_postings):
        building = site_building.get(p["site_id"])
        terms = buildings.get(building or "")
        if (
            not terms or not terms["coverage_billable"]
            or (p["status"] or "").upper() != "FILLED"
            or (p["reason"] or "").upper() not in ("CALLOUT", "VACATION")
            or not (p["shift_date"] and start <= p["shift_date"] <= end)
        ):  # fmt: skip
            continue
        ref = p["source_ref"]
        covering = by_id.get(worker_employee.get(p["assigned_worker_id"] or "") or "")
        shift = SHIFT_CODES.get((p["shift"] or "").upper())
        if covering is None or shift is None:
            flag(ref, f"covering worker {p['assigned_worker_id']} or shift {p['shift']!r} not resolved",
                 "no backup note; billable amount unknown", "low")  # fmt: skip
            continue
        base_rate, burden = rates.base_rate(covering, p["shift_date"]), rates.burden(covering)
        if base_rate is None or burden is None or terms["markup_pct"] is None:
            flag(ref, f"no rate, burden or markup for {covering['employee_id']} on {p['shift_date']}",
                 "no backup note; billable amount unknown", "low")  # fmt: skip
            continue
        overtime = (p["fill_type"] or "").upper() == "OT"
        absent = _absent_employee(p, building, employees, assignments, callout_link)
        if absent is None:
            flag(ref, f"absent employee {p['absent_employee_text']!r} not identified",
                 "position covered written as 'Not recorded'", "medium")  # fmt: skip
        own_punches = [x for x in punches_by_employee[covering["employee_id"]] if x["building"] == building]
        clock_in, clock_out = on_site(own_punches, p["shift_date"], shift)
        coverage.append({
            "posting_id": p["posting_id"], "building": building, "client_name": terms["client_name"],
            "template": terms["backup_template"], "shift_date": p["shift_date"], "shift": shift,
            "reason": p["reason"], "overtime": overtime,
            "covering_employee_id": covering["employee_id"], "covering_name": full_name(covering),
            "covering_employee": covering,
            "absent_employee_id": absent["employee_id"] if absent else None,
            "position_covered": (absent or {}).get("job_class") or "Not recorded",
            "base_rate": base_rate, "burden_pct": burden * 100, "markup_pct": terms["markup_pct"],
            "billable_amount": billable_amount(base_rate, burden, terms["markup_pct"], overtime),
            "on_site_in": clock_in, "on_site_out": clock_out, "source_ref": ref,
        })  # fmt: skip

    _match_invoices(engine, coverage, aliases(engine, "finance_site"), start, end, flag)
    _write_notes(output_dir, coverage, flag)

    columns = [c.name for c in db.billable_coverage.columns]
    db.insert_rows(engine, db.billable_coverage, [{k: c.get(k) for k in columns} for c in coverage])

    unbilled: dict[str, tuple[int, Decimal]] = {b: (0, Decimal(0)) for b in buildings}
    for c in coverage:
        if not c["billed"]:
            count, dollars = unbilled[c["building"]]
            unbilled[c["building"]] = (count + 1, dollars + c["billable_amount"])
            flag(c["source_ref"], f"billable coverage on {c['shift_date']} at {c['building']} is on no invoice",
                 f"backup note written; {c['billable_amount']} unbilled", "high")  # fmt: skip
    log.info("billing: %d billable coverage shifts, %d unbilled ($%s)", len(coverage),
             sum(n for n, _ in unbilled.values()), sum(d for _, d in unbilled.values()))  # fmt: skip
    return unbilled


def _match_invoices(engine, coverage, finance_building, start, end, flag) -> None:
    by_posting = {c["posting_id"]: c for c in coverage}
    for c in coverage:
        c["billed"] = False
    taken: set[str] = set()
    lines = [
        line for line in db.fetch(engine, db.invoice_lines) if (line["line_type"] or "").upper() == "COVERAGE"
    ]
    for line in sorted(
        lines, key=lambda line: "ref P-" not in (line["description"] or "")
    ):  # referenced first
        if line["service_date"] and not start <= line["service_date"] <= end:
            continue
        building = finance_building.get(line["site_name"])
        match = match_line(line, building, coverage, taken)
        ref = line["source_ref"]
        if match.posting_id is None:
            flag(ref, f"coverage line '{line['description']}' matches no billable posting: {match.method}",
                 "not linked; check the invoice", "medium")  # fmt: skip
            continue
        c = by_posting.get(match.posting_id)
        if c is None or match.posting_id in taken:
            flag(ref, f"coverage line names {match.posting_id}, which is not billable or is already billed by another line",
                 "not linked; check the invoice", "medium")  # fmt: skip
            continue
        taken.add(match.posting_id)
        c.update(billed=True, invoice_no=line["invoice_no"], invoice_ref=ref, billed_amount=line["amount"],
                 match_method=match.method)  # fmt: skip
        if line["amount"] != c["billable_amount"]:
            flag(ref, f"{match.posting_id} billed {line['amount']}, rules give {c['billable_amount']}",
                 "billed amount left as invoiced", "high")  # fmt: skip


def _write_notes(output_dir: Path, coverage: list[dict], flag) -> None:
    folder = output_dir / "backup_notes"
    shutil.rmtree(folder, ignore_errors=True)  # only this run's notes, never stale ones
    folder.mkdir(parents=True)
    for c in coverage:
        template = TEMPLATES.get(c["template"] or "")
        if template is None:
            flag(c["source_ref"], f"no backup template known for {c['building']}", "no backup note", "high")
            continue
        if c["template"] == "A" and (c["on_site_in"] is None or c["on_site_out"] is None):
            missing = " and ".join(w for w, t in (("clock-in", c["on_site_in"]), ("clock-out", c["on_site_out"]))
                                   if t is None)  # fmt: skip
            flag(c["source_ref"], f"{c['covering_name']} has no {missing} for this shift",
                 "written as 'Not recorded' on the backup note", "high")  # fmt: skip
        path = folder / f"{c['posting_id']}.txt"
        path.write_text(template(c), encoding="utf-8")
        c["note_path"] = str(path.relative_to(output_dir))
