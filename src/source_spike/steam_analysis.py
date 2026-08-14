from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Mapping
from urllib.parse import parse_qs, urlparse

from src.source_spike.adapters.base import CollectionResult, CollectionStatus, TerminationReason
from src.source_spike.adapters.steam import SteamReviewAdapter
from src.source_spike.adapters.steam_http import HttpSteamTransport
from src.source_spike.analysis_bundle import privacy_violations, write_run_bundle
from src.source_spike.collection import collect_source
from src.source_spike.labeling import create_stratified_labeling_assignments
from src.source_spike.local_secret import load_secret
from src.source_spike.protocol import content_sha256
from src.source_spike.raw_items import validate_raw_source_item
from src.source_spike.steam_analysis_manifest import validate_steam_analysis_manifest
from src.source_spike.steam_capacity import RECEIPT_PATH, validate_capacity_receipt


ROOT=Path(__file__).resolve().parents[2]
MANIFEST_PATH=ROOT/"config/source-spike/steam-analysis.json"
CAPACITY_PATH=ROOT/"config/source-spike/steam-capacity.json"
COMPLIANCE_PATH=ROOT/"config/source-spike/compliance/steam.json"
ARTIFACT_ROOT=ROOT/"artifacts/source-spike/steam-analysis"
EXPECTED={"730","1086940","413150","431960"}


def _plain(value: object) -> object:
    if isinstance(value,Mapping): return {str(k):_plain(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)): return [_plain(v) for v in value]
    return value


def qualify_steam_analysis(result: object, *, expected_manifest_hash: str,
                           expected_compliance_hash: str, secrets: tuple[str,...]=()) -> dict[str,object]:
    items=list(getattr(result,"items",())); failures=[]
    if getattr(result,"status",None) is not CollectionStatus.SUCCESS or getattr(result,"termination_reason",None) is not TerminationReason.TARGET_REACHED: failures.append("collection_not_successful")
    if getattr(result,"accepted_item_count",None)!=100 or len(items)!=100: failures.append("accepted_count_mismatch")
    if {x.segment_id:x.accepted_item_count for x in getattr(result,"segment_results",())}!={x:25 for x in EXPECTED}: failures.append("application_quota_mismatch")
    if any(validate_raw_source_item(_plain(x)) for x in items): failures.append("raw_item_invalid")
    for item in items:
        parsed=urlparse(str(item.get("source_url",""))); query=parse_qs(parsed.query)
        if parsed.scheme!="https" or parsed.hostname!="steamcommunity.com" or not parsed.path.startswith(f"/app/{item.get('community')}/reviews/") or "recommendationid" not in query:
            failures.append("canonical_url_mismatch"); break
    if len({str(x.get("document_id")) for x in items})!=len(items): failures.append("duplicate_document_id")
    if Counter(str(x.get("community")) for x in items)!=Counter({x:25 for x in EXPECTED}): failures.append("application_item_count_mismatch")
    if any(count>2 for count in Counter(str(x.get("author_hash")) for x in items).values()): failures.append("author_quota_exceeded")
    if getattr(result,"manifest_hash",None)!=expected_manifest_hash or getattr(result,"compliance_hash",None)!=expected_compliance_hash: failures.append("provenance_mismatch")
    if privacy_violations(items,secrets=secrets): failures.append("privacy_violation")
    serialized=json.dumps(_plain(items),ensure_ascii=False).casefold()
    if any(token in serialized for token in ('"steamid"','"playtime_forever"','"developer_response"')): failures.append("steam_private_field_retained")
    return {"qualified":not failures,"failures":sorted(set(failures)),"official_eligibility":"deferred","interpretation":"balanced_product_archetype_experimental_sample"}


def publish_analysis_result(result: CollectionResult, *, manifest: Mapping[str,object],
                            secrets: tuple[str,...]=(), artifact_root: Path=ARTIFACT_ROOT) -> Path:
    qualification=qualify_steam_analysis(result,expected_manifest_hash=content_sha256(manifest),expected_compliance_hash=str(manifest["compliance_hash"]),secrets=secrets)
    assignments=create_stratified_labeling_assignments(result.items,seed=int(manifest["random_seed"])) if qualification["qualified"] else []
    source_qualification={k:v for k,v in qualification.items() if k!="qualified"}
    return write_run_bundle(artifact_root,run_id=result.run_id,items=result.items,
        collection_result=result.to_dict(),assignments=assignments,qualified=bool(qualification["qualified"]),
        secrets=secrets,source_qualification=source_qualification)


def main() -> int:
    manifest=json.loads(MANIFEST_PATH.read_text()); capacity=json.loads(CAPACITY_PATH.read_text()); compliance=json.loads(COMPLIANCE_PATH.read_text())
    if not RECEIPT_PATH.is_file(): print("Steam analysis prerequisite failure: capacity receipt missing"); return 3
    try: receipt=json.loads(RECEIPT_PATH.read_text())
    except (OSError,json.JSONDecodeError): print("Steam analysis prerequisite failure: capacity receipt malformed"); return 3
    errors=validate_steam_analysis_manifest(manifest,compliance)+validate_capacity_receipt(receipt,capacity_manifest_hash=content_sha256(capacity),analysis_manifest_hash=content_sha256(manifest),compliance_hash=content_sha256(compliance))
    if errors: print(f"Steam analysis prerequisite failure: {'; '.join(errors)}"); return 3
    try: secret=load_secret()
    except (FileNotFoundError,ValueError) as error: print(f"Steam analysis prerequisite failure: {error}"); return 3
    result=collect_source(SteamReviewAdapter(HttpSteamTransport(),author_secret=secret.secret,
        compliance_record=compliance,manifest_validator=validate_steam_analysis_manifest),manifest,100,manifest_version="1.0.0")
    destination=publish_analysis_result(result,manifest=manifest,secrets=(secret.secret.hex(),))
    print(f"Steam analysis accepted={result.accepted_item_count}/100 status={result.status.value} termination={result.termination_reason.value} bundle={destination}")
    if result.termination_reason is TerminationReason.PREREQUISITE_FAILED: return 3
    return 0 if result.status is CollectionStatus.SUCCESS else 2


if __name__=="__main__": raise SystemExit(main())
