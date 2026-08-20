from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.source_spike.adapters.ted_http import (
    HttpResponse,
    HttpTedTransport,
    TedTransportFailure,
    TedTransportSuccess,
)


ROOT = Path(__file__).resolve().parents[3]
FIXTURE = ROOT / "tests/fixtures/ted/search-page-1.json"
FIXTURE_PROVENANCE = ROOT / "tests/fixtures/ted/search-page-1.provenance.json"
MANIFEST = ROOT / "config/source-spike/ted-capacity.json"


def manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def fixture_bytes() -> bytes:
    return FIXTURE.read_bytes()


def fetch(transport: HttpTedTransport, **overrides: object):
    values = {
        "query": manifest()["strata"][0]["query"],
        "fields": manifest()["fields"],
        "page": 1,
        "page_size": 2,
        "scope": "ALL",
        "check_query_syntax": False,
        "pagination_mode": "PAGE_NUMBER",
        "max_http_attempts": 2,
        "request_timeout_seconds": 10,
        "deadline_seconds": 60,
        "max_response_bytes": 10_000,
        "max_retries": 1,
        "base_backoff_seconds": 0,
        "max_backoff_seconds": 0,
    }
    values.update(overrides)
    return transport.fetch_notices(**values)


def test_request_uses_official_host_and_executable_search_body() -> None:
    captured = {}

    def execute(request, timeout, max_bytes):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["body"] = json.loads(request.data)
        return HttpResponse(200, {}, fixture_bytes())

    result = fetch(HttpTedTransport(execute=execute))

    assert isinstance(result, TedTransportSuccess)
    assert captured["url"] == "https://api.ted.europa.eu/v3/notices/search"
    assert captured["timeout"] == 10
    assert captured["body"] == {
        "query": manifest()["strata"][0]["query"],
        "fields": manifest()["fields"],
        "page": 1,
        "limit": 2,
        "scope": "ALL",
        "checkQuerySyntax": False,
        "paginationMode": "PAGE_NUMBER",
    }
    assert "sort" not in captured["body"]


def test_official_wrapper_preserves_multilingual_notice_shape_in_memory() -> None:
    result = fetch(HttpTedTransport(execute=lambda request, timeout, max_bytes: HttpResponse(200, {}, fixture_bytes())))

    assert isinstance(result, TedTransportSuccess)
    assert len(result.page.notices) == 2
    assert result.page.notices[0]["notice-title"] == {"eng": ["Synthetic software tender"]}
    assert result.page.notices[1]["notice-title"] == {"fra": ["Appel d'offres synthétique"]}
    assert result.page.total_notice_count == 5
    assert result.page.has_more is True
    assert len(result.page.payload_signature) == 64


def test_synthetic_fixture_is_bound_to_the_official_openapi_shape() -> None:
    provenance = json.loads(FIXTURE_PROVENANCE.read_text(encoding="utf-8"))

    assert provenance["spec_url"] == "https://api.ted.europa.eu/api-v3.yaml"
    assert provenance["request_schema"] == "PublicExpertSearchRequestV1"
    assert provenance["response_schema"] == "ExpertSearchResponse"
    assert provenance["contains_real_notice_data"] is False


def test_retryable_failure_is_bounded_and_non_retryable_is_immediate() -> None:
    responses = iter((HttpResponse(503, {}, b"temporary"), HttpResponse(200, {}, fixture_bytes())))
    success = fetch(HttpTedTransport(execute=lambda request, timeout, max_bytes: next(responses)))
    failure = fetch(HttpTedTransport(execute=lambda request, timeout, max_bytes: HttpResponse(400, {}, b"bad query")))

    assert isinstance(success, TedTransportSuccess)
    assert success.http_attempt_count == 2
    assert success.retry_count == 1
    assert isinstance(failure, TedTransportFailure)
    assert failure.error_code == "http_400"
    assert failure.http_attempt_count == 1


def test_malformed_timeout_and_response_byte_budget_fail_closed() -> None:
    malformed = fetch(HttpTedTransport(execute=lambda request, timeout, max_bytes: HttpResponse(200, {}, b'{"notices": {}}')))
    timed_out = fetch(HttpTedTransport(execute=lambda request, timeout, max_bytes: HttpResponse(200, {}, b'{"notices": [], "totalNoticeCount": 0, "timedOut": true}')))
    oversized = fetch(
        HttpTedTransport(execute=lambda request, timeout, max_bytes: HttpResponse(200, {}, fixture_bytes())),
        max_response_bytes=10,
    )

    assert isinstance(malformed, TedTransportFailure) and malformed.error_code == "malformed_wrapper"
    assert isinstance(timed_out, TedTransportFailure) and timed_out.error_code == "search_timed_out"
    assert isinstance(oversized, TedTransportFailure) and oversized.error_code == "response_byte_budget_exhausted"


def test_non_finite_json_numbers_fail_closed() -> None:
    for value in (b"NaN", b"Infinity"):
        body = b'{"notices":[{"value":' + value + b'}],"totalNoticeCount":1,"timedOut":false}'

        result = fetch(
            HttpTedTransport(
                execute=lambda request, timeout, max_bytes, body=body: HttpResponse(200, {}, body)
            )
        )

        assert isinstance(result, TedTransportFailure)
        assert result.error_code == "invalid_json_response"


def test_transport_exception_is_aggregated_and_retry_after_respects_backoff_budget() -> None:
    attempts = 0

    def timeout_then_success(request, timeout, max_bytes):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TimeoutError
        return HttpResponse(200, {}, fixture_bytes())

    recovered = fetch(HttpTedTransport(execute=timeout_then_success))
    rate_limited = fetch(
        HttpTedTransport(
            execute=lambda request, timeout, max_bytes: HttpResponse(
                429, {"Retry-After": "5"}, b"rate limited"
            )
        ),
        max_backoff_seconds=4,
    )

    assert isinstance(recovered, TedTransportSuccess)
    assert recovered.events == (
        {
            "attempt": 1,
            "status_code": None,
            "category": "transport_error",
            "retryable": True,
            "retry_after_seconds": None,
        },
    )
    assert isinstance(rate_limited, TedTransportFailure)
    assert rate_limited.error_code == "backoff_budget_exhausted"


def test_exhausted_deadline_makes_no_http_attempt() -> None:
    called = False

    def execute(request, timeout, max_bytes):
        nonlocal called
        called = True
        return HttpResponse(200, {}, fixture_bytes())

    result = fetch(HttpTedTransport(execute=execute), deadline_seconds=0)

    assert isinstance(result, TedTransportFailure)
    assert result.error_code == "deadline_exhausted"
    assert result.http_attempt_count == 0
    assert called is False


def test_manifest_transport_contract_matches_official_openapi() -> None:
    value = manifest()["api"]

    assert value["base_url"] == "https://api.ted.europa.eu"
    assert value["endpoint"] == "/v3/notices/search"
    assert value["check_query_syntax"] is False


def test_syntax_validation_surface_forces_check_mode_and_minimal_fields() -> None:
    captured = {}

    def execute(request, timeout, max_bytes):
        captured["body"] = json.loads(request.data)
        return HttpResponse(200, {}, fixture_bytes())

    result = HttpTedTransport(execute=execute).validate_query_syntax(
        query="publication-date = 20260817 SORT BY publication-date DESC",
        max_http_attempts=2,
        request_timeout_seconds=10,
        deadline_seconds=30,
        max_response_bytes=2_097_152,
        max_retries=1,
        base_backoff_seconds=1,
        max_backoff_seconds=4,
    )

    assert isinstance(result, TedTransportSuccess)
    assert captured["body"]["checkQuerySyntax"] is True
    assert captured["body"]["fields"] == ["publication-number"]
    assert captured["body"]["page"] == 1
    assert captured["body"]["limit"] == 1
    assert captured["body"]["paginationMode"] == "PAGE_NUMBER"


def test_syntax_validation_accepts_nullable_total_without_weakening_data_fetch() -> None:
    nullable_wrapper = json.dumps(
        {"notices": [], "totalNoticeCount": None, "timedOut": False}
    ).encode("utf-8")
    transport = HttpTedTransport(
        execute=lambda request, timeout, max_bytes: HttpResponse(200, {}, nullable_wrapper)
    )

    syntax_result = transport.validate_query_syntax(
        query="publication-date = 20260817 SORT BY publication-date DESC",
        max_http_attempts=1,
        request_timeout_seconds=10,
        deadline_seconds=30,
        max_response_bytes=10_000,
        max_retries=0,
        base_backoff_seconds=1,
        max_backoff_seconds=4,
    )
    data_result = transport.fetch_notices(
        query="publication-date = 20260817 SORT BY publication-date DESC",
        fields=("publication-number",),
        page=1,
        page_size=1,
        scope="ALL",
        check_query_syntax=False,
        pagination_mode="PAGE_NUMBER",
        max_http_attempts=1,
        request_timeout_seconds=10,
        deadline_seconds=30,
        max_response_bytes=10_000,
        max_retries=0,
        base_backoff_seconds=1,
        max_backoff_seconds=4,
    )

    assert isinstance(syntax_result, TedTransportSuccess)
    assert isinstance(data_result, TedTransportFailure)
    assert data_result.error_code == "malformed_wrapper"


@pytest.mark.parametrize(
    "unexpected",
    (
        {"querySyntaxError": {"message": "invalid SORT BY"}},
        {"unexpected": "extension"},
    ),
)
def test_syntax_validation_rejects_unknown_success_wrapper_fields(
    unexpected: dict[str, object],
) -> None:
    payload = {
        "notices": [],
        "totalNoticeCount": 0,
        "timedOut": False,
        **unexpected,
    }
    result = HttpTedTransport(
        execute=lambda request, timeout, max_bytes: HttpResponse(
            200, {}, json.dumps(payload).encode("utf-8")
        )
    ).validate_query_syntax(
        query="broken SORT BY query",
        max_http_attempts=1,
        request_timeout_seconds=10,
        deadline_seconds=30,
        max_response_bytes=10_000,
        max_retries=0,
        base_backoff_seconds=1,
        max_backoff_seconds=4,
    )

    assert isinstance(result, TedTransportFailure)
    assert result.error_code == "unexpected_syntax_wrapper"
