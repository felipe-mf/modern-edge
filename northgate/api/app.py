"""HTTP API for the interface: `uvicorn northgate.api.app:app`.

Read-only over the pipeline's tables, except the review actions. Errors come back as
{"detail": "..."} with 404 for unknown items and 409 for actions that are not allowed.
"""

from datetime import date
from functools import cache
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import Engine

from northgate import db
from northgate.api import review, views
from northgate.config import Settings, load_settings

app = FastAPI(title="Northgate", docs_url="/api/docs", openapi_url="/api/openapi.json")


@cache
def settings() -> Settings:
    return load_settings()


@cache
def engine() -> Engine:
    return db.connect(settings().database_url)


def _found(fn, *args):
    try:
        return fn(*args)
    except KeyError as exc:
        raise HTTPException(404, f"not found: {exc.args[0]}") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/run")
def run():
    info = views.run_info(engine())
    if info is None:
        raise HTTPException(404, "the pipeline has not run yet")
    return {**info, "buildings": [b["building"] for b in db.fetch(engine(), db.buildings)]}


@app.get("/api/buildings")
def buildings():
    return sorted(db.fetch(engine(), db.buildings), key=lambda b: b["building"])


@app.get("/api/buildings/{building}/board")
def board(building: str, day: date, shift: Literal["day", "night"]):
    return _found(views.building_board, engine(), building, day, shift)


@app.get("/api/kpis")
def kpis():
    return views.kpi_panel(engine())


@app.get("/api/kpis/{building}/{metric}")
def kpi_detail(building: str, metric: str):
    return _found(views.kpi_detail, engine(), building, metric)


@app.get("/api/ar-aging/{bucket}")
def ar_bucket(bucket: str):
    return [i for i in db.fetch(engine(), db.ar_open_items) if i["bucket"] == bucket]


@app.get("/api/payroll-submissions")
def payroll_submissions():
    return sorted(
        (e for e in db.fetch(engine(), db.callout_events) if e["outcome"] in ("absence", "unreadable")),
        key=lambda e: (e["absence_date"] or date.max, e["id"]),
    )


@app.get("/api/records")
def records(ref: str):
    return views.find_records(engine(), ref)


@app.get("/api/review")
def review_queue():
    return review.review_queue(engine())


class AbsenceAction(BaseModel):
    action: Literal["approve", "dismiss"]
    note: str | None = None


@app.post("/api/review/absences/{event_id}")
def review_absence(event_id: int, body: AbsenceAction):
    act = review.approve_absence if body.action == "approve" else review.dismiss_absence
    return _found(act, engine(), settings(), event_id, body.note)


class ExceptionAction(BaseModel):
    item_key: str
    action: Literal["acknowledge", "dismiss"]
    note: str | None = None


@app.post("/api/review/exceptions")
def review_exception(body: ExceptionAction):
    _found(review.acknowledge_exception, engine(), body.item_key, body.action, body.note)
    return {"status": "recorded"}
