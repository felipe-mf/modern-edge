"""Raw call-out sources: the reception spreadsheet and the managers' chat export.

These parsers only structure the text (who, when, what was written). Deciding whether a message
is an absence, for whom and for which date is done later by the call-out step, because it needs
the language model and the rest of the data.
"""

import re
from datetime import datetime, time
from pathlib import Path

import openpyxl

from northgate.ingest.common import clean_text, normalize_header, parse_date

# --- reception call-out log (xlsx) ------------------------------------------------------------

REQUIRED_LOG_COLUMNS = {"date", "caller", "message"}


def _parse_time(value: object) -> time | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.time()
    if isinstance(value, time):
        return value
    text = str(value).strip().upper()
    for fmt in ("%I:%M %p", "%I:%M%p", "%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    raise ValueError(f"Unrecognised time: {value!r}")


def parse_callout_log(path: Path) -> tuple[list[dict], list[str]]:
    """Every sheet is scanned for a header row with Date, Caller and Message columns."""
    rows, issues = [], []
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    for sheet in workbook.worksheets:
        header: list[str] | None = None
        for row_no, values in enumerate(sheet.iter_rows(values_only=True), start=1):
            if header is None:
                names = [normalize_header(v) for v in values]
                if REQUIRED_LOG_COLUMNS <= set(names):
                    header = names
                continue
            if not any(v not in (None, "") for v in values):
                continue
            row = dict(zip(header, values))
            ref = f"{path.name} [{sheet.title}] row {row_no}"
            try:
                log_date = parse_date(row.get("date"))
                log_time = _parse_time(row.get("time"))
            except ValueError as exc:
                issues.append(f"{ref}: {exc}")
                continue
            rows.append(
                {
                    "logged_at": datetime.combine(log_date, log_time) if log_date and log_time else None,
                    "log_date": log_date,
                    "taken_by": clean_text(row.get("taken_by")),
                    "channel": clean_text(row.get("channel")),
                    # Kept as typed ("10/02 00:21"): it has no year, which is filled in later
                    # from the log date.
                    "vm_received_raw": clean_text(row.get("vm_received")),
                    "caller": clean_text(row.get("caller")),
                    "message": clean_text(row.get("message")),
                    "sent_to_ops": clean_text(row.get("sent_to_ops")),
                    "source_ref": ref,
                }
            )
        if header is None:
            issues.append(f"{path.name} [{sheet.title}]: no header row with Date, Caller and Message")
    workbook.close()
    return rows, issues


# --- managers' group chat export (WhatsApp-style text) ----------------------------------------

_CHAT_LINE = re.compile(
    r"^\[(?P<date>\d{1,2}/\d{1,2}/\d{2,4}),\s*(?P<time>\d{1,2}:\d{2}(?::\d{2})?\s*[AaPp][Mm])\]\s*(?P<rest>.*)$"
)
# "Name: text". Names are short; this keeps "Note: something" in a system line from matching.
_AUTHOR = re.compile(r"^(?P<author>[^:]{1,60}?):\s(?P<text>.*)$")


def _chat_timestamp(day: str, clock: str) -> datetime:
    clock = clock.upper().replace(" ", "")
    for date_fmt in ("%m/%d/%y", "%m/%d/%Y"):
        for time_fmt in ("%I:%M:%S%p", "%I:%M%p"):
            try:
                return datetime.strptime(f"{day} {clock}", f"{date_fmt} {time_fmt}")
            except ValueError:
                continue
    raise ValueError(f"Unrecognised chat timestamp: {day} {clock}")


def parse_chat_export(path: Path) -> list[dict]:
    """One dict per message. Lines without a timestamp continue the previous message.

    The export has no time zone; `sent_at_local` is the phone's wall-clock time as printed.
    """
    messages: list[dict] = []
    for line_no, raw_line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        line = clean_text(raw_line)
        if not line:
            continue
        match = _CHAT_LINE.match(line)
        if not match:
            if messages:
                messages[-1]["text"] += "\n" + line
            continue
        author_match = _AUTHOR.match(match["rest"])
        messages.append(
            {
                "sent_at_local": _chat_timestamp(match["date"], match["time"]),
                "author": author_match["author"].strip() if author_match else None,  # None = system line
                "text": author_match["text"] if author_match else match["rest"],
                "source_ref": f"{path.name} line {line_no}",
            }
        )
    return messages
