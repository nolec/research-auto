from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse

from src.source_spike.adapters.base import CollectionResult, CollectionStatus, TerminationReason
from src.source_spike.adapters.stackexchange import StackExchangeQuestionAdapter
from src.source_spike.adapters.stackexchange_http import HttpStackExchangeTransport
from src.source_spike.analysis_bundle import privacy_violations, write_run_bundle
from src.source_spike.collection import collect_source
from src.source_spike.labeling import create_stratified_labeling_assignments
from src.source_spike.local_secret import load_secret
from src.source_spike.protocol import content_sha256
from src.source_spike.raw_items import validate_raw_source_item
from src.source_spike.stackexchange_analysis_manifest import validate_stackexchange_analysis_manifest
from src.source_spike.stackexchange_capacity import RECEIPT_PATH, validate_capacity_receipt


EXPECTED_SITES = {"stackoverflow", "superuser", "serverfault", "softwareengineering"}
EXPECTED_HOSTS = {
    "stackoverflow": "stackoverflow.com", "superuser": "superuser.com",
    "serverfault": "serverfault.com", "softwareengineering": "softwareengineering.stackexchange.com",
}
ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "config/source-spike/stackexchange-analysis.json"
COMPLIANCE_PATH = ROOT / "config/source-spike/compliance/stackexchange.json"
FILTER_PATH = ROOT / "config/source-spike/stackexchange-filter.json"
ARTIFACT_ROOT = ROOT / "artifacts/source-spike/stackexchange-analysis"


def _plain_json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain_json_value(nested) for key, nested in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_json_value(nested) for nested in value]
    return value


def qualify_stackexchange_analysis(result: object, *, expected_manifest_hash: str, expected_compliance_hash: str, secrets: tuple[str, ...] = ()) -> dict[str, object]:
    items = list(getattr(result, "items", ()))
    failures: list[str] = []
    if getattr(result, "status", None) is not CollectionStatus.SUCCESS or getattr(result, "termination_reason", None) is not TerminationReason.TARGET_REACHED: failures.append("collection_not_successful")
    if getattr(result, "accepted_item_count", None) != 100 or len(items) != 100: failures.append("accepted_count_mismatch")
    segments = getattr(result, "segment_results", ())
    if {value.segment_id: value.accepted_item_count for value in segments} != {site:25 for site in EXPECTED_SITES}: failures.append("site_quota_mismatch")
    if any(validate_raw_source_item(_plain_json_value(item)) for item in items): failures.append("raw_item_invalid")
    for item in items:
        site = str(item.get("community", "")); parsed = urlparse(str(item.get("source_url", "")))
        if parsed.scheme != "https" or parsed.hostname != EXPECTED_HOSTS.get(site) or not parsed.path.startswith("/questions/"):
            failures.append("canonical_url_mismatch"); break
    if any(not isinstance(item.get("source_metadata"), Mapping) or not item["source_metadata"].get("content_license") for item in items): failures.append("license_incomplete")
    if len({str(item.get("document_id")) for item in items}) != len(items): failures.append("duplicate_document_id")
    if getattr(result, "manifest_hash", None) != expected_manifest_hash or getattr(result, "compliance_hash", None) != expected_compliance_hash: failures.append("provenance_mismatch")
    counts = Counter(str(item.get("community")) for item in items)
    if counts != Counter({site:25 for site in EXPECTED_SITES}): failures.append("site_item_count_mismatch")
    if any(count > 2 for count in Counter(str(item.get("author_hash")) for item in items).values()): failures.append("author_quota_exceeded")
    if privacy_violations(items, secrets=secrets): failures.append("privacy_violation")
    return {"qualified": not failures, "failures": sorted(set(failures)), "official_eligibility": "deferred", "interpretation": "balanced_multi_site_experimental_sample", "license_completeness": "PASS" if "license_incomplete" not in failures else "FAIL"}


def publish_analysis_result(result: CollectionResult, *, manifest: Mapping[str, object], secrets: tuple[str, ...] = (), artifact_root: Path = ARTIFACT_ROOT) -> Path:
    qualification = qualify_stackexchange_analysis(result, expected_manifest_hash=content_sha256(manifest), expected_compliance_hash=str(manifest["compliance_hash"]), secrets=secrets)
    assignments = create_stratified_labeling_assignments(result.items, seed=int(manifest["random_seed"])) if qualification["qualified"] else []
    source_qualification = {key:value for key,value in qualification.items() if key != "qualified"}
    return write_run_bundle(artifact_root, run_id=result.run_id, items=result.items, collection_result=result.to_dict(), assignments=assignments, qualified=bool(qualification["qualified"]), secrets=secrets, source_qualification=source_qualification)


def preflight_capacity_receipt(path: Path, *, capacity_manifest_hash: str, analysis_manifest_hash: str, compliance_hash: str, filter_hash: str) -> list[str]:
    if not path.is_file(): return ["capacity receipt missing"]
    try: receipt=json.loads(path.read_text())
    except (OSError, json.JSONDecodeError): return ["capacity receipt malformed"]
    if not isinstance(receipt, Mapping): return ["capacity receipt malformed"]
    return validate_capacity_receipt(receipt, capacity_manifest_hash=capacity_manifest_hash, analysis_manifest_hash=analysis_manifest_hash, compliance_hash=compliance_hash, filter_hash=filter_hash)


def main() -> int:
    manifest=json.loads(MANIFEST_PATH.read_text()); compliance=json.loads(COMPLIANCE_PATH.read_text()); filter_record=json.loads(FILTER_PATH.read_text())
    capacity_manifest=json.loads((ROOT / "config/source-spike/stackexchange-capacity.json").read_text())
    preflight=preflight_capacity_receipt(RECEIPT_PATH, capacity_manifest_hash=content_sha256(capacity_manifest), analysis_manifest_hash=content_sha256(manifest), compliance_hash=content_sha256(compliance), filter_hash=content_sha256(filter_record))
    if preflight: print(f"Stack Exchange analysis prerequisite failure: {'; '.join(preflight)}"); return 3
    try: secret=load_secret()
    except (FileNotFoundError, ValueError) as error:
        print(f"Stack Exchange analysis prerequisite failure: {error}"); return 3
    key=os.environ.get("STACKEXCHANGE_KEY")
    adapter=StackExchangeQuestionAdapter(HttpStackExchangeTransport(key=key), author_secret=secret.secret, compliance_record=compliance, filter_record=filter_record, manifest_validator=validate_stackexchange_analysis_manifest)
    result=collect_source(adapter, manifest, 100, manifest_version=str(manifest["manifest_version"]))
    destination=publish_analysis_result(result, manifest=manifest, secrets=tuple(value for value in (key, secret.secret.hex()) if value))
    print(f"Stack Exchange analysis accepted={result.accepted_item_count}/100 status={result.status.value} termination={result.termination_reason.value} bundle={destination}")
    if result.termination_reason is TerminationReason.PREREQUISITE_FAILED: return 3
    return 0 if result.status is CollectionStatus.SUCCESS else 2


if __name__ == "__main__": raise SystemExit(main())
