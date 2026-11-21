"""The two backup note templates of docs/backup_note_templates.md.

Neither template ever names the absent employee or says why they were absent: the absent
employee only contributes their job class ("Position covered").
"""

from datetime import datetime, timedelta

from northgate.callouts.rules import SHIFT_HOURS, SHIFT_START

LABEL_WIDTH = 19  # "Posting reference: " - the values line up as in the templates


def _line(label: str, value: object) -> str:
    return f"{label + ':':<{LABEL_WIDTH}}{value}"


def _clock(moment: datetime | None) -> str:
    return f"{moment:%H:%M}" if moment else "Not recorded"


def scheduled_hours(shift: str) -> str:
    """'Night, 16:00 to 00:00' (Article 14.1)."""
    start = datetime.combine(datetime.min.date(), SHIFT_START[shift])
    end = start + timedelta(hours=SHIFT_HOURS)
    return f"{shift.title()}, {start:%H:%M} to {end:%H:%M}"


def template_a(c: dict) -> str:
    """Full detail: replacement's name and actual time on site."""
    return "\n".join([
        "COVERAGE BACKUP NOTE",
        _line("Client", c["client_name"]),
        _line("Building", c["building"]),
        _line("Date of service", f"{c['shift_date']:%m/%d/%Y}"),
        _line("Shift", scheduled_hours(c["shift"])),
        _line("Position covered", c["position_covered"]),
        _line("Coverage type", "Overtime" if c["overtime"] else "Replacement"),
        _line("Replacement", c["covering_name"]),
        _line("On site", f"{_clock(c['on_site_in'])} to {_clock(c['on_site_out'])}"),
        _line("Billable hours", f"{SHIFT_HOURS:.2f}"),
        _line("Billable amount", f"${c['billable_amount']:,.2f}"),
        _line("Posting reference", c["posting_id"]),
    ]) + "\n"  # fmt: skip


def template_b(c: dict) -> str:
    """No names: confirms that coverage was provided."""
    return "\n".join([
        "COVERAGE BACKUP NOTE",
        _line("Client", c["client_name"]),
        _line("Building", c["building"]),
        _line("Date of service", f"{c['shift_date']:%m/%d/%Y}"),
        _line("Shift", c["shift"].title()),
        _line("Position covered", c["position_covered"]),
        _line("Coverage", "Replacement provided"),
        _line("Billable hours", f"{SHIFT_HOURS:.2f}"),
        _line("Billable amount", f"${c['billable_amount']:,.2f}"),
        _line("Posting reference", c["posting_id"]),
    ]) + "\n"  # fmt: skip


TEMPLATES = {"A": template_a, "B": template_b}
