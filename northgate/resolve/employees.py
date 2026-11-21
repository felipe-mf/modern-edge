"""Employee identity and home building over time.

IDs: HR "E10041", badge "0010041" / "10041" and payroll 10041 share a number, and dispatch workers
carry a hand-typed HR number. A number is accepted only if the name in that source matches the HR
name; otherwise the employee is searched by name, and only a single clear match is accepted.

Home building: the HR roster, updated by Personnel Action Forms that carry every approval. A form
missing an approval has no effect (KPI definitions) and is reported.
"""

import re
from dataclasses import dataclass
from datetime import date, timedelta

from northgate.resolve.names import best_building_match, fold, person_match_score


@dataclass
class XRef:
    source: str
    source_id: str
    name_in_source: str | None
    employee_id: str | None
    method: str
    confidence: str


@dataclass
class Issue:
    record_ref: str
    issue: str
    action_taken: str
    confidence: str


def hr_number(identifier: str | int | None) -> int | None:
    digits = re.sub(r"\D", "", str(identifier or ""))
    return int(digits) if digits else None


def find_by_name(name: str | None, employees: list[dict]) -> tuple[dict | None, int]:
    """The single employee whose name matches best (score 2 beats 1), or None if tied or no match."""
    scored = [(person_match_score(name, e["first_name"], e["last_name"]), e) for e in employees]
    best = max((s for s, _ in scored), default=0)
    if best == 0:
        return None, 0
    top = [e for s, e in scored if s == best]
    return (top[0], best) if len(top) == 1 else (None, best)


def link_id(
    source: str, source_id: str, name: str | None, claimed: str | int | None, employees: list[dict]
) -> XRef:
    """claimed is the number the source gives (badge, payroll id, hand-typed HR number)."""
    by_number = {hr_number(e["employee_id"]): e for e in employees}
    candidate = by_number.get(hr_number(claimed))
    if candidate and person_match_score(name, candidate["first_name"], candidate["last_name"]) >= 1:
        return XRef(source, source_id, name, candidate["employee_id"], "number, name confirmed", "high")

    found, score = find_by_name(name, employees)
    why = (
        "number not in HR"
        if candidate is None
        else f"number points to {candidate['employee_id']}, name differs"
    )
    if found:
        confidence = "medium" if score == 2 else "low"
        return XRef(source, source_id, name, found["employee_id"], f"name match ({why})", confidence)
    return XRef(source, source_id, name, None, f"unresolved ({why}; no single name match)", "low")


# --- home building over time ----------------------------------------------------------------------


@dataclass
class Segment:
    building: str | None
    shift: str | None
    start: date | None
    end: date | None  # inclusive
    basis: str


def location_building(
    text: str | None, location_to_building: dict[str, str], canonical: list[str]
) -> str | None:
    """'BLD-06 (Bramwell Annex), Night, Dept 460' -> the building, by HR code first, then by name."""
    if not text:
        return None
    for code, building in location_to_building.items():
        if re.search(rf"(?<![\w-]){re.escape(code)}(?![\w-])", text):
            return building
    inside = re.findall(r"\(([^)]+)\)", text)
    for candidate in [*inside, text.split(",")[0]]:
        building, _ = best_building_match(candidate, canonical)
        if building:
            return building
    return None


def shift_in(text: str | None) -> str | None:
    words = fold(text).split()
    for shift in ("DAY", "NIGHT"):
        if shift in words:
            return shift
    return None


def build_assignments(
    employees: list[dict], forms: list[dict], location_to_building: dict[str, str], canonical: list[str]
) -> tuple[list[dict], list[Issue]]:
    timelines: dict[str, list[Segment]] = {}
    for e in employees:
        building = location_to_building.get(e.get("home_location") or "")
        timelines[e["employee_id"]] = [
            Segment(
                building,
                e.get("shift"),
                e.get("hire_date"),
                e.get("termination_date"),
                f"HR roster ({e['source_ref']})",
            )
        ]

    issues: list[Issue] = []
    for form in sorted(forms, key=lambda f: f.get("effective_date") or date.min):
        ref = form["source_ref"]
        employee = _form_employee(form, employees, issues)
        if employee is None:
            continue
        if not form["fully_approved"]:
            missing = [a["role"] for a in form.get("approvals") or [] if not a.get("signed")]
            issues.append(
                Issue(
                    ref,
                    f"{form['action']} for {employee['employee_id']} is missing approvals: "
                    f"{', '.join(missing) or 'none listed'}",
                    "form has no effect; HR roster kept",
                    "high",
                )
            )
            continue
        effective = form.get("effective_date")
        if effective is None:
            issues.append(
                Issue(ref, "approved form has no readable effective date", "form not applied", "low")
            )
            continue
        timeline = timelines[employee["employee_id"]]
        if form["action"] == "transfer":
            _apply_transfer(form, employee, timeline, effective, location_to_building, canonical, issues)
        elif form["action"] == "termination":
            _apply_end(timeline, effective, employee, ref, issues)
        elif form["action"] == "new_hire":
            if employee.get("hire_date") != effective:
                issues.append(
                    Issue(
                        ref,
                        f"hire date on form {effective} differs from HR {employee.get('hire_date')}",
                        "form date used",
                        "medium",
                    )
                )
                timeline[0].start = effective
        else:
            issues.append(
                Issue(
                    ref, f"{form['action']} form does not change the home building", "recorded only", "high"
                )
            )

    rows = [
        {
            "employee_id": employee_id,
            "building": s.building,
            "shift": s.shift,
            "start_date": s.start,
            "end_date": s.end,
            "basis": s.basis,
        }
        for employee_id, timeline in timelines.items()
        for s in timeline
    ]
    return rows, issues


def _form_employee(form: dict, employees: list[dict], issues: list[Issue]) -> dict | None:
    """The employee a form is about: by the id on the form if the name agrees, else by name."""
    ref = form["source_ref"]
    number = hr_number(form.get("employee_id"))
    employee = next(
        (e for e in employees if number is not None and hr_number(e["employee_id"]) == number), None
    )
    if employee and person_match_score(
        form.get("employee_name"), employee["first_name"], employee["last_name"]
    ):
        return employee
    found, _ = find_by_name(form.get("employee_name"), employees)
    if found:
        issues.append(
            Issue(
                ref,
                f"form id {form.get('employee_id')!r} does not match name {form.get('employee_name')!r}",
                f"matched by name to {found['employee_id']}",
                "medium",
            )
        )
        return found
    issues.append(
        Issue(
            ref,
            f"employee {form.get('employee_name')!r} ({form.get('employee_id')}) not in HR",
            "form not applied",
            "low",
        )
    )
    return None


def _apply_transfer(
    form: dict,
    employee: dict,
    timeline: list[Segment],
    effective: date,
    location_to_building: dict[str, str],
    canonical: list[str],
    issues: list[Issue],
) -> None:
    ref = form["source_ref"]
    origin = location_building(form.get("from_location"), location_to_building, canonical)
    destination = location_building(form.get("to_location"), location_to_building, canonical)
    if destination is None:
        issues.append(
            Issue(ref, f"cannot read destination {form.get('to_location')!r}", "form not applied", "low")
        )
        return
    current = _segment_on(timeline, effective)
    if current is None:
        issues.append(
            Issue(ref, f"{employee['employee_id']} not employed on {effective}", "form not applied", "low")
        )
        return
    if origin and current.building not in (origin, destination):
        issues.append(
            Issue(
                ref,
                f"form says from {origin}, HR says {current.building}",
                "transfer applied from the form's origin",
                "medium",
            )
        )
    before = Segment(
        origin or current.building, current.shift, current.start, effective - timedelta(days=1), current.basis
    )
    after = Segment(
        destination,
        shift_in(form.get("to_location")) or current.shift,
        effective,
        current.end,
        f"transfer form {ref}",
    )
    index = timeline.index(current)
    timeline[index : index + 1] = [
        s for s in (before, after) if s.start is None or s.end is None or s.start <= s.end
    ]


def _apply_end(
    timeline: list[Segment], effective: date, employee: dict, ref: str, issues: list[Issue]
) -> None:
    hr_end = employee.get("termination_date")
    if hr_end != effective:
        issues.append(
            Issue(
                ref,
                f"termination date on form {effective} differs from HR {hr_end}",
                "form date used",
                "medium",
            )
        )
    timeline[-1].end = effective


def _segment_on(timeline: list[Segment], day: date) -> Segment | None:
    for s in timeline:
        if (s.start is None or s.start <= day) and (s.end is None or day <= s.end):
            return s
    return None


def building_on(assignments: list[dict], employee_id: str, day: date) -> dict | None:
    """The assignment row in force for an employee on a day, or None if not employed."""
    for a in assignments:
        if a["employee_id"] != employee_id:
            continue
        if (a["start_date"] is None or a["start_date"] <= day) and (
            a["end_date"] is None or day <= a["end_date"]
        ):
            return a
    return None
