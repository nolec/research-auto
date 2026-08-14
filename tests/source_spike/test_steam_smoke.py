from types import SimpleNamespace

from src.source_spike.adapters.base import CollectionStatus, SegmentResult, TerminationReason
from src.source_spike.steam_smoke import build_qualification_report, privacy_qualification_for_references, write_report


def test_report_excludes_raw_text_identity_and_play_history(tmp_path) -> None:
    marker="RAW-REVIEW-CANARY"
    item={"source_item_id":"730:1","community":"730","source_url":"https://steamcommunity.com/app/730/reviews/?recommendationid=1","published_at":"2026-08-13T00:00:00Z","text_fingerprint":"a"*64,"text":marker,"source_metadata":{"voted_up":False,"steam_purchase":True,"received_for_free":False}}
    result=SimpleNamespace(run_id="run",status=CollectionStatus.SUCCESS,termination_reason=TerminationReason.TARGET_REACHED,manifest_version="0.1.0",manifest_hash="b"*64,compliance_hash="c"*64,adapter_version="0.1.0",accepted_item_count=1,rejected_item_count=0,fetched_item_count=1,processed_item_count=1,request_count=1,successful_request_count=1,http_attempt_count=1,retry_count=0,rate_limit_events=0,response_bytes=10,segment_results=(SegmentResult("application","730",1,1,1,1,0),),invalid_items=(),items=(item,),to_dict=lambda:{"started_at":"2026-08-13T00:00:00Z","finished_at":"2026-08-13T00:00:01Z"})
    report=build_qualification_report(result); write_report(report,tmp_path/"q.json")
    serialized=(tmp_path/"q.json").read_text()
    assert marker not in serialized and "playtime" not in serialized and "steamid" not in serialized
    assert report["privacy_qualification"] == "PASS"


def test_privacy_shape_fails_with_extra_identity_field() -> None:
    safe={"source_item_id":"730:1","appid":"730","source_url":"https://steamcommunity.com/app/730/reviews/?recommendationid=1","published_at":"2026-08-13T00:00:00Z","text_fingerprint":"a"*64,"voted_up":False,"steam_purchase":True,"received_for_free":False}
    assert privacy_qualification_for_references([safe]) == "PASS"
    assert privacy_qualification_for_references([{**safe,"steamid":"x"}]) == "FAIL"
