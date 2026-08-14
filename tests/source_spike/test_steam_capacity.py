from types import SimpleNamespace

from src.source_spike.adapters.base import InvalidItem, SegmentResult
from src.source_spike.steam_capacity import build_capacity_receipt, validate_capacity_receipt
from src.source_spike.protocol import content_sha256

def test_capacity_receipt_retains_metrics_not_items():
    appids=("730","1086940","413150","431960")
    result=SimpleNamespace(invalid_items=(InvalidItem("730:x","short_text",("short",)),),segment_results=tuple(SegmentResult("application",x,38,38,100,39,1 if x=="730" else 0) if x=="730" else SegmentResult("application",x,38,38,100,38,0) for x in appids),request_count=4,http_attempt_count=4,retry_count=0,rate_limit_events=0)
    manifest={"m":1}; analysis={"a":1}; compliance={"c":1}
    receipt=build_capacity_receipt(result,manifest=manifest,analysis=analysis,compliance=compliance)
    assert receipt["status"]=="PASS" and receipt["retained_items"]==0
    assert validate_capacity_receipt(receipt,capacity_manifest_hash=content_sha256(manifest),analysis_manifest_hash=content_sha256(analysis),compliance_hash=content_sha256(compliance))==[]
