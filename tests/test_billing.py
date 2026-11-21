"""Billable amount, invoice matching, time on site and the two note templates (invented data)."""

from datetime import date, datetime
from decimal import Decimal

from northgate.billing.coverage import billable_amount, match_line, on_site
from northgate.billing.notes import template_a, template_b

DAY = date(2025, 3, 5)


def test_billable_amount_formula_and_rounding():
    # 8 x 21.00 x 1.0 x 1.18 x 1.15 = 227.976 -> 227.98
    assert billable_amount(Decimal("21.00"), Decimal("0.18"), Decimal(15), overtime=False) == Decimal(
        "227.98"
    )
    # 8 x 25.35 x 1.5 x 1.32 x 1.15 = 461.7756 -> 461.78
    assert billable_amount(Decimal("25.35"), Decimal("0.32"), Decimal(15), overtime=True) == Decimal("461.78")


def _cov(pid, shift="night", first="Ana", last="Silva", amount="227.98", day=DAY, building="North"):
    return {"posting_id": pid, "building": building, "shift_date": day, "shift": shift,
            "billable_amount": Decimal(amount),
            "covering_employee": {"first_name": first, "last_name": last}}  # fmt: skip


def _line(description, amount="227.98", day=DAY):
    return {"description": description, "amount": Decimal(amount), "service_date": day}


def test_line_with_reference_wins():
    match = match_line(_line("Coverage 03/05 Night (ref P-9)"), "North", [_cov("P-1")], set())
    assert match.posting_id == "P-9"


def test_line_without_reference_matches_by_building_date_shift():
    pool = [_cov("P-1", shift="day"), _cov("P-2", shift="night")]
    assert match_line(_line("Coverage 03/05 Night"), "North", pool, set()).posting_id == "P-2"


def test_name_then_amount_break_ties():
    pool = [_cov("P-1", first="Ana", last="Silva"), _cov("P-2", first="Rui", last="Costa", amount="300.00")]
    assert match_line(_line("Coverage 03/05 Night - replacement Rui Costa", "300.00"), "North", pool,
                      set()).posting_id == "P-2"  # fmt: skip
    # No name on the line (template B clients): the amount decides.
    assert match_line(_line("Coverage 03/05 Night", "300.00"), "North", pool, set()).posting_id == "P-2"


def test_ambiguous_or_already_billed_line_is_not_guessed():
    pool = [_cov("P-1"), _cov("P-2")]
    assert match_line(_line("Coverage 03/05 Night"), "North", pool, set()).posting_id is None
    assert match_line(_line("Coverage 03/05 Night"), "North", pool, {"P-1"}).posting_id == "P-2"


def _punch(event, when):
    return {"event": event, "local_time": when}


def test_on_site_separates_a_day_shift_from_overtime_night_at_the_same_building():
    punches = [
        _punch("IN", datetime(2025, 3, 5, 7, 4)), _punch("OUT", datetime(2025, 3, 5, 15, 4)),
        _punch("IN", datetime(2025, 3, 5, 16, 5)), _punch("MEAL_START", datetime(2025, 3, 5, 19, 0)),
        _punch("OUT", datetime(2025, 3, 6, 0, 6)),
    ]  # fmt: skip
    assert on_site(punches, DAY, "night") == (datetime(2025, 3, 5, 16, 5), datetime(2025, 3, 6, 0, 6))
    assert on_site(punches, DAY, "day") == (datetime(2025, 3, 5, 7, 4), datetime(2025, 3, 5, 15, 4))


def test_missing_clock_out_and_previous_night_are_not_confused():
    punches = [_punch("OUT", datetime(2025, 3, 5, 0, 5)), _punch("IN", datetime(2025, 3, 5, 16, 4))]
    assert on_site(punches, DAY, "night") == (datetime(2025, 3, 5, 16, 4), None)


NOTE = {
    "client_name": "Client Co", "building": "North Tower", "shift_date": DAY, "shift": "night",
    "position_covered": "Cleaner", "overtime": True, "covering_name": "Rui Costa",
    "on_site_in": datetime(2025, 3, 5, 15, 55), "on_site_out": None,
    "billable_amount": Decimal("1461.78"), "posting_id": "P-7",
}  # fmt: skip


def test_template_a_lists_replacement_and_time_on_site():
    text = template_a(NOTE)
    assert "Replacement:       Rui Costa" in text
    assert "On site:           15:55 to Not recorded" in text
    assert "Shift:             Night, 16:00 to 00:00" in text
    assert "Coverage type:     Overtime" in text
    assert "Billable amount:   $1,461.78" in text
    assert "Date of service:   03/05/2025" in text


def test_template_b_has_no_names():
    text = template_b(NOTE)
    assert "Rui Costa" not in text and "Replacement:" not in text and "On site" not in text
    assert "Coverage:          Replacement provided" in text
    assert "Shift:             Night\n" in text
