from __future__ import annotations

import json
import math
import ssl
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4

import certifi
from jsonschema import Draft202012Validator

from src.contracts.validation import FORMAT_CHECKER


_SCHEMA = json.loads(
    (Path(__file__).resolve().parents[2] / "schemas" / "wikimedia-phabricator-preflight-receipt.schema.json")
    .read_text(encoding="utf-8")
)
_VALIDATOR = Draft202012Validator(_SCHEMA, format_checker=FORMAT_CHECKER)
_ROOT_KEYS = {"result", "error_code", "error_info"}
_RESULT_KEYS = {"data", "maps", "query", "cursor"}
_PRIVACY_ZERO = {
    "persisted_task_text": 0,
    "persisted_usernames": 0,
    "persisted_author_identifiers": 0,
    "persisted_queries": 0,
    "persisted_response_bodies": 0,
}


@dataclass(frozen=True)
class PreflightLimits:
    sample_size: int = 5
    timeout_seconds: int = 10
    max_response_bytes: int = 1_048_576

    def __post_init__(self) -> None:
        if self.sample_size != 5:
            raise ValueError("preflight sample size is frozen at five")
        if not 1 <= self.timeout_seconds <= 30:
            raise ValueError("timeout must be between one and thirty seconds")
        if not 1 <= self.max_response_bytes <= 1_048_576:
            raise ValueError("response-byte limit is outside the frozen boundary")


@dataclass(frozen=True)
class StaticResponse:
    status_code: int
    body: bytes


def _zero_completeness() -> dict[str, float]:
    return {
        "task_id": 0.0,
        "created_timestamp": 0.0,
        "author_phid": 0.0,
        "public_visibility": 0.0,
    }


def _base_receipt(
    *, limits: PreflightLimits, now: datetime, request_count: int, response_bytes: int
) -> dict[str, object]:
    timestamp = now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "schema_version": "1.0.0",
        "source": "wikimedia_phabricator",
        "run_id": str(uuid4()),
        "started_at": timestamp,
        "finished_at": timestamp,
        "status": "FAIL",
        "termination_reason": "no_request_executed",
        "observed_task_count": 0,
        "completeness": _zero_completeness(),
        "shape": {
            "wrapper_exact": False,
            "cursor_present": False,
            "cursor_after_key_present": False,
        },
        "request_count": request_count,
        "response_bytes": response_bytes,
        "canonical_checks": 0,
        "canonical_successes": 0,
        "limits": asdict(limits),
        "privacy": dict(_PRIVACY_ZERO),
    }


def execute_preflight(
    *,
    api_response: StaticResponse | None,
    canonical_responses: Sequence[StaticResponse],
    limits: PreflightLimits,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> dict[str, object]:
    now = clock()
    request_count = (1 if api_response is not None else 0) + len(canonical_responses)
    response_bytes = (len(api_response.body) if api_response is not None else 0) + sum(
        len(response.body) for response in canonical_responses
    )
    receipt = _base_receipt(
        limits=limits, now=now, request_count=request_count, response_bytes=response_bytes
    )
    if api_response is None:
        return receipt
    if api_response.status_code in {401, 403}:
        receipt["termination_reason"] = "authentication_required"
        return receipt
    if api_response.status_code != 200:
        receipt["termination_reason"] = "http_error"
        return receipt
    if response_bytes > limits.max_response_bytes:
        receipt["termination_reason"] = "response_byte_budget_exhausted"
        return receipt
    try:
        payload = json.loads(api_response.body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        receipt["termination_reason"] = "malformed_response"
        return receipt
    if not isinstance(payload, dict) or set(payload) != _ROOT_KEYS:
        receipt["termination_reason"] = "unexpected_wrapper"
        return receipt
    if payload.get("error_code") in {"ERR-INVALID-SESSION", "ERR-INVALID-AUTH"}:
        receipt["termination_reason"] = "authentication_required"
        return receipt
    result = payload.get("result")
    if (
        payload.get("error_code") is not None
        or not isinstance(result, dict)
        or set(result) != _RESULT_KEYS
    ):
        receipt["termination_reason"] = "unexpected_wrapper"
        return receipt
    data = result.get("data")
    if not isinstance(data, list) or not data:
        receipt["termination_reason"] = "empty_result"
        return receipt
    if len(data) > limits.sample_size:
        receipt["termination_reason"] = "sample_limit_exceeded"
        return receipt
    cursor = result.get("cursor")
    cursor_present = isinstance(cursor, dict)
    cursor_after_present = cursor_present and "after" in cursor
    receipt["shape"] = {
        "wrapper_exact": True,
        "cursor_present": cursor_present,
        "cursor_after_key_present": cursor_after_present,
    }
    if not cursor_after_present:
        receipt["termination_reason"] = "cursor_shape_missing"
        return receipt

    counts = dict.fromkeys(_zero_completeness(), 0)
    task_ids: list[int] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        fields = item.get("fields")
        if not isinstance(fields, dict):
            continue
        task_id = item.get("id")
        if isinstance(task_id, int) and task_id > 0:
            counts["task_id"] += 1
            task_ids.append(task_id)
        created = fields.get("dateCreated")
        if isinstance(created, int) and created > 0:
            counts["created_timestamp"] += 1
        author = fields.get("authorPHID")
        if isinstance(author, str) and author.startswith("PHID-USER-"):
            counts["author_phid"] += 1
        policy = fields.get("policy")
        if isinstance(policy, dict) and policy.get("view") == "public":
            counts["public_visibility"] += 1
    total = len(data)
    completeness = {name: count / total for name, count in counts.items()}
    receipt["observed_task_count"] = total
    receipt["completeness"] = completeness
    if any(value != 1.0 for value in completeness.values()):
        receipt["termination_reason"] = "required_field_incomplete"
        return receipt
    if len(canonical_responses) != len(task_ids):
        receipt["termination_reason"] = "canonical_anonymous_read_failed"
        return receipt
    canonical_successes = sum(response.status_code == 200 for response in canonical_responses)
    receipt["canonical_checks"] = len(canonical_responses)
    receipt["canonical_successes"] = canonical_successes
    if canonical_successes != len(task_ids):
        receipt["termination_reason"] = "canonical_anonymous_read_failed"
        return receipt
    receipt["status"] = "PASS"
    receipt["termination_reason"] = "shape_qualified"
    return receipt


def validate_preflight_receipt(value: Mapping[str, object]) -> list[str]:
    errors = [
        f"{'.'.join(map(str, error.absolute_path)) or '$'}: {error.message}"
        for error in sorted(
            _VALIDATOR.iter_errors(value),
            key=lambda error: tuple(map(str, error.absolute_path)),
        )
    ]
    completeness = value.get("completeness")
    if isinstance(completeness, Mapping):
        metrics = list(completeness.values())
        if any(not isinstance(metric, (int, float)) or not math.isfinite(metric) for metric in metrics):
            errors.append("completeness metrics must be finite")
    privacy = value.get("privacy")
    if isinstance(privacy, Mapping) and any(value != 0 for value in privacy.values()):
        errors.append("persisted sensitive fields must remain zero")
    status = value.get("status")
    if status == "PASS":
        if value.get("termination_reason") != "shape_qualified":
            errors.append("PASS requires shape_qualified termination")
        if int(value.get("request_count", 0)) < 2:
            errors.append("PASS requires executed API and canonical requests")
        if int(value.get("observed_task_count", 0)) < 1:
            errors.append("PASS requires observed tasks")
        if isinstance(completeness, Mapping) and any(metric != 1.0 for metric in completeness.values()):
            errors.append("PASS requires complete required fields")
        shape = value.get("shape")
        if not isinstance(shape, Mapping) or any(
            shape.get(name) is not True
            for name in ("wrapper_exact", "cursor_present", "cursor_after_key_present")
        ):
            errors.append("PASS requires exact wrapper and cursor shape")
        observed_task_count = int(value.get("observed_task_count", 0))
        canonical_checks = int(value.get("canonical_checks", 0))
        if canonical_checks != observed_task_count:
            errors.append("PASS requires one canonical check per observed task")
        if value.get("canonical_checks") != value.get("canonical_successes"):
            errors.append("PASS requires canonical anonymous reads")
        if int(value.get("request_count", 0)) != 1 + canonical_checks:
            errors.append("request count must equal API plus canonical checks")
        limits = value.get("limits")
        if isinstance(limits, Mapping) and int(value.get("response_bytes", 0)) > int(
            limits.get("max_response_bytes", 0)
        ):
            errors.append("PASS exceeds response-byte budget")
    return sorted(set(errors))


def fetch_static_response(
    request: Request, limits: PreflightLimits, *, max_read_bytes: int | None = None
) -> StaticResponse:
    context = ssl.create_default_context(cafile=certifi.where())
    read_limit = limits.max_response_bytes if max_read_bytes is None else max_read_bytes
    try:
        with urlopen(request, timeout=limits.timeout_seconds, context=context) as response:
            body = response.read(read_limit + 1)
            return StaticResponse(response.status, body)
    except HTTPError as error:
        return StaticResponse(error.code, b"")
    except URLError:
        return StaticResponse(599, b"")


def run_live_preflight(
    *, limits: PreflightLimits = PreflightLimits(), clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
) -> dict[str, object]:
    params = urlencode({"constraints": "{}", "order": "newest", "limit": limits.sample_size})
    api_request = Request(
        "https://phabricator.wikimedia.org/api/maniphest.search",
        data=params.encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "research-auto-source-spike/1.0"},
        method="POST",
    )
    api_response = fetch_static_response(api_request, limits)
    canonical_responses: list[StaticResponse] = []
    if api_response.status_code == 200 and len(api_response.body) <= limits.max_response_bytes:
        try:
            payload = json.loads(api_response.body)
            data = cast(Mapping[str, object], payload["result"])["data"]
            if isinstance(data, list) and len(data) <= limits.sample_size:
                for item in data:
                    task_id = cast(Mapping[str, object], item).get("id")
                    if isinstance(task_id, int) and task_id > 0:
                        consumed_bytes = len(api_response.body) + sum(
                            len(response.body) for response in canonical_responses
                        )
                        remaining_bytes = limits.max_response_bytes - consumed_bytes
                        if remaining_bytes <= 0:
                            break
                        canonical_responses.append(
                            fetch_static_response(
                                Request(
                                    f"https://phabricator.wikimedia.org/T{task_id}",
                                    headers={"User-Agent": "research-auto-source-spike/1.0"},
                                    method="GET",
                                ),
                                limits,
                                max_read_bytes=remaining_bytes,
                            )
                        )
                        if len(canonical_responses[-1].body) > remaining_bytes:
                            break
        except (KeyError, TypeError, json.JSONDecodeError):
            pass
    return execute_preflight(
        api_response=api_response,
        canonical_responses=canonical_responses,
        limits=limits,
        clock=clock,
    )
