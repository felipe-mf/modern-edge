"""Load every source into Postgres, one table per source, nothing reconciled yet.

Files are found by folder and by their content (header row), not by exact file name, so a
dataset with other file names but the same kinds of files still loads. Whatever cannot be read
cleanly is written to the exceptions table instead of stopping the run.
"""

import logging
from collections import Counter
from datetime import datetime
from pathlib import Path

from sqlalchemy import Engine, func, select

from northgate import db
from northgate.clients.dispatch import DispatchClient
from northgate.clients.finance import FinanceClient, ReportNotAvailable
from northgate.clients.payroll import PayrollClient
from northgate.ingest import contracts, paf
from northgate.ingest.callouts import parse_callout_log, parse_chat_export
from northgate.ingest.common import data_files, parse_date
from northgate.ingest.hr import parse_hr_roster
from northgate.ingest.labor_budget import parse_labor_budget
from northgate.ingest.punches import (
    is_punch_file,
    is_site_code_file,
    parse_punches,
    parse_site_codes,
    read_header,
)
from northgate.llm import ExtractionFailed, Extractor
from northgate.parsers.finance_reports import (
    ParsedReport,
    parse_gl_labor,
    parse_invoice_register,
    parse_open_receivables,
)

log = logging.getLogger(__name__)


def _issue(engine: Engine, source: str, ref: str, issue: str, action: str, confidence: str = "high") -> None:
    log.warning("%s | %s | %s", source, ref, issue)
    db.add_exception(engine, source, ref, issue, action, confidence)


def _parse_issue(engine: Engine, source: str, message: str) -> None:
    """Parser issues are 'file line N: problem' strings."""
    ref, _, issue = message.partition(": ")
    _issue(engine, source, ref, issue or message, "row not loaded")


# --- files --------------------------------------------------------------------------------------


def ingest_files(data_dir: Path, engine: Engine, extractor: Extractor) -> Counter:
    counts: Counter = Counter()

    for path in data_files(data_dir / "hr", "*.csv"):
        counts["hr_employees"] += db.insert_rows(engine, db.hr_employees, parse_hr_roster(path))

    for path in data_files(data_dir / "time_attendance", "*.csv"):
        header = read_header(path)
        if is_punch_file(header):
            rows, issues = parse_punches(path)
            counts["time_punches"] += db.insert_rows(engine, db.time_punches, rows)
            for message in issues:
                _parse_issue(engine, "time_attendance", message)
        elif is_site_code_file(header):
            counts["ta_site_codes"] += db.insert_rows(engine, db.ta_site_codes, parse_site_codes(path))
        else:
            _issue(engine, "time_attendance", path.name, "unrecognised file layout", "file not loaded")

    for path in data_files(data_dir / "callouts", "*.xlsx"):
        rows, issues = parse_callout_log(path)
        counts["callout_log"] += db.insert_rows(engine, db.callout_log, rows)
        for message in issues:
            _parse_issue(engine, "callout_log", message)
    for path in data_files(data_dir / "callouts", "*.txt"):
        counts["chat_messages"] += db.insert_rows(engine, db.chat_messages, parse_chat_export(path))

    for path in data_files(data_dir / "labor_budget", "*.xlsx"):
        counts["labor_budget"] += db.insert_rows(engine, db.labor_budget, parse_labor_budget(path))

    for path in data_files(data_dir / "contracts", "*.pdf"):
        counts.update(_ingest_contract(path, engine, extractor))

    for path in data_files(data_dir / "hr" / "personnel_action_forms", "*.pdf"):
        try:
            form = paf.extract_paf(path, extractor)
        except ExtractionFailed as exc:
            _issue(
                engine,
                "personnel_action_forms",
                path.name,
                f"could not read form: {exc}",
                "form ignored; review by hand",
                "low",
            )
            continue
        if form.legibility_notes.strip():
            _issue(
                engine,
                "personnel_action_forms",
                path.name,
                f"legibility: {form.legibility_notes}",
                "values used as read; check the scan",
                "medium",
            )
        counts["personnel_actions"] += db.insert_rows(engine, db.personnel_actions, [paf.to_row(form, path)])

    return counts


def _ingest_contract(path: Path, engine: Engine, extractor: Extractor) -> Counter:
    counts: Counter = Counter()
    try:
        doc, text = contracts.extract_contract(path, extractor)
    except ExtractionFailed as exc:
        _issue(
            engine,
            "contracts",
            path.name,
            f"could not read document: {exc}",
            "document ignored; review by hand",
            "low",
        )
        return counts

    for message in contracts.check_contract(doc, text, path.name):
        _, _, issue = message.partition(": ")
        _issue(engine, "contracts", path.name, issue, "term kept as read; check the document", "low")

    agreement_date = parse_date(doc.document_date)
    counts["contracts"] += db.insert_rows(
        engine,
        db.contracts,
        [
            {
                "source_file": path.name,
                "document_type": doc.document_type,
                "client_name": doc.client_name,
                "contractor_name": doc.contractor_name,
                "document_date": agreement_date,
                "amends_agreement_dated": parse_date(doc.amends_agreement_dated),
                "payment_terms_days": doc.payment_terms_days,
                "coverage_backup": doc.coverage_backup.model_dump() if doc.coverage_backup else None,
                "notes": doc.notes,
                "details": doc.model_dump(),
                "source_ref": path.name,
            }
        ],
    )
    counts["contract_buildings"] += db.insert_rows(
        engine,
        db.contract_buildings,
        [
            {
                "source_file": path.name,
                "client_name": doc.client_name,
                "contractor_name": doc.contractor_name,
                "agreement_date": agreement_date,
                **b.model_dump(),
                "source_ref": f"{path.name} buildings schedule",
            }
            for b in doc.buildings
        ],
    )
    counts["contract_changes"] += db.insert_rows(
        engine,
        db.contract_changes,
        [
            {
                "source_file": path.name,
                "client_name": doc.client_name,
                **c.model_dump(exclude={"effective_date"}),
                "effective_date": parse_date(c.effective_date),
                "source_ref": f"{path.name} amendment",
            }
            for c in doc.building_changes
        ],
    )
    if doc.wage_terms:
        w = doc.wage_terms
        counts["wage_rates"] += db.insert_rows(
            engine,
            db.wage_rates,
            [
                {
                    "schedule": schedule,
                    "classification": r.classification,
                    "effective_date": parse_date(r.effective_date),
                    "hourly_rate": r.hourly_rate,
                    "source_ref": f"{path.name} {schedule} rates",
                }
                for schedule, rates in (("union", w.union_rates), ("non_union", w.non_union_rates))
                for r in rates
            ],
        )
        counts["labor_burden"] += db.insert_rows(
            engine,
            db.labor_burden,
            [
                {"schedule": schedule, "burden_pct": pct, "source_ref": f"{path.name} labor burden"}
                for schedule, pct in (("union", w.union_burden_pct), ("non_union", w.non_union_burden_pct))
                if pct is not None
            ],
        )
    return counts


# --- APIs ---------------------------------------------------------------------------------------


def current_assignment(events: list[dict]) -> tuple[str | None, str | None]:
    """Replay a posting's history: the last ASSIGNED counts, an UNASSIGNED clears it."""
    worker, fill_type = None, None
    for event in sorted(events, key=lambda e: e.get("at") or ""):
        if event.get("type") == "ASSIGNED":
            worker, fill_type = event.get("worker_id"), event.get("fill_type")
        elif event.get("type") == "UNASSIGNED":
            worker, fill_type = None, None
    return worker, fill_type


def _timestamp(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value)  # Python 3.11+ reads the trailing "Z" if value else None


def ingest_apis(
    engine: Engine, payroll: PayrollClient, dispatch: DispatchClient, finance: FinanceClient, period: str
) -> Counter:
    counts: Counter = Counter()

    counts["dispatch_sites"] += db.insert_rows(
        engine,
        db.dispatch_sites,
        [
            {
                **{k: s.get(k) for k in ("site_id", "name", "timezone", "active")},
                "source_ref": f"dispatch site {s['site_id']}",
            }
            for s in dispatch.sites()
        ],
    )
    counts["dispatch_workers"] += db.insert_rows(
        engine,
        db.dispatch_workers,
        [
            {
                **{
                    k: w.get(k)
                    for k in ("worker_id", "display_name", "hr_employee_no", "phone_last4", "active")
                },
                "source_ref": f"dispatch worker {w['worker_id']}",
            }
            for w in dispatch.workers()
        ],
    )
    postings = []
    for p in dispatch.postings():
        worker, fill_type = current_assignment(p.get("events") or [])
        postings.append(
            {
                "posting_id": p["posting_id"],
                "site_id": p.get("site_id"),
                "shift_date": parse_date(p.get("shift_date")),
                "shift": p.get("shift"),
                "start_local": p.get("start_local"),
                "reason": p.get("reason"),
                "absent_employee_text": p.get("absent_employee_text"),
                "status": p.get("status"),
                "created_at": _timestamp(p.get("created_at")),
                "updated_at": _timestamp(p.get("updated_at")),
                "assigned_worker_id": worker,
                "fill_type": fill_type,
                "events": p.get("events"),
                "source_ref": f"dispatch posting {p['posting_id']}",
            }
        )
    counts["dispatch_postings"] += db.insert_rows(engine, db.dispatch_postings, postings)

    counts["payroll_employees"] += db.insert_rows(
        engine,
        db.payroll_employees,
        [
            {
                "employee_id": e["employee_id"],
                "name": e.get("name"),
                "status": e.get("status"),
                "source_ref": f"payroll employee {e['employee_id']}",
            }
            for e in payroll.employees()
        ],
    )
    counts["payroll_codes"] += db.insert_rows(
        engine,
        db.payroll_codes,
        [
            {
                **{k: c.get(k) for k in ("code", "description", "paid", "union_only")},
                "source_ref": f"payroll code {c['code']}",
            }
            for c in payroll.codes()["codes"]
        ],
    )

    entities = finance.entities()
    counts["finance_entities"] += db.insert_rows(
        engine,
        db.finance_entities,
        [
            {
                "entity_code": e["entity_code"],
                "name": e.get("name"),
                "source_ref": f"finance entity {e['entity_code']}",
            }
            for e in entities
        ],
    )
    counts["finance_sites"] += db.insert_rows(
        engine,
        db.finance_sites,
        [
            {
                **{k: s.get(k) for k in ("site_name", "department", "description")},
                "source_ref": f"finance site {s['site_name']}",
            }
            for s in finance.sites()
        ],
    )
    counts["finance_customers"] += db.insert_rows(
        engine,
        db.finance_customers,
        [
            {
                **{k: c.get(k) for k in ("entity_code", "customer_no", "customer_name", "terms", "status")},
                "source_ref": f"finance customer {c['entity_code']}/{c['customer_no']}",
            }
            for c in finance.customers()
        ],
    )

    reports = (
        ("INV_REG", parse_invoice_register, db.invoice_lines),
        ("AR_OPEN", parse_open_receivables, db.ar_items),
        ("GL_LABOR", parse_gl_labor, db.gl_lines),
    )
    for entity in (e["entity_code"] for e in entities):
        for code, parse, table in reports:
            try:
                text = finance.run_report(code, entity, period)
            except ReportNotAvailable as exc:
                _issue(
                    engine,
                    "finance",
                    f"{code} {entity} {period}",
                    f"report not available: {exc}",
                    "treated as no data for this entity",
                    "medium",
                )
                continue
            report: ParsedReport = parse(text, entity)
            counts[table.name] += db.insert_rows(engine, table, report.rows)
            db.insert_rows(
                engine,
                db.report_control_totals,
                [
                    {"label": label, "amount": amount, "source_ref": f"{code} {entity} {period}"}
                    for label, amount in report.control_totals.items()
                ],
            )
            for message in report.issues:
                _issue(
                    engine,
                    "finance",
                    f"{code} {entity} {period}",
                    message,
                    "rows loaded; totals do not tie, review the report",
                    "low",
                )
    return counts


# --- period ------------------------------------------------------------------------------------


def infer_period(engine: Engine) -> str:
    """The reporting month = the month most punches fall in (night shifts spill into the next day)."""
    with engine.connect() as conn:
        month = func.to_char(db.time_punches.c.local_time, "YYYY-MM")
        row = conn.execute(
            select(month, func.count()).group_by(month).order_by(func.count().desc()).limit(1)
        ).first()
    if row is None:
        raise RuntimeError("Cannot infer the reporting period: no time clock punches loaded. Set PERIOD.")
    return row[0]
