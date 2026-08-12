from __future__ import annotations

import json
from urllib.error import HTTPError

import pytest

from src.source_spike.adapters.github import GitHubPage
from src.source_spike.adapters.github_http import (
    GitHubTransportFailure,
    GitHubTransportSuccess,
    HttpGitHubTransport,
    HttpResponse,
)


def response(status: int, payload: object, headers: dict[str, str] | None = None) -> HttpResponse:
    body = json.dumps(payload).encode()
    return HttpResponse(status, headers or {}, body)


def test_http_transport_returns_success_with_bounded_metrics() -> None:
    calls: list[tuple[str, float]] = []

    def execute(request, timeout: float) -> HttpResponse:
        calls.append((request.full_url, timeout))
        return response(200, [{"id": 1}], {"Link": '<next>; rel="next"'})

    outcome = HttpGitHubTransport(execute=execute).fetch_issues(
        "microsoft/vscode", page=1, per_page=30, state="open", sort="created",
        direction="desc", max_http_attempts=3, request_timeout_seconds=5,
        max_total_elapsed_seconds=20, max_rate_limit_wait_seconds=2,
        max_retries=2, base_backoff_seconds=0, max_backoff_seconds=0,
    )

    assert isinstance(outcome, GitHubTransportSuccess)
    assert outcome.page == GitHubPage([{"id": 1}], len(b'[{"id": 1}]'), True)
    assert outcome.http_attempt_count == 1
    assert outcome.retry_count == 0
    assert calls[0][1] == 5
    assert "state=open" in calls[0][0]


def test_transport_retries_503_without_exposing_response_body() -> None:
    marker = "SECRET-RAW-BODY"
    outcomes = [response(503, {"message": marker}), response(200, [])]

    def execute(_request, _timeout: float) -> HttpResponse:
        return outcomes.pop(0)

    result = HttpGitHubTransport(execute=execute, sleep=lambda _: None).fetch_issues(
        "python/cpython", page=1, per_page=30, state="open", sort="created",
        direction="desc", max_http_attempts=3, request_timeout_seconds=5,
        max_total_elapsed_seconds=20, max_rate_limit_wait_seconds=2,
        max_retries=2, base_backoff_seconds=0, max_backoff_seconds=0,
    )

    assert isinstance(result, GitHubTransportSuccess)
    assert result.http_attempt_count == 2
    assert result.retry_count == 1
    assert marker not in repr(result)


def test_transport_backoff_is_not_capped_by_rate_limit_wait_policy() -> None:
    outcomes = [response(503, {"message": "unavailable"}), response(200, [])]
    sleeps: list[float] = []

    def execute(_request, _timeout: float) -> HttpResponse:
        return outcomes.pop(0)

    result = HttpGitHubTransport(
        execute=execute,
        sleep=sleeps.append,
        monotonic=lambda: 0.0,
    ).fetch_issues(
        "python/cpython", page=1, per_page=30, state="open", sort="created",
        direction="desc", max_http_attempts=2, request_timeout_seconds=5,
        max_total_elapsed_seconds=45, max_rate_limit_wait_seconds=2,
        max_retries=1, base_backoff_seconds=3, max_backoff_seconds=3,
    )

    assert isinstance(result, GitHubTransportSuccess)
    assert result.http_attempt_count == 2
    assert sleeps == [3]


def test_transport_returns_rate_limit_failure_without_waiting_too_long() -> None:
    def execute(_request, _timeout: float) -> HttpResponse:
        return response(403, {"message": "secondary rate limit"}, {"Retry-After": "60"})

    result = HttpGitHubTransport(execute=execute, sleep=lambda _: None).fetch_issues(
        "python/cpython", page=1, per_page=30, state="open", sort="created",
        direction="desc", max_http_attempts=3, request_timeout_seconds=5,
        max_total_elapsed_seconds=20, max_rate_limit_wait_seconds=2,
        max_retries=2, base_backoff_seconds=1, max_backoff_seconds=8,
    )

    assert isinstance(result, GitHubTransportFailure)
    assert result.error_code == "rate_limit_exhausted"
    assert result.rate_limit_event_count == 1
    assert result.events[0].rate_limit.retry_after_seconds == 60


def test_transport_does_not_retry_non_rate_limit_403() -> None:
    result = HttpGitHubTransport(
        execute=lambda _request, _timeout: response(403, {"message": "forbidden"})
    ).fetch_issues(
        "python/cpython", page=1, per_page=30, state="open", sort="created",
        direction="desc", max_http_attempts=3, request_timeout_seconds=5,
        max_total_elapsed_seconds=20, max_rate_limit_wait_seconds=2,
        max_retries=2, base_backoff_seconds=1, max_backoff_seconds=8,
    )

    assert isinstance(result, GitHubTransportFailure)
    assert result.error_code == "http_forbidden"
    assert result.http_attempt_count == 1


def test_each_attempt_timeout_is_capped_by_remaining_total_deadline() -> None:
    time_values = iter([0.0, 0.0, 4.25])
    observed_timeouts: list[float] = []

    def execute(_request, timeout: float) -> HttpResponse:
        observed_timeouts.append(timeout)
        return response(200, [])

    result = HttpGitHubTransport(
        execute=execute, monotonic=lambda: next(time_values)
    ).fetch_issues(
        "python/cpython", page=1, per_page=30, state="open", sort="created",
        direction="desc", max_http_attempts=1, request_timeout_seconds=10,
        max_total_elapsed_seconds=5, max_rate_limit_wait_seconds=2,
        max_retries=0, base_backoff_seconds=0, max_backoff_seconds=0,
    )

    assert isinstance(result, GitHubTransportSuccess)
    assert observed_timeouts == [pytest.approx(0.75)]


def test_unknown_rate_limit_resource_is_normalized_before_outcome() -> None:
    result = HttpGitHubTransport(
        execute=lambda _request, _timeout: response(
            403,
            {"message": "rate limited"},
            {
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Resource": "CANARY-NEW-RESOURCE",
            },
        )
    ).fetch_issues(
        "python/cpython", page=1, per_page=30, state="open", sort="created",
        direction="desc", max_http_attempts=1, request_timeout_seconds=5,
        max_total_elapsed_seconds=10, max_rate_limit_wait_seconds=2,
        max_retries=0, base_backoff_seconds=0, max_backoff_seconds=0,
    )

    assert isinstance(result, GitHubTransportFailure)
    assert result.error_code == "rate_limit_exhausted"
    assert result.events[0].rate_limit.resource == "unknown"
    assert "CANARY-NEW-RESOURCE" not in repr(result)
