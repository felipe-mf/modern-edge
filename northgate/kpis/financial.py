"""Financial KPIs and AR aging, implemented as docs/kpi_definitions.md words them."""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

AR_BUCKETS = ("current", "1_30", "31_60", "61_90", "over_90")


def revenue_by_building(
    invoice_lines: list[dict], finance_site_to_building: dict[str, str], period: str
) -> tuple[dict[str, Decimal], list[dict]]:
    """Every invoice line with service period = period, whatever its type, invoice date or entity.

    Returns (revenue per building, lines that could not be attributed to a building).
    """
    revenue: dict[str, Decimal] = defaultdict(Decimal)
    unattributed = []
    for line in invoice_lines:
        if line["service_period"] != period:
            continue
        building = finance_site_to_building.get(line["site_name"])
        if building is None:
            unattributed.append(line)
        else:
            revenue[building] += line["amount"]
    return revenue, unattributed


def labor_cost_by_building(
    gl_lines: list[dict], dept_to_building: dict[str, str]
) -> tuple[dict[str, Decimal], list[dict]]:
    """The building's department's labor cost, every account, both entities.

    The GL report is requested for the period, so every line it returns belongs to the period
    (including the week ending in the next month that the ledger closes into it).
    """
    cost: dict[str, Decimal] = defaultdict(Decimal)
    unattributed = []
    for line in gl_lines:
        building = dept_to_building.get(line["department"])
        if building is None:
            unattributed.append(line)
        else:
            cost[building] += line["amount"]
    return cost, unattributed


@dataclass
class AgingResult:
    buckets: dict[str, Decimal] = field(default_factory=lambda: {b: Decimal(0) for b in AR_BUCKETS})
    items: list[dict] = field(default_factory=list)  # every open item with its balance and bucket
    issues: list[tuple[str, str]] = field(default_factory=list)


def bucket_for(days_past_due: int) -> str:
    if days_past_due <= 0:
        return "current"
    if days_past_due <= 30:
        return "1_30"
    if days_past_due <= 60:
        return "31_60"
    if days_past_due <= 90:
        return "61_90"
    return "over_90"


def ar_aging(ar_items: list[dict], as_of: date) -> AgingResult:
    """Open receivables as of `as_of`, both entities.

    An invoice is open for its amount less the payments applied to it, aged from its due date. A
    credit memo is open at its own amount, aged from its document date. A payment that names no
    invoice in the report is treated like a credit (open, aged from its own date) and reported.
    Documents dated after `as_of` are not yet part of the balance.
    """
    result = AgingResult()
    current = [i for i in ar_items if i["doc_date"] is None or i["doc_date"] <= as_of]
    invoices = {i["doc_no"]: i for i in current if i["doc_type"] == "INV"}
    applied: dict[str, Decimal] = defaultdict(Decimal)

    open_items: list[tuple[dict, Decimal, date | None]] = []
    for item in current:
        kind = item["doc_type"]
        if kind == "PMT" and item.get("apply_to") in invoices:
            applied[item["apply_to"]] += item["amount"]  # payments are negative amounts
        elif kind == "INV":
            continue  # handled below, once all payments are known
        else:
            if kind == "PMT":
                result.issues.append(
                    (
                        item["source_ref"],
                        (
                            f"payment {item['doc_no']} applies to {item.get('apply_to')!r}, "
                            "not an invoice in the report; aged as an unapplied credit"
                        ),
                    )
                )
            elif kind != "CM":
                result.issues.append(
                    (item["source_ref"], f"unknown document type {kind!r}; aged by its date")
                )
            open_items.append((item, item["amount"], item["doc_date"]))

    for doc_no, invoice in invoices.items():
        balance = invoice["amount"] + applied.get(doc_no, Decimal(0))
        if balance < 0:
            result.issues.append((invoice["source_ref"], f"invoice {doc_no} is overpaid by {-balance}"))
        if balance != 0:
            open_items.append((invoice, balance, invoice["due_date"] or invoice["doc_date"]))

    for item, balance, aged_from in open_items:
        days = (as_of - aged_from).days if aged_from else 0
        bucket = bucket_for(days)
        result.buckets[bucket] += balance
        result.items.append({**item, "open_amount": balance, "days_past_due": days, "bucket": bucket})
    return result
