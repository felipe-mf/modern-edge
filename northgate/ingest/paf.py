"""Scanned Personnel Action Forms -> typed form data.

The scans have no text layer, so Claude reads the page image. Claude only transcribes; whether a
form takes effect (every approval signed) is decided here, in code, from the transcription.
"""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from northgate.ingest.common import parse_date
from northgate.llm import Extractor, pdf_block


class Approval(BaseModel):
    role: str = Field(description="Approval row label, e.g. Human Resources")
    signed: bool = Field(description="True only if a signature is visibly present")
    signer_name: str | None
    signed_date: str | None = Field(description="YYYY-MM-DD as written next to the signature")


class FormField(BaseModel):
    label: str
    value: str


class PersonnelActionForm(BaseModel):
    action: Literal["new_hire", "transfer", "termination", "rate_change", "leave_of_absence", "other"] = (
        Field(description="The action whose box is checked")
    )
    employee_name: str | None
    employee_id: str | None
    job_class: str | None
    effective_date: str | None = Field(description="YYYY-MM-DD")
    from_location: str | None = Field(description="Transfers: the From field, verbatim")
    to_location: str | None = Field(description="Transfers: the To field, verbatim")
    location: str | None = Field(description="Hires/terminations: the Location field, verbatim")
    other_fields: list[FormField] = Field(description="Every other filled-in field, verbatim")
    remarks: str | None
    approvals: list[Approval] = Field(description="Every row of the approvals table, signed or not")
    approval_rule: str | None = Field(description="Printed rule about when the form takes effect, quoted")
    legibility_notes: str = Field(description="Anything hard to read or uncertain; empty if all clear")


INSTRUCTIONS = """You transcribe scanned HR Personnel Action Forms. Copy every value exactly as
written. Report every row of the approvals table, including rows with no signature (signed=false).
A row counts as signed only if a signature is visibly present. Dates as YYYY-MM-DD. Do not guess
illegible values: leave them null and describe the problem in legibility_notes."""


def extract_paf(path: Path, extractor: Extractor) -> PersonnelActionForm:
    return extractor.extract(PersonnelActionForm, INSTRUCTIONS, [pdf_block(path)])


def fully_approved(form: PersonnelActionForm) -> bool:
    """A form takes effect only when every approval on it is signed."""
    return bool(form.approvals) and all(a.signed and a.signer_name for a in form.approvals)


def to_row(form: PersonnelActionForm, path: Path) -> dict:
    return {
        "source_file": path.name,
        "action": form.action,
        "employee_name": form.employee_name,
        "employee_id": form.employee_id,
        "job_class": form.job_class,
        "effective_date": parse_date(form.effective_date),
        "from_location": form.from_location,
        "to_location": form.to_location,
        "location": form.location,
        "fully_approved": fully_approved(form),
        "approvals": [a.model_dump() for a in form.approvals],
        "details": form.model_dump(),
        "source_ref": path.name,
    }
