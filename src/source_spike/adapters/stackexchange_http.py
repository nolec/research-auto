from __future__ import annotations

import gzip
import json
import socket
import ssl
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

try:
    import certifi
except ImportError:  # pragma: no cover
    certifi = None  # type: ignore[assignment]

from src.source_spike.adapters.stackexchange import StackExchangePage


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    headers: Mapping[str, str]
    body: bytes


@dataclass(frozen=True)
class StackExchangeTransportSuccess:
    page: StackExchangePage
    http_attempt_count: int
    retry_count: int
    response_bytes: int
    events: Sequence[Mapping[str, object]] = ()


@dataclass(frozen=True)
class StackExchangeTransportFailure:
    error_code: str
    http_attempt_count: int
    retry_count: int
    response_bytes: int
    events: Sequence[Mapping[str, object]] = ()


def _default_execute(request: Request, timeout: float) -> HttpResponse:
    context = ssl.create_default_context(cafile=certifi.where() if certifi else None)
    try:
        with urlopen(request, timeout=timeout, context=context) as response:
            return HttpResponse(response.status, dict(response.headers.items()), response.read())
    except HTTPError as error:
        return HttpResponse(error.code, dict(error.headers.items()), error.read(65536))


def _epoch(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())


def _integer_header(headers: Mapping[str, str], name: str) -> int | None:
    target = name.casefold()
    value = next((value for key, value in headers.items() if key.casefold() == target), None)
    try:
        parsed = int(value) if value is not None else None
        return parsed if parsed is None or parsed >= 0 else None
    except ValueError:
        return None


class HttpStackExchangeTransport:
    def __init__(self, *, key: str | None = None, execute: Callable[[Request, float], HttpResponse] = _default_execute,
                 sleep: Callable[[float], None] = time.sleep, monotonic: Callable[[], float] = time.monotonic) -> None:
        self._key, self._execute, self._sleep, self._monotonic = key, execute, sleep, monotonic
        self._next_questions_at = 0.0
        self.quota_remaining: int | None = None

    def fetch_questions(self, *, site: str, page: int, page_size: int, filter_id: str,
                        sort: str, order: str, published_after: str, published_before: str,
                        max_http_attempts: int, request_timeout_seconds: float,
                        max_total_elapsed_seconds: float, max_backoff_wait_seconds: float,
                        max_retries: int, base_backoff_seconds: float,
                        max_backoff_seconds: float) -> StackExchangeTransportSuccess | StackExchangeTransportFailure:
        started = self._monotonic()
        wait = max(0.0, self._next_questions_at - started)
        if wait > max_backoff_wait_seconds or wait >= max_total_elapsed_seconds:
            return StackExchangeTransportFailure("backoff_budget_exhausted", 0, 0, 0)
        if wait:
            self._sleep(wait)
        query = {"site": site, "page": page, "pagesize": page_size, "filter": filter_id,
                 "sort": sort, "order": order, "fromdate": _epoch(published_after), "todate": _epoch(published_before)}
        if self._key:
            query["key"] = self._key
        request = Request(f"https://api.stackexchange.com/2.3/questions?{urlencode(query)}",
                          headers={"Accept":"application/json", "Accept-Encoding":"gzip", "User-Agent":"research-auto/0.1.0"})
        response_bytes = 0
        events: list[Mapping[str, object]] = []
        limit = min(max_http_attempts, max_retries + 1)
        for attempt in range(1, limit + 1):
            remaining = max_total_elapsed_seconds - (self._monotonic() - started)
            if remaining <= 0:
                return StackExchangeTransportFailure("smoke_deadline_exhausted", attempt - 1, max(0, attempt - 2), response_bytes, tuple(events))
            try:
                response = self._execute(request, min(request_timeout_seconds, remaining))
            except (TimeoutError, socket.timeout, ConnectionResetError, URLError):
                response = None
            if response is not None:
                response_bytes += len(response.body)
                if response.status_code == 200:
                    body = response.body
                    encoding = next((v for k, v in response.headers.items() if k.casefold() == "content-encoding"), "")
                    if encoding.casefold() == "gzip":
                        try: body = gzip.decompress(body)
                        except OSError: return StackExchangeTransportFailure("invalid_gzip_response", attempt, attempt - 1, response_bytes, tuple(events))
                    try: payload = json.loads(body)
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        return StackExchangeTransportFailure("invalid_json_response", attempt, attempt - 1, response_bytes, tuple(events))
                    required = ("items", "has_more", "quota_max", "quota_remaining")
                    if not isinstance(payload, Mapping) or any(key not in payload for key in required) or not isinstance(payload["items"], list):
                        return StackExchangeTransportFailure("malformed_wrapper", attempt, attempt - 1, response_bytes, tuple(events))
                    backoff = payload.get("backoff")
                    if backoff is not None and (isinstance(backoff, bool) or not isinstance(backoff, int) or backoff < 0):
                        return StackExchangeTransportFailure("malformed_wrapper", attempt, attempt - 1, response_bytes, tuple(events))
                    if isinstance(backoff, int): self._next_questions_at = max(self._next_questions_at, self._monotonic() + backoff)
                    try:
                        page_value = StackExchangePage(payload["items"], response_bytes, payload["has_more"], backoff, payload["quota_max"], payload["quota_remaining"])
                    except ValueError:
                        return StackExchangeTransportFailure("malformed_wrapper", attempt, attempt - 1, response_bytes, tuple(events))
                    self.quota_remaining = page_value.quota_remaining
                    return StackExchangeTransportSuccess(page_value, attempt, attempt - 1, response_bytes, tuple(events))
                retry_after = None
                if response.status_code == 429:
                    retry_after = _integer_header(response.headers, "Retry-After")
                    events.append(
                        {
                            "sequence": len(events) + 1,
                            "category": "rate_limit",
                            "attempt": attempt,
                            "status_code": 429,
                            "retryable": True,
                            "rate_limit": {
                                "limit": None,
                                "remaining": None,
                                "reset_at": None,
                                "resource": None,
                                "retry_after_seconds": retry_after,
                            },
                        }
                    )
                retryable = response.status_code in {429, 502, 503, 504}
                if not retryable:
                    return StackExchangeTransportFailure(f"http_{response.status_code}", attempt, attempt - 1, response_bytes, tuple(events))
            if attempt == limit:
                return StackExchangeTransportFailure("transport_error", attempt, attempt - 1, response_bytes, tuple(events))
            delay = min(base_backoff_seconds * 2 ** (attempt - 1), max_backoff_seconds)
            if retry_after is not None:
                if retry_after > max_backoff_wait_seconds:
                    return StackExchangeTransportFailure("backoff_budget_exhausted", attempt, attempt - 1, response_bytes, tuple(events))
                delay = float(retry_after)
            remaining = max_total_elapsed_seconds - (self._monotonic() - started)
            if delay >= remaining:
                return StackExchangeTransportFailure("smoke_deadline_exhausted", attempt, attempt - 1, response_bytes, tuple(events))
            self._sleep(delay)
        raise AssertionError("unreachable")
