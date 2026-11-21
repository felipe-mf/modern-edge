"""Building identity: every name and code a source uses -> the building name in Schedule B.

The names in the client agreements are the canonical names (KPI definitions require them in every
output). Each other identifier is linked to one of them, strongest evidence first:

- Finance sites carry a department and a description; the description is matched to a name.
- HR location codes are linked through their department. A location whose department has no
  finance site falls back to forms that print the code next to a building name, e.g.
  "BLD-06 (Bramwell Annex)", and finally to elimination (the only building and location left).
- Time clock sites, dispatch sites, invoice sites and budget names are matched by name. For time
  clock sites, the employees who punch there must agree: their HR home building is used to confirm
  the name match, or to decide when the name alone does not.

Every link records how it was made and with what confidence, and weak links become exceptions.
"""

import re
from collections import Counter
from dataclasses import dataclass, field

from northgate.resolve.names import best_building_match, fold


@dataclass
class Link:
    source: str
    alias: str
    building: str | None
    method: str
    confidence: str
    note: str | None = None


@dataclass
class BuildingLinks:
    links: list[Link] = field(default_factory=list)
    dept_to_building: dict[str, str] = field(default_factory=dict)
    location_to_building: dict[str, str] = field(default_factory=dict)
    # Departments that Finance lists as a site but that match no client building (e.g. a float pool).
    non_client_depts: dict[str, str] = field(default_factory=dict)

    def add(self, link: Link) -> None:
        self.links.append(link)

    def lookup(self, source: str, alias: str | None) -> str | None:
        for link in self.links:
            if link.source == source and link.alias == alias:
                return link.building
        return None


def link_departments(canonical: list[str], finance_sites: list[dict], result: BuildingLinks) -> None:
    for site in finance_sites:
        name = site.get("description") or site["site_name"]
        building, score = best_building_match(name, canonical)
        method = f"finance site description matched by name (score {score:.0f})"
        if building is None and not site.get("description"):
            result.add(
                Link(
                    "finance_site",
                    site["site_name"],
                    None,
                    "no description, no name match",
                    "high",
                    "not a client building",
                )
            )
            if site.get("department"):
                result.non_client_depts[site["department"]] = site["site_name"]
            continue
        confidence = "high" if score == 100 else "medium"
        result.add(Link("finance_site", site["site_name"], building, method, confidence))
        if building and site.get("department"):
            result.dept_to_building[site["department"]] = building
            result.add(
                Link(
                    "department",
                    site["department"],
                    building,
                    f"via finance site {site['site_name']}",
                    confidence,
                )
            )


def link_hr_locations(
    canonical: list[str], location_depts: Counter, form_texts: list[str], result: BuildingLinks
) -> None:
    """location_depts counts (hr_location, department) pairs seen in the roster."""
    location_dept: dict[str, str] = {}
    for (location, dept), _count in location_depts.most_common():
        location_dept.setdefault(location, dept)

    unresolved = []
    for location, dept in sorted(location_dept.items()):
        building = result.dept_to_building.get(dept)
        if building:
            result.location_to_building[location] = building
            result.add(Link("hr_location", location, building, f"via department {dept}", "high"))
        elif dept in result.non_client_depts:
            result.add(
                Link(
                    "hr_location",
                    location,
                    None,
                    f"department {dept} is finance site {result.non_client_depts[dept]!r}",
                    "high",
                    "not a client building",
                )
            )
        else:
            unresolved.append((location, dept))

    still_unresolved = []
    for location, dept in unresolved:
        # "BLD-06 (Bramwell Annex)" printed on a form
        named = Counter(
            match.group(1).strip()
            for text in form_texts
            for match in re.finditer(rf"{re.escape(location)}\s*\(([^)]+)\)", text or "")
        )
        candidates = {best_building_match(name, canonical)[0] for name in named} - {None}
        if len(candidates) == 1:
            building = candidates.pop()
            _link_location(
                result, location, dept, building, "named next to the code on personnel forms", "high"
            )
        else:
            still_unresolved.append((location, dept))

    # Elimination: one location left and one client building without a location.
    free_buildings = [b for b in canonical if b not in result.location_to_building.values()]
    if len(still_unresolved) == 1 and len(free_buildings) == 1:
        location, dept = still_unresolved.pop()
        _link_location(result, location, dept, free_buildings[0], "only location and building left", "medium")
    for location, dept in still_unresolved:
        result.add(
            Link(
                "hr_location",
                location,
                None,
                "no department, form or name evidence",
                "high",
                f"department {dept}; treated as not a client building (e.g. a float pool)",
            )
        )


def _link_location(
    result: BuildingLinks, location: str, dept: str, building: str, method: str, confidence: str
) -> None:
    result.location_to_building[location] = building
    result.add(Link("hr_location", location, building, method, confidence))
    if dept and dept not in result.dept_to_building:
        result.dept_to_building[dept] = building
        result.add(
            Link(
                "department",
                dept,
                building,
                f"via HR location {location} ({method})",
                confidence,
                "department has no finance site",
            )
        )


def link_by_name(
    source: str,
    aliases: dict[str, str],
    canonical: list[str],
    result: BuildingLinks,
    evidence: dict[str, Counter] | None = None,
    inactive: set[str] = frozenset(),
) -> None:
    """aliases maps the identifier to the name to match (a code -> its site name, or name -> name).

    evidence (optional) counts, per identifier, the home buildings of the people seen there.
    """
    for alias, name in sorted(aliases.items()):
        building, score = best_building_match(name, canonical)
        seen = (evidence or {}).get(alias, Counter())
        majority, share = _majority(seen)
        note = "inactive in source" if alias in inactive else None

        if building and (not seen or majority == building):
            confidence = "high" if score == 100 or majority == building else "medium"
            method = f"name match (score {score:.0f})" + (
                f", confirmed by {share:.0%} of punches" if seen else ""
            )
            result.add(Link(source, alias, building, method, confidence, note))
        elif building is None and majority and share >= 0.8:
            result.add(
                Link(
                    source,
                    alias,
                    majority,
                    f"{share:.0%} of punches by employees of this building",
                    "medium",
                    f"name {name!r} did not match a building",
                )
            )
        elif building and majority != building:
            result.add(
                Link(
                    source,
                    alias,
                    building,
                    f"name match (score {score:.0f})",
                    "low",
                    f"punches point to {majority} ({share:.0%}); name match kept",
                )
            )
        else:
            result.add(
                Link(
                    source,
                    alias,
                    None,
                    f"no clear name match (best score {score:.0f})",
                    "high",
                    note or f"name {name!r}",
                )
            )


def _majority(counter: Counter) -> tuple[str | None, float]:
    total = sum(counter.values())
    if not total:
        return None, 0.0
    building, count = counter.most_common(1)[0]
    return building, count / total


def entity_for(contractor_name: str | None, entities: list[dict]) -> str | None:
    """Legal entity code whose name matches the contractor named in an agreement."""
    target = _company_key(contractor_name)
    matches = [e["entity_code"] for e in entities if _company_key(e.get("name")) == target]
    return matches[0] if len(matches) == 1 else None


def _company_key(name: str | None) -> str:
    """'Northgate Facility Staffing Inc.' and 'NORTHGATE FACILITY STAFFING INC' compare equal."""
    words = fold(name).split()
    return " ".join(w for w in words if w not in {"INC", "LLC", "LTD", "CORP", "CO", "COMPANY", "THE"})


def client_key(name: str | None) -> str:
    """'Corlett Asset Mgmt LLC' and 'Corlett Asset Management' compare equal."""
    words = {"MGMT": "MANAGEMENT", "MGT": "MANAGEMENT", "ASSOC": "ASSOCIATES", "PROP": "PROPERTIES"}
    return " ".join(words.get(w, w) for w in _company_key(name).split())
