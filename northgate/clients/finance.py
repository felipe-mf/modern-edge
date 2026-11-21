"""Finance ERP client: reference data plus the asynchronous report service.

Reports are submitted as jobs, polled until COMPLETE, then downloaded as the raw text the ERP
prints. A FAILED job is resubmitted. Parsing the three report formats lives in northgate/parsers.
"""

import logging
import time
from collections.abc import Callable
from typing import Any

import httpx

from northgate.clients.http import DEFAULT_TIMEOUT, raise_for_status, send_with_retry

log = logging.getLogger(__name__)


class ReportNotAvailable(Exception):
    """The ERP has no data for the requested report/entity/period (e.g. fault RPT-020)."""


class FinanceClient:
    def __init__(
        self,
        base_url: str,
        user: str,
        password: str,
        http: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.base_url = base_url
        self.http = http or httpx.Client(timeout=DEFAULT_TIMEOUT, auth=(user, password))
        self.sleep = sleep

    def _get(self, path: str, params: dict[str, Any] | None = None) -> httpx.Response:
        url = f"{self.base_url}{path}"
        return raise_for_status(send_with_retry(lambda: self.http.get(url, params=params)))

    # --- reference data ---------------------------------------------------------------------

    def entities(self) -> list[dict]:
        return self._get("/api/v1/entities").json()["items"]

    def customers(self) -> list[dict]:
        out: list[dict] = []
        offset = 0
        while True:
            body = self._get("/api/v1/customers", {"offset": offset, "limit": 100}).json()
            out.extend(body["items"])
            offset += len(body["items"])
            if not body["items"] or offset >= body.get("total", 0):
                return out

    def sites(self) -> list[dict]:
        return self._get("/api/v1/sites").json()["items"]

    # --- reports ----------------------------------------------------------------------------

    def run_report(
        self,
        report_code: str,
        entity_code: str,
        period: str,
        *,
        max_submissions: int = 5,
        poll_interval_s: float = 0.5,
        poll_timeout_s: float = 120.0,
    ) -> str:
        """Submit a report job, wait for it and return the file text. Resubmits FAILED jobs."""
        request = {"report_code": report_code, "entity_code": entity_code, "period": period}
        for submission in range(1, max_submissions + 1):
            response = send_with_retry(
                lambda: self.http.post(f"{self.base_url}/api/v1/reports", json=request)
            )
            if response.status_code == 404:
                raise ReportNotAvailable(f"{request}: {response.text[:200]}")
            job = raise_for_status(response).json()

            status = self._wait_for_job(job["job_id"], poll_interval_s, poll_timeout_s)
            if status["status"] == "COMPLETE":
                file_path = status.get("file_url") or f"/api/v1/reports/{job['job_id']}/file"
                return self._get(file_path).text
            log.warning(
                "Report %s failed (submission %d/%d): %s",
                request,
                submission,
                max_submissions,
                status.get("error"),
            )
        raise RuntimeError(f"Report {request} failed {max_submissions} times")

    def _wait_for_job(self, job_id: str, interval_s: float, timeout_s: float) -> dict:
        waited = 0.0
        while True:
            status = self._get(f"/api/v1/reports/{job_id}").json()
            if status["status"] in ("COMPLETE", "FAILED"):
                return status
            if waited >= timeout_s:
                raise TimeoutError(f"Report job {job_id} still {status['status']} after {timeout_s}s")
            self.sleep(interval_s)
            waited += interval_s
