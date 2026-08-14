import copy
import json
from pathlib import Path

from src.source_spike.steam_analysis_manifest import validate_steam_analysis_manifest, validate_steam_capacity_manifest

ROOT=Path(__file__).resolve().parents[2]

def records():
    load=lambda name:json.loads((ROOT/name).read_text())
    return load("config/source-spike/steam-analysis.json"),load("config/source-spike/steam-capacity.json"),load("config/source-spike/compliance/steam.json")

def test_analysis_and_capacity_manifests_are_hash_bound_and_balanced():
    analysis,capacity,compliance=records()
    assert validate_steam_analysis_manifest(analysis,compliance)==[]
    assert validate_steam_capacity_manifest(capacity,analysis,compliance)==[]
    assert [x["quota"] for x in analysis["applications"]]==[25]*4
    assert [x["quota"] for x in capacity["applications"]]==[38]*4

def test_analysis_rejects_sentiment_or_purchase_bias():
    analysis,_,compliance=records()
    for key,value in (("review_type","negative"),("purchase_type","steam"),("language","all")):
        changed=copy.deepcopy(analysis); changed["request"][key]=value
        assert "request policy mismatch" in validate_steam_analysis_manifest(changed,compliance)

def test_capacity_rejects_analysis_or_compliance_drift():
    analysis,capacity,compliance=records()
    changed=copy.deepcopy(analysis); changed["random_seed"]+=1
    assert validate_steam_capacity_manifest(capacity,changed,compliance)
    compliance["decision"]="blocked"
    assert validate_steam_capacity_manifest(capacity,analysis,compliance)
