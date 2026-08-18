from __future__ import annotations

import hashlib
import json
import socket
import ssl
import time
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    import certifi
except ImportError:  # pragma: no cover
    certifi = None  # type: ignore[assignment]


_URL = "https://api.ted.europa.eu/v3/notices/search"
_RETRYABLE_STATUSES = frozenset({429, 502, 503, 504})


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    headers: Mapping[str, str]
    body: bytes


@dataclass(frozen=True)
class TedPage:
    notices: Sequence[Mapping[str, object]]
    total_notice_count: int
    page_number: int
    has_more: bool
    payload_signature: str
    iteration_next_token: str | None


@dataclass(frozen=True)
class TedTransportSuccess:
    page: TedPage
    http_attempt_count: int
    retry_count: int
    response_bytes: int
    events: Sequence[Mapping[str, object]] = ()


@dataclass(frozen=True)
class TedTransportFailure:
    error_code: str
    http_attempt_count: int
    retry_count: int
    response_bytes: int
    events: Sequence[Mapping[str, object]] = ()


def _default_execute(request: Request, timeout: float, max_bytes: int) -> HttpResponse:
    context = ssl.create_default_context(cafile=certifi.where() if certifi else None)
    try:
        with urlopen(request, timeout=timeout, context=context) as response:
            return HttpResponse(
                response.status,
                dict(response.headers.items()),
                response.read(max_bytes + 1),
            )
    except HTTPError as error:
        return HttpResponse(
            error.code,
            dict(error.headers.items()),
            error.read(max_bytes + 1),
        )


def _header_integer(headers: Mapping[str, str], name: str) -> int | None:
    raw = next(
        (value for key, value in headers.items() if key.casefold() == name.casefold()),
        None,
    )
    try:
        value = int(raw) if raw is not None else None
    except ValueError:
        return None
    return value if value is None or value >= 0 else None


def _signature(notices: Sequence[Mapping[str, object]]) -> str:
    payload = json.dumps(
        list(notices),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _reject_non_finite(value: str) -> object:
    raise ValueError(f"non-finite JSON number: {value}")


class HttpTedTransport:
    def __init__(
        self,
        *,
        execute: Callable[[Request, float, int], HttpResponse] = _default_execute,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._execute = execute
        self._sleep = sleep
        self._monotonic = monotonic

    def fetch_notices(
        self,
        *,
        query: str,
        fields: Sequence[str],
        page: int,
        page_size: int,
        scope: str,
        check_query_syntax: bool,
        pagination_mode: str,
        max_http_attempts: int,
        request_timeout_seconds: float,
        deadline_seconds: float,
        max_response_bytes: int,
        max_retries: int,
        base_backoff_seconds: float,
        max_backoff_seconds: float,
        reject_unknown_wrapper_fields: bool = False,
    ) -> TedTransportSuccess | TedTransportFailure:
        body = json.dumps(
            {
                "query": query,
                "fields": list(fields),
                "page": page,
                "limit": page_size,
                "scope": scope,
                "checkQuerySyntax": check_query_syntax,
                "paginationMode": pagination_mode,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        request = Request(
            _URL,
            data=body,
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "research-auto/0.1.0",
            },
        )
        started = self._monotonic()
        response_bytes = 0
        events: list[Mapping[str, object]] = []
        attempt_limit = min(max_http_attempts, max_retries + 1)
        for attempt in range(1, attempt_limit + 1):
            remaining = deadline_seconds - (self._monotonic() - started)
            if remaining <= 0:
                return TedTransportFailure(
                    "deadline_exhausted", attempt - 1, max(0, attempt - 2), response_bytes, tuple(events)
                )
            try:
                response = self._execute(
                    request,
                    min(request_timeout_seconds, remaining),
                    max_response_bytes - response_bytes,
                )
            except (TimeoutError, socket.timeout, ConnectionResetError, URLError):
                response = None
                events.append(
                    {
                        "attempt": attempt,
                        "status_code": None,
                        "category": "transport_error",
                        "retryable": True,
                        "retry_after_seconds": None,
                    }
                )

            retry_after: int | None = None
            if response is not None:
                response_bytes += len(response.body)
                if response_bytes > max_response_bytes:
                    return TedTransportFailure(
                        "response_byte_budget_exhausted",
                        attempt,
                        attempt - 1,
                        response_bytes,
                        tuple(events),
                    )
                if response.status_code == 200:
                    return self._parse_success(
                        response.body,
                        page=page,
                        page_size=page_size,
                        attempt=attempt,
                        response_bytes=response_bytes,
                        events=events,
                        reject_unknown_wrapper_fields=reject_unknown_wrapper_fields,
                    )
                retryable = response.status_code in _RETRYABLE_STATUSES
                retry_after = _header_integer(response.headers, "Retry-After")
                events.append(
                    {
                        "attempt": attempt,
                        "status_code": response.status_code,
                        "category": "rate_limit" if response.status_code == 429 else "http_error",
                        "retryable": retryable,
                        "retry_after_seconds": retry_after,
                    }
                )
                if not retryable:
                    return TedTransportFailure(
                        f"http_{response.status_code}",
                        attempt,
                        attempt - 1,
                        response_bytes,
                        tuple(events),
                    )
            if attempt == attempt_limit:
                return TedTransportFailure(
                    "transport_error", attempt, attempt - 1, response_bytes, tuple(events)
                )
            delay = min(base_backoff_seconds * 2 ** (attempt - 1), max_backoff_seconds)
            if retry_after is not None:
                if retry_after > max_backoff_seconds:
                    return TedTransportFailure(
                        "backoff_budget_exhausted",
                        attempt,
                        attempt - 1,
                        response_bytes,
                        tuple(events),
                    )
                delay = float(retry_after)
            remaining = deadline_seconds - (self._monotonic() - started)
            if delay >= remaining:
                return TedTransportFailure(
                    "deadline_exhausted", attempt, attempt - 1, response_bytes, tuple(events)
                )
            self._sleep(delay)
        raise AssertionError("unreachable")

    def validate_query_syntax(
        self,
        *,
        query: str,
        max_http_attempts: int,
        request_timeout_seconds: float,
        deadline_seconds: float,
        max_response_bytes: int,
        max_retries: int,
        base_backoff_seconds: float,
        max_backoff_seconds: float,
    ) -> TedTransportSuccess | TedTransportFailure:
        return self.fetch_notices(
            query=query,
            fields=("publication-number",),
            page=1,
            page_size=1,
            scope="ALL",
            check_query_syntax=True,
            pagination_mode="PAGE_NUMBER",
            max_http_attempts=max_http_attempts,
            request_timeout_seconds=request_timeout_seconds,
            deadline_seconds=deadline_seconds,
            max_response_bytes=max_response_bytes,
            max_retries=max_retries,
            base_backoff_seconds=base_backoff_seconds,
            max_backoff_seconds=max_backoff_seconds,
            reject_unknown_wrapper_fields=True,
        )

    @staticmethod
    def _parse_success(
        body: bytes,
        *,
        page: int,
        page_size: int,
        attempt: int,
        response_bytes: int,
        events: Sequence[Mapping[str, object]],
        reject_unknown_wrapper_fields: bool = False,
    ) -> TedTransportSuccess | TedTransportFailure:
        try:
            payload = json.loads(body, parse_constant=_reject_non_finite)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return TedTransportFailure(
                "invalid_json_response", attempt, attempt - 1, response_bytes, tuple(events)
            )
        if not isinstance(payload, Mapping):
            return TedTransportFailure(
                "malformed_wrapper", attempt, attempt - 1, response_bytes, tuple(events)
            )
        if reject_unknown_wrapper_fields and not set(payload).issubset(
            {"notices", "totalNoticeCount", "timedOut", "iterationNextToken"}
        ):
            return TedTransportFailure(
                "unexpected_syntax_wrapper",
                attempt,
                attempt - 1,
                response_bytes,
                tuple(events),
            )
        notices = payload.get("notices")
        total = payload.get("totalNoticeCount")
        timed_out = payload.get("timedOut")
        token = payload.get("iterationNextToken")
        if (
            not isinstance(notices, list)
            or any(not isinstance(notice, Mapping) for notice in notices)
            or isinstance(total, bool)
            or not isinstance(total, int)
            or total < 0
            or not isinstance(timed_out, bool)
            or (token is not None and not isinstance(token, str))
        ):
            return TedTransportFailure(
                "malformed_wrapper", attempt, attempt - 1, response_bytes, tuple(events)
            )
        if timed_out:
            return TedTransportFailure(
                "search_timed_out", attempt, attempt - 1, response_bytes, tuple(events)
            )
        copied_notices = json.loads(json.dumps(notices, ensure_ascii=False, allow_nan=False))
        page_value = TedPage(
            notices=tuple(copied_notices),
            total_notice_count=total,
            page_number=page,
            has_more=page * page_size < total,
            payload_signature=_signature(copied_notices),
            iteration_next_token=token,
        )
        return TedTransportSuccess(
            page_value,
            attempt,
            attempt - 1,
            response_bytes,
            tuple(events),
        )
