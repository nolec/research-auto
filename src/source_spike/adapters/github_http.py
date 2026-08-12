from __future__ import annotations

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
except ImportError:  # pragma: no cover - platform CA fallback
    certifi = None  # type: ignore[assignment]

from src.source_spike.adapters.github import GitHubPage


_KNOWN_RATE_LIMIT_RESOURCES = frozenset(
    {"core", "search", "graphql", "integration_manifest", "source_import", "code_scanning", "actions_runner_registration", "scim"}
)


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    headers: Mapping[str, str]
    body: bytes


@dataclass(frozen=True)
class RateLimitSnapshot:
    limit: int | None = None
    remaining: int | None = None
    reset_at: int | None = None
    resource: str | None = None
    retry_after_seconds: int | None = None


@dataclass(frozen=True)
class TransportEvent:
    sequence: int
    category: str
    attempt: int
    status_code: int | None
    retryable: bool
    rate_limit: RateLimitSnapshot | None = None

    def to_dict(self) -> dict[str, object]:
        rate_limit = None
        if self.rate_limit is not None:
            rate_limit = {
                "limit": self.rate_limit.limit,
                "remaining": self.rate_limit.remaining,
                "reset_at": self.rate_limit.reset_at,
                "resource": self.rate_limit.resource,
                "retry_after_seconds": self.rate_limit.retry_after_seconds,
            }
        return {
            "sequence": self.sequence,
            "category": self.category,
            "attempt": self.attempt,
            "status_code": self.status_code,
            "retryable": self.retryable,
            "rate_limit": rate_limit,
        }


@dataclass(frozen=True)
class GitHubTransportSuccess:
    page: GitHubPage
    http_attempt_count: int
    retry_count: int
    rate_limit_event_count: int
    response_bytes: int
    events: Sequence[TransportEvent]


@dataclass(frozen=True)
class GitHubTransportFailure:
    error_code: str
    http_attempt_count: int
    retry_count: int
    rate_limit_event_count: int
    response_bytes: int
    events: Sequence[TransportEvent]


GitHubTransportOutcome = GitHubTransportSuccess | GitHubTransportFailure
HttpExecutor = Callable[[Request, float], HttpResponse]


def _header(headers: Mapping[str, str], name: str) -> str | None:
    target = name.casefold()
    for key, value in headers.items():
        if key.casefold() == target:
            return str(value)
    return None


def _integer_header(headers: Mapping[str, str], name: str) -> int | None:
    value = _header(headers, name)
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _rate_limit_snapshot(headers: Mapping[str, str]) -> RateLimitSnapshot:
    resource = _header(headers, "X-RateLimit-Resource")
    return RateLimitSnapshot(
        limit=_integer_header(headers, "X-RateLimit-Limit"),
        remaining=_integer_header(headers, "X-RateLimit-Remaining"),
        reset_at=_integer_header(headers, "X-RateLimit-Reset"),
        resource=(
            resource if resource is None or resource in _KNOWN_RATE_LIMIT_RESOURCES
            else "unknown"
        ),
        retry_after_seconds=_integer_header(headers, "Retry-After"),
    )


def _secondary_rate_limit(body: bytes) -> bool:
    try:
        payload = json.loads(body[:65536])
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not isinstance(payload, Mapping):
        return False
    message = payload.get("message")
    return isinstance(message, str) and "secondary rate limit" in message.casefold()


def _default_execute(request: Request, timeout: float) -> HttpResponse:
    context = ssl.create_default_context(cafile=certifi.where() if certifi else None)
    try:
        with urlopen(request, timeout=timeout, context=context) as response:
            body = response.read()
            return HttpResponse(response.status, dict(response.headers.items()), body)
    except HTTPError as error:
        body = error.read(65536)
        return HttpResponse(error.code, dict(error.headers.items()), body)


class HttpGitHubTransport:
    def __init__(
        self,
        *,
        token: str | None = None,
        execute: HttpExecutor = _default_execute,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._token = token
        self._execute = execute
        self._sleep = sleep
        self._monotonic = monotonic

    def fetch_issues(
        self,
        repository: str,
        *,
        page: int,
        per_page: int,
        state: str,
        sort: str,
        direction: str,
        max_http_attempts: int,
        request_timeout_seconds: float,
        max_total_elapsed_seconds: float,
        max_rate_limit_wait_seconds: float,
        max_retries: int,
        base_backoff_seconds: float,
        max_backoff_seconds: float,
    ) -> GitHubTransportOutcome:
        query = urlencode(
            {"page": page, "per_page": per_page, "state": state, "sort": sort, "direction": direction}
        )
        url = f"https://api.github.com/repos/{repository}/issues?{query}"
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "research-auto/0.2.0",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        request = Request(url, headers=headers, method="GET")
        started = self._monotonic()
        events: list[TransportEvent] = []
        response_bytes = 0

        for attempt in range(1, min(max_http_attempts, max_retries + 1) + 1):
            remaining = max_total_elapsed_seconds - (self._monotonic() - started)
            if remaining <= 0:
                return self._failure("smoke_deadline_exhausted", attempt - 1, response_bytes, events)
            try:
                remaining = max_total_elapsed_seconds - (self._monotonic() - started)
                if remaining <= 0:
                    return self._failure("smoke_deadline_exhausted", attempt - 1, response_bytes, events)
                response = self._execute(request, min(request_timeout_seconds, remaining))
            except (TimeoutError, socket.timeout):
                category, status, retryable = "timeout", None, True
                response = None
            except (ConnectionResetError, URLError):
                category, status, retryable = "connection_reset", None, True
                response = None
            else:
                response_bytes += len(response.body)
                status = response.status_code
                if status == 200:
                    try:
                        payload = json.loads(response.body)
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        return self._failure("invalid_json_response", attempt, response_bytes, events)
                    if not isinstance(payload, list) or any(not isinstance(item, Mapping) for item in payload):
                        return self._failure("invalid_json_response", attempt, response_bytes, events)
                    page_result = GitHubPage(
                        payload,
                        len(response.body),
                        'rel="next"' in (_header(response.headers, "Link") or ""),
                    )
                    return GitHubTransportSuccess(
                        page_result, attempt, attempt - 1,
                        sum(event.category == "rate_limit" for event in events),
                        response_bytes, tuple(events),
                    )
                snapshot = _rate_limit_snapshot(response.headers)
                is_rate_limit = (
                    status == 429
                    or (status == 403 and snapshot.retry_after_seconds is not None)
                    or (status == 403 and snapshot.remaining == 0)
                    or (status == 403 and _secondary_rate_limit(response.body))
                )
                if is_rate_limit:
                    category, retryable = "rate_limit", True
                else:
                    category = "http_error"
                    retryable = status in {502, 503, 504}

            snapshot = _rate_limit_snapshot(response.headers) if response is not None and category == "rate_limit" else None
            events.append(TransportEvent(len(events) + 1, category, attempt, status, retryable, snapshot))
            if category == "rate_limit" and snapshot is not None:
                wait = snapshot.retry_after_seconds
                if wait is not None and wait > max_rate_limit_wait_seconds:
                    return self._failure("rate_limit_exhausted", attempt, response_bytes, events)
                if wait is None and snapshot.remaining == 0:
                    return self._failure("rate_limit_exhausted", attempt, response_bytes, events)
            if not retryable:
                code = "http_forbidden" if status == 403 else f"http_{status}"
                return self._failure(code, attempt, response_bytes, events)
            if attempt >= min(max_http_attempts, max_retries + 1):
                code = "rate_limit_exhausted" if category == "rate_limit" else "transport_error"
                return self._failure(code, attempt, response_bytes, events)
            delay = min(base_backoff_seconds * (2 ** (attempt - 1)), max_backoff_seconds)
            if snapshot is not None and snapshot.retry_after_seconds is not None:
                delay = float(snapshot.retry_after_seconds)
            if category == "rate_limit" and delay > max_rate_limit_wait_seconds:
                return self._failure("rate_limit_exhausted", attempt, response_bytes, events)
            if self._monotonic() - started + delay > max_total_elapsed_seconds:
                return self._failure("smoke_deadline_exhausted", attempt, response_bytes, events)
            self._sleep(delay)
        return self._failure("transport_error", 0, response_bytes, events)

    @staticmethod
    def _failure(
        code: str, attempts: int, response_bytes: int, events: Sequence[TransportEvent]
    ) -> GitHubTransportFailure:
        return GitHubTransportFailure(
            code,
            attempts,
            max(attempts - 1, 0),
            sum(event.category == "rate_limit" for event in events),
            response_bytes,
            tuple(events),
        )
