from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import Mapping

from src.source_spike.adapters.steam import SteamReviewAdapter
from src.source_spike.adapters.steam_http import HttpSteamTransport
from src.source_spike.collection import collect_source
from src.source_spike.local_secret import load_secret
from src.source_spike.protocol import content_sha256
from src.source_spike.steam_analysis_manifest import validate_steam_capacity_manifest


ROOT=Path(__file__).resolve().parents[2]
MANIFEST_PATH=ROOT/"config/source-spike/steam-capacity.json"
ANALYSIS_PATH=ROOT/"config/source-spike/steam-analysis.json"
COMPLIANCE_PATH=ROOT/"config/source-spike/compliance/steam.json"
RECEIPT_PATH=ROOT/"artifacts/source-spike/steam-capacity/latest.json"
EXPECTED=("730","1086940","413150","431960")


def build_capacity_receipt(result: object, *, manifest: Mapping[str,object], analysis: Mapping[str,object], compliance: Mapping[str,object]) -> dict[str,object]:
    rejected={appid:Counter() for appid in EXPECTED}
    for value in getattr(result,"invalid_items",()):
        appid=value.source_item_id.split(":",1)[0] if value.source_item_id else None
        if appid in rejected: rejected[appid][value.error_code]+=1
    segments={value.segment_id:value for value in getattr(result,"segment_results",())}
    apps={}
    for appid in EXPECTED:
        segment=segments.get(appid)
        apps[appid]={"fetched":segment.fetched_item_count if segment else 0,
            "processed":segment.processed_item_count if segment else 0,
            "accepted":segment.accepted_item_count if segment else 0,
            "rejected":segment.rejected_item_count if segment else 0,
            "rejection_reason_counts":dict(sorted(rejected[appid].items())),
            "capacity_pass":bool(segment and segment.accepted_item_count>=38)}
    passed=set(segments)==set(EXPECTED) and all(x["capacity_pass"] for x in apps.values())
    return {"schema_version":1,"status":"PASS" if passed else "FAIL",
        "capacity_manifest_hash":content_sha256(manifest),"analysis_manifest_hash":content_sha256(analysis),
        "compliance_hash":content_sha256(compliance),"required_per_application":38,
        "retained_items":0,"applications":apps,"transport":{"requests":result.request_count,
        "attempts":result.http_attempt_count,"retries":result.retry_count,
        "rate_limit_events":result.rate_limit_events}}


def validate_capacity_receipt(receipt: Mapping[str,object], *, capacity_manifest_hash: str,
                              analysis_manifest_hash: str, compliance_hash: str) -> list[str]:
    errors=[]
    if receipt.get("status")!="PASS" or receipt.get("schema_version")!=1: errors.append("capacity receipt is not PASS")
    for key,expected in (("capacity_manifest_hash",capacity_manifest_hash),("analysis_manifest_hash",analysis_manifest_hash),("compliance_hash",compliance_hash)):
        if receipt.get(key)!=expected: errors.append(f"{key} mismatch")
    if receipt.get("required_per_application")!=38 or receipt.get("retained_items")!=0: errors.append("capacity receipt policy mismatch")
    apps=receipt.get("applications")
    if not isinstance(apps,Mapping) or set(apps)!=set(EXPECTED): errors.append("capacity applications mismatch")
    else:
        for appid,value in apps.items():
            if not isinstance(value,Mapping) or value.get("capacity_pass") is not True or not isinstance(value.get("accepted"),int) or value["accepted"]<38: errors.append(f"capacity failed: {appid}")
            elif value.get("processed")!=value.get("accepted",0)+value.get("rejected",0) or value.get("processed",0)>value.get("fetched",0): errors.append(f"capacity arithmetic mismatch: {appid}")
    return errors


def write_receipt(value: Mapping[str,object]) -> None:
    RECEIPT_PATH.parent.mkdir(parents=True,exist_ok=True); temporary=RECEIPT_PATH.with_name(".latest.tmp")
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2,sort_keys=True)+"\n"); os.replace(temporary,RECEIPT_PATH)


def main() -> int:
    manifest=json.loads(MANIFEST_PATH.read_text()); analysis=json.loads(ANALYSIS_PATH.read_text()); compliance=json.loads(COMPLIANCE_PATH.read_text())
    errors=validate_steam_capacity_manifest(manifest,analysis,compliance)
    if errors: print(f"Steam capacity prerequisite failure: {'; '.join(errors)}"); return 3
    try: secret=load_secret()
    except (FileNotFoundError,ValueError) as error: print(f"Steam capacity prerequisite failure: {error}"); return 3
    validator=lambda value,compliance_value:validate_steam_capacity_manifest(value,analysis,compliance_value)
    result=collect_source(SteamReviewAdapter(HttpSteamTransport(),author_secret=secret.secret,compliance_record=compliance,manifest_validator=validator),manifest,152,manifest_version="1.0.0")
    receipt=build_capacity_receipt(result,manifest=manifest,analysis=analysis,compliance=compliance); write_receipt(receipt)
    print(json.dumps(receipt,sort_keys=True)); return 0 if receipt["status"]=="PASS" else 2


if __name__=="__main__": raise SystemExit(main())
