from __future__ import annotations

import json

from src.source_spike.adapters.stackexchange_http import HttpResponse, HttpStackExchangeTransport, StackExchangeTransportFailure, StackExchangeTransportSuccess


def wrapper(*, backoff=None, remaining=9000):
    value = {"items": [{"question_id": 1}], "has_more": False, "quota_max": 10000, "quota_remaining": remaining}
    if backoff is not None: value["backoff"] = backoff
    return json.dumps(value).encode()


def kwargs():
    return {"site":"stackoverflow","page":1,"page_size":30,"filter_id":"!frozen","sort":"creation","order":"desc","published_after":"2026-05-15T00:00:00Z","published_before":"2026-08-13T00:00:00Z","max_http_attempts":3,"request_timeout_seconds":10,"max_total_elapsed_seconds":30,"max_backoff_wait_seconds":10,"max_retries":2,"base_backoff_seconds":1,"max_backoff_seconds":8}


def test_transport_builds_frozen_questions_query_and_parses_wrapper() -> None:
    seen = []
    def execute(request, timeout):
        seen.append(request.full_url)
        return HttpResponse(200, {}, wrapper())
    result = HttpStackExchangeTransport(execute=execute).fetch_questions(**kwargs())
    assert isinstance(result, StackExchangeTransportSuccess)
    assert "site=stackoverflow" in seen[0] and "sort=creation" in seen[0]
    assert "fromdate=" in seen[0] and "todate=" in seen[0] and "filter=%21frozen" in seen[0]
    assert result.page.quota_remaining == 9000


def test_backoff_is_shared_across_sites_and_is_not_a_retry() -> None:
    now = [0.0]; sleeps = []; bodies = [wrapper(backoff=5), wrapper()]
    def execute(request, timeout): return HttpResponse(200, {}, bodies.pop(0))
    def sleep(value): sleeps.append(value); now[0] += value
    transport = HttpStackExchangeTransport(execute=execute, sleep=sleep, monotonic=lambda: now[0])
    first = transport.fetch_questions(**kwargs())
    second_args = kwargs(); second_args["site"] = "superuser"
    second = transport.fetch_questions(**second_args)
    assert isinstance(first, StackExchangeTransportSuccess) and isinstance(second, StackExchangeTransportSuccess)
    assert sleeps == [5]
    assert first.retry_count == 0 and second.retry_count == 0


def test_backoff_beyond_budget_returns_distinct_failure() -> None:
    transport = HttpStackExchangeTransport(execute=lambda request, timeout: HttpResponse(200, {}, wrapper(backoff=20)))
    first = transport.fetch_questions(**kwargs())
    assert isinstance(first, StackExchangeTransportSuccess)
    second = transport.fetch_questions(**kwargs())
    assert isinstance(second, StackExchangeTransportFailure)
    assert second.error_code == "backoff_budget_exhausted"


def test_http_429_is_bounded_retry_with_rate_limit_event() -> None:
    responses = [
        HttpResponse(429, {}, b'{"error_name":"throttle_violation"}'),
        HttpResponse(200, {}, wrapper()),
    ]
    sleeps = []
    transport = HttpStackExchangeTransport(
        execute=lambda request, timeout: responses.pop(0),
        sleep=sleeps.append,
    )

    result = transport.fetch_questions(**kwargs())

    assert isinstance(result, StackExchangeTransportSuccess)
    assert result.http_attempt_count == 2
    assert result.retry_count == 1
    assert sleeps == [1]
    assert result.events == (
        {
            "sequence": 1,
            "category": "rate_limit",
            "attempt": 1,
            "status_code": 429,
            "retryable": True,
            "rate_limit": {
                "limit": None,
                "remaining": None,
                "reset_at": None,
                "resource": None,
                "retry_after_seconds": None,
            },
        },
    )


def test_http_429_uses_retry_after_as_actual_delay() -> None:
    responses = [
        HttpResponse(429, {"Retry-After": "4"}, b"{}"),
        HttpResponse(200, {}, wrapper()),
    ]
    sleeps = []
    transport = HttpStackExchangeTransport(
        execute=lambda request, timeout: responses.pop(0),
        sleep=sleeps.append,
    )
    arguments = kwargs()
    arguments["max_backoff_wait_seconds"] = 5

    result = transport.fetch_questions(**arguments)

    assert isinstance(result, StackExchangeTransportSuccess)
    assert sleeps == [4]
    assert result.events[0]["rate_limit"]["retry_after_seconds"] == 4


def test_http_429_retry_after_beyond_budget_stops_without_sleep() -> None:
    sleeps = []
    transport = HttpStackExchangeTransport(
        execute=lambda request, timeout: HttpResponse(429, {"Retry-After": "30"}, b"{}"),
        sleep=sleeps.append,
    )

    result = transport.fetch_questions(**kwargs())

    assert isinstance(result, StackExchangeTransportFailure)
    assert result.error_code == "backoff_budget_exhausted"
    assert result.http_attempt_count == 1
    assert sleeps == []


def test_invalid_retry_after_is_not_persisted_or_used() -> None:
    responses = [
        HttpResponse(429, {"Retry-After": "-2"}, b"{}"),
        HttpResponse(200, {}, wrapper()),
    ]
    sleeps = []
    transport = HttpStackExchangeTransport(
        execute=lambda request, timeout: responses.pop(0),
        sleep=sleeps.append,
    )

    result = transport.fetch_questions(**kwargs())

    assert isinstance(result, StackExchangeTransportSuccess)
    assert sleeps == [1]
    assert result.events[0]["rate_limit"]["retry_after_seconds"] is None
