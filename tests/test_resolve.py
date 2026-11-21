"""Identity resolution on small synthetic data (invented names, not client data)."""

from collections import Counter
from datetime import date

from northgate.resolve.buildings import (
    BuildingLinks,
    entity_for,
    link_by_name,
    link_departments,
    link_hr_locations,
)
from northgate.resolve.employees import build_assignments, link_id
from northgate.resolve.names import best_building_match, person_match_score

CANONICAL = ["North Tower", "South Plaza", "East Annex"]


def test_building_names_with_abbreviations():
    assert best_building_match("NORTH TWR", CANONICAL)[0] == "North Tower"
    assert best_building_match("South Plz Bldg", CANONICAL)[0] == "South Plaza"
    assert best_building_match("EAST ANX", CANONICAL)[0] == "East Annex"
    assert best_building_match("Training room", CANONICAL)[0] is None


def test_ambiguous_building_name_is_not_resolved():
    assert best_building_match("Meadow", ["Meadow One", "Meadow Plaza"])[0] is None


def test_person_names_in_different_formats():
    assert person_match_score("DOE, JANE", "Jane", "Doe") == 2
    assert person_match_score("Jane D.", "Jane", "Doe") == 1
    assert person_match_score("J. Doe", "Jane", "Doe") == 1
    assert person_match_score("Jane", "Jane", "Doe") == 0  # first name alone identifies nobody
    assert person_match_score("Jane Roe", "Jane", "Doe") == 0


def test_hr_locations_via_department_form_text_and_elimination():
    links = BuildingLinks()
    finance_sites = [
        {"site_name": "North Twr", "department": "100", "description": "North Tower"},
        {"site_name": "Pool", "department": "900", "description": None},
    ]
    link_departments(CANONICAL, finance_sites, links)
    pairs = Counter({("L1", "100"): 5, ("L2", "200"): 3, ("L3", "300"): 2, ("POOL", "900"): 4})
    forms = ["L2 (South Plaza), Night, Dept 200"]
    link_hr_locations(CANONICAL, pairs, forms, links)

    assert links.location_to_building["L1"] == "North Tower"  # department of a finance site
    assert links.location_to_building["L2"] == "South Plaza"  # code printed next to the name on a form
    assert links.location_to_building["L3"] == "East Annex"  # the only one left
    assert links.dept_to_building["300"] == "East Annex"
    assert "POOL" not in links.location_to_building


def test_time_clock_site_confirmed_or_decided_by_who_punches_there():
    links = BuildingLinks()
    evidence = {"S-1": Counter({"North Tower": 95, "South Plaza": 5}), "S-9": Counter({"East Annex": 40})}
    link_by_name("time_clock_site", {"S-1": "NORTH TWR", "S-9": "UNIT 9"}, CANONICAL, links, evidence)

    assert links.lookup("time_clock_site", "S-1") == "North Tower"
    assert links.lookup("time_clock_site", "S-9") == "East Annex"  # name unknown, punches decide
    assert [link.confidence for link in links.links] == ["high", "medium"]


EMPLOYEES = [
    {
        "employee_id": "E501",
        "first_name": "Jane",
        "last_name": "Doe",
        "home_location": "L1",
        "shift": "NIGHT",
        "hire_date": date(2020, 1, 1),
        "termination_date": None,
        "source_ref": "roster line 2",
    },
    {
        "employee_id": "E502",
        "first_name": "Omar",
        "last_name": "Diaz",
        "home_location": "L1",
        "shift": "DAY",
        "hire_date": date(2021, 1, 1),
        "termination_date": None,
        "source_ref": "roster line 3",
    },
]


def test_id_link_rejects_a_mistyped_number_and_falls_back_to_name():
    assert link_id("payroll", "501", "DOE, JANE", 501, EMPLOYEES).employee_id == "E501"
    typo = link_id("dispatch", "W-1", "Omar Diaz", "E510", EMPLOYEES)
    assert (typo.employee_id, typo.confidence) == ("E502", "medium")
    wrong_name = link_id("dispatch", "W-2", "Omar Diaz", "E501", EMPLOYEES)  # number of someone else
    assert wrong_name.employee_id == "E502"
    assert link_id("dispatch", "W-3", "Nobody Here", "E999", EMPLOYEES).employee_id is None


def _form(action: str, approved: bool, **fields) -> dict:
    return {
        "action": action,
        "fully_approved": approved,
        "employee_id": "E501",
        "employee_name": "Jane Doe",
        "effective_date": date(2025, 3, 10),
        "source_ref": f"{action}.pdf",
        "approvals": [{"role": "HR", "signed": True}, {"role": "Ops", "signed": approved}],
        **fields,
    }


def test_approved_transfer_splits_the_home_building_on_the_effective_date():
    transfer = _form(
        "transfer", True, from_location="L1 (North Tower), Night", to_location="L2 (South Plaza), Day"
    )
    rows, issues = build_assignments(
        EMPLOYEES[:1], [transfer], {"L1": "North Tower", "L2": "South Plaza"}, CANONICAL
    )
    assert [(r["building"], r["shift"], r["start_date"], r["end_date"]) for r in rows] == [
        ("North Tower", "NIGHT", date(2020, 1, 1), date(2025, 3, 9)),
        ("South Plaza", "DAY", date(2025, 3, 10), None),
    ]
    assert issues == []


def test_form_missing_an_approval_has_no_effect():
    transfer = _form("transfer", False, from_location="L1", to_location="L2")
    rows, issues = build_assignments(
        EMPLOYEES[:1], [transfer], {"L1": "North Tower", "L2": "South Plaza"}, CANONICAL
    )
    assert [r["building"] for r in rows] == ["North Tower"]
    assert "missing approvals: Ops" in issues[0].issue


def test_entity_matching_ignores_company_suffixes():
    entities = [
        {"entity_code": "AAA", "name": "Acme Services LLC"},
        {"entity_code": "BBB", "name": "Acme Staffing Inc."},
    ]
    assert entity_for("ACME STAFFING INC", entities) == "BBB"
    assert entity_for("Other Company", entities) is None
