import httpx
import pytest
import respx

from northgate.clients.dispatch import DispatchClient
from northgate.clients.finance import FinanceClient, ReportNotAvailable
from northgate.clients.http import RetriesExhausted, retry_delay, send_with_retry


def no_sleep(_seconds: float) -> None:
    """Stand-in for time.sleep so retry tests run instantly."""


def _response(status: int, headers: dict | None = None) -> httpx.Response:
    return httpx.Response(status, headers=headers, request=httpx.Request("GET", "http://x/test"))


def test_retry_delay_honors_retry_after():
    assert retry_delay(0, _response(429, {"Retry-After": "3"})) == 3.0


def test_retry_delay_backs_off_without_header():
    assert 0.5 <= retry_delay(0, None) < 0.8
    assert 4.0 <= retry_delay(3, None) < 4.3
    assert retry_delay(20, None) < 20.3  # capped


def test_send_with_retry_retries_retryable_statuses_then_returns():
    responses = iter([_response(503), _response(429), _response(502), _response(200)])
    result = send_with_retry(lambda: next(responses), sleep=no_sleep)
    assert result.status_code == 200


def test_send_with_retry_returns_client_errors_immediately():
    calls = []

    def send():
        calls.append(1)
        return _response(422)

    assert send_with_retry(send, sleep=no_sleep).status_code == 422
    assert len(calls) == 1


def test_send_with_retry_gives_up():
    with pytest.raises(RetriesExhausted):
        send_with_retry(lambda: _response(503), max_attempts=3, sleep=no_sleep)


def test_send_with_retry_retries_transport_errors():
    attempts = iter([httpx.ConnectError("refused"), _response(200)])

    def send():
        item = next(attempts)
        if isinstance(item, Exception):
            raise item
        return item

    assert send_with_retry(send, sleep=no_sleep).status_code == 200


@respx.mock
def test_dispatch_refreshes_token_on_401_and_follows_cursor():
    base = "http://dispatch"
    token_route = respx.post(f"{base}/oauth/token").mock(
        side_effect=[
            httpx.Response(200, json={"access_token": "t1", "expires_in": 300}),
            httpx.Response(200, json={"access_token": "t2", "expires_in": 300}),
        ]
    )
    respx.get(f"{base}/v2/workers", params={"cursor": "c2"}).mock(
        return_value=httpx.Response(200, json={"data": [{"worker_id": "W-2"}], "next_cursor": None})
    )
    respx.get(f"{base}/v2/workers").mock(
        side_effect=[
            httpx.Response(401, json={"error": "invalid_token"}),
            httpx.Response(200, json={"data": [{"worker_id": "W-1"}], "next_cursor": "c2"}),
        ]
    )

    workers = DispatchClient(base, "id", "secret").workers()

    assert [w["worker_id"] for w in workers] == ["W-1", "W-2"]
    assert token_route.call_count == 2


@respx.mock
def test_finance_resubmits_failed_report_job():
    base = "http://finance"
    respx.post(f"{base}/api/v1/reports").mock(
        side_effect=[
            httpx.Response(202, json={"job_id": "J1", "status": "QUEUED"}),
            httpx.Response(202, json={"job_id": "J2", "status": "QUEUED"}),
        ]
    )
    respx.get(f"{base}/api/v1/reports/J1").mock(
        return_value=httpx.Response(200, json={"job_id": "J1", "status": "FAILED", "error": "boom"})
    )
    respx.get(f"{base}/api/v1/reports/J2").mock(
        side_effect=[
            httpx.Response(200, json={"job_id": "J2", "status": "RUNNING"}),
            httpx.Response(
                200, json={"job_id": "J2", "status": "COMPLETE", "file_url": "/api/v1/reports/J2/file"}
            ),
        ]
    )
    respx.get(f"{base}/api/v1/reports/J2/file").mock(return_value=httpx.Response(200, text="REPORT"))

    client = FinanceClient(base, "u", "p", sleep=no_sleep)
    assert client.run_report("INV_REG", "AAA", "2026-10") == "REPORT"


@respx.mock
def test_finance_report_without_data_raises():
    base = "http://finance"
    respx.post(f"{base}/api/v1/reports").mock(
        return_value=httpx.Response(404, json={"faultcode": "RPT-020", "faultstring": "No data"})
    )
    with pytest.raises(ReportNotAvailable):
        FinanceClient(base, "u", "p", sleep=no_sleep).run_report("INV_REG", "AAA", "2026-09")
