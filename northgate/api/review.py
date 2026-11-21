"""The review queue: held absences and exceptions, and what a person decides about them.

Approving a held absence sends it through the same exactly-once payroll writer as the pipeline (it
asks payroll first, so it can never create a duplicate). Every action is kept in `review_actions`,
which survives pipeline runs; the next run reads it, so an approved absence stays written.
"""

from pathlib import Path

from sqlalchemy import Engine, update

from northgate import db, outputs
from northgate.callouts.run import REVIEW, WRITE, event_key, latest_reviews
from northgate.clients.payroll import PayrollClient
from northgate.config import Settings
from northgate.payroll.writer import PayrollWriter


def exception_key(x: dict) -> str:
    return f"{x['source']}|{x['record_ref']}|{x['issue']}"


def review_queue(engine: Engine) -> dict:
    callout_reviews = latest_reviews(engine, "callout")
    exception_reviews = latest_reviews(engine, "exception")
    absences = []
    for e in db.fetch(engine, db.callout_events):
        if e["outcome"] not in ("absence", "unreadable"):
            continue
        key = event_key(e)
        if e["decision"] == REVIEW or key in callout_reviews:
            absences.append({**e, "item_key": key, "review": callout_reviews.get(key)})
    exceptions = [{**x, "item_key": exception_key(x), "review": exception_reviews.get(exception_key(x))}
                  for x in db.fetch(engine, db.exceptions)]  # fmt: skip
    return {
        "absences": sorted(absences, key=lambda e: e["id"]),
        "exceptions": sorted(exceptions, key=lambda x: x["id"]),
    }


def _record(engine: Engine, kind: str, key: str, action: str, note: str | None, result: str) -> None:
    db.insert_rows(engine, db.review_actions, [{"item_kind": kind, "item_key": key, "action": action,
                                                "note": note, "result": result}])  # fmt: skip


def _event(engine: Engine, event_id: int) -> dict:
    event = next((e for e in db.fetch(engine, db.callout_events) if e["id"] == event_id), None)
    if event is None:
        raise KeyError(event_id)
    return event


def _save(engine: Engine, event_id: int, values: dict, output_dir: Path | None) -> dict:
    with engine.begin() as conn:
        conn.execute(update(db.callout_events).where(db.callout_events.c.id == event_id).values(**values))
    if output_dir and output_dir.is_dir():
        outputs.write_payroll_submissions(engine, output_dir)  # keep the output file equal to payroll
    return _event(engine, event_id)


def approve_absence(engine: Engine, settings: Settings, event_id: int, note: str | None) -> dict:
    event = _event(engine, event_id)
    if event["decision"] != REVIEW:
        raise ValueError("only absences held for review can be approved")
    missing = [f for f in ("payroll_id", "absence_date", "code") if not event.get(f)]
    if missing:
        raise ValueError(
            f"cannot be written to payroll: no {', '.join(missing)}; dismiss it or fix the source"
        )

    client = PayrollClient(settings.payroll_url, settings.payroll_api_key)
    writer = PayrollWriter(client, engine, settings.payroll_dry_run, settle_seconds=30)
    result = writer.write(event)
    if result["decision"] == WRITE and result.get("submission_id"):
        status = writer.settle([{**event, **result}])
        result["final_status"] = status.get(result["submission_id"], result.get("final_status"))

    if result["decision"] == WRITE:
        values = {**result, "hold_reason": None,
                  "evidence": "; ".join(filter(None, [event["evidence"],
                                                      f"held ({event['hold_reason']}), approved by reviewer"]))}  # fmt: skip
        outcome = f"written: {result.get('submission_id')} {result.get('final_status')}"
    else:
        values = {"hold_reason": f"{event['hold_reason']}; approval failed: {result['hold_reason']}"}
        outcome = f"not written: {result['hold_reason']}"
    _record(engine, "callout", event_key(event), "approve", note, outcome)
    return _save(engine, event_id, values, settings.output_dir)


def dismiss_absence(engine: Engine, settings: Settings, event_id: int, note: str | None) -> dict:
    event = _event(engine, event_id)
    if event["decision"] != REVIEW:
        raise ValueError("only absences held for review can be dismissed")
    _record(engine, "callout", event_key(event), "dismiss", note, "kept out of payroll")
    reason = f"dismissed by reviewer{f' ({note})' if note else ''}; was: {event['hold_reason']}"
    return _save(engine, event_id, {"hold_reason": reason}, settings.output_dir)


def acknowledge_exception(engine: Engine, item_key: str, action: str, note: str | None) -> None:
    if action not in ("acknowledge", "dismiss"):
        raise ValueError("action must be acknowledge or dismiss")
    if not any(exception_key(x) == item_key for x in db.fetch(engine, db.exceptions)):
        raise KeyError(item_key)
    _record(engine, "exception", item_key, action, note, action)
