"""Bounded one-shot public Steam review intake; internal research only."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re

from src.source_spike.adapters.steam_http import HttpSteamTransport, SteamTransportFailure
from src.source_spike.adapters.steam_reviews_webapi import HttpSteamWebAPITransport
from src.source_spike.raw_items import normalize_text
from src.source_spike.ted_contact_redaction import residual_contact_count
from src.source_spike.fresh_ted_economic_intake import historical
from src.extraction.codex_cli_diagnostic import _private_create

ROOT=Path(__file__).resolve().parents[2]
RUN_ROOT=ROOT/'artifacts/extraction/calibration/audit-local/fresh-economic-steam-intake-20261123'
PROTOCOL=ROOT/'docs/economic-signal-fresh-steam-intake-20261123.md'
RUN_ROOT_V2=RUN_ROOT.parent/'fresh-economic-steam-webapi-v2-20261123'
PROTOCOL_V2=ROOT/'docs/economic-signal-fresh-steam-webapi-v2-20261123.md'
ARMS=((431960,'Wallpaper Engine'),(413150,'Stardew Valley'))
WINDOW=('2026-08-25T00:00:00Z','2026-11-22T23:59:59Z')


def published_time(value):
    try:
        return datetime.fromtimestamp(value,timezone.utc).isoformat().replace('+00:00','Z') if type(value) is int else None
    except (ValueError,OSError,OverflowError):
        return None


def collect(root,transport,old_ids,old_thread_ids,old_texts,*,protocol=PROTOCOL):
    root.mkdir(mode=0o700,exist_ok=False)
    _private_create(root/'claim.json',{'applications':ARMS,'date_window':WINDOW,'max_requests':2,'page_size':50,
        'protocol_sha256':sha256(protocol.read_bytes()).hexdigest(),'implementation_sha256':sha256(Path(__file__).read_bytes()).hexdigest(),
        'webapi_transport_sha256':sha256((ROOT/'src/source_spike/adapters/steam_reviews_webapi.py').read_bytes()).hexdigest() if protocol==PROTOCOL_V2 else None})
    records,arms=[],[]
    seen_ids,seen_excerpts=set(old_ids),set()
    owners=Counter(); reason=None
    for appid,name in ARMS:
        response=transport.fetch_reviews(appid,cursor='*',num_per_page=50,filter='recent',language='english',
          review_type='all',purchase_type='all',filter_offtopic_activity=1,request_timeout_seconds=10,
          max_http_attempts=1,max_total_elapsed_seconds=12,max_retries=0,base_backoff_seconds=0,
          max_backoff_seconds=0,min_request_interval_seconds=1)
        if isinstance(response,SteamTransportFailure):
            reason=response.error_code; arms.append({'appid':appid,'status':'FAILED','error':reason}); break
        accepted=0; rejected=Counter()
        for item in response.page.items[:50]:
            if accepted>=5: break
            rid=item.get('recommendationid'); owner=item.get('author')
            steamid=owner.get('steamid') if isinstance(owner,dict) else None
            published=published_time(item.get('timestamp_created'))
            updated=published_time(item.get('timestamp_updated')) if item.get('timestamp_updated') is not None else None
            if (not isinstance(rid,str) or not re.fullmatch(r'\d{1,30}',rid) or not isinstance(steamid,str) or not steamid.isdigit()
                or not published or not WINDOW[0]<=published<=WINDOW[1] or item.get('language')!='english'
                or (item.get('timestamp_updated') is not None and (not updated or updated>WINDOW[1]))):
                rejected['provenance_or_scope']+=1; continue
            doc_id=f'steam:{appid}:{rid}'
            if doc_id in seen_ids or f'{appid}:{rid}' in old_thread_ids or owners[steamid]>=2:
                rejected['duplicate_or_author_cap']+=1; continue
            body=normalize_text(item['review']) if isinstance(item.get('review'),str) else ''
            words=list(re.finditer(r'\S+',body)); excerpt=body[:words[min(len(words),25)-1].end()] if words else ''
            if (len(words)<5 or residual_contact_count(body) or re.search(r'\b(?:exploit|vulnerability|malware|ransomware|password|credential|bypass|private key|weapon|ammunition|pathogen|medical record)\b',body,re.I)):
                rejected['privacy_or_context']+=1; continue
            if excerpt in seen_excerpts or any(excerpt in old for old in old_texts):
                rejected['duplicate_excerpt']+=1; continue
            flags={k:item[k] for k in ('steam_purchase','received_for_free','voted_up','refunded') if type(item.get(k)) is bool}
            records.append({'source':'steam','document_id':doc_id,'appid':appid,'title':name,
                'source_url':f'https://steamcommunity.com/app/{appid}/reviews/?recommendationid={rid}',
                'published_at':published,'date_precision':'second','excerpt':excerpt,'excerpt_sha256':sha256(excerpt.encode()).hexdigest(),
                'observed_fields':flags})
            seen_ids.add(doc_id); seen_excerpts.add(excerpt); owners[steamid]+=1; accepted+=1
        arms.append({'appid':appid,'status':'COLLECTED','returned':min(len(response.page.items),50),'accepted':accepted,'rejection_counts':dict(rejected)})
    result={'status':'INCOMPLETE' if reason else 'STEAM_INTAKE_GOLD_PENDING','reason':reason,'target':10,
            'source_counts':{'steam':len(records)},'arms':arms,'records':records,
            'scope':'fresh excerpt intake only; purchase metadata is not economic gold; internal use only'}
    _private_create(root/'result.json',result)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__); action=parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--check',action='store_true'); action.add_argument('--execute',action='store_true')
    action.add_argument('--check-v2',action='store_true'); action.add_argument('--execute-v2',action='store_true')
    args=parser.parse_args(); old=historical()
    v2=args.check_v2 or args.execute_v2
    root=RUN_ROOT_V2 if v2 else RUN_ROOT
    if args.check or args.check_v2:
        print(json.dumps({'status':'READY_OFFLINE','historical_ids':len(old[0]),'run_exists':root.exists(),'max_requests':2})); return 0
    if root.exists():
        print('Run already exists; no retry.'); return 2
    result=collect(root,HttpSteamWebAPITransport() if v2 else HttpSteamTransport(),*old,protocol=PROTOCOL_V2 if v2 else PROTOCOL)
    print(json.dumps({'status':result['status'],'steam_count':result['source_counts']['steam'],'reason':result['reason'],'result':str(root/'result.json')}))
    return 1 if result['status']=='INCOMPLETE' else 0


if __name__=='__main__':
    raise SystemExit(main())
