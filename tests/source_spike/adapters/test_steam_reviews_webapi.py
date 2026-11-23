import importlib.util
import json
from urllib.parse import parse_qs, urlparse

import pytest
from src.source_spike.adapters.steam_http import HttpResponse, SteamTransportSuccess, SteamTransportFailure


@pytest.mark.parametrize('status,wrapped', [(200,True),(200,False),(302,False),(429,False)])
def test_official_replacement_review_contract(status, wrapped):
    assert importlib.util.find_spec('src.source_spike.adapters.steam_reviews_webapi') is not None
    from src.source_spike.adapters.steam_reviews_webapi import HttpSteamWebAPITransport
    requests=[]
    def execute(request, timeout):
        requests.append(request)
        payload={'reviews':[{'recommendationid':100,'author':{'steamid':76561190000000000,'playtime_forever':100},
             'review':'Synthetic review','language':'english','timestamp_created':1794000000,'refunded':False,'hardware':{'os':'fixture'}}], 'cursor':'next'}
        return HttpResponse(status,{},json.dumps({'response':payload} if wrapped else payload).encode())
    result=HttpSteamWebAPITransport(execute=execute).fetch_reviews(431960,cursor='*',num_per_page=50,
        filter='recent',language='english',review_type='all',purchase_type='all',filter_offtopic_activity=1,
        request_timeout_seconds=10,max_http_attempts=1,max_total_elapsed_seconds=12,max_retries=0,
        base_backoff_seconds=0,max_backoff_seconds=0,min_request_interval_seconds=1)
    assert len(requests)==1
    url=urlparse(requests[0].full_url); params=json.loads(parse_qs(url.query)['input_json'][0])
    assert url.netloc=='api.steampowered.com' and url.path=='/IUserReviewsService/GetAppReviews/v1/'
    assert params['filter']==1 and params['purchase_type']==1 and params['languages']==['english']
    assert params['date_range_start']<params['date_range_end']
    if status==200:
        assert isinstance(result,SteamTransportSuccess)
        item=result.page.items[0]
        assert item['recommendationid']=='100' and item['author']=={'steamid':'76561190000000000'}
        assert 'hardware' not in item and item['refunded'] is False
    else:
        assert isinstance(result,SteamTransportFailure) and result.error_code==f'http_{status}'
