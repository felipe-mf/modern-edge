"""From extracted messages to absence events: when notice was given, which day, which employee.

All deterministic. Each helper returns its answer plus the evidence it used, so the decision can be
shown to a reviewer and written to the exceptions list when it is not certain.
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from northgate.callouts.extract import CalloutExtraction, DayReference
from northgate.callouts.rules import SHIFT_START
from northgate.resolve.employees import building_on
from northgate.resolve.names import best_building_match, fold, name_tokens

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
EARLIEST_SHIFT_START = min(SHIFT_START.values())


# --- when the call-out was received (14.2: notice is measured from that moment) ------------------


@dataclass
class Contact:
    at: datetime | None
    basis: str
    certain: bool = True


def _stated_time(extraction: CalloutExtraction, day: date) -> datetime | None:
    if not extraction.stated_contact_time:
        return None
    hour, minute = (int(p) for p in extraction.stated_contact_time.split(":"))
    return datetime.combine(day, time(hour, minute))


def parse_voicemail_stamp(raw: str | None, log_date: date) -> datetime | None:
    """'10/05 22:00' has no year: take the log date's year, or the year before if that would put
    the voicemail after the day reception logged it (a late-December voicemail logged in January)."""
    match = re.fullmatch(r"\s*(\d{1,2})/(\d{1,2})(?:/\d{2,4})?\s+(\d{1,2}):(\d{2})\s*", raw or "")
    if not match:
        return None
    month, day, hour, minute = (int(g) for g in match.groups())
    stamp = datetime(log_date.year, month, day, hour, minute)
    if stamp.date() > log_date:
        stamp = stamp.replace(year=log_date.year - 1)
    return stamp


def is_voicemail(row: dict) -> bool:
    return "VOICE" in fold(row.get("channel")) or bool(row.get("vm_received_raw"))


def log_contact(row: dict, extraction: CalloutExtraction) -> Contact:
    if not is_voicemail(row):
        return Contact(row["logged_at"], "time reception logged the call")
    stamp = parse_voicemail_stamp(row.get("vm_received_raw"), row["log_date"])
    if stamp:
        return Contact(stamp, "voicemail timestamp")
    stated = _stated_time(extraction, row["log_date"])
    if stated and (row["logged_at"] is None or stated <= row["logged_at"]):
        return Contact(stated, "time the caller states in the voicemail (no phone timestamp)", certain=False)
    # Without any timestamp the time reception logged it is the latest the message can have arrived.
    return Contact(row["logged_at"], "time reception logged the voicemail (no timestamp)", certain=False)


def chat_contact(message: dict, extraction: CalloutExtraction) -> Contact:
    sent = message["sent_at_local"]
    stated = _stated_time(extraction, sent.date())
    if stated and stated <= sent:
        return Contact(stated, "time the employee texted the manager, as the manager states")
    return Contact(sent, "time the message was posted")


# --- which day ----------------------------------------------------------------------------------


def candidate_dates(ref: DayReference, contact: datetime) -> list[date]:
    """Possible dates for a day reference, most likely first. More than one = ambiguous."""
    today = contact.date()
    if ref.kind in ("today", "tonight"):
        return [today]
    if ref.kind == "tomorrow":
        # Before the first shift of the day, "tomorrow" may mean the day that has just begun.
        if contact.time() < EARLIEST_SHIFT_START:
            return [today + timedelta(days=1), today]
        return [today + timedelta(days=1)]
    if ref.kind == "weekday" and ref.weekday:
        ahead = (WEEKDAYS.index(ref.weekday) - today.weekday()) % 7
        if ahead == 0:
            return [today, today + timedelta(days=7)]
        return [today + timedelta(days=ahead)]
    if ref.kind == "date" and ref.date:
        try:
            return [date.fromisoformat(ref.date)]
        except ValueError:
            return []
    return []


# --- which employee -----------------------------------------------------------------------------


NAME_LEVELS = {3: "full name", 2: "name with an initial", 1: "first name only"}


def name_level(text: str | None, employee: dict) -> int:
    """3 = first and last name; 2 = one of them as an initial; 1 = first name only; 0 = no match."""
    tokens = name_tokens(text)
    first = fold(employee.get("first_name")).split()
    last = fold(employee.get("last_name")).split()
    if not tokens or not first:
        return 0
    has_first = all(w in tokens for w in first)
    has_last = bool(last) and all(w in tokens for w in last)
    first_initial = any(t == first[0][0] for t in tokens if len(t) == 1)
    last_initial = bool(last) and any(t == last[0][0] for t in tokens if len(t) == 1)
    if has_first and has_last:
        return 3
    if (has_first and last_initial) or (has_last and first_initial):
        return 2
    if has_first and set(tokens) <= set(first):
        return 1
    return 0


@dataclass
class Match:
    employee: dict | None
    confidence: str  # high / medium / low
    evidence: list[str] = field(default_factory=list)
    candidates: list[dict] = field(default_factory=list)  # set when ambiguous


def match_employee(
    names: list[str],
    building: str | None,
    shift: str | None,
    day: date,
    employees: list[dict],
    assignments: list[dict],
) -> Match:
    """Name first, then the building and shift the caller gave, among people employed that day."""
    employed = [e for e in employees if building_on(assignments, e["employee_id"], day)]
    scored = [(max((name_level(n, e) for n in names), default=0), e) for e in employed]
    best = max((s for s, _ in scored), default=0)
    if best == 0:
        return Match(None, "low", [f"no employee employed on {day} matches {names}"])
    pool = [e for s, e in scored if s == best]
    evidence = [f"identified by {NAME_LEVELS[best]}"]

    def narrow(pool: list[dict], keep, label: str) -> list[dict]:
        kept = [e for e in pool if keep(e)]
        if kept:
            if len(kept) < len(pool):
                evidence.append(f"{label} narrows {len(pool)} to {len(kept)}")
            return kept
        evidence.append(f"{label} matches none of the {len(pool)} candidates")
        return pool

    if building:
        pool = narrow(pool, lambda e: building_on(assignments, e["employee_id"], day)["building"] == building,
                      f"building {building}")  # fmt: skip
    if shift:

        def works_shift(e: dict) -> bool:
            assigned = building_on(assignments, e["employee_id"], day)["shift"] or e.get("shift")
            return (assigned or "").lower() in (shift, "flex")

        pool = narrow(pool, works_shift, f"{shift} shift")

    if len(pool) > 1:
        ids = ", ".join(e["employee_id"] for e in pool)
        return Match(None, "low", evidence + [f"{len(pool)} employees match ({ids})"], candidates=pool)
    conflict = any("matches none" in line for line in evidence)
    confidence = "high" if best >= 2 and not conflict else "medium"
    if best == 1 and not building:
        confidence = "medium"
    return Match(pool[0], confidence, evidence)


def stated_building(text: str | None, canonical: list[str], aliases: dict[str, str]) -> str | None:
    """A building the caller named, as the canonical (contract) name."""
    if not text:
        return None
    if text in aliases:
        return aliases[text]
    building, _ = best_building_match(text, canonical)
    return building
