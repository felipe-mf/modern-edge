"""Document extraction: the cache, the checks against the text, and the PAF approval rule.

Claude itself is replaced by a fake client, so these tests run offline and for free.
"""

from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from northgate.ingest.contracts import BuildingChange, BuildingTerms, ContractDocument, check_contract
from northgate.ingest.paf import Approval, PersonnelActionForm, fully_approved
from northgate.llm import ExtractionFailed, Extractor, MemoryCache


class Answer(BaseModel):
    value: int


class FakeMessages:
    def __init__(self, stop_reason: str = "end_turn"):
        self.calls = 0
        self.stop_reason = stop_reason

    def parse(self, **kwargs):
        self.calls += 1
        return SimpleNamespace(
            stop_reason=self.stop_reason,
            parsed_output=kwargs["output_format"](value=42),
            usage=SimpleNamespace(input_tokens=10),
        )


def test_extractor_caches_answers():
    messages = FakeMessages()
    extractor = Extractor(SimpleNamespace(messages=messages), "model-x", MemoryCache())
    content = [{"type": "text", "text": "hello"}]

    assert extractor.extract(Answer, "instructions", content).value == 42
    assert extractor.extract(Answer, "instructions", content).value == 42
    assert messages.calls == 1
    extractor.extract(Answer, "other instructions", content)  # new prompt -> new cache key
    assert messages.calls == 2


def test_extractor_without_key_uses_cache_only():
    cache = MemoryCache()
    online = Extractor(SimpleNamespace(messages=FakeMessages()), "model-x", cache)
    content = [{"type": "text", "text": "hello"}]
    online.extract(Answer, "i", content)

    offline = Extractor(None, "model-x", cache)
    assert offline.extract(Answer, "i", content).value == 42
    with pytest.raises(ExtractionFailed):
        offline.extract(Answer, "i", [{"type": "text", "text": "not cached"}])


def test_extractor_rejects_refusals():
    extractor = Extractor(SimpleNamespace(messages=FakeMessages("refusal")), "model-x", MemoryCache())
    with pytest.raises(ExtractionFailed):
        extractor.extract(Answer, "i", [{"type": "text", "text": "x"}])


SCHEDULE_TEXT = """
SCHEDULE B
Building        Day posts   Night posts   Pricing basis
North Tower     2           5             Cost plus 10% on labor cost
South Annex     1           3             Fixed monthly fee of $12,500.00
"""


def _doc(buildings, changes=()) -> ContractDocument:
    return ContractDocument(
        document_type="client_agreement",
        client_name="Client",
        contractor_name="Us",
        document_date="2025-01-01",
        amends_agreement_dated=None,
        payment_terms_days=30,
        buildings=buildings,
        coverage_backup=None,
        building_changes=list(changes),
        wage_terms=None,
        notes="",
    )


def _building(**overrides) -> BuildingTerms:
    values = {
        "building": "North Tower",
        "day_posts": 2,
        "night_posts": 5,
        "pricing_basis": "cost_plus",
        "monthly_fee": None,
        "markup_pct": 10,
        "coverage_billable": True,
    }
    return BuildingTerms(**{**values, **overrides})


def test_contract_check_accepts_terms_printed_in_the_document():
    south = _building(
        building="South Annex",
        day_posts=1,
        night_posts=3,
        pricing_basis="fixed_fee",
        monthly_fee=12500,
        markup_pct=None,
        coverage_billable=False,
    )
    assert check_contract(_doc([_building(), south]), SCHEDULE_TEXT, "msa.pdf") == []


def test_contract_check_flags_terms_not_in_the_document():
    issues = check_contract(_doc([_building(building="East Wing", markup_pct=12)]), SCHEDULE_TEXT, "msa.pdf")
    assert any("East Wing" in i for i in issues)
    assert any("markup 12" in i for i in issues)


def test_contract_check_flags_amendment_numbers_not_printed():
    change = BuildingChange(
        building="North Tower",
        effective_date="2025-02-01",
        day_posts=None,
        night_posts=9,
        markup_pct=None,
        monthly_fee=None,
    )
    issues = check_contract(_doc([], [change]), SCHEDULE_TEXT, "amendment.pdf")
    assert issues == ["amendment.pdf: North Tower: new night posts 9 not printed"]


def _form(approvals: list[Approval]) -> PersonnelActionForm:
    return PersonnelActionForm(
        action="transfer",
        employee_name="Jane Doe",
        employee_id="E1",
        job_class="Cleaner",
        effective_date="2025-03-10",
        from_location="A",
        to_location="B",
        location=None,
        other_fields=[],
        remarks=None,
        approvals=approvals,
        approval_rule=None,
        legibility_notes="",
    )


def test_paf_takes_effect_only_with_every_approval_signed():
    signed = Approval(role="HR", signed=True, signer_name="X", signed_date="2025-03-01")
    unsigned = Approval(role="Payroll", signed=False, signer_name=None, signed_date=None)
    assert fully_approved(_form([signed, signed.model_copy(update={"role": "Ops"}), signed]))
    assert not fully_approved(_form([signed, unsigned]))
    assert not fully_approved(_form([]))
