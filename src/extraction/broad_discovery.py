"""Industry-neutral exploratory intake. Empty search arms remain visible.

Source selection and semantic grouping are attributed review inputs; this
module does not perform live search or assert verified buyer independence.
"""
import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from src.extraction.fresh_buyer_intake import job_key


def identity(record):
    url = urlsplit(record['url'])
    if url.scheme != 'https' or url.username or url.password:
        raise ValueError('Public HTTPS URL required')
    if url.hostname == 'www.airtasker.com':
        m = re.fullmatch(r'/tasks/[^/]+-(x[0-9a-z]+)/?',url.path)
        if not m:
            raise ValueError('Not an individual task')
        return 'airtasker:'+m.group(1)
    if url.hostname in ('www.reddit.com','reddit.com'):
        m=re.match(r'/r/[^/]+/comments/([0-9a-z]+)/',url.path)
        if not m:
            raise ValueError('Not an individual discussion')
        return 'reddit:'+m.group(1)
    return job_key(record)


def build(snapshot):
    as_of=date.fromisoformat(snapshot['as_of']); cutoff=as_of-timedelta(days=90)
    arms=snapshot['arms']
    if set(arms)!={'time_burden','recurring_purchase','struggle','alternative_dissatisfaction'}:
        raise ValueError('All discovery arms must be accounted for')
    selected=Counter(); seen=set(); groups=defaultdict(list); sources=Counter(); domains=Counter(); rows=[]
    for arm,settings in arms.items():
        if not isinstance(settings['queries'],list) or not settings['queries'] or not isinstance(settings['cap'],int) or not 1<=settings['cap']<=20:
            raise ValueError('Invalid discovery arm')
    for record in snapshot['records']:
        arm=record['arm']; selected[arm]+=1
        if arm not in arms or selected[arm]>arms[arm]['cap']:
            raise ValueError('Exceeded per-arm intake cap')
        token=identity(record)
        if token in seen:
            raise ValueError('Duplicate source identity')
        seen.add(token)
        if record['role'] not in ('buyer','user') or record['access'] not in ('DIRECT_OPEN','INDEX_ONLY','DIRECT_BLOCKED') or record['recurrence'] not in ('RECURRING_TASK','POTENTIAL_REPEAT','ONE_OFF','UNKNOWN'):
            raise ValueError('Invalid role, access or recurrence')
        if not all(isinstance(record[k],str) and record[k].strip() for k in ('problem_key','problem','domain','summary')):
            raise ValueError('Missing observed problem annotation')
        if record['date_precision']=='DAY':
            day=date.fromisoformat(record['published_date']); freshness='RECENT_DAY_ONLY' if cutoff<=day<=as_of else 'OUTSIDE_WINDOW'
        elif record['date_precision'] in ('RELATIVE','UNKNOWN') and record['published_date'] is None:
            freshness='UNKNOWN'
        else:
            raise ValueError('Invalid publication date precision')
        budget=record.get('budget')
        if budget is not None:
            if record['role']!='buyer' or budget['currency'] not in ('USD','AUD','GBP','INR','EUR','CAD','KRW') or budget['unit'] not in ('fixed','hourly','monthly') or not all(type(budget[k]) in (int,float) and 0<budget[k]<1e9 for k in ('low','high')) or budget['low']>budget['high']:
                raise ValueError('Invalid stated budget')
        row={**record,'id':token,'freshness':freshness,'actual_payment':'UNKNOWN','independence':'UNKNOWN'}; rows.append(row)
        sources[token.split(':',1)[0]]+=1; domains[record['domain']]+=1
        if freshness!='OUTSIDE_WINDOW': groups[record['problem_key']].append(row)
    candidates=[]
    for key,items in groups.items():
        if len({r['problem'] for r in items})!=1:
            raise ValueError('Inconsistent group label')
        candidates.append({'key':key,'problem':items[0]['problem'],'observations':len(items),'budget_requests':sum(r.get('budget') is not None for r in items),'recurring_requests':sum(r['recurrence']=='RECURRING_TASK' for r in items),'potential_repeat_requests':sum(r['recurrence']=='POTENTIAL_REPEAT' for r in items),'recent_day_only':sum(r['freshness']=='RECENT_DAY_ONLY' for r in items),'direct_open':sum(r['access']=='DIRECT_OPEN' for r in items),'verified_independent_buyers':0,'payment':'UNKNOWN','counter_evidence':'NOT_ASSESSED','evidence_status':'NEEDS_REVIEW','actionability':'UNKNOWN','decision':'HOLD','records':items})
    candidates.sort(key=lambda c:(-c['recurring_requests'],-c['budget_requests'],-c['observations'],c['key']))
    return {'as_of':snapshot['as_of'],'mode':'DISCOVERY_REVIEW_ONLY','sampling':'purposive, not representative; AI-assisted source selection and semantic grouping','arms':{k:{**v,'selected':selected[k]} for k,v in arms.items()},'sources':dict(sources),'domains':dict(domains),'observations':len(rows),'candidates':candidates,'review_queue':[c['key'] for c in candidates[:20]],'official_top20':None,'verified_opportunities':0}


def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('snapshot',type=Path); p.add_argument('output',type=Path); args=p.parse_args()
    result=build(json.loads(args.snapshot.read_text()));
    with args.output.open('x',encoding='utf-8') as f: json.dump(result,f,ensure_ascii=False,indent=2)
    print(json.dumps({k:v for k,v in result.items() if k!='candidates'},ensure_ascii=False,indent=2))


if __name__=='__main__': main()
