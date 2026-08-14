from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Mapping, Sequence, cast

from src.source_spike.protocol import content_sha256


EXPECTED = {730:"free_live_service",1086940:"premium_aaa",413150:"paid_indie",431960:"paid_software"}


def _common(manifest: Mapping[str, object], compliance: Mapping[str, object], *, quota: int, target: int) -> list[str]:
    errors=[]
    required={"manifest_version","source","adapter_version","target_valid_records","max_items_per_author","published_after","published_before","applications","request","retry","compliance_hash","compliance_decision"}
    if not required.issubset(manifest): return ["manifest fields missing"]
    if manifest.get("source")!="steam" or manifest.get("adapter_version")!="0.1.0" or manifest.get("target_valid_records")!=target or manifest.get("max_items_per_author")!=2: errors.append("manifest identity or target mismatch")
    apps=cast(Sequence[Mapping[str,object]],manifest["applications"])
    if len(apps)!=4 or {int(x.get("appid",0)):str(x.get("archetype","")) for x in apps}!=EXPECTED: errors.append("application strata mismatch")
    if any(x.get("quota")!=quota for x in apps) or sum(int(x.get("quota",0)) for x in apps)!=target: errors.append("application quota mismatch")
    after=datetime.fromisoformat(str(manifest["published_after"]).replace("Z","+00:00")); before=datetime.fromisoformat(str(manifest["published_before"]).replace("Z","+00:00"))
    if not 89 <= (before-after).total_seconds()/86400 <= 91: errors.append("published window must be 90 days")
    request=cast(Mapping[str,object],manifest["request"]); retry=cast(Mapping[str,object],manifest["retry"])
    frozen={"endpoint":"/appreviews/{appid}","filter":"recent","language":"english","review_type":"all","purchase_type":"all","filter_offtopic_activity":1}
    if any(request.get(k)!=v for k,v in frozen.items()): errors.append("request policy mismatch")
    if not isinstance(request.get("num_per_page"),int) or not 1<=int(request["num_per_page"])<=100: errors.append("page size invalid")
    if int(request.get("max_http_attempts",0))<int(request.get("max_requests",0)): errors.append("attempt budget invalid")
    if float(request.get("min_request_interval_seconds",0))<1: errors.append("request interval invalid")
    if float(retry.get("base_backoff_seconds",0))>float(retry.get("max_backoff_seconds",0)): errors.append("retry policy invalid")
    if content_sha256(compliance)!=manifest.get("compliance_hash"): errors.append("compliance hash mismatch")
    elif compliance.get("source")!="steam" or compliance.get("decision")!=manifest.get("compliance_decision"): errors.append("compliance decision mismatch")
    return errors


def validate_steam_analysis_manifest(manifest: Mapping[str, object], compliance: Mapping[str, object]) -> list[str]:
    errors=_common(manifest,compliance,quota=25,target=100)
    if manifest.get("manifest_version")!="1.0.0" or manifest.get("random_seed")!=20260814 or manifest.get("interpretation")!="balanced_product_archetype_experimental_sample" or manifest.get("official_eligibility")!="deferred": errors.append("analysis policy mismatch")
    return errors


def validate_steam_capacity_manifest(manifest: Mapping[str, object], analysis: Mapping[str, object], compliance: Mapping[str, object]) -> list[str]:
    errors=_common(manifest,compliance,quota=38,target=152)
    if manifest.get("manifest_version")!="1.0.0" or manifest.get("capacity_multiplier")!=1.5 or manifest.get("analysis_quota_per_application")!=25 or manifest.get("required_valid_per_application")!=38: errors.append("capacity policy mismatch")
    if manifest.get("analysis_manifest_hash")!=content_sha256(analysis): errors.append("analysis manifest hash mismatch")
    if validate_steam_analysis_manifest(analysis,compliance): errors.append("analysis manifest invalid")
    return errors
