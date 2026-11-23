import importlib.util
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from src.source_spike.adapters.steam import SteamReviewPage
from src.source_spike.adapters.steam_http import SteamTransportSuccess, SteamTransportFailure


@pytest.mark.parametrize('failed, expected', [(False, 10), (True, 0)])
def test_fresh_steam_intake_capped_and_private(tmp_path, failed, expected):
    assert importlib.util.find_spec('src.source_spike.fresh_steam_economic_intake') is not None
    from src.source_spike.fresh_steam_economic_intake import collect
    calls=[]
    def fetch(appid, **kwargs):
        calls.append((appid,kwargs))
        if failed:
            return SteamTransportFailure('http_429',1,0,0)
        items=[{'recommendationid':str(i), 'author':{'steamid':str(76561190000000000+i+appid), 'playtime_forever':999999},
                'review':f'The interface is pleasant and review example {appid} item {i} is easy to use.',
                'timestamp_created':int(datetime(2026,11,10,tzinfo=timezone.utc).timestamp()),
                'language':'english','steam_purchase':True,'received_for_free':False,'voted_up':True} for i in range(10)]
        items[1]['review']='Contact someone@example.test for assistance with this review.'
        return SteamTransportSuccess(SteamReviewPage(items,100,'fixture-cursor'),1,0,100)
    root=tmp_path/'run'; result=collect(root,SimpleNamespace(fetch_reviews=fetch),{'steam:431960:0'},set(),[])
    assert result['source_counts']['steam']==expected
    assert len(calls)==(1 if failed else 2)
    assert all(x[1]['max_retries']==0 and x[1]['min_request_interval_seconds']>=1 for x in calls)
    saved=(root/'result.json').read_text()
    assert '7656119' not in saved and '999999' not in saved and 'someone@example.test' not in saved
    assert all(r['observed_fields']['steam_purchase'] is True for r in result['records'])
    with pytest.raises(FileExistsError):
        collect(root,SimpleNamespace(fetch_reviews=fetch),set(),set(),[])
