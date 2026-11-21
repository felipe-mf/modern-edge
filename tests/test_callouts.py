"""Call-out rules on small invented cases: notice time, dates, names, Article 14 coding."""

from datetime import date, datetime

from northgate.callouts.events import (
    candidate_dates,
    chat_contact,
    log_contact,
    match_employee,
    name_level,
    parse_voicemail_stamp,
)
from northgate.callouts.extract import (
    CalloutExtraction,
    DayReference,
    check_extraction,
    contact_time_supported,
)
from northgate.callouts.rules import Balances, code_absence, notice_hours

# Wednesday 2025-03-05 is the reference day in these tests.
WED = date(2025, 3, 5)


def _extraction(**fields) -> CalloutExtraction:
    return CalloutExtraction(**{"is_absence": True, "follow_up_of_earlier_report": False, "reason": "own_illness",
                                **fields})  # fmt: skip


def _employee(employee_id="E1", *, union=True, kind="PERMANENT", hired=date(2015, 1, 1), first="Ana", last="Silva",
              shift="NIGHT", sick=2, clinic=False):  # fmt: skip
    return {"employee_id": employee_id, "union_member": union, "employment_type": kind, "hire_date": hired,
            "first_name": first, "last_name": last, "shift": shift, "sick_days_remaining": sick,
            "clinic_day_used": clinic}  # fmt: skip


# --- notice time ----------------------------------------------------------------------------------


def test_voicemail_stamp_takes_year_from_log_and_rolls_back_over_new_year():
    assert parse_voicemail_stamp("03/04 22:10", WED) == datetime(2025, 3, 4, 22, 10)
    assert parse_voicemail_stamp("12/31 23:00", date(2025, 1, 2)) == datetime(2024, 12, 31, 23, 0)
    assert parse_voicemail_stamp("", WED) is None


def test_voicemail_uses_phone_stamp_then_stated_time_then_logged_time():
    row = {"channel": "Voicemail", "vm_received_raw": "03/05 01:00", "log_date": WED,
           "logged_at": datetime(2025, 3, 5, 8, 40)}  # fmt: skip
    assert log_contact(row, _extraction()).at == datetime(2025, 3, 5, 1, 0)

    no_stamp = {**row, "vm_received_raw": None}
    stated = log_contact(no_stamp, _extraction(stated_contact_time="07:15"))
    assert (stated.at, stated.certain) == (datetime(2025, 3, 5, 7, 15), False)
    fallback = log_contact(no_stamp, _extraction())
    assert (fallback.at, fallback.certain) == (datetime(2025, 3, 5, 8, 40), False)


def test_chat_uses_the_time_the_employee_texted_when_stated():
    message = {"sent_at_local": datetime(2025, 3, 5, 13, 0)}
    assert chat_contact(message, _extraction(stated_contact_time="10:30")).at == datetime(2025, 3, 5, 10, 30)
    assert chat_contact(message, _extraction()).at == datetime(2025, 3, 5, 13, 0)


def test_stated_time_must_be_written_in_the_message():
    assert contact_time_supported(_extraction(stated_contact_time="11:00"), "it's about 11 in the morning")
    assert not contact_time_supported(_extraction(stated_contact_time="04:34"), "won't be in today")


# --- dates ----------------------------------------------------------------------------------------


def _ref(kind, weekday=None):
    return DayReference(quote="x", kind=kind, weekday=weekday)


def test_relative_days_count_from_the_call_time():
    evening = datetime(2025, 3, 5, 21, 0)
    assert candidate_dates(_ref("tonight"), evening) == [WED]
    assert candidate_dates(_ref("tomorrow"), evening) == [date(2025, 3, 6)]
    assert candidate_dates(_ref("weekday", "monday"), evening) == [date(2025, 3, 10)]


def test_tomorrow_after_midnight_is_ambiguous():
    assert candidate_dates(_ref("tomorrow"), datetime(2025, 3, 5, 0, 25)) == [date(2025, 3, 6), WED]


def test_same_weekday_is_ambiguous():
    assert candidate_dates(_ref("weekday", "wednesday"), datetime(2025, 3, 5, 9, 0)) == [
        WED,
        date(2025, 3, 12),
    ]


# --- people ---------------------------------------------------------------------------------------


def test_name_levels():
    ana = _employee()
    assert name_level("Ana Silva", ana) == 3
    assert name_level("Silva, Ana", ana) == 3
    assert name_level("Ana S.", ana) == 2
    assert name_level("A. Silva", ana) == 2
    assert name_level("Ana", ana) == 1
    assert name_level("Ana Costa", ana) == 0


def test_same_name_is_settled_by_building_and_unknown_building_stays_ambiguous():
    twins = [_employee("E1"), _employee("E2")]
    assignments = [
        {"employee_id": "E1", "building": "North", "shift": "NIGHT", "start_date": None, "end_date": None},
        {"employee_id": "E2", "building": "South", "shift": "NIGHT", "start_date": None, "end_date": None},
    ]
    assert (
        match_employee(["Ana Silva"], "South", "night", WED, twins, assignments).employee["employee_id"]
        == "E2"
    )
    unclear = match_employee(["Ana Silva"], None, "night", WED, twins, assignments)
    assert unclear.employee is None and len(unclear.candidates) == 2


def test_extraction_check_rejects_words_not_in_the_message():
    ok = _extraction(employee_name="Ana", days=[DayReference(quote="mañana", kind="tomorrow")])
    assert check_extraction(ok, "Ana: no puedo ir mañana") == []
    invented = _extraction(employee_name="Ana", days=[DayReference(quote="tonight", kind="tonight")])
    assert check_extraction(invented, "Ana: no puedo ir mañana")


# --- Article 14 coding ----------------------------------------------------------------------------


def _code(reason, employee, notice, balances=None, day=WED):
    balances = balances or Balances.from_hr([employee])
    return code_absence(reason, employee, day, notice, balances).code


def test_notice_is_measured_to_the_shift_start():
    assert notice_hours(datetime(2025, 3, 5, 12, 0), WED, "night") == 4.0
    assert notice_hours(datetime(2025, 3, 5, 4, 30), WED, "day") == 2.5


def test_sick_order_eligibility_then_notice_then_balance():
    assert _code("own_illness", _employee(), 5) == "SKP"
    assert _code("own_illness", _employee(), 3.9) == "LTN"
    assert _code("own_illness", _employee(sick=0), 5) == "SKU"
    assert _code("own_illness", _employee(union=False), 1) == "SKU"  # not eligible beats late notice
    assert _code("own_illness", _employee(kind="TEMP"), 5) == "SKU"
    assert _code("own_illness", _employee(hired=date(2025, 1, 1)), 5) == "SKU"  # 63 days: probation


def test_sick_days_are_used_in_date_order():
    ana = _employee(sick=1)
    balances = Balances.from_hr([ana])
    assert _code("own_illness", ana, 5, balances, date(2025, 3, 3)) == "SKP"
    assert _code("own_illness", ana, 5, balances, date(2025, 3, 10)) == "SKU"


def test_late_notice_does_not_use_a_sick_day():
    ana = _employee(sick=1)
    balances = Balances.from_hr([ana])
    assert _code("own_illness", ana, 2, balances) == "LTN"
    assert _code("own_illness", ana, 5, balances) == "SKP"


def test_clinic_day():
    assert _code("medical_appointment", _employee(), 5) == "CLN"
    assert _code("medical_appointment", _employee(), 2) == "LTN"
    assert _code("medical_appointment", _employee(clinic=True), 5) == "PER"
    assert _code("medical_appointment", _employee(union=False), 5) == "PER"


def test_codes_without_notice_rules():
    assert _code("jury_duty", _employee(union=False), 0) == "JRY"
    assert _code("family_illness", _employee(), 0) == "FEM"
    assert _code("personal", _employee(), 0) == "PER"


def test_bereavement_three_paid_days_with_notice():
    ana = _employee()
    balances = Balances.from_hr([ana])
    assert [_code("bereavement", ana, 6, balances) for _ in range(3)] == ["BRV"] * 3
    fourth = code_absence("bereavement", ana, WED, 6, balances)
    assert fourth.hold
    assert _code("bereavement", _employee(union=False), 2) == "LTN"
