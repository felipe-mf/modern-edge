"""The "Ask the data" chatbot.

Claude answers only from Northgate's database. It gets a few fixed tools (the building board, the
records behind a KPI, a lookup by source reference) and one read-only SQL tool, and it must finish
by calling `answer` with the source references it relied on, so the interface can link them.

The SQL tool is read-only three times over: only a single SELECT/WITH statement is accepted, it runs
in a READ ONLY transaction (Postgres refuses any write), and it has a statement timeout and a row cap.
"""

import json
import re
from datetime import date, datetime
from decimal import Decimal

import anthropic
from sqlalchemy import Engine, text

from northgate import db
from northgate.api import views

MAX_ROWS = 200
MAX_TURNS = 8
STATEMENT_TIMEOUT_MS = 5000
HIDDEN_TABLES = {db.llm_cache.name}  # cached model answers: not business data

SYSTEM = """You answer questions from Northgate's back-office staff (operations, payroll, finance) \
about one month of their data: buildings, employees, shifts and time punches, call-outs and the \
payroll codes given to them, dispatch coverage, billing, KPIs and receivables.

Rules:
- Answer only from the tools. Never guess a number, name or date. If the data cannot answer, say so \
plainly and say what is missing.
- Prefer the fixed tools; use run_sql for anything else. Look at the schema below before writing SQL.
- Keep answers short and concrete: the figure or names first, then one or two lines of why.
- Always finish by calling `answer` with the text and the source references (the `source_ref` or \
`record_ref` values of the rows you used, at most 8).
- Payroll codes: SKP sick paid, SKU sick unpaid, LTN late notice, CLN clinic, BRV bereavement, \
JRY jury duty, FEM family emergency, PER personal.

Database schema (PostgreSQL):
{schema}
"""

TOOLS = [
    {
        "name": "run_sql",
        "description": "Run one read-only SQL SELECT on the database and get up to 200 rows back as JSON. "
        "Include source_ref or record_ref columns so you can cite them.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "A single SELECT or WITH statement."}},
            "required": ["query"],
        },
    },
    {
        "name": "building_board",
        "description": "Who was assigned, on site, out (and why) and covering at one building, date and shift.",
        "input_schema": {
            "type": "object",
            "properties": {
                "building": {"type": "string"},
                "day": {"type": "string", "description": "YYYY-MM-DD"},
                "shift": {"type": "string", "enum": ["day", "night"]},
            },
            "required": ["building", "day", "shift"],
        },
    },
    {
        "name": "kpi_detail",
        "description": "A building's KPI value, its definition and the records it was computed from. Metrics: "
        + ", ".join(views.METRICS),
        "input_schema": {
            "type": "object",
            "properties": {"building": {"type": "string"}, "metric": {"type": "string"}},
            "required": ["building", "metric"],
        },
    },
    {
        "name": "find_records",
        "description": "Every stored row, in any table, whose source_ref or record_ref equals the given value.",
        "input_schema": {
            "type": "object",
            "properties": {"ref": {"type": "string"}},
            "required": ["ref"],
        },
    },
    {
        "name": "answer",
        "description": "Give the final answer to the user. Call this exactly once, last.",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "sources": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
            },
            "required": ["text", "sources"],
        },
    },
]


def schema_text() -> str:
    lines = []
    for table in db.metadata.sorted_tables:
        if table.name not in HIDDEN_TABLES:
            lines.append(f"{table.name}({', '.join(c.name for c in table.columns)})")
    return "\n".join(lines)


def _json(value) -> str:
    def default(v):
        if isinstance(v, (date, datetime)):
            return v.isoformat()
        if isinstance(v, Decimal):
            return str(v)
        return str(v)

    return json.dumps(value, default=default)[:60_000]


def read_only_sql(engine: Engine, query: str) -> dict:
    statement = query.strip().rstrip(";").strip()
    if ";" in statement:
        raise ValueError("only one statement is allowed")
    if not re.match(r"(?is)^(select|with)\b", statement):
        raise ValueError("only SELECT or WITH queries are allowed")
    if any(name in statement.lower() for name in HIDDEN_TABLES):
        raise ValueError("that table is not available")
    with engine.connect() as conn, conn.begin():
        if engine.dialect.name == "postgresql":
            conn.execute(text("SET TRANSACTION READ ONLY"))
            conn.execute(text(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}"))
        result = conn.execute(text(statement))
        columns = list(result.keys())
        rows = [dict(zip(columns, row, strict=True)) for row in result.fetchmany(MAX_ROWS + 1)]
    return {"columns": columns, "rows": rows[:MAX_ROWS], "truncated": len(rows) > MAX_ROWS}


def run_tool(engine: Engine, name: str, args: dict):
    if name == "run_sql":
        return read_only_sql(engine, args["query"])
    if name == "building_board":
        return views.building_board(engine, args["building"], date.fromisoformat(args["day"]), args["shift"])
    if name == "kpi_detail":
        detail = views.kpi_detail(engine, args["building"], args["metric"])
        for section in detail["sections"]:
            section["records"] = section["records"][:60]
        return detail
    if name == "find_records":
        return views.find_records(engine, args["ref"])
    raise ValueError(f"unknown tool {name}")


def ask(engine: Engine, client: anthropic.Anthropic, model: str, history: list[dict]) -> dict:
    """Run the tool loop for one user question; `history` is the visible conversation so far."""
    messages = [{"role": m["role"], "content": m["content"]} for m in history[-12:]]
    system = SYSTEM.format(schema=schema_text())
    for _ in range(MAX_TURNS):
        response = client.messages.create(
            model=model,
            max_tokens=8000,
            system=system,
            tools=TOOLS,
            messages=messages,
            thinking={"type": "adaptive"},
            output_config={"effort": "medium"},
        )
        messages.append({"role": "assistant", "content": response.content})
        calls = [b for b in response.content if b.type == "tool_use"]
        final = next((c for c in calls if c.name == "answer"), None)
        if final is not None:
            return {
                "answer": final.input["text"],
                "sources": list(dict.fromkeys(final.input.get("sources", []))),
            }
        if not calls:  # answered in plain text without the answer tool
            words = "".join(b.text for b in response.content if b.type == "text").strip()
            return {"answer": words or "I could not find an answer in the data.", "sources": []}
        results = []
        for call in calls:
            try:
                content, error = _json(run_tool(engine, call.name, call.input)), False
            except Exception as exc:  # noqa: BLE001 - the model sees the error and can fix its query
                content, error = f"error: {exc}", True
            results.append(
                {"type": "tool_result", "tool_use_id": call.id, "content": content, "is_error": error}
            )
        messages.append({"role": "user", "content": results})
    return {"answer": "I could not finish looking this up. Try a narrower question.", "sources": []}
