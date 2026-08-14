from datetime import datetime, timezone
from types import SimpleNamespace

from src.source_spike.adapters.base import CollectionStatus, SegmentResult, TerminationReason
from src.source_spike.adapters.steam import parse_steam_review
from src.source_spike.steam_analysis import qualify_steam_analysis

SECRET=b"steam-analysis-test-secret-32bytes"
NOW=datetime(2026,8,14,tzinfo=timezone.utc)

def item(index,appid):
    payload={"recommendationid":str(index),"author":{"steamid":str(index)},"review":f"A detailed recurring product failure {index} prevents the customer from completing an expected workflow safely.","timestamp_created":1786320000,"voted_up":False,"votes_up":0,"comment_count":0,"steam_purchase":True,"received_for_free":False,"written_during_early_access":False}
    return parse_steam_review(payload,appid=int(appid),app_name="App",author_secret=SECRET,run_id="run",adapter_version="0.1.0",collected_at=NOW,published_after=datetime(2026,5,16,tzinfo=timezone.utc),published_before=NOW).item

def result(items):
    return SimpleNamespace(items=items,status=CollectionStatus.SUCCESS,termination_reason=TerminationReason.TARGET_REACHED,accepted_item_count=len(items),manifest_hash="a"*64,compliance_hash="b"*64,segment_results=tuple(SegmentResult("application",appid,25,25,25,25,0) for appid in ("730","1086940","413150","431960")))

def test_qualification_accepts_balanced_privacy_safe_dataset():
    items=[]
    for appid,offset in (("730",0),("1086940",100),("413150",200),("431960",300)):
        items.extend(item(offset+i,appid) for i in range(25))
    value=qualify_steam_analysis(result(items),expected_manifest_hash="a"*64,expected_compliance_hash="b"*64,secrets=(SECRET.hex(),))
    assert value["qualified"] is True and value["failures"]==[]

def test_qualification_rejects_wrong_count_and_identity_field():
    items=[item(i,"730") for i in range(25)]
    value=qualify_steam_analysis(result(items),expected_manifest_hash="a"*64,expected_compliance_hash="b"*64)
    assert value["qualified"] is False
    assert "accepted_count_mismatch" in value["failures"]
