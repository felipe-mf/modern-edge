"""Article 14 of the CBA and the employer's payroll coding guide, as code.

Every number here is quoted from docs/union_rules.pdf, with its section. The coding order is the one
the guide prescribes: eligibility (14.10 and the 14.3 probation period), then notice (14.9), then the
employee's remaining balance. Absences are applied in date order, so earlier sick days reduce the
balance available to later ones.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from northgate.resolve.names import fold

# 14.1: day shift 7:00 a.m. to 3:00 p.m., night shift 4:00 p.m. to midnight, Monday to Friday, 8 paid hours.
SHIFT_START = {"day": time(7, 0), "night": time(16, 0)}
SHIFT_HOURS = 8
WORKDAYS = range(5)  # Monday..Friday as date.weekday()
# 14.2: notice at least four hours before the start of the shift.
NOTICE_HOURS = 4
# 14.3: paid sick leave after ninety calendar days of employment.
PROBATION_DAYS = 90
# 14.5: up to three paid bereavement days, for these relatives.
BEREAVEMENT_DAYS = 3
IMMEDIATE_FAMILY = {
    "SPOUSE", "HUSBAND", "WIFE", "PARTNER", "DOMESTIC PARTNER", "CHILD", "SON", "DAUGHTER", "PARENT",
    "FATHER", "MOTHER", "DAD", "MOM", "SIBLING", "BROTHER", "SISTER", "GRANDPARENT", "GRANDFATHER",
    "GRANDMOTHER", "GRANDMA", "GRANDPA",
}  # fmt: skip

REASONS = (
    "own_illness",
    "family_illness",
    "family_emergency",
    "medical_appointment",
    "bereavement",
    "jury_duty",
    "personal",
    "late_arrival",
    "other",
)


def shift_start(day: date, shift: str) -> datetime:
    return datetime.combine(day, SHIFT_START[shift])


def notice_hours(contact: datetime, day: date, shift: str) -> float:
    return (shift_start(day, shift) - contact) / timedelta(hours=1)


def in_bargaining_unit(employee: dict) -> bool:
    """14.10: sick leave and clinic days do not apply to non-union or temporary employees."""
    return bool(employee.get("union_member")) and (employee.get("employment_type") or "").upper() != "TEMP"


def past_probation(employee: dict, day: date) -> bool:
    """14.3: has completed ninety calendar days of employment on the day of the absence."""
    hired = employee.get("hire_date")
    return hired is not None and (day - hired).days >= PROBATION_DAYS


@dataclass
class Balances:
    """What each employee has left, updated as absences are coded in date order."""

    sick_days: dict[str, int] = field(default_factory=dict)
    clinic_used: dict[str, bool] = field(default_factory=dict)
    bereavement_used: dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_hr(cls, employees: list[dict]) -> "Balances":
        return cls(
            sick_days={e["employee_id"]: e.get("sick_days_remaining") or 0 for e in employees},
            clinic_used={e["employee_id"]: bool(e.get("clinic_day_used")) for e in employees},
        )


@dataclass
class Coding:
    code: str | None
    why: str
    hold: str | None = None  # set when the rules cannot decide safely


def code_absence(reason: str, employee: dict, day: date, notice: float | None, balances: Balances) -> Coding:
    """The payroll code for one absence. Updates `balances` when a paid day is used."""
    emp = employee["employee_id"]
    eligible = in_bargaining_unit(employee)
    probation_done = past_probation(employee, day)
    notice_ok = notice is not None and notice >= NOTICE_HOURS
    notice_text = "notice unknown" if notice is None else f"notice {notice:.1f}h"

    if reason == "jury_duty":
        return Coding("JRY", "jury service; no notice requirement (14.6)")
    if reason in ("family_illness", "family_emergency"):
        return Coding("FEM", "family illness or emergency, unpaid (14.7)")
    if reason == "personal":
        return Coding("PER", "personal day, unpaid (14.8)")

    if reason == "own_illness":
        if not eligible:
            return Coding("SKU", "not in the bargaining unit, no paid sick leave (14.10)")
        if not probation_done:
            return Coding("SKU", f"fewer than {PROBATION_DAYS} days of employment (14.3)")
        if not notice_ok:
            return Coding("LTN", f"{notice_text}, less than {NOTICE_HOURS}h (14.9)")
        left = balances.sick_days.get(emp, 0)
        if left <= 0:
            return Coding("SKU", "no paid sick days left (14.3)")
        balances.sick_days[emp] = left - 1
        return Coding("SKP", f"{notice_text}; sick day used, {left - 1} left (14.3)")

    if reason == "medical_appointment":
        if not eligible or not probation_done:
            return Coding("PER", "clinic visit by an employee not eligible for a clinic day (14.4, 14.10)")
        if not notice_ok:
            return Coding("LTN", f"{notice_text}, less than {NOTICE_HOURS}h (14.9)")
        if balances.clinic_used.get(emp):
            return Coding("PER", "clinic day already used this year (14.4); unpaid like a personal day")
        balances.clinic_used[emp] = True
        return Coding("CLN", f"{notice_text}; annual clinic day (14.4)")

    if reason == "bereavement":
        if not notice_ok:
            return Coding("LTN", f"{notice_text}, less than {NOTICE_HOURS}h (14.9)")
        used = balances.bereavement_used.get(emp, 0)
        if used >= BEREAVEMENT_DAYS:
            return Coding(
                "PER", "paid bereavement days exhausted", hold=f"more than {BEREAVEMENT_DAYS} days (14.5)"
            )
        balances.bereavement_used[emp] = used + 1
        return Coding("BRV", f"{notice_text}; bereavement day {used + 1} of {BEREAVEMENT_DAYS} (14.5)")

    return Coding(None, f"reason '{reason}' is not an Article 14 absence", hold="reason needs a person")


def is_immediate_family(relative: str | None) -> bool:
    return fold(relative) in IMMEDIATE_FAMILY
