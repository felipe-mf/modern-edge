"""Writes approved absences to payroll exactly once.

Payroll has no idempotency key, can answer 503 during processing windows, and does nothing to stop
the same absence being recorded twice. So for every absence (payroll employee + date):

1. Ask payroll first. If the absence is already there with the same code, adopt it (a rerun, or a
   write whose answer was lost). If it is there with another code, hold it for a person: never
   overwrite what payroll holds.
2. Otherwise POST once. If the answer is lost or a 5xx comes back, the write may or may not have
   happened: wait, ask payroll again, and only POST again if it is still not there.
3. When everything is sent, wait for payroll to process the batch, then look once more: any extra
   copy with the same code is voided, keeping one.

Dry-run mode reads payroll but never writes or voids. Every request and answer goes to
`payroll_audit`; the last known state of each absence is kept in `payroll_ledger`.
"""

import json
import logging
import time
from collections.abc import Callable
from datetime import date

import httpx
from sqlalchemy import Engine, update
from sqlalchemy.dialects.postgresql import insert

from northgate import db
from northgate.callouts.rules import SHIFT_HOURS
from northgate.clients.http import RETRYABLE_STATUS, RetriesExhausted, retry_delay
from northgate.clients.payroll import PayrollClient

log = logging.getLogger(__name__)

INACTIVE = {"VOIDED", "VOID", "DELETED", "CANCELLED"}
WRITTEN, REVIEW = "written", "held_for_review"


def active(absences: list[dict]) -> list[dict]:
    return [a for a in absences if (a.get("status") or "").upper() not in INACTIVE and not a.get("voided")]


def _keep_first(copies: list[dict]) -> dict:
    """The copy to keep among duplicates: a processed one if any, then the earliest submitted."""
    return min(copies, key=lambda a: ((a.get("status") or "") != "POSTED", str(a.get("received_at") or ""),
                                         a["submission_id"]))  # fmt: skip


class PayrollWriter:
    def __init__(
        self,
        client: PayrollClient,
        engine: Engine,
        dry_run: bool,
        sleep: Callable[[float], None] = time.sleep,
        max_attempts: int = 6,
        settle_seconds: float = 90,
    ):
        self.client = client
        self.engine = engine
        self.dry_run = dry_run
        self.sleep = sleep
        self.max_attempts = max_attempts
        self.settle_seconds = settle_seconds

    # --- records ----------------------------------------------------------------------------

    def _audit(self, action, payroll_id, day, request=None, response=None, attempt=None, error=None):
        db.insert_rows(self.engine, db.payroll_audit, [{
            "action": action, "payroll_id": payroll_id, "absence_date": day, "request": request,
            "status_code": response.status_code if response is not None else None,
            "response": (response.text[:2000] if response is not None else error),
            "attempt": attempt, "dry_run": self.dry_run,
        }])  # fmt: skip

    def _ledger(self, payroll_id: int, day: date, code: str, submission_id: str | None, status: str | None,
                source_ref: str | None = None) -> None:  # fmt: skip
        values = {"payroll_id": payroll_id, "absence_date": day, "code": code, "submission_id": submission_id,
                  "status": status, "source_ref": source_ref}  # fmt: skip
        stmt = insert(db.payroll_ledger).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["payroll_id", "absence_date"],
            set_={
                k: v for k, v in values.items() if v is not None and k not in ("payroll_id", "absence_date")
            },
        )
        with self.engine.begin() as conn:
            conn.execute(stmt)

    # --- payroll calls ----------------------------------------------------------------------

    def find(self, payroll_id: int, day: date) -> list[dict]:
        found = self.client.find_absences(payroll_id, day.isoformat())
        self._audit("GET", payroll_id, day, {"employee_id": payroll_id, "date": day.isoformat()},
                    error=json.dumps(found, default=str)[:2000])  # fmt: skip
        return active(found)

    def void(self, payroll_id: int, day: date, submission_id: str) -> None:
        if self.dry_run:
            self._audit("DRY_RUN", payroll_id, day, {"void": submission_id})
            return
        response = self.client.void_absence(submission_id)
        self._audit("DELETE", payroll_id, day, {"submission_id": submission_id}, response)
        log.warning("voided duplicate payroll submission %s (%s on %s)", submission_id, payroll_id, day)

    def _adopt(self, copies: list[dict], payroll_id: int, day: date) -> dict:
        keep = _keep_first(copies)
        for extra in copies:
            if extra["submission_id"] != keep["submission_id"]:
                self.void(payroll_id, day, extra["submission_id"])
        return keep

    # --- one absence ------------------------------------------------------------------------

    def write(self, event: dict) -> dict:
        """Returns the fields to update on the event: decision, submission_id, final_status, hold_reason."""
        payroll_id, day, code = event["payroll_id"], event["absence_date"], event["code"]
        payload = {"employee_id": payroll_id, "date": day.isoformat(), "code": code, "hours": SHIFT_HOURS,
                   "note": note(event)}  # fmt: skip
        try:
            existing = self.find(payroll_id, day)
        except RetriesExhausted as exc:
            return self._hold(f"payroll could not be read: {exc}")

        same = [a for a in existing if a.get("code") == code]
        if same:
            keep = self._adopt(same, payroll_id, day)
            self._ledger(
                payroll_id, day, code, keep["submission_id"], keep.get("status"), event["record_ref"]
            )
            return {
                "decision": WRITTEN,
                "submission_id": keep["submission_id"],
                "final_status": keep.get("status"),
            }
        if existing:
            codes = ", ".join(f"{a.get('code')} ({a['submission_id']})" for a in existing)
            return self._hold(f"payroll already has {codes} for this date; not changed")

        if self.dry_run:
            self._audit("DRY_RUN", payroll_id, day, payload)
            return {"decision": WRITTEN, "submission_id": None, "final_status": "DRY_RUN"}

        for attempt in range(1, self.max_attempts + 1):
            response, error = None, None
            try:
                response = self.client.create_absence(payload)
            except httpx.TransportError as exc:
                error = f"{type(exc).__name__}: {exc}"
            self._audit("POST", payroll_id, day, payload, response, attempt, error)

            if response is not None and response.status_code in (200, 201, 202):
                submission_id = response.json()["submission_id"]
                self._ledger(payroll_id, day, code, submission_id, response.json().get("status"),
                             event["record_ref"])  # fmt: skip
                return {"decision": WRITTEN, "submission_id": submission_id, "final_status": None}
            if response is not None and response.status_code not in RETRYABLE_STATUS:
                return self._hold(
                    f"payroll rejected the absence: HTTP {response.status_code} {_error(response)}"
                )

            # The outcome is unknown: look before trying again.
            self.sleep(retry_delay(attempt - 1, response))
            try:
                landed = [a for a in self.find(payroll_id, day) if a.get("code") == code]
            except RetriesExhausted:
                continue
            if landed:
                keep = self._adopt(landed, payroll_id, day)
                self._ledger(
                    payroll_id, day, code, keep["submission_id"], keep.get("status"), event["record_ref"]
                )
                return {"decision": WRITTEN, "submission_id": keep["submission_id"], "final_status": None}
        return self._hold(f"payroll unavailable after {self.max_attempts} attempts; nothing written")

    @staticmethod
    def _hold(reason: str) -> dict:
        return {"decision": REVIEW, "submission_id": None, "final_status": None, "hold_reason": reason}

    # --- after the batch --------------------------------------------------------------------

    def settle(self, written: list[dict]) -> dict[str, str]:
        """Wait until payroll has processed every submission, then sweep for duplicates.

        Returns submission_id -> final status.
        """
        pending = {e["submission_id"]: e for e in written if e.get("submission_id")}
        status: dict[str, str] = {}
        deadline = time.monotonic() + self.settle_seconds
        while pending:
            for submission_id in list(pending):
                try:
                    current = self.client.get_absence(submission_id).get("status")
                except RetriesExhausted:
                    continue
                status[submission_id] = current
                if current != "RECEIVED":
                    pending.pop(submission_id)
            if not pending or time.monotonic() > deadline:
                break
            self.sleep(3)

        for e in written:
            if not e.get("submission_id"):
                continue
            copies = [a for a in self.find(e["payroll_id"], e["absence_date"]) if a.get("code") == e["code"]]
            for extra in copies:
                if extra["submission_id"] != e["submission_id"]:
                    self.void(e["payroll_id"], e["absence_date"], extra["submission_id"])
            self._ledger(e["payroll_id"], e["absence_date"], e["code"], e["submission_id"],
                         status.get(e["submission_id"]))  # fmt: skip
        return status


def note(event: dict) -> str:
    """Short enough for payroll's note field (it keeps 40 characters): 'Call-out 10/02 08:51 log row 2'."""
    where = f"log row {event['source_ref']}" if event["source"] == "reception_log" else "mgr chat"
    return f"Call-out {event['contact_at']:%m/%d %H:%M} {where}"


def _error(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:200]
    detail = body.get("detail", body) if isinstance(body, dict) else body
    return str(detail.get("error", detail) if isinstance(detail, dict) else detail)


def write_to_payroll(engine: Engine, client: PayrollClient, dry_run: bool) -> None:
    """Send every absence decided as `written`, then record what payroll answered on the event."""
    writer = PayrollWriter(client, engine, dry_run)
    events = [
        e
        for e in db.fetch(engine, db.callout_events)
        if e["outcome"] == "absence" and e["decision"] == WRITTEN
    ]
    updates: dict[int, dict] = {}
    for e in sorted(events, key=lambda e: e["id"]):
        result = writer.write(e)
        if result.get("hold_reason"):
            db.add_exception(engine, f"payroll:{e['source']}", f"{e['source_ref']} ({e['record_ref']})",
                             result["hold_reason"], "held for review", "high")  # fmt: skip
        updates[e["id"]] = result
        e.update(result)

    final = writer.settle([e for e in events if e.get("submission_id") and e.get("decision") == WRITTEN])
    for e in events:
        if e.get("submission_id") in final:
            updates[e["id"]]["final_status"] = final[e["submission_id"]]

    with engine.begin() as conn:
        for event_id, values in updates.items():
            conn.execute(update(db.callout_events).where(db.callout_events.c.id == event_id).values(**values))
    log.info("payroll%s: %d written, %d held after the API answered", " (dry run)" if dry_run else "",
             sum(1 for v in updates.values() if v["decision"] == WRITTEN),
             sum(1 for v in updates.values() if v["decision"] == REVIEW))  # fmt: skip
