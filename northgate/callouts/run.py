"""Call-out step: every reception log row and chat message becomes zero or more absence events.

Order of work:
1. Claude extracts each message (in parallel, cached); code checks the extraction against the text.
2. Code works out the notice time, the date(s), the employee and the shift.
3. Duplicates (same employee and date, any channel) are folded into the earliest report.
4. Absences are coded in date order with the Article 14 rules (rules.py).
5. Payroll guards decide what is written and what is held for review.
6. Every absence is checked against the dispatch app's call-out postings, both ways.

The events are stored in `callout_events`; the payroll writer then fills in what payroll answered.
"""

import logging
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import Engine

from northgate import db
from northgate.callouts.events import (
    Contact,
    candidate_dates,
    chat_contact,
    log_contact,
    match_employee,
    name_level,
    stated_building,
)
from northgate.callouts.extract import (
    CalloutExtraction,
    check_extraction,
    contact_time_supported,
    describe_chat_message,
    describe_log_row,
    extract_callout,
)
from northgate.callouts.rules import (
    WORKDAYS,
    Balances,
    code_absence,
    is_immediate_family,
    notice_hours,
)
from northgate.llm import ExtractionFailed, Extractor
from northgate.resolve.employees import building_on

log = logging.getLogger(__name__)

REVIEW = "held_for_review"
WRITE = "written"


def event_key(e: dict) -> str:
    """Stable across runs: the message and the day it is about."""
    return f"{e['source']}|{e['source_ref']}|{e.get('absence_date') or ''}"


def latest_reviews(engine: Engine, kind: str) -> dict[str, dict]:
    """The last action a reviewer took on each item."""
    latest: dict[str, dict] = {}
    for action in sorted(db.fetch(engine, db.review_actions), key=lambda a: a["id"]):
        if action["item_kind"] == kind:
            latest[action["item_key"]] = action
    return latest


@dataclass
class Message:
    source: str  # reception_log / area_manager_chat (the output file's names)
    output_ref: str  # log row number or chat timestamp, as payroll_submissions.csv asks
    record_ref: str  # our own source_ref, pointing at the exact file line
    description: str  # what Claude reads
    names: list[str]  # names to match, besides what Claude extracted
    raw: dict
    extraction: CalloutExtraction | None = None
    problems: list[str] = field(default_factory=list)  # reasons to hold for review
    notes: list[str] = field(default_factory=list)  # worth recording, not a reason to hold


def _messages(engine: Engine) -> list[Message]:
    out = []
    for row in db.fetch(engine, db.callout_log):
        row_no = re.search(r"row (\d+)$", row["source_ref"])
        out.append(
            Message("reception_log", row_no[1] if row_no else row["source_ref"], row["source_ref"],
                    describe_log_row(row), [row.get("caller") or ""], row)
        )  # fmt: skip
    for msg in db.fetch(engine, db.chat_messages):
        if msg["author"] is None:  # system lines ("created group", encryption notice)
            continue
        out.append(
            Message("area_manager_chat", f"{msg['sent_at_local']:%Y-%m-%d %H:%M:%S}", msg["source_ref"],
                    describe_chat_message(msg), [], msg)
        )  # fmt: skip
    return out


def _extract_all(messages: list[Message], extractor: Extractor) -> None:
    def work(m: Message) -> None:
        try:
            m.extraction = extract_callout(m.description, extractor)
        except ExtractionFailed as exc:
            m.problems.append(f"could not be read: {exc}")
            return
        source_text = " ".join(m.names + [m.raw.get("message") or m.raw.get("text") or ""])
        m.problems += check_extraction(m.extraction, source_text)
        if m.extraction.stated_contact_time and not contact_time_supported(m.extraction, source_text):
            m.notes.append(
                f"stated contact time {m.extraction.stated_contact_time!r} ignored: not in the message"
            )
            m.extraction.stated_contact_time = None

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(work, messages))


def run_callouts(engine: Engine, extractor: Extractor, start: date, end: date) -> list[dict]:
    employees = db.fetch(engine, db.hr_employees)
    by_id = {e["employee_id"]: e for e in employees}
    assignments = db.fetch(engine, db.employee_assignments)
    canonical = [b["building"] for b in db.fetch(engine, db.buildings)]
    aliases = {a["alias"]: a["building"] for a in db.fetch(engine, db.building_aliases) if a["building"]}
    site_building = {a["alias"]: a["building"] for a in db.fetch(engine, db.building_aliases)
                     if a["source"] == "dispatch_site" and a["building"]}  # fmt: skip
    postings = [p for p in db.fetch(engine, db.dispatch_postings) if (p["reason"] or "").upper() == "CALLOUT"]
    payroll_id = {x["employee_id"]: int(x["source_id"]) for x in db.fetch(engine, db.employee_xref)
                  if x["source"] == "payroll" and x["employee_id"]}  # fmt: skip
    payroll_status = {p["employee_id"]: p["status"] for p in db.fetch(engine, db.payroll_employees)}

    messages = _messages(engine)
    _extract_all(messages, extractor)

    def posting_for(employee: dict, day: date) -> dict | None:
        home = building_on(assignments, employee["employee_id"], day)
        for p in postings:
            if (p["status"] or "").upper() == "CANCELLED" or p["shift_date"] != day:
                continue
            if home and home["building"] and site_building.get(p["site_id"]) != home["building"]:
                continue
            if name_level(p["absent_employee_text"], employee) >= 1:
                return p
        return None

    events: list[dict] = []
    for m in messages:
        base = {"source": m.source, "source_ref": m.output_ref, "record_ref": m.record_ref}
        ex = m.extraction
        if ex is None:
            events.append({**base, "outcome": "unreadable", "decision": REVIEW, "confidence": "low",
                           "hold_reason": "; ".join(m.problems)})  # fmt: skip
            continue
        if not ex.is_absence:
            why = (
                "follow-up of an earlier report" if ex.follow_up_of_earlier_report else ex.not_absence_reason
            )
            events.append({**base, "outcome": "not_absence", "reason": ex.reason, "hold_reason": why,
                           "extraction": ex.model_dump()})  # fmt: skip
            continue

        contact: Contact = (log_contact if m.source == "reception_log" else chat_contact)(m.raw, ex)
        building = stated_building(ex.building, canonical, aliases)
        for ref in ex.days or [None]:
            event = {**base, "outcome": "absence", "reason": ex.reason, "name_as_written": ex.employee_name,
                     "contact_at": contact.at, "contact_basis": contact.basis, "contact_certain": contact.certain,
                     "extraction": ex.model_dump(),
                     "evidence": list(m.notes), "holds": list(m.problems)}  # fmt: skip
            events.append(event)
            dates = candidate_dates(ref, contact.at) if ref and contact.at else []
            if not dates:
                event["holds"].append("absence date could not be determined")
                continue
            match = match_employee([*m.names, ex.employee_name or ""], building, ex.shift, dates[0],
                                   employees, assignments)  # fmt: skip
            event["evidence"] += match.evidence
            employee, day, confidence = match.employee, dates[0], match.confidence

            # Ambiguous person or day: the dispatch posting made for the absence can settle it.
            if employee is None or len(dates) > 1:
                people = match.candidates or ([employee] if employee else [])
                found = [(e, d, p) for e in people for d in dates if (p := posting_for(e, d))]
                if len(found) == 1:
                    employee, day, posting = found[0]
                    confidence = "medium"
                    event["evidence"].append(
                        f"dispatch posting {posting['posting_id']} settles "
                        + (
                            f"the date ('{ref.quote}' at {contact.at:%H:%M} could be "
                            f"{' or '.join(map(str, dates))})"
                            if len(dates) > 1
                            else "the employee"
                        )
                    )
                elif employee is not None:
                    event["holds"].append(f"'{ref.quote}' could mean {', '.join(map(str, dates))}")
                else:
                    event["holds"].append("employee not identified: " + "; ".join(match.evidence))
            if employee is None:
                event["confidence"] = "low"
                continue

            home = building_on(assignments, employee["employee_id"], day)
            hr_shift = (home or {}).get("shift") or employee.get("shift")
            shift = ex.shift or (
                (hr_shift or "").lower() if (hr_shift or "").lower() in ("day", "night") else None
            )
            if shift is None and (posting := posting_for(employee, day)):
                shift = {"D": "day", "N": "night"}.get((posting["shift"] or "").upper())
            event.update(
                employee_id=employee["employee_id"],
                payroll_id=payroll_id.get(employee["employee_id"]),
                absence_date=day,
                building=(home or {}).get("building"),
                shift=shift,
                confidence=confidence,
            )

    absences = _fold_duplicates(engine, [e for e in events if e["outcome"] == "absence"])
    _code(absences, by_id, Balances.from_hr(employees))
    _payroll_guards(absences, payroll_status, start, end)
    _check_dispatch(engine, absences, postings, by_id, posting_for, site_building)

    reviews = latest_reviews(engine, "callout")
    for e in events:
        e["evidence"] = "; ".join(e.get("evidence") or [])
        e["hold_reason"] = e.get("hold_reason") or "; ".join(e.pop("holds", None) or []) or None
        e.pop("holds", None)
        if e["outcome"] == "absence" and not e.get("decision"):
            e["decision"] = REVIEW if e["hold_reason"] else WRITE
            _apply_review(e, reviews.get(event_key(e)))
        _report(engine, e)
    columns = [c.name for c in db.callout_events.columns if c.name != "id"]
    db.insert_rows(engine, db.callout_events, [{c: e.get(c) for c in columns} for e in events])
    log.info("call-outs: %s", dict(Counter(e["outcome"] for e in events)))
    return db.fetch(engine, db.callout_events)


def _apply_review(e: dict, review: dict | None) -> None:
    """A person's decision in the review queue overrides the hold (approve) or confirms it (dismiss)."""
    if review is None or e["decision"] != REVIEW:
        return
    note = f" ({review['note']})" if review.get("note") else ""
    if review["action"] == "approve" and e.get("payroll_id") and e.get("code"):
        e["decision"] = WRITE
        e["evidence"] = "; ".join(
            filter(None, [e["evidence"], f"held ({e['hold_reason']}), approved by reviewer{note}"])
        )
        e["hold_reason"] = None
    elif review["action"] == "dismiss":
        e["hold_reason"] = f"dismissed by reviewer{note}; was: {e['hold_reason']}"


def _fold_duplicates(engine: Engine, absences: list[dict]) -> list[dict]:
    """One absence per employee per date: the earliest report is kept, the others point to it."""
    kept: dict[tuple, dict] = {}
    for e in sorted(absences, key=lambda e: e.get("contact_at") or datetime.max):
        key = (e.get("employee_id"), e.get("absence_date"))
        if None in key:
            continue
        if key in kept:
            first = kept[key]
            e.update(outcome="duplicate", duplicate_of=f"{first['source']} {first['source_ref']}")
            continue
        kept[key] = e
    return [e for e in absences if e["outcome"] == "absence"]


def _code(absences: list[dict], by_id: dict[str, dict], balances: Balances) -> None:
    """Article 14 coding in date order (earlier sick days reduce later balances)."""
    order = sorted(
        absences, key=lambda e: (e.get("absence_date") or date.max, e.get("contact_at") or datetime.max)
    )
    for e in order:
        if not e.get("employee_id") or not e.get("absence_date"):
            continue
        notice = (
            notice_hours(e["contact_at"], e["absence_date"], e["shift"]) if e.get("shift") and e.get("contact_at")
            else None
        )  # fmt: skip
        e["notice_hours"] = round(notice, 2) if notice is not None else None
        coding = code_absence(e["reason"], by_id[e["employee_id"]], e["absence_date"], notice, balances)
        e["code"], e["code_reason"] = coding.code, coding.why
        if coding.hold:
            e["holds"].append(coding.hold)
        if e["reason"] == "bereavement" and not is_immediate_family(e["extraction"].get("family_member")):
            e["holds"].append(
                f"bereavement relative {e['extraction'].get('family_member')!r} not verified (14.5)"
            )
        if notice is None and coding.code in ("SKP", "CLN", "BRV", "LTN"):
            e["holds"].append("shift unknown, notice cannot be measured")
        if not e["contact_certain"] and coding.code in ("SKP", "CLN", "BRV", "LTN"):
            e["evidence"].append(f"notice measured from the {e['contact_basis']}")
            if coding.code == "LTN":
                e["holds"].append("late notice measured from an uncertain call time")
            elif e.get("confidence") == "high":
                e["confidence"] = "medium"


def _payroll_guards(absences: list[dict], payroll_status: dict, start: date, end: date) -> None:
    for e in absences:
        day = e.get("absence_date")
        if day and not start <= day <= end:
            e["holds"].append(f"{day} is outside the open pay period")
        if day and day.weekday() not in WORKDAYS:
            e["holds"].append(f"{day:%A} is not a scheduled shift day (14.1)")
        if e.get("employee_id"):
            if e.get("payroll_id") is None:
                e["holds"].append("employee has no payroll record")
            elif (status := payroll_status.get(e["payroll_id"])) != "ACTIVE":
                e["holds"].append(f"payroll status is {status}")
        if e.get("confidence") == "low":
            e["holds"].append("low confidence")


def _check_dispatch(engine, absences, postings, by_id, posting_for, site_building) -> None:
    """Each absence should have a call-out posting, and each posting an absence."""
    used = set()
    for e in absences:
        if not e.get("employee_id") or not e.get("absence_date"):
            continue
        posting = posting_for(by_id[e["employee_id"]], e["absence_date"])
        if posting:
            used.add(posting["posting_id"])
            e["posting_id"] = posting["posting_id"]
        else:
            e["evidence"].append("no dispatch posting")
            db.add_exception(engine, f"callout:{e['source']}", f"{e['source_ref']} ({e['record_ref']})",
                             f"no dispatch call-out posting for {e['employee_id']} on {e['absence_date']}",
                             "decided from the message alone", "medium")  # fmt: skip
    for p in postings:
        if (p["status"] or "").upper() != "CANCELLED" and p["posting_id"] not in used:
            db.add_exception(engine, "dispatch", p["source_ref"],
                             f"call-out posting for {p['absent_employee_text']!r} on {p['shift_date']} "
                             f"at {site_building.get(p['site_id'], p['site_id'])} has no call-out record",
                             "no payroll entry made from dispatch alone", "medium")  # fmt: skip


def _report(engine: Engine, e: dict) -> None:
    ref = f"{e['source_ref']} ({e['record_ref']})"
    source = f"callout:{e['source']}"
    if e["outcome"] == "not_absence" and e["source"] == "reception_log":
        # Every log row is a call about attendance, so one that is not an absence is worth listing.
        # Ordinary chat conversation is kept in callout_events but is not an exception.
        db.add_exception(
            engine, source, ref, f"not an absence: {e['hold_reason']}", "not sent to payroll", "high"
        )
    elif e["outcome"] == "duplicate":
        db.add_exception(engine, source, ref,
                         f"same absence as {e['duplicate_of']} ({e.get('employee_id')} on {e.get('absence_date')})",
                         "counted once; not sent to payroll again", "high")  # fmt: skip
    elif e.get("decision") == REVIEW:
        db.add_exception(engine, source, ref, e["hold_reason"], "held for review, not sent to payroll",
                         e.get("confidence") or "low")  # fmt: skip
    elif e.get("confidence") == "medium":
        db.add_exception(engine, source, ref, f"{e['name_as_written']!r} -> {e['employee_id']}: {e['evidence']}",
                         f"written to payroll as {e.get('code')} for {e['absence_date']}", "medium")  # fmt: skip


def callout_shifts(events: list[dict], start: date, end: date) -> Counter:
    """KPI: one call-out shift per employee per date, at the building they were assigned to that day."""
    return Counter(
        e["building"]
        for e in events
        if e["outcome"] == "absence" and e.get("building") and e.get("absence_date")
        and start <= e["absence_date"] <= end
    )  # fmt: skip
