"""Payroll absence API client.

This is a thin wrapper. Reads are retried freely. `create_absence` makes exactly ONE attempt:
payroll has no idempotency key, so a blind retry after a timeout could record the absence twice.
The payroll writer (northgate/payroll/writer.py) owns the check-then-retry logic.
"""

from collections.abc import Iterator
from typing import Any

import httpx

from northgate.clients.http import DEFAULT_TIMEOUT, raise_for_status, send_with_retry


class PayrollClient:
    def __init__(self, base_url: str, api_key: str, http: httpx.Client | None = None):
        self.base_url = base_url
        self.http = http or httpx.Client(timeout=DEFAULT_TIMEOUT, headers={"X-API-Key": api_key})

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        return raise_for_status(send_with_retry(lambda: self.http.get(url, params=params))).json()

    def health(self) -> dict:
        return self._get("/v1/health")

    def codes(self) -> Any:
        return self._get("/v1/codes")

    def employees(self) -> list[dict]:
        out: list[dict] = []
        page = 1
        while True:
            body = self._get("/v1/employees", {"page": page, "page_size": 100})
            out.extend(body["employees"])
            if not body["employees"] or len(out) >= body.get("total", 0):
                return out
            page += 1

    def iter_absences(self, **filters: Any) -> Iterator[dict]:
        page = 1
        while True:
            body = self._get("/v1/absences", {**filters, "page": page, "page_size": 100})
            yield from body["absences"]
            seen = (page - 1) * 100 + len(body["absences"])
            if not body["absences"] or seen >= body.get("total", 0):
                return
            page += 1

    def find_absences(self, employee_id: int, date: str) -> list[dict]:
        return list(self.iter_absences(employee_id=employee_id, date=date))

    def get_absence(self, submission_id: str) -> dict:
        return self._get(f"/v1/absences/{submission_id}")

    def create_absence(self, payload: dict) -> httpx.Response:
        """Single attempt; returns the raw response so the caller can decide what happened."""
        return self.http.post(f"{self.base_url}/v1/absences", json=payload)

    def void_absence(self, submission_id: str) -> httpx.Response:
        # Voiding the same submission twice is harmless, so retries are safe here.
        return send_with_retry(lambda: self.http.delete(f"{self.base_url}/v1/absences/{submission_id}"))

    def reset(self) -> httpx.Response:
        """Development only: deletes every submission."""
        return send_with_retry(lambda: self.http.post(f"{self.base_url}/v1/admin/reset"))
