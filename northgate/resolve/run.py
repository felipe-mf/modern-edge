"""Resolve identities across sources and write the crosswalk tables.

Order matters: employee ids first (the time clock evidence for buildings needs them), then building
links, then each building's terms as of the period end, clients and departments, and finally each
employee's home building over time.
"""

import logging
from collections import Counter
from datetime import date

from sqlalchemy import Engine

from northgate import db
from northgate.resolve.buildings import (
    BuildingLinks,
    client_key,
    entity_for,
    link_by_name,
    link_departments,
    link_hr_locations,
)
from northgate.resolve.employees import XRef, build_assignments, hr_number, link_id
from northgate.resolve.names import best_building_match

log = logging.getLogger(__name__)


def _exception(engine: Engine, source: str, ref: str, issue: str, action: str, confidence: str) -> None:
    log.info("exception | %s | %s | %s", source, ref, issue)
    db.add_exception(engine, source, ref, issue, action, confidence)


def resolve_all(engine: Engine, period_end: date) -> Counter:
    counts: Counter = Counter()
    employees = db.fetch(engine, db.hr_employees)

    # --- employee ids -------------------------------------------------------------------------
    xrefs = _link_employee_ids(engine, employees)
    counts["employee_xref"] = db.insert_rows(engine, db.employee_xref, [x.__dict__ for x in xrefs])
    badge_to_employee = {x.source_id: x.employee_id for x in xrefs if x.source == "badge"}

    # --- buildings ----------------------------------------------------------------------------
    agreements = db.fetch(engine, db.contract_buildings)
    canonical = sorted({b["building"] for b in agreements})
    links = BuildingLinks()
    link_departments(canonical, db.fetch(engine, db.finance_sites), links)

    forms = db.fetch(engine, db.personnel_actions)
    form_texts = [str(f.get(k) or "") for f in forms for k in ("from_location", "to_location", "location")]
    link_hr_locations(
        canonical, Counter((e["home_location"], e["department"]) for e in employees), form_texts, links
    )

    home_of = {
        e["employee_id"]: links.location_to_building.get(e["home_location"])
        for e in employees
        if e.get("employment_type") == "PERMANENT"
    }
    punch_evidence: dict[str, Counter] = {}
    for punch in db.fetch(engine, db.time_punches):
        building = home_of.get(badge_to_employee.get(punch["badge_no"]) or "")
        if building:
            punch_evidence.setdefault(punch["site_raw"], Counter())[building] += 1
    site_codes = {s["site_code"]: s["site_name"] for s in db.fetch(engine, db.ta_site_codes)}
    clock_sites = {raw: site_codes.get(raw, raw) for raw in punch_evidence} | site_codes
    inactive_codes = {s["site_code"] for s in db.fetch(engine, db.ta_site_codes) if s["status"] != "ACTIVE"}
    link_by_name("time_clock_site", clock_sites, canonical, links, punch_evidence, inactive_codes)

    dispatch_sites = db.fetch(engine, db.dispatch_sites)
    link_by_name(
        "dispatch_site",
        {s["site_id"]: s["name"] for s in dispatch_sites},
        canonical,
        links,
        inactive={s["site_id"] for s in dispatch_sites if not s["active"]},
    )

    known_finance_sites = {link.alias for link in links.links if link.source == "finance_site"}
    invoice_only_sites = {
        line["site_name"] for line in db.fetch(engine, db.invoice_lines)
    } - known_finance_sites
    link_by_name("finance_site", {s: s for s in invoice_only_sites}, canonical, links)
    link_by_name(
        "labor_budget",
        {r["building"]: r["building"] for r in db.fetch(engine, db.labor_budget)},
        canonical,
        links,
    )

    for link in links.links:
        if link.confidence != "high" or link.building is None or link.note:
            _exception(
                engine,
                f"building:{link.source}",
                link.alias,
                "; ".join(
                    part
                    for part in (
                        "unresolved" if link.building is None else f"linked to {link.building}",
                        link.method,
                        link.note,
                    )
                    if part
                ),
                "excluded from building figures" if link.building is None else "link used",
                link.confidence,
            )
    counts["building_aliases"] = db.insert_rows(
        engine, db.building_aliases, [l.__dict__ for l in links.links]
    )

    # --- building terms, clients, departments ----------------------------------------------------
    buildings = _building_terms(engine, agreements, canonical, links, period_end)
    counts["buildings"] = db.insert_rows(engine, db.buildings, buildings)
    _check_departments(engine, links, buildings)

    # --- home building over time -----------------------------------------------------------------
    assignments, issues = build_assignments(employees, forms, links.location_to_building, canonical)
    for issue in issues:
        _exception(
            engine,
            "personnel_action_forms",
            issue.record_ref,
            issue.issue,
            issue.action_taken,
            issue.confidence,
        )
    counts["employee_assignments"] = db.insert_rows(engine, db.employee_assignments, assignments)
    return counts


def _link_employee_ids(engine: Engine, employees: list[dict]) -> list[XRef]:
    xrefs: list[XRef] = []
    badges = {(p["badge_no"], p["employee_name"]) for p in db.fetch(engine, db.time_punches)}
    for badge, name in sorted(badges):
        xrefs.append(link_id("badge", badge, name, badge, employees))
    for p in db.fetch(engine, db.payroll_employees):
        xrefs.append(link_id("payroll", str(p["employee_id"]), p["name"], p["employee_id"], employees))
    for w in db.fetch(engine, db.dispatch_workers):
        xrefs.append(link_id("dispatch", w["worker_id"], w["display_name"], w["hr_employee_no"], employees))

    linked_numbers = {(x.source, hr_number(x.employee_id)) for x in xrefs if x.employee_id}
    for x in xrefs:
        if x.confidence != "high":
            _exception(
                engine,
                f"employee:{x.source}",
                f"{x.source_id} {x.name_in_source!r}",
                f"{x.method}",
                f"linked to {x.employee_id}" if x.employee_id else "not linked",
                x.confidence,
            )
    for e in employees:
        if ("payroll", hr_number(e["employee_id"])) not in linked_numbers:
            _exception(
                engine,
                "employee:payroll",
                e["employee_id"],
                "HR employee has no payroll record",
                "absences for this employee cannot be posted",
                "high",
            )
    status_by_payroll_id = {
        str(p["employee_id"]): p["status"] for p in db.fetch(engine, db.payroll_employees)
    }
    payroll_status = {
        x.employee_id: status_by_payroll_id[x.source_id]
        for x in xrefs
        if x.source == "payroll" and x.employee_id
    }
    for e in employees:
        status = payroll_status.get(e["employee_id"])
        if status and status != e["status"]:
            _exception(
                engine,
                "employee:payroll",
                e["employee_id"],
                f"HR status {e['status']}, payroll status {status}",
                "absences are held for review until payroll matches HR",
                "high",
            )
    return xrefs


def _building_terms(
    engine: Engine, agreements: list[dict], canonical: list[str], links: BuildingLinks, period_end: date
) -> list[dict]:
    contracts = {c["source_file"]: c for c in db.fetch(engine, db.contracts)}
    changes = sorted(db.fetch(engine, db.contract_changes), key=lambda c: c["effective_date"] or date.min)
    entities = db.fetch(engine, db.finance_entities)
    customers = db.fetch(engine, db.finance_customers)
    invoice_lines = db.fetch(engine, db.invoice_lines)

    rows = []
    for building in canonical:
        # The latest agreement covering the building is the one in force.
        terms = max(
            (a for a in agreements if a["building"] == building),
            key=lambda a: a["agreement_date"] or date.min,
        )
        day_posts, night_posts = terms["day_posts"], terms["night_posts"]
        markup, fee = terms["markup_pct"], terms["monthly_fee"]
        applied = []
        for change in changes:
            if best_building_match(change["building"], canonical)[0] != building:
                continue
            if change["effective_date"] is None or change["effective_date"] > period_end:
                continue
            day_posts = change["day_posts"] if change["day_posts"] is not None else day_posts
            night_posts = change["night_posts"] if change["night_posts"] is not None else night_posts
            markup = change["markup_pct"] if change["markup_pct"] is not None else markup
            fee = change["monthly_fee"] if change["monthly_fee"] is not None else fee
            applied.append(f"{change['source_file']} (effective {change['effective_date']})")

        backup = (contracts.get(terms["source_file"]) or {}).get("coverage_backup") or {}
        template = (
            {"required": "A", "forbidden": "B"}.get(backup.get("replacement_names"))
            if backup.get("applies")
            else None
        )
        contract_entity = entity_for(terms["contractor_name"], entities)
        if contract_entity is None:
            _exception(
                engine,
                "contracts",
                terms["source_file"],
                f"contractor {terms['contractor_name']!r} matches no finance entity",
                "entity left blank",
                "low",
            )

        invoice_accounts = Counter(
            (line["entity"], line["customer_no"])
            for line in invoice_lines
            if links.lookup("finance_site", line["site_name"]) == building
        )
        invoice_entity, invoice_customer = (
            invoice_accounts.most_common(1)[0][0] if invoice_accounts else (None, None)
        )
        if len(invoice_accounts) > 1:
            _exception(
                engine,
                "finance",
                building,
                f"invoiced under several accounts: {dict(invoice_accounts)}",
                f"{invoice_entity}/{invoice_customer} taken as the main account",
                "medium",
            )

        master = [c for c in customers if client_key(c["customer_name"]) == client_key(terms["client_name"])]
        master_no = master[0]["customer_no"] if len(master) == 1 else None
        _check_client(
            engine, building, terms, contract_entity, invoice_entity, invoice_customer, master, customers
        )

        department = next((d for d, b in links.dept_to_building.items() if b == building), None)
        hr_location = next((loc for loc, b in links.location_to_building.items() if b == building), None)
        rows.append(
            {
                "building": building,
                "client_name": terms["client_name"],
                "contractor_name": terms["contractor_name"],
                "contract_entity": contract_entity,
                "department": department,
                "hr_location": hr_location,
                "day_posts": day_posts,
                "night_posts": night_posts,
                "pricing_basis": terms["pricing_basis"],
                "monthly_fee": fee,
                "markup_pct": markup,
                "coverage_billable": terms["coverage_billable"],
                "backup_template": template,
                "invoice_entity": invoice_entity,
                "invoice_customer_no": invoice_customer,
                "master_customer_no": master_no,
                "source_ref": "; ".join([terms["source_file"], *applied]),
            }
        )
    return rows


def _check_client(
    engine: Engine,
    building: str,
    terms: dict,
    contract_entity: str | None,
    invoice_entity: str | None,
    invoice_customer: str | None,
    master: list[dict],
    customers: list[dict],
) -> None:
    in_master = any(
        c["entity_code"] == invoice_entity and c["customer_no"] == invoice_customer for c in customers
    )
    if invoice_customer and not in_master:
        _exception(
            engine,
            "finance",
            f"{invoice_entity}/{invoice_customer}",
            f"customer billed for {building} is not in the customer master",
            "revenue still attributed to the building through the invoice site",
            "high",
        )
    if not master:
        _exception(
            engine,
            "finance",
            building,
            f"client {terms['client_name']!r} not found in the customer master",
            "none",
            "medium",
        )
    for c in master:
        if contract_entity and c["entity_code"] != contract_entity:
            _exception(
                engine,
                "finance",
                f"{c['entity_code']}/{c['customer_no']}",
                f"customer master lists {terms['client_name']!r} under {c['entity_code']}, but the agreement "
                f"for {building} is with {contract_entity}",
                "agreement entity used",
                "high",
            )
    if invoice_entity and contract_entity and invoice_entity != contract_entity:
        _exception(
            engine,
            "finance",
            building,
            f"invoiced by {invoice_entity}, agreement is with {contract_entity}",
            "invoices counted as issued",
            "medium",
        )


def _check_departments(engine: Engine, links: BuildingLinks, buildings: list[dict]) -> None:
    gl_departments = Counter((line["department"], line["entity"]) for line in db.fetch(engine, db.gl_lines))
    entity_of = {b["building"]: b["contract_entity"] for b in buildings}
    for (dept, entity), _ in sorted(gl_departments.items()):
        building = links.dept_to_building.get(dept)
        if building is None:
            _exception(
                engine,
                "finance",
                f"GL dept {dept} ({entity})",
                "GL department is not a client building",
                "excluded from building labor cost",
                "high",
            )
        elif entity_of.get(building) and entity_of[building] != entity:
            _exception(
                engine,
                "finance",
                f"GL dept {dept} ({entity})",
                f"labor for {building} booked in {entity}, agreement is with {entity_of[building]}",
                "included in the building's labor cost",
                "medium",
            )
    for b in buildings:
        if b["department"] is None:
            _exception(
                engine,
                "buildings",
                b["building"],
                "no ledger department linked to the building",
                "labor cost will be zero",
                "low",
            )
