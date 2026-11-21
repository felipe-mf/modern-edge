"""Database schema (SQLAlchemy Core) and small write helpers.

Two kinds of tables:
- Source tables hold what was read from each file or API, one row per record, each with a
  `source_ref` pointing back to the file line / API record it came from. They are rebuilt from
  scratch on every pipeline run.
- State tables (`llm_cache`, and later the payroll ledger and audit log) survive between runs,
  because they record what already happened outside the system.
"""

from collections.abc import Iterable

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    Engine,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    create_engine,
    func,
    insert,
    select,
)

metadata = MetaData()
MONEY = Numeric(14, 2)


def _source_ref() -> Column:
    return Column("source_ref", Text, nullable=False)


# --- files --------------------------------------------------------------------------------------

hr_employees = Table(
    "hr_employees",
    metadata,
    Column("employee_id", String, primary_key=True),
    Column("last_name", String),
    Column("first_name", String),
    Column("middle_initial", String),
    Column("job_class", String),
    Column("union_member", Boolean),
    Column("local_member_no", String),
    Column("home_location", String),
    Column("department", String),
    Column("shift", String),
    Column("employment_type", String),
    Column("hire_date", Date),
    Column("termination_date", Date),
    Column("status", String),
    Column("sick_days_remaining", Integer),
    Column("clinic_day_used", Boolean),
    Column("primary_language", String),
    _source_ref(),
)

personnel_actions = Table(
    "personnel_actions",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("source_file", String),
    Column("action", String),
    Column("employee_name", String),
    Column("employee_id", String),
    Column("job_class", String),
    Column("effective_date", Date),
    Column("from_location", String),
    Column("to_location", String),
    Column("location", String),
    Column("fully_approved", Boolean),
    Column("approvals", JSON),
    Column("details", JSON),
    _source_ref(),
)

time_punches = Table(
    "time_punches",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("badge_no", String),
    Column("employee_name", String),
    Column("site_raw", String),
    Column("event", String),
    Column("local_time", DateTime),
    Column("utc_offset_min", Integer),
    Column("device", String),
    _source_ref(),
)

ta_site_codes = Table(
    "ta_site_codes",
    metadata,
    Column("site_code", String, primary_key=True),
    Column("site_name", String),
    Column("status", String),
    _source_ref(),
)

callout_log = Table(
    "callout_log",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("logged_at", DateTime),
    Column("log_date", Date),
    Column("taken_by", String),
    Column("channel", String),
    Column("vm_received_raw", String),
    Column("caller", String),
    Column("message", Text),
    Column("sent_to_ops", String),
    _source_ref(),
)

chat_messages = Table(
    "chat_messages",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("sent_at_local", DateTime),
    Column("author", String),
    Column("text", Text),
    _source_ref(),
)

labor_budget = Table(
    "labor_budget",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("building", String),
    Column("position", String),
    Column("employee_name", String),
    Column("shift", String),
    Column("status", String),
    Column("weekly_hours", Numeric(8, 2)),
    Column("rate", Numeric(10, 2)),
    _source_ref(),
)

contracts = Table(
    "contracts",
    metadata,
    Column("source_file", String, primary_key=True),
    Column("document_type", String),
    Column("client_name", String),
    Column("contractor_name", String),
    Column("document_date", Date),
    Column("amends_agreement_dated", Date),
    Column("payment_terms_days", Integer),
    Column("coverage_backup", JSON),
    Column("notes", Text),
    Column("details", JSON),
    _source_ref(),
)

contract_buildings = Table(
    "contract_buildings",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("source_file", String),
    Column("client_name", String),
    Column("contractor_name", String),
    Column("agreement_date", Date),
    Column("building", String),
    Column("day_posts", Integer),
    Column("night_posts", Integer),
    Column("pricing_basis", String),
    Column("monthly_fee", MONEY),
    Column("markup_pct", Numeric(6, 3)),
    Column("coverage_billable", Boolean),
    _source_ref(),
)

contract_changes = Table(
    "contract_changes",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("source_file", String),
    Column("client_name", String),
    Column("building", String),
    Column("effective_date", Date),
    Column("day_posts", Integer),
    Column("night_posts", Integer),
    Column("markup_pct", Numeric(6, 3)),
    Column("monthly_fee", MONEY),
    _source_ref(),
)

wage_rates = Table(
    "wage_rates",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("schedule", String),  # "union" (CBA wage schedule) or "non_union" (rate card)
    Column("classification", String),
    Column("effective_date", Date),
    Column("hourly_rate", Numeric(10, 2)),
    _source_ref(),
)

labor_burden = Table(
    "labor_burden",
    metadata,
    Column("schedule", String, primary_key=True),  # "union" / "non_union"
    Column("burden_pct", Numeric(6, 3)),
    _source_ref(),
)

# --- APIs ---------------------------------------------------------------------------------------

dispatch_sites = Table(
    "dispatch_sites",
    metadata,
    Column("site_id", String, primary_key=True),
    Column("name", String),
    Column("timezone", String),
    Column("active", Boolean),
    _source_ref(),
)

dispatch_workers = Table(
    "dispatch_workers",
    metadata,
    Column("worker_id", String, primary_key=True),
    Column("display_name", String),
    Column("hr_employee_no", String),
    Column("phone_last4", String),
    Column("active", Boolean),
    _source_ref(),
)

dispatch_postings = Table(
    "dispatch_postings",
    metadata,
    Column("posting_id", String, primary_key=True),
    Column("site_id", String),
    Column("shift_date", Date),
    Column("shift", String),
    Column("start_local", String),
    Column("reason", String),
    Column("absent_employee_text", String),
    Column("status", String),
    Column("created_at", DateTime(timezone=True)),
    Column("updated_at", DateTime(timezone=True)),
    Column("assigned_worker_id", String),
    Column("fill_type", String),
    Column("events", JSON),
    _source_ref(),
)

payroll_employees = Table(
    "payroll_employees",
    metadata,
    Column("employee_id", Integer, primary_key=True),
    Column("name", String),
    Column("status", String),
    _source_ref(),
)

payroll_codes = Table(
    "payroll_codes",
    metadata,
    Column("code", String, primary_key=True),
    Column("description", String),
    Column("paid", Boolean),
    Column("union_only", Boolean),
    _source_ref(),
)

finance_entities = Table(
    "finance_entities",
    metadata,
    Column("entity_code", String, primary_key=True),
    Column("name", String),
    _source_ref(),
)

finance_sites = Table(
    "finance_sites",
    metadata,
    Column("site_name", String, primary_key=True),
    Column("department", String),
    Column("description", String),
    _source_ref(),
)

finance_customers = Table(
    "finance_customers",
    metadata,
    Column("entity_code", String, primary_key=True),
    Column("customer_no", String, primary_key=True),
    Column("customer_name", String),
    Column("terms", String),
    Column("status", String),
    _source_ref(),
)

invoice_lines = Table(
    "invoice_lines",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("entity", String),
    Column("invoice_no", String),
    Column("invoice_date", Date),
    Column("customer_no", String),
    Column("customer_name", String),
    Column("service_period", String),
    Column("site_name", String),
    Column("line_no", Integer),
    Column("line_type", String),
    Column("service_date", Date),
    Column("description", Text),
    Column("amount", MONEY),
    _source_ref(),
)

ar_items = Table(
    "ar_items",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("entity", String),
    Column("customer_no", String),
    Column("customer_name", String),
    Column("doc_type", String),
    Column("doc_no", String),
    Column("apply_to", String),
    Column("doc_date", Date),
    Column("due_date", Date),
    Column("amount", MONEY),
    _source_ref(),
)

gl_lines = Table(
    "gl_lines",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("entity", String),
    Column("department", String),
    Column("account", String),
    Column("account_name", String),
    Column("week_ending", Date),
    Column("amount", MONEY),
    _source_ref(),
)

report_control_totals = Table(
    "report_control_totals",
    metadata,
    Column("label", String, primary_key=True),
    Column("amount", MONEY),
    _source_ref(),
)

# --- resolved identities (step "resolve") --------------------------------------------------------

# Every name or code a source uses for a building, and the Schedule B building it means.
building_aliases = Table(
    "building_aliases",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("source", String, nullable=False),  # finance_site, department, hr_location, dispatch_site, ...
    Column("alias", String, nullable=False),
    Column("building", String),  # None = could not be resolved
    Column("method", String, nullable=False),
    Column("confidence", String, nullable=False),
    Column("note", Text),
)

# One row per Schedule B building with its terms as of the end of the reporting period.
buildings = Table(
    "buildings",
    metadata,
    Column("building", String, primary_key=True),
    Column("client_name", String),
    Column("contractor_name", String),
    Column("contract_entity", String),
    Column("department", String),
    Column("hr_location", String),
    Column("day_posts", Integer),
    Column("night_posts", Integer),
    Column("pricing_basis", String),
    Column("monthly_fee", MONEY),
    Column("markup_pct", Numeric(6, 3)),
    Column("coverage_billable", Boolean),
    Column("backup_template", String),  # "A" names required, "B" names forbidden, None = no backup rules
    Column("invoice_entity", String),
    Column("invoice_customer_no", String),
    Column("master_customer_no", String),
    _source_ref(),
)

# Ids other systems use for an employee (badge, payroll number, dispatch worker) -> HR employee_id.
employee_xref = Table(
    "employee_xref",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("source", String, nullable=False),  # badge / payroll / dispatch
    Column("source_id", String, nullable=False),
    Column("name_in_source", String),
    Column("employee_id", String),  # None = could not be resolved
    Column("method", String, nullable=False),
    Column("confidence", String, nullable=False),
)

# Home building and shift of each employee over time (HR roster, updated by fully approved PAFs).
employee_assignments = Table(
    "employee_assignments",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("employee_id", String, nullable=False),
    Column("building", String),  # None for the float pool
    Column("shift", String),
    Column("start_date", Date),
    Column("end_date", Date),  # inclusive; None = still assigned
    Column("basis", Text, nullable=False),
)

# --- KPIs ----------------------------------------------------------------------------------------

kpis_by_building = Table(
    "kpis_by_building",
    metadata,
    Column("building", String, primary_key=True),
    Column("contracted_headcount", Integer),
    Column("active_headcount", Integer),
    Column("headcount_variance", Integer),
    Column("scheduled_shifts", Integer),
    Column("callout_shifts", Integer),
    Column("callout_rate", Numeric(8, 4)),
    Column("fill_rate", Numeric(8, 4)),
    Column("overtime_hours", Numeric(10, 2)),
    Column("overtime_dollars", MONEY),
    Column("revenue", MONEY),
    Column("labor_cost", MONEY),
    Column("gross_margin", MONEY),
    Column("gross_margin_pct", Numeric(8, 4)),
    Column("unbilled_coverage_count", Integer),
    Column("unbilled_coverage_dollars", MONEY),
)

# Every open receivable item behind ar_aging.csv, so each bucket can be drilled into.
ar_open_items = Table(
    "ar_open_items",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("entity", String),
    Column("customer_no", String),
    Column("doc_type", String),
    Column("doc_no", String),
    Column("doc_date", Date),
    Column("due_date", Date),
    Column("open_amount", MONEY),
    Column("days_past_due", Integer),
    Column("bucket", String),
    _source_ref(),
)

# --- call-outs and payroll ------------------------------------------------------------------------

# One row per message outcome: an absence (one per day named), a duplicate, or not an absence.
callout_events = Table(
    "callout_events",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("source", String, nullable=False),  # reception_log / area_manager_chat
    Column("source_ref", String, nullable=False),  # log row number or chat timestamp
    Column("record_ref", Text, nullable=False),  # exact file line
    Column("outcome", String, nullable=False),  # absence / duplicate / not_absence / unreadable
    Column("reason", String),
    Column("name_as_written", String),
    Column("employee_id", String),
    Column("payroll_id", Integer),
    Column("absence_date", Date),
    Column("building", String),
    Column("shift", String),
    Column("contact_at", DateTime),
    Column("contact_basis", String),
    Column("notice_hours", Numeric(6, 2)),
    Column("code", String),
    Column("code_reason", Text),
    Column("decision", String),  # written / held_for_review
    Column("hold_reason", Text),
    Column("confidence", String),
    Column("evidence", Text),
    Column("duplicate_of", String),
    Column("posting_id", String),
    Column("submission_id", String),
    Column("final_status", String),
    Column("extraction", JSON),
)

# State tables: kept across runs so payroll writes are never repeated and every call is on record.
payroll_ledger = Table(
    "payroll_ledger",
    metadata,
    Column("payroll_id", Integer, primary_key=True),
    Column("absence_date", Date, primary_key=True),
    Column("code", String, nullable=False),
    Column("submission_id", String),
    Column("status", String),
    Column("source_ref", Text),
    Column("updated_at", DateTime(timezone=True), server_default=func.now(), onupdate=func.now()),
)

payroll_audit = Table(
    "payroll_audit",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("at", DateTime(timezone=True), server_default=func.now()),
    Column("action", String, nullable=False),  # GET / POST / DELETE / DRY_RUN
    Column("payroll_id", Integer),
    Column("absence_date", Date),
    Column("request", JSON),
    Column("status_code", Integer),
    Column("response", Text),
    Column("attempt", Integer),
    Column("dry_run", Boolean, nullable=False),
)

# --- billing --------------------------------------------------------------------------------------

# One row per billable coverage shift (filled posting at a cost-plus building) and how it was billed.
billable_coverage = Table(
    "billable_coverage",
    metadata,
    Column("posting_id", String, primary_key=True),
    Column("building", String),
    Column("client_name", String),
    Column("template", String),
    Column("shift_date", Date),
    Column("shift", String),
    Column("reason", String),
    Column("overtime", Boolean),
    Column("covering_employee_id", String),
    Column("covering_name", String),
    Column("absent_employee_id", String),
    Column("position_covered", String),
    Column("base_rate", MONEY),
    Column("burden_pct", Numeric(6, 3)),
    Column("markup_pct", Numeric(6, 3)),
    Column("billable_amount", MONEY),
    Column("on_site_in", DateTime),
    Column("on_site_out", DateTime),
    Column("billed", Boolean),
    Column("invoice_no", String),
    Column("invoice_ref", Text),
    Column("billed_amount", MONEY),
    Column("match_method", String),
    Column("note_path", String),
    _source_ref(),
)

# --- findings -----------------------------------------------------------------------------------

# Same columns as output/exceptions.csv. Every step appends what it could not resolve cleanly.
exceptions = Table(
    "exceptions",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("source", String, nullable=False),
    Column("record_ref", Text, nullable=False),
    Column("issue", Text, nullable=False),
    Column("action_taken", Text, nullable=False),
    Column("confidence", String, nullable=False),  # high / medium / low
)

# --- state kept between runs --------------------------------------------------------------------

llm_cache = Table(
    "llm_cache",
    metadata,
    Column("key", String, primary_key=True),
    Column("model", String),
    Column("schema", String),
    Column("value", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)

STATE_TABLES = {llm_cache.name, payroll_ledger.name, payroll_audit.name}


def connect(database_url: str) -> Engine:
    return create_engine(database_url, future=True)


def rebuild_source_tables(engine: Engine) -> None:
    """Drop and recreate every source table; create state tables only if missing."""
    source_tables = [t for t in metadata.sorted_tables if t.name not in STATE_TABLES]
    metadata.drop_all(engine, tables=source_tables)
    metadata.create_all(engine)


def fetch(engine: Engine, table: Table) -> list[dict]:
    with engine.connect() as conn:
        return [dict(r._mapping) for r in conn.execute(select(table))]


def insert_rows(engine: Engine, table: Table, rows: Iterable[dict]) -> int:
    rows = list(rows)
    if rows:
        with engine.begin() as conn:
            conn.execute(insert(table), rows)
    return len(rows)


def add_exception(
    engine: Engine, source: str, record_ref: str, issue: str, action_taken: str, confidence: str
) -> None:
    insert_rows(
        engine,
        exceptions,
        [
            {
                "source": source,
                "record_ref": record_ref,
                "issue": issue,
                "action_taken": action_taken,
                "confidence": confidence,
            }
        ],
    )


class DbCache:
    """LLM answer cache stored in Postgres (see northgate/llm.py)."""

    def __init__(self, engine: Engine):
        self.engine = engine

    def get(self, key: str) -> str | None:
        with self.engine.connect() as conn:
            return conn.execute(select(llm_cache.c.value).where(llm_cache.c.key == key)).scalar_one_or_none()

    def put(self, key: str, model: str, schema: str, value: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(llm_cache.delete().where(llm_cache.c.key == key))
            conn.execute(insert(llm_cache).values(key=key, model=model, schema=schema, value=value))
