"""Runtime settings, read once from environment variables.

Every setting the evaluators may change (data folder, system URLs, model key) comes from the
environment, so nothing about a specific dataset or deployment is baked into the code.
"""

import os
from dataclasses import dataclass
from pathlib import Path


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def _env_bool(name: str, default: bool = False) -> bool:
    value = _env(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    output_dir: Path
    database_url: str

    payroll_url: str
    payroll_api_key: str
    dispatch_url: str
    dispatch_client_id: str
    dispatch_client_secret: str
    finance_url: str
    finance_user: str
    finance_password: str

    anthropic_api_key: str | None
    anthropic_model: str  # documents: contracts and PAF scans
    anthropic_callout_model: str  # short call-out messages
    anthropic_chat_model: str  # the "Ask the data" chatbot

    payroll_dry_run: bool
    period: str | None  # "YYYY-MM"; None means infer it from the data


def load_settings() -> Settings:
    return Settings(
        data_dir=Path(_env("DATA_DIR", "./data")),
        output_dir=Path(_env("OUTPUT_DIR", "./output")),
        database_url=_env(
            "DATABASE_URL", "postgresql+psycopg://northgate:northgate@localhost:5432/northgate"
        ),
        payroll_url=_env("PAYROLL_URL", "http://localhost:8081").rstrip("/"),
        payroll_api_key=_env("PAYROLL_API_KEY", ""),
        dispatch_url=_env("DISPATCH_URL", "http://localhost:8082").rstrip("/"),
        dispatch_client_id=_env("DISPATCH_CLIENT_ID", ""),
        dispatch_client_secret=_env("DISPATCH_CLIENT_SECRET", ""),
        finance_url=_env("FINANCE_URL", "http://localhost:8083").rstrip("/"),
        finance_user=_env("FINANCE_USER", ""),
        finance_password=_env("FINANCE_PASSWORD", ""),
        anthropic_api_key=_env("ANTHROPIC_API_KEY"),
        anthropic_model=_env("ANTHROPIC_MODEL", "claude-opus-5-5"),
        anthropic_callout_model=_env("ANTHROPIC_CALLOUT_MODEL", "claude-sonnet-5-5"),
        anthropic_chat_model=_env("ANTHROPIC_CHAT_MODEL", "claude-sonnet-5-5"),
        payroll_dry_run=_env_bool("PAYROLL_DRY_RUN", False),
        period=_env("PERIOD"),
    )
