from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import Mapping, Sequence
from urllib.parse import urlparse

from src.source_spike.adapters.base import CollectionResult, CollectionStatus, TerminationReason
from src.source_spike.adapters.ted import TedNoticeAdapter
from src.source_spike.adapters.ted_http import HttpTedTransport
from src.source_spike.analysis_bundle import privacy_violations, write_run_bundle
from src.source_spike.collection import collect_source
from src.source_spike.labeling import create_stratified_labeling_assignments
from src.source_spike.local_secret import load_secret
from src.source_spike.protocol import content_sha256
from src.source_spike.raw_items import validate_raw_source_item
from src.source_spike.ted_analysis_authorization import check_authorization
from src.source_spike.ted_analysis_manifest import validate_ted_analysis_manifest
from src.source_spike.ted_contact_redaction import LANGUAGE_VERSION, POLICY_VERSION, residual_contact_count


ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "config/source-spike/ted-analysis.json"
CAPACITY_PATH = ROOT / "config/source-spike/ted-capacity.json"
SMOKE_RECEIPT_PATH = ROOT / "artifacts/source-spike/ted-real-smoke/qualification.json"
AUTHORIZATION_PATH = ROOT / "artifacts/source-spike/ted-analysis-authorization/authorization.json"
ARTIFACT_ROOT = ROOT / "artifacts/source-spike/ted-analysis"
FAILURE_ROOT = ROOT / "artifacts/source-spike/ted-analysis-failures"
EXPECTED_STRATA = {
    "software_and_information_systems",
    "business_services",
    "health_and_social_services",
    "repair_and_maintenance_services",
}


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(nested) for key, nested in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(nested) for nested in value]
    return value


def qualify_ted_analysis(
    result: object,
    *,
    expected_manifest_hash: str,
    expected_compliance_hash: str,
    secrets: Sequence[str] = (),
) -> dict[str, object]:
    items = list(getattr(result, "items", ()))
    failures: list[str] = []
    if (
        getattr(result, "status", None) is not CollectionStatus.SUCCESS
        or getattr(result, "termination_reason", None) is not TerminationReason.TARGET_REACHED
    ):
        failures.append("collection_not_successful")
    if getattr(result, "accepted_item_count", None) != 100 or len(items) != 100:
        failures.append("accepted_count_mismatch")
    segment_counts = {
        value.segment_id: value.accepted_item_count
        for value in getattr(result, "segment_results", ())
    }
    if segment_counts != {stratum: 25 for stratum in EXPECTED_STRATA}:
        failures.append("cpv_stratum_quota_mismatch")
    if any(validate_raw_source_item(_plain(item)) for item in items):
        failures.append("raw_item_invalid")
    for item in items:
        parsed = urlparse(str(item.get("source_url", "")))
        if (
            parsed.scheme != "https"
            or parsed.hostname != "ted.europa.eu"
            or not parsed.path.startswith("/en/notice/-/detail/")
        ):
            failures.append("canonical_url_mismatch")
            break
    if len({str(item.get("document_id")) for item in items}) != len(items):
        failures.append("duplicate_document_id")
    if len({str(item.get("thread_id")) for item in items}) != len(items):
        failures.append("duplicate_procedure_id")
    if Counter(str(item.get("community")) for item in items) != Counter(
        {stratum: 25 for stratum in EXPECTED_STRATA}
    ):
        failures.append("cpv_stratum_item_count_mismatch")
    if any(count > 2 for count in Counter(str(item.get("author_hash")) for item in items).values()):
        failures.append("author_quota_exceeded")
    if (
        getattr(result, "manifest_hash", None) != expected_manifest_hash
        or getattr(result, "compliance_hash", None) != expected_compliance_hash
    ):
        failures.append("provenance_mismatch")
    if privacy_violations(items, secrets=secrets):
        failures.append("privacy_violation")

    redacted_contact_count = 0
    for item in items:
        metadata = item.get("source_metadata")
        if not isinstance(metadata, Mapping):
            failures.append("privacy_metadata_missing")
            continue
        if metadata.get("redaction_policy_version") != POLICY_VERSION:
            failures.append("redaction_policy_mismatch")
        if metadata.get("language_selection_version") != LANGUAGE_VERSION:
            failures.append("language_selection_policy_mismatch")
        count = metadata.get("redacted_contact_count")
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            failures.append("redaction_count_invalid")
        else:
            redacted_contact_count += count
        if residual_contact_count(f"{item.get('title') or ''} {item.get('text') or ''}"):
            failures.append("residual_contact")

    return {
        "qualified": not failures,
        "failures": sorted(set(failures)),
        "official_eligibility": "deferred",
        "interpretation": "balanced_cpv_stratum_experimental_sample",
        "redacted_contact_count": redacted_contact_count,
        "redaction_policy_version": POLICY_VERSION,
        "language_selection_version": LANGUAGE_VERSION,
    }


def write_privacy_failure_receipt(
    root: Path,
    *,
    run_id: str,
    reason_code: str,
    aggregate_count: int,
    manifest_hash: str,
    provenance_hash: str,
    occurred_at: str,
) -> Path:
    run_directory = root / "runs" / run_id
    run_directory.mkdir(parents=True, mode=0o700)
    os.chmod(run_directory, 0o700)
    receipt = {
        "schema_version": "1.0.0",
        "source": "ted",
        "run_id": run_id,
        "status": "FAIL",
        "termination_reason": "privacy_failure",
        "reason_code": reason_code,
        "aggregate_count": aggregate_count,
        "manifest_hash": manifest_hash,
        "provenance_hash": provenance_hash,
        "occurred_at": occurred_at,
        "raw_text_persisted": 0,
        "raw_author_persisted": 0,
        "corpus_persisted": False,
    }
    destination = run_directory / "receipt.json"
    temporary = run_directory / ".receipt.json.tmp"
    temporary.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, destination)
    latest = root / ".latest-failure.tmp"
    latest.write_text(json.dumps({"run_id": run_id, "reason_code": reason_code}, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(latest, 0o600)
    os.replace(latest, root / "latest-failure.json")
    return destination


def publish_analysis_result(
    result: CollectionResult,
    *,
    manifest: Mapping[str, object],
    secrets: Sequence[str] = (),
    artifact_root: Path = ARTIFACT_ROOT,
    failure_root: Path = FAILURE_ROOT,
) -> Path:
    qualification = qualify_ted_analysis(
        result,
        expected_manifest_hash=content_sha256(manifest),
        expected_compliance_hash=str(manifest["compliance_hash"]),
        secrets=secrets,
    )
    failures = set(qualification["failures"])
    if result.termination_reason is TerminationReason.PRIVACY_FAILURE or failures.intersection(
        {"privacy_violation", "privacy_metadata_missing", "redaction_policy_mismatch", "language_selection_policy_mismatch", "redaction_count_invalid", "residual_contact"}
    ):
        return write_privacy_failure_receipt(
            failure_root,
            run_id=result.run_id,
            reason_code="residual_contact" if "residual_contact" in failures else "privacy_qualification_failed",
            aggregate_count=max(1, sum(item.error_code == "residual_contact" for item in result.invalid_items)),
            manifest_hash=result.manifest_hash,
            provenance_hash=result.compliance_hash or "0" * 64,
            occurred_at=result.finished_at.isoformat().replace("+00:00", "Z"),
        )
    assignments = (
        create_stratified_labeling_assignments(result.items, seed=int(manifest["random_seed"]))
        if qualification["qualified"] else []
    )
    source_qualification = {key: value for key, value in qualification.items() if key != "qualified"}
    retention = manifest.get("retention")
    if isinstance(retention, Mapping):
        source_qualification["retention"] = dict(retention)
    return write_run_bundle(
        artifact_root,
        run_id=result.run_id,
        items=result.items,
        collection_result=result.to_dict(),
        assignments=assignments,
        qualified=bool(qualification["qualified"]),
        secrets=secrets,
        source_qualification=source_qualification,
    )


def analysis_exit_code(result: object, *, qualified: bool) -> int:
    if getattr(result, "termination_reason", None) is TerminationReason.PREREQUISITE_FAILED:
        return 3
    if getattr(result, "status", None) is CollectionStatus.SUCCESS and qualified:
        return 0
    return 2


def _load_authorization() -> tuple[Mapping[str, object] | None, list[str]]:
    if AUTHORIZATION_PATH.is_symlink() or not AUTHORIZATION_PATH.is_file():
        return None, ["analysis authorization missing or unsafe"]
    if AUTHORIZATION_PATH.stat().st_mode & 0o077:
        return None, ["analysis authorization permissions must be 0600"]
    try:
        value = json.loads(AUTHORIZATION_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return None, ["analysis authorization malformed"]
    if not isinstance(value, Mapping):
        return None, ["analysis authorization malformed"]
    return value, check_authorization(value, SMOKE_RECEIPT_PATH)


def main() -> int:
    manifest = json.loads(MANIFEST_PATH.read_text())
    capacity = json.loads(CAPACITY_PATH.read_text())
    errors = validate_ted_analysis_manifest(manifest, capacity)
    authorization, authorization_errors = _load_authorization()
    errors.extend(authorization_errors)
    if errors:
        print(f"TED analysis prerequisite failure: {'; '.join(errors)}")
        return 3
    assert authorization is not None
    try:
        secret = load_secret()
    except (FileNotFoundError, ValueError) as error:
        print(f"TED analysis prerequisite failure: {error}")
        return 3
    result = collect_source(
        TedNoticeAdapter(
            HttpTedTransport(),
            capacity_manifest=capacity,
            author_secret=secret.secret,
            manifest_validator=validate_ted_analysis_manifest,
        ),
        manifest,
        100,
        manifest_version=str(manifest["manifest_version"]),
    )
    qualification = qualify_ted_analysis(
        result,
        expected_manifest_hash=content_sha256(manifest),
        expected_compliance_hash=str(manifest["compliance_hash"]),
        secrets=(secret.secret.hex(),),
    )
    destination = publish_analysis_result(
        result,
        manifest=manifest,
        secrets=(secret.secret.hex(),),
    )
    print(
        f"TED analysis accepted={result.accepted_item_count}/100 "
        f"status={result.status.value} termination={result.termination_reason.value} artifact={destination}"
    )
    return analysis_exit_code(result, qualified=bool(qualification["qualified"]))


if __name__ == "__main__":
    raise SystemExit(main())
