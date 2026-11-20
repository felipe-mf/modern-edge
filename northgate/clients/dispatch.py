"""Dispatch API v2 client (read-only): sites, workers and shift postings.

Handles OAuth client credentials (short-lived token, refreshed on expiry or on 401
invalid_token), cursor pagination, rate limiting and transient proxy errors.
"""

import logging
import time
from collections.abc import Iterator
from typing import Any

import httpx

from northgate.clients.http import DEFAULT_TIMEOUT, raise_for_status, send_with_retry

log = logging.getLogger(__name__)

PAGE_LIMIT = 50  # API maximum
TOKEN_SAFETY_MARGIN_S = 30  # refresh a little before the server-side expiry


class DispatchClient:
    def __init__(self, base_url: str, client_id: str, client_secret: str, http: httpx.Client | None = None):
        self.base_url = base_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.http = http or httpx.Client(timeout=DEFAULT_TIMEOUT)
        self._token: str | None = None
        self._token_expires_at = 0.0

    # --- auth -------------------------------------------------------------------------------

    def _fetch_token(self) -> None:
        response = send_with_retry(
            lambda: self.http.post(
                f"{self.base_url}/oauth/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                },
            )
        )
        body = raise_for_status(response).json()
        self._token = body["access_token"]
        self._token_expires_at = time.monotonic() + float(body.get("expires_in", 300)) - TOKEN_SAFETY_MARGIN_S

    def _auth_header(self) -> dict[str, str]:
        if self._token is None or time.monotonic() >= self._token_expires_at:
            self._fetch_token()
        return {"Authorization": f"Bearer {self._token}"}

    # --- requests ---------------------------------------------------------------------------

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        response = send_with_retry(lambda: self.http.get(url, params=params, headers=self._auth_header()))
        if response.status_code == 401:
            # Token expired between our check and the server's; get a new one and try once more.
            log.info("Dispatch token rejected (%s); refreshing", response.text[:100])
            self._token = None
            response = send_with_retry(lambda: self.http.get(url, params=params, headers=self._auth_header()))
        return raise_for_status(response).json()

    def _paginate(self, path: str, params: dict[str, Any] | None = None) -> Iterator[dict]:
        params = dict(params or {}, limit=PAGE_LIMIT)
        while True:
            page = self._get(path, params)
            yield from page["data"]
            cursor = page.get("next_cursor")
            if not cursor:
                return
            params["cursor"] = cursor

    def sites(self) -> list[dict]:
        # Documented as a plain list endpoint; follow a cursor anyway in case it is paginated.
        return list(self._paginate("/v2/sites"))

    def workers(self) -> list[dict]:
        return list(self._paginate("/v2/workers"))

    def postings(self) -> list[dict]:
        return list(self._paginate("/v2/postings"))
