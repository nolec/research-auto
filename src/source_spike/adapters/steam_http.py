from __future__ import annotations

import gzip
import json
import socket
import ssl
import time
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

try:
    import certifi
except ImportError:  # pragma: no cover
    certifi = None  # type: ignore[assignment]

from src.source_spike.adapters.steam import SteamReviewPage


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    headers: Mapping[str, str]
    body: bytes


@dataclass(frozen=True)
class SteamTransportSuccess:
    page: SteamReviewPage
    http_attempt_count: int
    retry_count: int
    response_bytes: int
    events: Sequence[Mapping[str, object]] = ()


@dataclass(frozen=True)
class SteamTransportFailure:
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


def _header_integer(headers: Mapping[str, str], name: str) -> int | None:
    value = next((v for k, v in headers.items() if k.casefold() == name.casefold()), None)
    try:
        parsed = int(value) if value is not None else None
        return parsed if parsed is None or parsed >= 0 else None
    except ValueError:
        return None


class HttpSteamTransport:
    def __init__(self, *, execute: Callable[[Request, float], HttpResponse] = _default_execute,
                 sleep: Callable[[float], None] = time.sleep,
                 monotonic: Callable[[], float] = time.monotonic) -> None:
        self._execute, self._sleep, self._monotonic = execute, sleep, monotonic
        self._next_request_at = 0.0

    def fetch_reviews(self, appid: int, *, cursor: str, num_per_page: int,
                      filter: str, language: str, review_type: str, purchase_type: str,
                      filter_offtopic_activity: int, request_timeout_seconds: float,
                      max_http_attempts: int, max_total_elapsed_seconds: float,
                      max_retries: int, base_backoff_seconds: float,
                      max_backoff_seconds: float, min_request_interval_seconds: float
                      ) -> SteamTransportSuccess | SteamTransportFailure:
        started = self._monotonic()
        interval_wait = max(0.0, self._next_request_at - started)
        if interval_wait >= max_total_elapsed_seconds:
            return SteamTransportFailure("smoke_deadline_exhausted", 0, 0, 0)
        if interval_wait:
            self._sleep(interval_wait)
        query = urlencode({"json":1,"filter":filter,"language":language,"review_type":review_type,
            "purchase_type":purchase_type,"filter_offtopic_activity":filter_offtopic_activity,
            "num_per_page":num_per_page,"cursor":cursor})
        request = Request(f"https://store.steampowered.com/appreviews/{appid}?{query}",
            headers={"Accept":"application/json","Accept-Encoding":"gzip","User-Agent":"research-auto/0.1.0"})
        response_bytes = 0; events: list[Mapping[str, object]] = []
        limit = min(max_http_attempts, max_retries + 1)
        for attempt in range(1, limit + 1):
            remaining = max_total_elapsed_seconds - (self._monotonic() - started)
            if remaining <= 0:
                return SteamTransportFailure("smoke_deadline_exhausted", attempt-1, max(0,attempt-2), response_bytes, tuple(events))
            self._next_request_at = self._monotonic() + min_request_interval_seconds
            try:
                response = self._execute(request, min(request_timeout_seconds, remaining))
            except (TimeoutError, socket.timeout, ConnectionResetError, URLError):
                response = None
            retry_after = None
            if response is not None:
                response_bytes += len(response.body)
                if response.status_code == 200:
                    body = response.body
                    encoding = next((v for k,v in response.headers.items() if k.casefold()=="content-encoding"), "")
                    if encoding.casefold() == "gzip":
                        try: body = gzip.decompress(body)
                        except OSError: return SteamTransportFailure("invalid_gzip_response", attempt, attempt-1, response_bytes, tuple(events))
                    try: payload = json.loads(body)
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        return SteamTransportFailure("invalid_json_response", attempt, attempt-1, response_bytes, tuple(events))
                    if (not isinstance(payload, Mapping) or payload.get("success") != 1
                            or not isinstance(payload.get("reviews"), list)):
                        return SteamTransportFailure("malformed_wrapper", attempt, attempt-1, response_bytes, tuple(events))
                    cursor_value = payload.get("cursor")
                    if cursor_value is not None and not isinstance(cursor_value, str):
                        return SteamTransportFailure("malformed_wrapper", attempt, attempt-1, response_bytes, tuple(events))
                    try: page = SteamReviewPage(payload["reviews"], response_bytes, cursor_value)
                    except ValueError: return SteamTransportFailure("malformed_wrapper", attempt, attempt-1, response_bytes, tuple(events))
                    return SteamTransportSuccess(page, attempt, attempt-1, response_bytes, tuple(events))
                if response.status_code == 429:
                    retry_after = _header_integer(response.headers, "Retry-After")
                    events.append({"sequence":len(events)+1,"category":"rate_limit","attempt":attempt,
                        "status_code":429,"retryable":True,"rate_limit":{"limit":None,"remaining":None,
                        "reset_at":None,"resource":"unknown","retry_after_seconds":retry_after}})
                if response.status_code not in {429, 502, 503, 504}:
                    return SteamTransportFailure(f"http_{response.status_code}", attempt, attempt-1, response_bytes, tuple(events))
            if attempt == limit:
                return SteamTransportFailure("transport_error", attempt, attempt-1, response_bytes, tuple(events))
            delay = float(retry_after) if retry_after is not None else min(base_backoff_seconds*2**(attempt-1), max_backoff_seconds)
            remaining = max_total_elapsed_seconds - (self._monotonic() - started)
            if delay >= remaining:
                return SteamTransportFailure("smoke_deadline_exhausted", attempt, attempt-1, response_bytes, tuple(events))
            self._sleep(delay)
        raise AssertionError("unreachable")
