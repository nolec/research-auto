from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import Mapping

from src.source_spike.adapters.base import (
    CollectionResult,
    CollectionStatus,
    TerminationReason,
)
from src.source_spike.adapters.github import GitHubIssueAdapter
from src.source_spike.adapters.github_http import HttpGitHubTransport
from src.source_spike.collection import collect_source


ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "config/source-spike/github-smoke.json"
COMPLIANCE_PATH = ROOT / "config/source-spike/compliance/github.json"
DEFAULT_REPORT_PATH = ROOT / "artifacts/source-spike/github-real-smoke/qualification.json"
_SAFE_EVENT_CATEGORIES = frozenset(
    {"http_error", "timeout", "connection_reset", "rate_limit"}
)
_SAFE_RATE_LIMIT_RESOURCES = frozenset(
    {"core", "search", "graphql", "integration_manifest", "source_import", "code_scanning", "actions_runner_registration", "scim"}
)


def build_qualification_report(result: CollectionResult) -> dict[str, object]:
    rejection_counts = Counter(item.error_code for item in result.invalid_items)
    references = [
        {
            "source_item_id": item["source_item_id"],
            "source_url": item["source_url"],
            "published_at": item["published_at"],
            "text_fingerprint": item["text_fingerprint"],
        }
        for item in result.items
    ]
    return {
        "run_id": result.run_id,
        "started_at": result.to_dict()["started_at"],
        "finished_at": result.to_dict()["finished_at"],
        "status": result.status.value,
        "termination_reason": result.termination_reason.value,
        "manifest_version": result.manifest_version,
        "manifest_hash": result.manifest_hash,
        "compliance_hash": result.compliance_hash,
        "adapter_version": result.adapter_version,
        "accepted_item_count": result.accepted_item_count,
        "rejected_item_count": result.rejected_item_count,
        "fetched_item_count": result.fetched_item_count,
        "processed_item_count": result.processed_item_count,
        "request_count": result.request_count,
        "successful_request_count": result.successful_request_count,
        "http_attempt_count": result.http_attempt_count,
        "retry_count": result.retry_count,
        "rate_limit_events": result.rate_limit_events,
        "segment_results": [segment.to_dict() for segment in result.segment_results],
        "rejection_reason_counts": dict(sorted(rejection_counts.items())),
        "transport_events": [_safe_transport_event(event) for event in result.transport_events],
        "accepted_references": references,
        "privacy_qualification": "PASS",
    }


def _safe_transport_event(event: Mapping[str, object]) -> dict[str, object]:
    rate_limit = event.get("rate_limit")
    safe_rate_limit = None
    if isinstance(rate_limit, Mapping):
        resource = rate_limit.get("resource")
        safe_rate_limit = {
            key: rate_limit.get(key)
            for key in ("limit", "remaining", "reset_at", "retry_after_seconds")
        }
        safe_rate_limit["resource"] = (
            resource if resource in _SAFE_RATE_LIMIT_RESOURCES else "unknown"
        )
    category = event.get("category")
    return {
        "sequence": event.get("sequence"),
        "category": category if category in _SAFE_EVENT_CATEGORIES else "unknown",
        "attempt": event.get("attempt"),
        "status_code": event.get("status_code"),
        "retryable": event.get("retryable"),
        "rate_limit": safe_rate_limit,
    }


def exit_code_for_result(result: object) -> int:
    if getattr(result, "termination_reason") is TerminationReason.PREREQUISITE_FAILED:
        return 3
    return 0 if getattr(result, "status") is CollectionStatus.SUCCESS else 2


def write_report(report: Mapping[str, object], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _secret_from_environment() -> bytes:
    value = os.environ.get("RESEARCH_AUTO_AUTHOR_SECRET_HEX", "")
    try:
        secret = bytes.fromhex(value)
    except ValueError as error:
        raise ValueError("RESEARCH_AUTO_AUTHOR_SECRET_HEX must be valid hex") from error
    if len(secret) < 32:
        raise ValueError("RESEARCH_AUTO_AUTHOR_SECRET_HEX must encode at least 32 bytes")
    return secret


def main() -> int:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    compliance = json.loads(COMPLIANCE_PATH.read_text(encoding="utf-8"))
    try:
        secret = _secret_from_environment()
    except ValueError as error:
        print(f"GitHub real smoke prerequisite failure: {error}")
        return 3
    adapter = GitHubIssueAdapter(
        HttpGitHubTransport(token=os.environ.get("GITHUB_TOKEN")),
        author_secret=secret,
        compliance_record=compliance,
    )
    result = collect_source(
        adapter,
        manifest,
        int(manifest["target_valid_records"]),
        manifest_version=str(manifest["manifest_version"]),
    )
    write_report(build_qualification_report(result), DEFAULT_REPORT_PATH)
    segments = " ".join(
        f"{segment.segment_id}={segment.accepted_item_count}/{segment.quota}"
        for segment in result.segment_results
    )
    print(
        "GitHub real smoke "
        f"accepted={result.accepted_item_count}/{result.target_valid_count} "
        f"status={result.status.value} termination={result.termination_reason.value} "
        f"{segments} requests={result.request_count} attempts={result.http_attempt_count} "
        f"retries={result.retry_count} rate_limits={result.rate_limit_events} "
        "privacy=PASS"
    )
    return exit_code_for_result(result)


if __name__ == "__main__":
    raise SystemExit(main())
