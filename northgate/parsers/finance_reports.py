"""Parsers for the three ERP report files. Pure functions: text in, rows out.

Every report prints its own control totals (REPORT TOTAL, record count, DEPT/ENTITY TOTAL). Each
parser re-adds the rows it read and compares them with those totals, so a line the parser skipped
or misread shows up as an issue instead of a silently wrong KPI.
"""

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from northgate.ingest.common import normalize_header, parse_amount, parse_date


@dataclass
class ParsedReport:
    rows: list[dict]
    issues: list[str] = field(default_factory=list)
    control_totals: dict[str, Decimal] = field(default_factory=dict)
    as_of: date | None = None  # AR_OPEN prints the date its balances are stated at


def _check_total(report: ParsedReport, label: str, expected: Decimal, actual: Decimal) -> None:
    report.control_totals[label] = expected
    if expected != actual:
        report.issues.append(f"{label}: report prints {expected}, parsed rows add up to {actual}")


# --- INV_REG: CSV with a banner on top and a REPORT TOTAL line at the bottom -------------------


def parse_invoice_register(text: str, entity: str) -> ParsedReport:
    lines = text.splitlines()
    header_at = next(
        (i for i, line in enumerate(lines) if "invoice" in line.lower() and "amount" in line.lower()), None
    )
    if header_at is None:
        return ParsedReport([], [f"{entity} INV_REG: header line not found"])

    reader = csv.reader(io.StringIO("\n".join(lines[header_at:])))
    header = [normalize_header(h) for h in next(reader)]
    report = ParsedReport([])
    printed_total: Decimal | None = None

    for line_no, values in enumerate(reader, start=header_at + 2):
        if not any(v.strip() for v in values):
            continue
        row = dict(zip(header, values))
        if not row.get("invoice", "").strip():
            if any("REPORT TOTAL" in v.upper() for v in values):
                printed_total = parse_amount(row.get("amount"))
            continue
        report.rows.append(
            {
                "entity": entity,
                "invoice_no": row["invoice"].strip(),
                "invoice_date": parse_date(row.get("inv_date")),
                "customer_no": row.get("cust_no", "").strip(),
                "customer_name": row.get("customer", "").strip(),
                "service_period": row.get("svc_period", "").strip(),
                "site_name": row.get("site", "").strip(),
                "line_no": int(row["ln"]) if row.get("ln", "").strip() else None,
                "line_type": row.get("type", "").strip().upper(),
                "service_date": parse_date(row.get("svc_date")),
                "description": row.get("description", "").strip(),
                "amount": parse_amount(row.get("amount")),
                "source_ref": f"INV_REG {entity} line {line_no}",
            }
        )

    if printed_total is None:
        report.issues.append(f"{entity} INV_REG: no REPORT TOTAL line")
    else:
        _check_total(report, f"{entity} INV_REG total", printed_total, sum(r["amount"] for r in report.rows))
    return report


# --- AR_OPEN: pipe-delimited, signed amounts like "72757.58-", trailer with a record count ------

_AR_TRAILER = re.compile(r"(\d+)\s+RECORDS(?:\s+AS OF\s+(\S+))?", re.IGNORECASE)


def parse_open_receivables(text: str, entity: str) -> ParsedReport:
    lines = [line for line in text.splitlines() if line.strip()]
    header_at = next((i for i, line in enumerate(lines) if "|" in line and "DOC_NO" in line.upper()), None)
    if header_at is None:
        return ParsedReport([], [f"{entity} AR_OPEN: header line not found"])

    header = [normalize_header(h) for h in lines[header_at].split("|")]
    report = ParsedReport([])
    printed_count: int | None = None

    for line_no, line in enumerate(lines[header_at + 1 :], start=header_at + 2):
        if "|" not in line:
            trailer = _AR_TRAILER.search(line)
            if trailer:
                printed_count = int(trailer.group(1))
                report.as_of = parse_date(trailer.group(2))
            continue
        row = dict(zip(header, (v.strip() for v in line.split("|"))))
        report.rows.append(
            {
                "entity": row.get("entity") or entity,
                "customer_no": row.get("cust_no"),
                "customer_name": row.get("cust_name"),
                "doc_type": (row.get("doc_type") or "").upper(),
                "doc_no": row.get("doc_no"),
                "apply_to": row.get("apply_to") or None,
                "doc_date": parse_date(row.get("doc_date")),
                "due_date": parse_date(row.get("due_date")),
                "amount": parse_amount(row.get("amount")),
                "source_ref": f"AR_OPEN {entity} line {line_no}",
            }
        )

    if printed_count is None:
        report.issues.append(f"{entity} AR_OPEN: no record-count trailer")
    elif printed_count != len(report.rows):
        report.issues.append(
            f"{entity} AR_OPEN: trailer says {printed_count} records, parsed {len(report.rows)}"
        )
    return report


# --- GL_LABOR: fixed-width, paginated, repeated headers, department and entity totals ---------

_GL_DETAIL = re.compile(
    r"^\s*(?P<dept>\d{2,})\s+(?P<account>\d{3,})\s+(?P<name>.+?)\s{2,}"
    r"(?P<week>\d{1,2}/\d{1,2}/\d{2,4})\s+(?P<amount>\(?-?[\d,]+\.\d{2}\)?-?)\s*$"
)
_GL_DEPT_TOTAL = re.compile(r"^\s*DEPT\s+(?P<dept>\S+)\s+TOTAL\s+(?P<amount>\(?-?[\d,]+\.\d{2}\)?-?)\s*$")
_GL_ENTITY_TOTAL = re.compile(r"^\s*ENTITY\s+TOTAL\s+(?P<amount>\(?-?[\d,]+\.\d{2}\)?-?)\s*$")


def parse_gl_labor(text: str, entity: str) -> ParsedReport:
    report = ParsedReport([])
    dept_totals: dict[str, Decimal] = {}
    entity_total: Decimal | None = None

    for line_no, line in enumerate(text.splitlines(), start=1):
        if match := _GL_DETAIL.match(line):
            report.rows.append(
                {
                    "entity": entity,
                    "department": match["dept"],
                    "account": match["account"],
                    "account_name": match["name"].strip(),
                    "week_ending": parse_date(match["week"]),
                    "amount": parse_amount(match["amount"]),
                    "source_ref": f"GL_LABOR {entity} line {line_no}",
                }
            )
        elif match := _GL_DEPT_TOTAL.match(line):
            dept_totals[match["dept"]] = parse_amount(match["amount"])
        elif match := _GL_ENTITY_TOTAL.match(line):
            entity_total = parse_amount(match["amount"])

    for dept, printed in dept_totals.items():
        parsed = sum((r["amount"] for r in report.rows if r["department"] == dept), Decimal(0))
        _check_total(report, f"{entity} GL dept {dept} total", printed, parsed)
    if entity_total is None:
        report.issues.append(f"{entity} GL_LABOR: no ENTITY TOTAL line")
    else:
        _check_total(
            report,
            f"{entity} GL entity total",
            entity_total,
            sum((r["amount"] for r in report.rows), Decimal(0)),
        )
    return report
