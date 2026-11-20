"""Shared HTTP plumbing: one place that decides when and how long to wait before retrying.

Only *safe* requests (reads, or writes the server treats idempotently) should go through
`send_with_retry`. The payroll absence POST has no idempotency key, so the payroll writer handles
its retries itself (it checks payroll before trying again).
"""

import logging
import random
import time
from collections.abc import Callable

import httpx

log = logging.getLogger(__name__)

# 429 = rate limited, 5xx = the client systems' "processing window" / proxy errors.
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


class RetriesExhausted(Exception):
    """Raised when a request still fails after every allowed attempt."""


def retry_delay(attempt: int, response: httpx.Response | None) -> float:
    """Seconds to wait before the next attempt.

    Honors the server's Retry-After header when present; otherwise exponential backoff
    (0.5s, 1s, 2s, ... capped at 20s) with a little jitter so parallel clients don't sync up.
    """
    if response is not None:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return max(float(retry_after), 0.0)
            except ValueError:
                pass  # HTTP-date form; fall back to backoff
    return min(0.5 * 2**attempt, 20.0) + random.uniform(0, 0.25)


def send_with_retry(
    send: Callable[[], httpx.Response],
    *,
    max_attempts: int = 8,
    sleep: Callable[[float], None] = time.sleep,
) -> httpx.Response:
    """Call `send()` until it returns a non-retryable response.

    `send` is a zero-argument callable so callers can rebuild the request on each attempt
    (for example with a refreshed auth token). Network errors are retried too.
    Returns the final response (which may be a 4xx the caller must handle).
    """
    last_error: Exception | None = None
    for attempt in range(max_attempts):
        response: httpx.Response | None = None
        try:
            response = send()
        except httpx.TransportError as exc:  # connection refused, timeout, reset...
            last_error = exc
            log.warning("HTTP transport error (attempt %d/%d): %s", attempt + 1, max_attempts, exc)
        else:
            if response.status_code not in RETRYABLE_STATUS:
                return response
            last_error = None
            log.info(
                "HTTP %s from %s (attempt %d/%d), retrying",
                response.status_code, response.request.url, attempt + 1, max_attempts,
            )
        if attempt + 1 < max_attempts:
            sleep(retry_delay(attempt, response))
    if last_error is not None:
        raise RetriesExhausted(str(last_error)) from last_error
    raise RetriesExhausted(f"still HTTP {response.status_code} after {max_attempts} attempts")


def raise_for_status(response: httpx.Response) -> httpx.Response:
    """Like httpx's raise_for_status, but includes the body: these APIs explain errors in it."""
    if response.is_error:
        raise httpx.HTTPStatusError(
            f"HTTP {response.status_code} for {response.request.method} {response.request.url}: "
            f"{response.text[:500]}",
            request=response.request,
            response=response,
        )
    return response
