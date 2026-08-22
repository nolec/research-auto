from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Protocol, Sequence, cast
from uuid import uuid4

from jsonschema import Draft202012Validator

from src.source_spike.adapters.ted import parse_ted_notice
from src.source_spike.adapters.ted_http import HttpTedTransport, TedTransportFailure, TedTransportSuccess
from src.source_spike.local_secret import load_secret
from src.source_spike.protocol import content_sha256
from src.source_spike.ted_capacity import TedIdentityState, TedRunBudget, TedSelectionState, measure_notice
from src.source_spike.ted_query_validation import build_query_set
from src.source_spike.ted_smoke_authorization import validate_ted_smoke_authorization
from src.source_spike.ted_smoke_manifest import validate_ted_smoke_manifest
from src.contracts.validation import FORMAT_CHECKER


_EXPECTED = {"software_and_information_systems": 3, "business_services": 3, "health_and_social_services": 2, "repair_and_maintenance_services": 2}
_ROOT = Path(__file__).resolve().parents[2]
_REPORT_SCHEMA = json.loads((_ROOT / "schemas/ted-smoke-qualification.schema.json").read_text())
_REPORT_VALIDATOR = Draft202012Validator(_REPORT_SCHEMA, format_checker=FORMAT_CHECKER)


class TedSmokeTransport(Protocol):
    def fetch_notices(self, **kwargs: object) -> TedTransportSuccess | TedTransportFailure: ...


def build_ted_smoke_report(*, run_id: str, counts: Mapping[str, int], target: int, accepted_refs: Sequence[Mapping[str, object]], transport: Mapping[str, object], provenance: Mapping[str, object]) -> dict[str, object]:
    safe_keys = {"source_item_id", "source_url", "published_at"}
    safe_refs = [{key: value for key, value in ref.items() if key in safe_keys} for ref in accepted_refs]
    references_valid = len(safe_refs) == len(accepted_refs) and all(
        set(ref) == safe_keys
        and isinstance(ref["source_item_id"], str) and bool(ref["source_item_id"])
        and isinstance(ref["source_url"], str) and ref["source_url"].startswith("https://ted.europa.eu/en/notice/-/detail/")
        and bool(ref["source_url"].removeprefix("https://ted.europa.eu/en/notice/-/detail/"))
        and isinstance(ref["published_at"], str) and _valid_timestamp(ref["published_at"])
        for ref in accepted_refs
    )
    provenance_valid = set(provenance) == {"manifest_hash", "capacity_manifest_hash", "authorization_hash"} and all(
        isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)
        for value in provenance.values()
    )
    passed = target == 10 and len(safe_refs) == target and dict(counts) == _EXPECTED and references_valid and provenance_valid and _transport_valid(transport)
    return {"schema_version": 1, "run_id": run_id, "status": "PASS" if passed else ("PARTIAL" if safe_refs and references_valid else "FAIL"), "termination_reason": "target_reached" if passed else "quota_unmet", "target": target, "accepted": len(safe_refs), "strata": dict(counts), "accepted_refs": safe_refs, "transport": dict(transport), "provenance": dict(provenance), "raw_text_persisted": 0, "raw_author_persisted": 0, "retained_items": 0}


def _valid_timestamp(value: str) -> bool:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is not None
    except ValueError:
        return False


def _transport_valid(value: Mapping[str, object]) -> bool:
    required = {"logical_requests", "http_attempts", "retries", "rate_limit_events", "transport_errors", "response_bytes", "max_logical_requests", "max_http_attempts", "deadline_seconds", "max_response_bytes"}
    if set(value) != required or any(isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in value.values()):
        return False
    return value["logical_requests"] <= value["max_logical_requests"] and value["http_attempts"] <= value["max_http_attempts"] and value["response_bytes"] <= value["max_response_bytes"] and value["logical_requests"] <= value["http_attempts"] and value["retries"] <= value["http_attempts"] and value["deadline_seconds"] > 0


def execute_ted_smoke(manifest: Mapping[str, object], capacity_manifest: Mapping[str, object], transport: TedSmokeTransport, *, author_secret: bytes, run_id: str, authorization_hash: str, monotonic=time.monotonic) -> dict[str, object]:
    query_set = build_query_set(capacity_manifest)
    request = cast(Mapping[str, object], manifest["request"])
    retry = cast(Mapping[str, object], manifest["retry"])
    api = cast(Mapping[str, object], capacity_manifest["api"])
    strata = cast(Sequence[Mapping[str, object]], manifest["strata"])
    counts = {str(value["name"]): 0 for value in strata}
    accepted_refs: list[Mapping[str, object]] = []
    budget = TedRunBudget(max_logical_requests=int(request["max_logical_requests"]), max_http_attempts=int(request["max_http_attempts"]), deadline_seconds=float(request["deadline_seconds"]), max_response_bytes=int(request["max_response_bytes"]), monotonic=monotonic)
    retries = rate_events = transport_errors = 0
    failure: str | None = None
    identity_state = TedIdentityState(max_items_per_buyer=int(manifest["max_items_per_buyer"]))
    window = cast(Mapping[str, object], manifest["window"])
    scope = cast(Mapping[str, object], capacity_manifest["notice_scope"])
    for candidate, stratum in zip(query_set.candidates, strata, strict=True):
        name, quota = str(stratum["name"]), int(stratum["quota"])
        selection = TedSelectionState(published_from=str(window["query_from_date"]), published_before=datetime.fromisoformat(str(window["published_before"]).replace("Z", "+00:00")).strftime("%Y%m%d"), allowed_notice_types=frozenset(cast(Sequence[str], scope["allowed_notice_types"])), form_type=str(scope["form_type"]), cpv_prefix=str(stratum["cpv_prefix"]), max_items_per_buyer=int(manifest["max_items_per_buyer"]), identity_state=identity_state)
        for page_number in range(1, int(request["max_pages_per_stratum"]) + 1):
            if counts[name] >= quota: break
            allowance = budget.begin_request(max_attempts_per_request=2)
            if not allowance.allowed: failure = allowance.termination_reason; break
            response = transport.fetch_notices(query=candidate.query, fields=cast(Sequence[str], manifest["fields"]), page=page_number, page_size=int(request["page_size"]), scope=str(api["scope"]), check_query_syntax=False, pagination_mode=str(api["pagination_mode"]), max_http_attempts=allowance.max_http_attempts, request_timeout_seconds=float(request["request_timeout_seconds"]), deadline_seconds=allowance.deadline_seconds, max_response_bytes=allowance.max_response_bytes, max_retries=min(int(retry["max_retries_per_logical_request"]), max(0, allowance.max_http_attempts - 1)), base_backoff_seconds=float(retry["base_backoff_seconds"]), max_backoff_seconds=float(retry["max_backoff_seconds"]), reject_unknown_wrapper_fields=True, allow_nullable_total=False)
            retries += response.retry_count
            rate_events += sum(event.get("category") == "rate_limit" for event in response.events)
            transport_errors += sum(event.get("category") == "transport_error" for event in response.events)
            failure = budget.record(http_attempts=response.http_attempt_count, response_bytes=response.response_bytes)
            if failure: break
            if isinstance(response, TedTransportFailure): failure = response.error_code; transport_errors += 1; break
            for payload in response.page.notices:
                if counts[name] >= quota: break
                measured = measure_notice(payload)
                parsed = parse_ted_notice(payload, stratum=name, author_secret=author_secret, run_id=run_id, adapter_version=str(manifest["adapter_version"]), collected_at=datetime.now(timezone.utc))
                if parsed.item is None: continue
                if not selection.select(measured).accepted: continue
                counts[name] += 1
                accepted_refs.append({"source_item_id": parsed.item["source_item_id"], "source_url": parsed.item["source_url"], "published_at": parsed.item["published_at"]})
            if not response.page.has_more and counts[name] < quota: failure = "source_exhausted"; break
        if failure: break
    transport_summary = {"logical_requests": budget.logical_requests, "http_attempts": budget.http_attempts, "retries": retries, "rate_limit_events": rate_events, "transport_errors": transport_errors, "response_bytes": budget.response_bytes, "max_logical_requests": int(request["max_logical_requests"]), "max_http_attempts": int(request["max_http_attempts"]), "deadline_seconds": int(request["deadline_seconds"]), "max_response_bytes": int(request["max_response_bytes"])}
    report = build_ted_smoke_report(run_id=run_id, counts=counts, target=int(manifest["target_valid_records"]), accepted_refs=accepted_refs, transport=transport_summary, provenance={"manifest_hash": content_sha256(manifest), "capacity_manifest_hash": content_sha256(capacity_manifest), "authorization_hash": authorization_hash})
    if failure and report["status"] != "PASS": report["termination_reason"] = failure
    return report


def _write_report(report: Mapping[str, object], path: Path) -> None:
    errors = validate_ted_smoke_report(report)
    if errors:
        raise ValueError("invalid TED smoke qualification report: " + "; ".join(errors))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, sort_keys=True, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def validate_ted_smoke_report(report: Mapping[str, object]) -> list[str]:
    return [
        f"{'.'.join(map(str, error.absolute_path)) or '$'}: {error.message}"
        for error in sorted(_REPORT_VALIDATOR.iter_errors(report), key=lambda value: tuple(map(str, value.absolute_path)))
    ]


def main(argv: list[str] | None = None, *, transport_factory=HttpTedTransport) -> int:
    parser = argparse.ArgumentParser(description="Run bounded TED real smoke")
    parser.add_argument("--manifest", type=Path, default=_ROOT / "config/source-spike/ted-smoke.json")
    parser.add_argument("--capacity-manifest", type=Path, default=_ROOT / "config/source-spike/ted-capacity.json")
    parser.add_argument("--authorization", type=Path, default=_ROOT / "config/source-spike/ted-smoke-authorization.json")
    parser.add_argument("--capacity-receipt", type=Path, default=_ROOT / "artifacts/source-spike/ted-capacity/latest.json")
    parser.add_argument("--output", type=Path, default=_ROOT / "artifacts/source-spike/ted-real-smoke/qualification.json")
    args = parser.parse_args(argv)
    try:
        secret = load_secret()
        manifest = json.loads(args.manifest.read_text())
        capacity = json.loads(args.capacity_manifest.read_text())
        authorization = json.loads(args.authorization.read_text())
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "FAIL", "error_code": "prerequisite_failed", "message": str(error)})); return 3
    errors = validate_ted_smoke_authorization(authorization, args.capacity_receipt) + validate_ted_smoke_manifest(manifest, authorization, capacity)
    if errors:
        print(json.dumps({"status": "FAIL", "error_code": "prerequisite_failed", "errors": errors})); return 3
    report = execute_ted_smoke(manifest, capacity, transport_factory(), author_secret=secret.secret, run_id=str(uuid4()), authorization_hash=content_sha256(authorization))
    _write_report(report, args.output)
    print(json.dumps({"status": report["status"], "accepted": report["accepted"], "termination_reason": report["termination_reason"], "privacy": "PASS" if report["raw_text_persisted"] == report["raw_author_persisted"] == 0 else "FAIL"}, sort_keys=True))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
