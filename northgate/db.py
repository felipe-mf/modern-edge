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

STATE_TABLES = {llm_cache.name}


def connect(database_url: str) -> Engine:
    return create_engine(database_url, future=True)


def rebuild_source_tables(engine: Engine) -> None:
    """Drop and recreate every source table; create state tables only if missing."""
    source_tables = [t for t in metadata.sorted_tables if t.name not in STATE_TABLES]
    metadata.drop_all(engine, tables=source_tables)
    metadata.create_all(engine)


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
