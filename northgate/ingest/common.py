"""Small parsing helpers shared by every ingest module.

Each source writes dates and amounts its own way, so these helpers accept the formats seen in the
client's files and fail loudly on anything else, instead of guessing.
"""

import re
import subprocess
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d-%b-%y", "%d-%b-%Y")


def parse_date(value: str | date | datetime | None) -> date | None:
    """Parse a date written as 2026-10-01, 10/01/2026, 10/01/26 or 01-OCT-26. Empty -> None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()  # %b matches "OCT" and "Oct" alike
        except ValueError:
            continue
    raise ValueError(f"Unrecognised date: {value!r}")


def parse_amount(value: str | float | Decimal | None) -> Decimal | None:
    """Parse money as printed by the ERP: "1,234.50", "(1,250.00)", "1250.00-", "$23.26"."""
    if value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value))
    text = str(value).strip().replace("$", "").replace(",", "").replace(" ", "")
    if not text:
        return None
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative, text = True, text[1:-1]
    elif text.endswith("-"):
        negative, text = True, text[:-1]
    elif text.startswith("-"):
        negative, text = True, text[1:]
    try:
        amount = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"Unrecognised amount: {value!r}") from exc
    return -amount if negative else amount


def parse_yes_no(value: str | None) -> bool | None:
    text = (value or "").strip().upper()
    if text in ("Y", "YES", "TRUE", "1"):
        return True
    if text in ("N", "NO", "FALSE", "0"):
        return False
    return None


def clean_text(value: object) -> str | None:
    """Strip whitespace and invisible characters that phone exports add; empty -> None."""
    if value is None:
        return None
    text = str(value).replace("‎", "").replace(" ", " ").replace("\xa0", " ").strip()
    return text or None


def normalize_header(name: object) -> str:
    """'VM Received' -> 'vm_received', 'EmpBadge' stays 'empbadge'."""
    return re.sub(r"[^a-z0-9]+", "_", str(name or "").strip().lower()).strip("_")


def is_temp_file(path: Path) -> bool:
    """Office lock files (.~lock.x#, ~$x.xlsx) and hidden files are not data."""
    return path.name.startswith((".", "~$"))


def data_files(folder: Path, pattern: str) -> list[Path]:
    return sorted(p for p in folder.glob(pattern) if p.is_file() and not is_temp_file(p))


def pdf_text(path: Path) -> str:
    """Text layer of a PDF, keeping the column layout (poppler's pdftotext). Empty for scans."""
    result = subprocess.run(
        ["pdftotext", "-layout", str(path), "-"], capture_output=True, text=True, check=True
    )
    return result.stdout
