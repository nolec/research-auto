"""Screen bounded public buyer-discovery snapshots without promoting them to evidence."""
import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlsplit


def job_key(record):
    url = urlsplit(record['url'])
    if url.scheme != 'https' or url.username or url.password:
        raise ValueError('Expected a public HTTPS source URL')
    if url.hostname == 'www.upwork.com':
        match = re.search(r'/freelance-jobs/apply/[^/]+_~(\d+)/?$', url.path)
        if not match:
            raise ValueError('Not an individual Upwork buyer listing')
        return 'upwork:' + match.group(1)
    if url.hostname == 'www.freelancer.com' and url.path.startswith('/projects/'):
        project_id = record.get('project_id')
        if not isinstance(project_id,str) or not project_id.isdecimal():
            raise ValueError('Freelancer project ID must be observed')
        return 'freelancer:' + project_id
    raise ValueError('Unsupported source')


def screen(spec):
    as_of = date.fromisoformat(spec['as_of'])
    cutoff = as_of - timedelta(days=90)
    arms = spec['arms']
    if not isinstance(arms,dict) or not arms or any(not isinstance(q,int) or isinstance(q,bool) or not 1<=q<=20 for q in arms.values()):
        raise ValueError('Invalid frozen per-arm caps')
    counts = Counter(); seen = set(); group = defaultdict(list); rows = []
    for r in spec['records']:
        arm = r['arm']; counts[arm] += 1
        if arm not in arms or counts[arm]>arms[arm]:
            raise ValueError('Exceeded frozen arm cap')
        key = job_key(r)
        if r['fit'] not in ('direct','adjacent','reject') or r['access'] not in ('INDEX_ONLY','DIRECT_OPEN','DIRECT_BLOCKED') or r['date_precision'] not in ('DAY','RELATIVE','UNKNOWN'):
            raise ValueError('Invalid observation classification')
        day = r.get('published_date')
        if r['date_precision']=='DAY':
            published = date.fromisoformat(day)
            freshness = 'RECENT_DAY_ONLY' if cutoff<=published<=as_of else 'OUTSIDE_WINDOW'
        else:
            if day is not None:
                raise ValueError('Do not invent an exact date from relative text')
            age_band = r.get('reported_age_band','UNKNOWN')
            if age_band not in ('UNKNOWN','CLEARLY_OLDER_THAN_90D') or (age_band=='CLEARLY_OLDER_THAN_90D' and r['date_precision']!='RELATIVE'):
                raise ValueError('Invalid relative-age annotation')
            freshness = 'OUTSIDE_WINDOW' if age_band=='CLEARLY_OLDER_THAN_90D' else 'UNKNOWN'
        prior = key in seen; seen.add(key)
        budget = r.get('budget')
        if budget is not None:
            lo,hi = budget['low'],budget['high']
            if not all(type(v) in (int,float) and 0<v<1e9 for v in (lo,hi)) or lo>hi or budget['currency'] not in ('USD','EUR','INR','KRW','CAD','AUD') or budget['unit'] not in ('fixed','hourly'):
                raise ValueError('Invalid stated budget')
        recurrence = r.get('recurrence','UNKNOWN')
        contract = r.get('contract_signal','UNKNOWN')
        family = r.get('possible_duplicate_family',key)
        if recurrence not in ('RECURRING_TASK','ONE_OFF','UNKNOWN') or contract not in ('AWARDED_DISPLAYED','HIRING_DISPLAYED','IN_PROGRESS_DISPLAYED','CLOSED','UNKNOWN') or not isinstance(family,str) or not family.strip():
            raise ValueError('Invalid recurrence, contract or overlap annotation')
        reason = 'DUPLICATE_ID' if prior else 'REJECTED_SCOPE' if r['fit']=='reject' else 'STALE_OR_FUTURE' if freshness=='OUTSIDE_WINDOW' else 'REVIEW_REQUIRED'
        row = {**r,'key':key,'freshness':freshness,'disposition':reason,'recurrence':recurrence,'contract_signal':contract,'possible_duplicate_family':family,'actual_payment':'UNKNOWN','independence':'UNKNOWN','official_recent_case':False}
        rows.append(row)
        if reason=='REVIEW_REQUIRED': group[arm].append(row)
    summary = {}
    for arm in arms:
        eligible=group[arm]; direct=[r for r in eligible if r['fit']=='direct']
        summary[arm]={'screened':counts[arm],'review_candidates':len(eligible),'direct':len(direct),'direct_description_families':len({r['possible_duplicate_family'] for r in direct}),'direct_recurring_task_families':len({r['possible_duplicate_family'] for r in direct if r['recurrence']=='RECURRING_TASK'}),'direct_contract_signal_families':len({r['possible_duplicate_family'] for r in direct if r['contract_signal'] in ('AWARDED_DISPLAYED','HIRING_DISPLAYED','IN_PROGRESS_DISPLAYED')}),'recent_day_only_direct':sum(r['freshness']=='RECENT_DAY_ONLY' for r in direct),'direct_with_budget':sum(r.get('budget') is not None for r in direct),'direct_with_confirmed_independence':0,'official_recent_cases':0,'verified_payments':0,'decision':'HOLD'}
    return {'as_of':spec['as_of'],'cutoff_day':cutoff.isoformat(),'source_mode':'SEARCH_SNAPSHOT_REVIEW_ONLY','summary':summary,'records':rows,'verified_opportunities':0,'official_top20':None}


def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('snapshot',type=Path); p.add_argument('output',type=Path); args=p.parse_args()
    spec=json.loads(args.snapshot.read_text()); result=screen(spec)
    with args.output.open('x',encoding='utf-8') as f: json.dump(result,f,ensure_ascii=False,indent=2)
    print(json.dumps(result['summary'],ensure_ascii=False,indent=2))


if __name__=='__main__': main()
