from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import Mapping, Sequence

from src.source_spike.adapters.base import CollectionResult, CollectionStatus, TerminationReason
from src.source_spike.adapters.stackexchange import StackExchangeQuestionAdapter
from src.source_spike.adapters.stackexchange_http import HttpStackExchangeTransport
from src.source_spike.collection import collect_source
from src.source_spike.local_secret import load_secret


ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "config/source-spike/stackexchange-smoke.json"
COMPLIANCE_PATH = ROOT / "config/source-spike/compliance/stackexchange.json"
FILTER_PATH = ROOT / "config/source-spike/stackexchange-filter.json"
DEFAULT_REPORT_PATH = ROOT / "artifacts/source-spike/stackexchange-real-smoke/qualification.json"
_SAFE_REFERENCE_KEYS = frozenset(
    {"source_item_id", "site", "source_url", "published_at", "text_fingerprint", "content_license"}
)


def privacy_qualification_for_references(references: Sequence[Mapping[str, object]]) -> str:
    safe = bool(references) and all(set(reference) == _SAFE_REFERENCE_KEYS for reference in references)
    return "PASS" if safe else "FAIL"


def build_qualification_report(result: CollectionResult, *, quota_remaining: int | None) -> dict[str, object]:
    rejection_counts = Counter(item.error_code for item in result.invalid_items)
    references = [{"source_item_id":item["source_item_id"], "site":item["community"],
                   "source_url":item["source_url"], "published_at":item["published_at"],
                   "text_fingerprint":item["text_fingerprint"],
                   "content_license":item["source_metadata"]["content_license"]} for item in result.items]
    license_complete = (
        result.accepted_item_count > 0
        and len(references) == result.accepted_item_count
        and all(value["content_license"] for value in references)
    )
    return {"run_id":result.run_id,"started_at":result.to_dict()["started_at"],"finished_at":result.to_dict()["finished_at"],
            "status":result.status.value,"termination_reason":result.termination_reason.value,"manifest_version":result.manifest_version,
            "manifest_hash":result.manifest_hash,"compliance_hash":result.compliance_hash,"adapter_version":result.adapter_version,
            "accepted_item_count":result.accepted_item_count,"rejected_item_count":result.rejected_item_count,
            "fetched_item_count":result.fetched_item_count,"processed_item_count":result.processed_item_count,
            "request_count":result.request_count,"successful_request_count":result.successful_request_count,
            "http_attempt_count":result.http_attempt_count,"retry_count":result.retry_count,"backoff_events":result.rate_limit_events,
            "response_bytes":result.response_bytes,"quota_remaining":quota_remaining,
            "segment_results":[value.to_dict() for value in result.segment_results],
            "rejection_reason_counts":dict(sorted(rejection_counts.items())),"accepted_references":references,
            "license_completeness":"PASS" if license_complete else "FAIL",
            "privacy_qualification":privacy_qualification_for_references(references)}


def write_report(report: Mapping[str, object], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)+"\n", encoding="utf-8")


def exit_code_for_result(result: object) -> int:
    if getattr(result, "termination_reason") is TerminationReason.PREREQUISITE_FAILED: return 3
    return 0 if getattr(result, "status") is CollectionStatus.SUCCESS else 2


def main() -> int:
    manifest=json.loads(MANIFEST_PATH.read_text()); compliance=json.loads(COMPLIANCE_PATH.read_text()); filter_record=json.loads(FILTER_PATH.read_text())
    try: secret=load_secret()
    except (ValueError, FileNotFoundError) as error:
        print(f"Stack Exchange real smoke prerequisite failure: {error}"); return 3
    transport=HttpStackExchangeTransport(key=os.environ.get("STACKEXCHANGE_KEY"))
    adapter=StackExchangeQuestionAdapter(transport, author_secret=secret.secret, compliance_record=compliance, filter_record=filter_record)
    result=collect_source(adapter, manifest, int(manifest["target_valid_records"]), manifest_version=str(manifest["manifest_version"]))
    report=build_qualification_report(result, quota_remaining=transport.quota_remaining); write_report(report, DEFAULT_REPORT_PATH)
    segments=" ".join(f"{value.segment_id}={value.accepted_item_count}/{value.quota}" for value in result.segment_results)
    print(f"Stack Exchange real smoke accepted={result.accepted_item_count}/{result.target_valid_count} status={result.status.value} termination={result.termination_reason.value} {segments} requests={result.request_count} attempts={result.http_attempt_count} retries={result.retry_count} backoffs={result.rate_limit_events} quota_remaining={transport.quota_remaining} license={report['license_completeness']} privacy={report['privacy_qualification']}")
    return exit_code_for_result(result)


if __name__ == "__main__": raise SystemExit(main())
