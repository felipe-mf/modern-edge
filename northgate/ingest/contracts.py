"""Contract documents (client agreements, amendments, wage schedule) -> typed terms.

The PDFs are prose and loosely formatted tables, and an unseen dataset may word them differently,
so Claude reads them into the schemas below. Code then checks the answer against the document
text: every building name, fee, markup, post count, rate and burden percentage must be printed in
the document. Anything that is not becomes an issue for review instead of a silent number.
"""

import re
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from northgate.ingest.common import pdf_text
from northgate.llm import Extractor, pdf_block, text_block


class BuildingTerms(BaseModel):
    building: str = Field(description="Building name exactly as written in the buildings schedule")
    day_posts: int
    night_posts: int
    pricing_basis: Literal["fixed_fee", "cost_plus", "other"]
    monthly_fee: float | None = Field(description="Fixed monthly fee, if pricing is a fixed fee")
    markup_pct: float | None = Field(description="Cost-plus markup in percent, e.g. 15 for 15%")
    coverage_billable: bool = Field(description="True if coverage (replacement) labor is billed separately")


class CoverageBackupRules(BaseModel):
    """What the client requires in the backup note for a billed coverage shift."""

    applies: bool = Field(description="True if the document sets coverage backup documentation rules")
    replacement_names: Literal["required", "forbidden", "not_specified"]
    actual_time_on_site_required: bool
    absent_employee_or_reason_forbidden: bool
    summary: str = Field(description="One or two sentences restating the rules in plain words")


class BuildingChange(BaseModel):
    building: str
    effective_date: str = Field(description="YYYY-MM-DD")
    day_posts: int | None = Field(description="New number of day posts, if changed")
    night_posts: int | None = Field(description="New number of night posts, if changed")
    markup_pct: float | None = Field(description="New cost-plus markup in percent, if changed")
    monthly_fee: float | None = Field(description="New fixed monthly fee, if changed")


class WageRate(BaseModel):
    classification: str
    effective_date: str = Field(description="YYYY-MM-DD the rate takes effect")
    hourly_rate: float


class WageTerms(BaseModel):
    union_rates: list[WageRate] = Field(description="Rates for bargaining-unit (union) employees")
    non_union_rates: list[WageRate] = Field(description="Rate card for non-union and temporary staff")
    union_burden_pct: float | None = Field(description="Labor burden in percent for union employees")
    non_union_burden_pct: float | None = Field(description="Labor burden in percent for non-union/temps")
    overtime_multiplier: float | None
    floater_rule: str | None = Field(description="Any rule on how floaters are paid, quoted")


class ContractDocument(BaseModel):
    document_type: Literal["client_agreement", "amendment", "wage_schedule", "other"]
    client_name: str | None
    contractor_name: str | None = Field(description="The Northgate legal entity that signed")
    document_date: str | None = Field(description="YYYY-MM-DD the document is dated or entered into")
    amends_agreement_dated: str | None = Field(description="For amendments: YYYY-MM-DD of the agreement")
    payment_terms_days: int | None
    buildings: list[BuildingTerms] = Field(description="Client agreements: every building in the schedule")
    coverage_backup: CoverageBackupRules | None
    building_changes: list[BuildingChange] = Field(description="Amendments: every change to a building")
    wage_terms: WageTerms | None = Field(description="Wage schedules and rate cards only")
    notes: str = Field(description="Anything ambiguous, illegible or surprising")


INSTRUCTIONS = """You read contract documents for a building services company and extract their terms.
Copy names exactly as the document writes them. Report numbers exactly as printed; percentages as
numbers (15 for 15%). Dates as YYYY-MM-DD. Leave a field null or a list empty when the document
does not say it. Do not infer terms from general knowledge. If something is unclear, say so in notes."""


def extract_contract(path: Path, extractor: Extractor) -> tuple[ContractDocument, str]:
    """Returns the extracted terms and the document text used to check them."""
    text = pdf_text(path)
    content = [text_block(path.name, text)] if text.strip() else [pdf_block(path)]
    return extractor.extract(ContractDocument, INSTRUCTIONS, content), text


# --- checks against the document text ----------------------------------------------------------


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).lower()


def _number_printed(value: float, text: str) -> bool:
    """True if the number appears in the text, written as 15, 15.0, 72,400.00 or 72400.00."""
    candidates = {f"{value:,.2f}", f"{value:.2f}", f"{value:g}", f"{value:,.0f}"}
    # Not part of a longer number: "12" must not match inside "12,500.00" or "1.12".
    return any(re.search(rf"(?<![\d.,]){re.escape(c)}(?![\d]|[.,]\d)", text) for c in candidates)


def _percent_printed(value: float, text: str) -> bool:
    """True if the text prints the value as a percentage: "15%", "15 %" or "15 percent"."""
    return (
        re.search(rf"(?<![\d.,]){re.escape(f'{value:g}')}(\.0+)?\s*(%|percent)", text, re.IGNORECASE)
        is not None
    )


def check_contract(doc: ContractDocument, text: str, source: str) -> list[str]:
    if not text.strip():
        return [f"{source}: scanned document, extracted terms could not be checked against text"]
    issues: list[str] = []
    squashed = _squash(text)

    def need(condition: bool, message: str) -> None:
        if not condition:
            issues.append(f"{source}: {message}")

    for b in doc.buildings:
        need(_squash(b.building) in squashed, f"building {b.building!r} not found in the text")
        need(_number_printed(b.day_posts, text), f"{b.building}: day posts {b.day_posts} not printed")
        need(_number_printed(b.night_posts, text), f"{b.building}: night posts {b.night_posts} not printed")
        if b.monthly_fee is not None:
            need(_number_printed(b.monthly_fee, text), f"{b.building}: fee {b.monthly_fee} not printed")
        if b.markup_pct is not None:
            need(_percent_printed(b.markup_pct, text), f"{b.building}: markup {b.markup_pct}% not printed")
        need(
            (b.pricing_basis == "cost_plus") == (b.markup_pct is not None),
            f"{b.building}: pricing {b.pricing_basis} but markup is {b.markup_pct}",
        )
    for c in doc.building_changes:
        need(_squash(c.building) in squashed, f"amended building {c.building!r} not found in the text")
        for label, value in (
            ("day posts", c.day_posts),
            ("night posts", c.night_posts),
            ("fee", c.monthly_fee),
        ):
            if value is not None:
                need(_number_printed(value, text), f"{c.building}: new {label} {value} not printed")
        if c.markup_pct is not None:
            need(
                _percent_printed(c.markup_pct, text), f"{c.building}: new markup {c.markup_pct}% not printed"
            )
        need(_is_iso_date(c.effective_date), f"{c.building}: effective date {c.effective_date!r} unreadable")
    if doc.wage_terms:
        w = doc.wage_terms
        for rate in w.union_rates + w.non_union_rates:
            need(
                _number_printed(rate.hourly_rate, text),
                f"rate {rate.hourly_rate} ({rate.classification}) not printed",
            )
            need(_is_iso_date(rate.effective_date), f"rate date {rate.effective_date!r} unreadable")
        for label, pct in (
            ("union burden", w.union_burden_pct),
            ("non-union burden", w.non_union_burden_pct),
        ):
            need(pct is not None, f"{label} not found")
            if pct is not None:
                need(_percent_printed(pct, text), f"{label} {pct}% not printed")
    return issues


def _is_iso_date(value: str | None) -> bool:
    try:
        date.fromisoformat(value or "")
        return True
    except ValueError:
        return False
