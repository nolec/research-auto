"""Anonymous bounded Steam GetAppReviews v1 transport (no legacy fallback)."""
from __future__ import annotations

from datetime import datetime
import gzip
import io
import json
import ssl
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler

from src.source_spike.adapters.steam import SteamReviewPage
from src.source_spike.adapters.steam_http import HttpResponse, SteamTransportSuccess, SteamTransportFailure, certifi

URL='https://api.steampowered.com/IUserReviewsService/GetAppReviews/v1/'
MAX_BYTES=2_000_000
WINDOW=('2026-08-25T00:00:00+00:00','2026-11-22T23:59:59+00:00')


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _execute(request, timeout):
    opener=build_opener(_NoRedirect(),HTTPSHandler(context=ssl.create_default_context(cafile=certifi.where() if certifi else None)))
    try:
        with opener.open(request,timeout=timeout) as response:
            return HttpResponse(response.status,dict(response.headers.items()),response.read(MAX_BYTES+1))
    except HTTPError as error:
        return HttpResponse(error.code,dict(error.headers.items()),b'')


class HttpSteamWebAPITransport:
    def __init__(self, *, execute=_execute, sleep=time.sleep, monotonic=time.monotonic):
        self.execute,self.sleep,self.monotonic=execute,sleep,monotonic
        self.next_at=0.0

    def fetch_reviews(self, appid, *, cursor, num_per_page, filter, language, review_type, purchase_type,
                      filter_offtopic_activity, request_timeout_seconds,max_http_attempts,max_total_elapsed_seconds,
                      max_retries,base_backoff_seconds,max_backoff_seconds,min_request_interval_seconds):
        if (max_http_attempts!=1 or max_retries!=0 or cursor!='*' or not 1<=num_per_page<=50
            or filter!='recent' or language!='english' or review_type!='all' or purchase_type!='all'
            or filter_offtopic_activity!=1 or min_request_interval_seconds<1 or type(appid) is not int or appid<=0):
            raise ValueError('unsupported bounded intake configuration')
        wait=max(0,self.next_at-self.monotonic())
        if wait>=max_total_elapsed_seconds:
            return SteamTransportFailure('deadline_exhausted',0,0,0)
        if wait: self.sleep(wait)
        params={'appid':appid,'filter':1,'languages':['english'],'review_type':0,'purchase_type':1,
                'cursor':'*','num_per_page':num_per_page,'filter_offtopic_activity':True,
                'date_range_start':int(datetime.fromisoformat(WINDOW[0]).timestamp()),
                'date_range_end':int(datetime.fromisoformat(WINDOW[1]).timestamp())}
        request=Request(URL+'?'+urlencode({'input_json':json.dumps(params,separators=(',',':'))}),
                        headers={'Accept':'application/json','User-Agent':'research-auto/0.1.0'})
        self.next_at=self.monotonic()+min_request_interval_seconds
        try:
            response=self.execute(request,min(request_timeout_seconds,max_total_elapsed_seconds-wait))
        except (URLError,TimeoutError,OSError):
            return SteamTransportFailure('transport_error',1,0,0)
        size=len(response.body)
        if response.status_code!=200:
            return SteamTransportFailure(f'http_{response.status_code}',1,0,size)
        if size>MAX_BYTES:
            return SteamTransportFailure('response_too_large',1,0,size)
        body=response.body
        try:
            if any(k.casefold()=='content-encoding' and v.casefold()=='gzip' for k,v in response.headers.items()):
                with gzip.GzipFile(fileobj=io.BytesIO(body)) as stream: body=stream.read(MAX_BYTES+1)
            if len(body)>MAX_BYTES: return SteamTransportFailure('response_too_large',1,0,size)
            raw=json.loads(body)
        except (OSError,UnicodeDecodeError,ValueError):
            return SteamTransportFailure('invalid_json_response',1,0,size)
        if isinstance(raw,dict) and 'response' in raw and 'reviews' not in raw:
            raw=raw['response']
        if not isinstance(raw,dict) or not isinstance(raw.get('reviews'),list) or not all(isinstance(x,dict) for x in raw['reviews']):
            return SteamTransportFailure('malformed_wrapper',1,0,size)
        cursor_value=raw.get('cursor')
        if cursor_value is not None and not isinstance(cursor_value,str):
            return SteamTransportFailure('malformed_wrapper',1,0,size)
        normalized=[]
        for item in raw['reviews'][:num_per_page]:
            row={k:item[k] for k in ('recommendationid','review','language','timestamp_created','timestamp_updated','steam_purchase','received_for_free','voted_up','refunded') if k in item}
            if type(row.get('recommendationid')) is int: row['recommendationid']=str(row['recommendationid'])
            author=item.get('author')
            if isinstance(author,dict) and type(author.get('steamid')) in (int,str):
                row['author']={'steamid':str(author['steamid'])}
            normalized.append(row)
        return SteamTransportSuccess(SteamReviewPage(normalized,size,cursor_value or None),1,0,size)
