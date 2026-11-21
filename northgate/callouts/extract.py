"""Claude reads one call-out message into a fixed schema; code checks the answer against the text.

Claude only reports what the message says (who, why, which days in the caller's own words, any time
the caller mentions). It never computes dates, codes or pay: those are deterministic code in
events.py and rules.py.
"""

import re
from typing import Literal

from pydantic import BaseModel, Field

from northgate.llm import Extractor, text_block
from northgate.resolve.names import fold

Weekday = Literal["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


class DayReference(BaseModel):
    quote: str = Field(
        description="The exact words in the message that name the day, e.g. 'tonight', 'mañana'"
    )
    kind: Literal["today", "tonight", "tomorrow", "weekday", "date"]
    weekday: Weekday | None = Field(None, description="Only for kind='weekday'")
    date: str | None = Field(
        None, description="Only for kind='date': YYYY-MM-DD, when a full date is written"
    )


class CalloutExtraction(BaseModel):
    is_absence: bool = Field(description="True only if an employee reports missing one or more whole shifts")
    follow_up_of_earlier_report: bool = Field(
        description="True if the message only confirms, repeats or refers back to an earlier report"
    )
    not_absence_reason: str | None = Field(None, description="When is_absence is false: why, in a few words")
    employee_name: str | None = Field(None, description="The absent employee's name exactly as written")
    reason: Literal[
        "own_illness",
        "family_illness",
        "family_emergency",
        "medical_appointment",
        "bereavement",
        "jury_duty",
        "personal",
        "late_arrival",
        "other",
    ]
    family_member: str | None = Field(None, description="For bereavement: the relative named, e.g. 'father'")
    building: str | None = Field(None, description="The building as written, or null")
    shift: Literal["day", "night"] | None = None
    days: list[DayReference] = Field(default_factory=list)
    stated_contact_time: str | None = Field(
        None, description="HH:MM (24h) if the message says when the employee called, texted or left it"
    )


INSTRUCTIONS = """You read one attendance message for a building services company: either a row of the \
reception call-out log (typed by reception, voicemails transcribed the next morning) or a message from \
the area managers' group chat. Messages can be in English, Spanish, Albanian or other languages.

Report only what the message says. Do not work out calendar dates, pay codes or entitlements.

- is_absence: true if the message reports that an employee will miss (or missed) one or more whole \
shifts, even if it says the employee also told someone else (repeated reports are removed later). \
False for questions (payroll, keys, schedules), lateness when the employee will still come in, \
operational chatter, acknowledgements ('got it'), and messages that add no absence of their own.
- follow_up_of_earlier_report: true only when is_absence is false because the message just confirms \
or refers back to an earlier report ('called back to confirm the call-out from earlier').
- employee_name: the absent employee as written. For a log row, combine the Caller column and the \
message (prefer the fuller form, e.g. 'Fatmire Berisha' over 'F. Berisha'). In the chat the author is \
usually a manager passing on an employee's message: give the employee, never the author.
- reason: own_illness (the employee is sick); family_illness (a child or other relative is sick); \
family_emergency (another urgent family matter); medical_appointment (clinic or doctor appointment, \
'clinic day'); bereavement (a death in the family); jury_duty; personal (a personal day); \
late_arrival; other.
- family_member: for bereavement only, the relative who died as written ('father').
- building: as written, or null if none is named ('the building' is not a name).
- shift: 'day' or 'night' when the message states it ('I work nights', 'turno de día', 'night shift') \
or says the absence is tonight. Otherwise null.
- days: one entry per day the employee will miss, in the message's order. quote = the exact words \
naming that day, copied from the message. kind = today (today, this morning, hoy, sot), tonight \
(tonight, esta noche, sonte), tomorrow (tomorrow, mañana, nesër), weekday (a named weekday: set \
weekday), date (a written calendar date: set date). 'Out tonight and Friday' gives two entries. Empty \
list if no day is named.
- stated_contact_time: only if the message text itself says at what time the employee called, texted \
or left the voicemail ('it's about 11 in the morning', 'texted me around 10:32'): that time as HH:MM, 24-hour. \
Never a shift or appointment time."""


def describe_log_row(row: dict) -> str:
    """Only what reception typed. Timestamps are left out on purpose: Claude does not need them, and
    without them it cannot copy a phone timestamp into `stated_contact_time`."""
    return "\n".join(
        [
            "Source: reception call-out log",
            f"Channel: {row.get('channel') or ''}",
            f"Caller: {row.get('caller') or ''}",
            f"Message: {row.get('message') or ''}",
        ]
    )


def describe_chat_message(message: dict) -> str:
    return "\n".join(
        [
            "Source: area managers' group chat",
            f"Author: {message.get('author') or ''}",
            f"Message: {message.get('text') or ''}",
        ]
    )


def extract_callout(description: str, extractor: Extractor) -> CalloutExtraction:
    return extractor.extract(CalloutExtraction, INSTRUCTIONS, [text_block("message", description)])


def check_extraction(extraction: CalloutExtraction, source_text: str) -> list[str]:
    """Things Claude reported that the message does not support. Empty list = consistent."""
    problems = []
    text = fold(source_text)
    words = set(text.split())
    for day in extraction.days:
        if fold(day.quote) not in text:
            problems.append(f"day words {day.quote!r} are not in the message")
        if day.kind == "weekday" and day.weekday is None:
            problems.append(f"day {day.quote!r} is a weekday without a weekday name")
    if extraction.employee_name:
        name_words = [w for w in fold(extraction.employee_name).split() if len(w) > 1]
        if name_words and not any(w in words for w in name_words):
            problems.append(f"name {extraction.employee_name!r} is not in the message")
    if extraction.is_absence and not extraction.days:
        problems.append("absence with no day named")
    return problems


def contact_time_supported(extraction: CalloutExtraction, source_text: str) -> bool:
    """A stated contact time is only used if its hour is written in the message."""
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", extraction.stated_contact_time or "")
    if not match:
        return False
    hour = int(match[1])
    return bool({str(hour), str(hour % 12 or 12)} & set(re.findall(r"\d+", source_text)))
