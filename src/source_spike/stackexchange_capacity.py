from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import Mapping

from src.source_spike.adapters.stackexchange import StackExchangeQuestionAdapter
from src.source_spike.adapters.stackexchange_http import HttpStackExchangeTransport
from src.source_spike.collection import collect_source
from src.source_spike.local_secret import load_secret
from src.source_spike.protocol import content_sha256
from src.source_spike.stackexchange_capacity_manifest import validate_stackexchange_capacity_manifest


ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "config/source-spike/stackexchange-capacity.json"
ANALYSIS_PATH = ROOT / "config/source-spike/stackexchange-analysis.json"
COMPLIANCE_PATH = ROOT / "config/source-spike/compliance/stackexchange.json"
FILTER_PATH = ROOT / "config/source-spike/stackexchange-filter.json"
RECEIPT_PATH = ROOT / "artifacts/source-spike/stackexchange-capacity/latest.json"
EXPECTED_SITES = ("stackoverflow", "superuser", "serverfault", "softwareengineering")
_RECEIPT_KEYS = {
    "schema_version", "status", "capacity_manifest_hash", "analysis_manifest_hash",
    "compliance_hash", "filter_hash", "required_per_site", "retained_items", "sites", "transport",
}
_SITE_KEYS = {"fetched", "processed", "accepted", "rejected", "rejection_reason_counts", "capacity_pass"}
_TRANSPORT_KEYS = {"requests", "attempts", "retries", "backoffs", "quota_remaining"}


def _nonnegative_integer(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value >= 0


def capacity_summary(counts: Mapping[str, int], *, required_per_site: int = 38) -> dict[str, object]:
    sites = {
        site: {"valid_candidate_count": int(count), "capacity_pass": int(count) >= required_per_site}
        for site, count in sorted(counts.items())
    }
    return {
        "required_per_site": required_per_site,
        "passed": set(sites) == set(EXPECTED_SITES) and all(value["capacity_pass"] for value in sites.values()),
        "sites": sites,
        "retained_items": 0,
    }


def validate_capacity_receipt(receipt: Mapping[str, object], *, capacity_manifest_hash: str, analysis_manifest_hash: str, compliance_hash: str, filter_hash: str) -> list[str]:
    errors: list[str] = []
    if set(receipt) != _RECEIPT_KEYS: errors.append("capacity receipt field set mismatch")
    if receipt.get("schema_version") != 1: errors.append("capacity receipt schema version mismatch")
    if receipt.get("status") != "PASS": errors.append("capacity receipt is not PASS")
    for key, expected in (("capacity_manifest_hash",capacity_manifest_hash),("analysis_manifest_hash",analysis_manifest_hash),("compliance_hash",compliance_hash),("filter_hash",filter_hash)):
        if receipt.get(key) != expected: errors.append(f"{key.replace('_', ' ')} mismatch")
    if receipt.get("required_per_site") != 38 or receipt.get("retained_items") != 0: errors.append("capacity receipt policy mismatch")
    sites = receipt.get("sites")
    if not isinstance(sites, Mapping) or set(sites) != set(EXPECTED_SITES): errors.append("capacity receipt sites mismatch")
    else:
        for site, value in sites.items():
            if not isinstance(value, Mapping) or set(value) != _SITE_KEYS:
                errors.append(f"capacity receipt site fields mismatch: {site}"); continue
            metrics = {key: value.get(key) for key in ("fetched", "processed", "accepted", "rejected")}
            if not all(_nonnegative_integer(metric) for metric in metrics.values()) or value.get("capacity_pass") is not True or metrics["accepted"] < 38:
                errors.append(f"capacity receipt site failed: {site}")
                continue
            reasons = value.get("rejection_reason_counts")
            if not isinstance(reasons, Mapping) or any(not isinstance(key, str) or not _nonnegative_integer(count) for key, count in reasons.items()):
                errors.append(f"capacity receipt rejection counts invalid: {site}")
            if metrics["processed"] != metrics["accepted"] + metrics["rejected"] or metrics["rejected"] != sum(reasons.values() if isinstance(reasons, Mapping) else ()) or metrics["processed"] > metrics["fetched"]:
                errors.append(f"capacity receipt site arithmetic mismatch: {site}")
    transport = receipt.get("transport")
    if not isinstance(transport, Mapping) or set(transport) != _TRANSPORT_KEYS: errors.append("capacity receipt transport metrics missing")
    else:
        for key, value in transport.items():
            if value is not None and not _nonnegative_integer(value): errors.append(f"capacity receipt transport metric invalid: {key}")
        if all(_nonnegative_integer(transport.get(key)) for key in ("requests", "attempts", "retries")) and transport["attempts"] != transport["requests"] + transport["retries"]:
            errors.append("capacity receipt transport arithmetic mismatch")
    return errors


def _site_from_invalid(source_item_id: str | None) -> str | None:
    if source_item_id:
        candidate = source_item_id.split(":", 1)[0]
        return candidate if candidate in EXPECTED_SITES else None
    return None


def build_capacity_receipt(result: object, *, manifest: Mapping[str, object], analysis: Mapping[str, object], compliance: Mapping[str, object], filter_record: Mapping[str, object], quota_remaining: int | None) -> dict[str, object]:
    accepted = Counter(str(item["community"]) for item in getattr(result, "items", ()))
    rejected: dict[str, Counter[str]] = {site: Counter() for site in EXPECTED_SITES}
    for invalid in getattr(result, "invalid_items", ()):
        site = _site_from_invalid(invalid.source_item_id)
        if site: rejected[site][invalid.error_code] += 1
    site_values = {}
    segments = {segment.segment_id: segment for segment in getattr(result, "segment_results", ())}
    for site in EXPECTED_SITES:
        segment = segments.get(site)
        segment_accepted = segment.accepted_item_count if segment is not None else 0
        segment_fetched = segment.fetched_item_count if segment is not None else 0
        segment_processed = segment.processed_item_count if segment is not None else 0
        segment_rejected = segment.rejected_item_count if segment is not None else 0
        site_values[site] = {
            "fetched": segment_fetched, "processed": segment_processed,
            "accepted": segment_accepted, "rejected": segment_rejected,
            "rejection_reason_counts": dict(sorted(rejected[site].items())),
            "capacity_pass": segment is not None and segment_accepted >= 38,
        }
    passed = (
        set(segments) == set(EXPECTED_SITES)
        and all(value["capacity_pass"] for value in site_values.values())
        and all(accepted[site] == site_values[site]["accepted"] for site in EXPECTED_SITES)
        and all(sum(rejected[site].values()) == site_values[site]["rejected"] for site in EXPECTED_SITES)
    )
    return {
        "schema_version": 1, "status": "PASS" if passed else "FAIL",
        "capacity_manifest_hash": content_sha256(manifest), "analysis_manifest_hash": content_sha256(analysis),
        "compliance_hash": content_sha256(compliance), "filter_hash": content_sha256(filter_record),
        "required_per_site": 38, "retained_items": 0, "sites": site_values,
        "transport": {"requests": result.request_count, "attempts": result.http_attempt_count, "retries": result.retry_count, "backoffs": result.rate_limit_events, "quota_remaining": quota_remaining},
    }


def write_capacity_receipt(receipt: Mapping[str, object], path: Path = RECEIPT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def main() -> int:
    manifest=json.loads(MANIFEST_PATH.read_text()); analysis=json.loads(ANALYSIS_PATH.read_text()); compliance=json.loads(COMPLIANCE_PATH.read_text()); filter_record=json.loads(FILTER_PATH.read_text())
    errors=validate_stackexchange_capacity_manifest(manifest, analysis, compliance, filter_record)
    if errors: print(f"Stack Exchange capacity prerequisite failure: {'; '.join(errors)}"); return 3
    try: secret=load_secret()
    except (FileNotFoundError, ValueError) as error: print(f"Stack Exchange capacity prerequisite failure: {error}"); return 3
    transport=HttpStackExchangeTransport(key=os.environ.get("STACKEXCHANGE_KEY"))
    validator=lambda value, compliance_value, filter_value: validate_stackexchange_capacity_manifest(value, analysis, compliance_value, filter_value)
    adapter=StackExchangeQuestionAdapter(transport, author_secret=secret.secret, compliance_record=compliance, filter_record=filter_record, manifest_validator=validator)
    result=collect_source(adapter, manifest, int(manifest["target_valid_records"]), manifest_version=str(manifest["manifest_version"]))
    receipt=build_capacity_receipt(result, manifest=manifest, analysis=analysis, compliance=compliance, filter_record=filter_record, quota_remaining=transport.quota_remaining)
    write_capacity_receipt(receipt)
    print(json.dumps(receipt, sort_keys=True))
    return 0 if receipt["status"] == "PASS" else 2


if __name__ == "__main__": raise SystemExit(main())
