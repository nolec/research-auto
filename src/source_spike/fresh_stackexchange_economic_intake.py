"""Bounded one-shot public Stack Exchange intake. No model inference."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from urllib.parse import urlparse

from src.source_spike.adapters.stackexchange_http import HttpStackExchangeTransport, StackExchangeTransportFailure
from src.source_spike.stackexchange_html import html_body_to_text, html_title_to_text
from src.source_spike.ted_contact_redaction import residual_contact_count
from src.source_spike.fresh_ted_economic_intake import historical
from src.extraction.codex_cli_diagnostic import _private_create

ROOT = Path(__file__).resolve().parents[2]
RUN_ROOT = ROOT / 'artifacts/extraction/calibration/audit-local/fresh-economic-stackexchange-intake-20261123'
PROTOCOL = ROOT / 'docs/economic-signal-fresh-stackexchange-intake-20261123.md'
ARMS = ('microsoft-excel', 'libreoffice-calc')
FILTER = ROOT / 'config/source-spike/stackexchange-filter.json'
WINDOW = ('2026-08-25T00:00:00Z', '2026-11-22T23:59:59Z')


def collect(root, transport, old_ids, old_thread_ids, old_texts):
    filter_id = json.loads(FILTER.read_text())['filter_id']
    root.mkdir(mode=0o700, exist_ok=False)
    _private_create(root/'claim.json', {'site':'superuser','tags':ARMS,'date_window':WINDOW,'max_requests':2,
       'protocol_sha256':sha256(PROTOCOL.read_bytes()).hexdigest(), 'filter_sha256':sha256(FILTER.read_bytes()).hexdigest(),
       'implementation_sha256':sha256(Path(__file__).read_bytes()).hexdigest()})
    records, arms = [], []
    seen_ids, seen_excerpts = set(old_ids), set()
    owners = Counter()
    reason = None
    for tag in ARMS:
        response = transport.fetch_questions(site='superuser', tagged=tag, page=1, page_size=10,
            filter_id=filter_id, sort='creation', order='desc', published_after=WINDOW[0], published_before=WINDOW[1],
            max_http_attempts=1, request_timeout_seconds=10, max_total_elapsed_seconds=10,
            max_backoff_wait_seconds=0, max_retries=0, base_backoff_seconds=0, max_backoff_seconds=0)
        if isinstance(response, StackExchangeTransportFailure):
            reason = response.error_code
            arms.append({'tag':tag,'status':'FAILED','error':reason})
            break
        accepted = 0
        rejected = Counter()
        for item in response.page.items[:10]:
            if accepted >= 5:
                break
            qid, creation = item.get('question_id'), item.get('creation_date')
            owner = item.get('owner')
            owner_id = owner.get('user_id') if isinstance(owner, dict) else None
            license_value = item.get('content_license')
            link = urlparse(item['link']) if isinstance(item.get('link'), str) else None
            try:
                published = datetime.fromtimestamp(creation, timezone.utc).isoformat().replace('+00:00','Z') if type(creation) is int else ''
            except (ValueError, OSError, OverflowError):
                published = ''
            if (type(qid) is not int or qid <= 0 or type(owner_id) is not int or owner_id <= 0
                or not isinstance(license_value,str) or license_value not in ('CC BY-SA 2.5','CC BY-SA 3.0','CC BY-SA 4.0')
                or not link or link.scheme!='https' or link.netloc!='superuser.com' or not re.match(rf'^/questions/{qid}(?:/|$)',link.path)
                or not published or not WINDOW[0] <= published <= WINDOW[1] or tag not in (item.get('tags') or [])):
                rejected['provenance_or_scope'] += 1; continue
            doc_id = f'stackexchange:superuser:{qid}'
            if doc_id in seen_ids or f'superuser:{qid}' in old_thread_ids or owners[owner_id] >= 2:
                rejected['duplicate_or_author_cap'] += 1; continue
            title = html_title_to_text(item['title']) if isinstance(item.get('title'),str) else ''
            body = html_body_to_text(item['body']) if isinstance(item.get('body'),str) else ''
            words = list(re.finditer(r'\S+', body)); excerpt = body[:words[min(len(words),25)-1].end()] if words else ''
            if (not title or len(words)<5 or residual_contact_count(title+' '+body)
                or re.search(r'\b(?:exploit|vulnerability|malware|ransomware|password|credential|bypass|private key|token leak|weapon|ammunition|pathogen|medical record)\b', title+' '+body, re.I)):
                rejected['privacy_or_context'] += 1; continue
            if excerpt in seen_excerpts or any(excerpt in old for old in old_texts):
                rejected['duplicate_excerpt'] += 1; continue
            records.append({'source':'stackexchange','document_id':doc_id,'source_url':f'https://superuser.com/questions/{qid}',
                            'published_at':published,'date_precision':'second','content_license':license_value,'title':title,
                            'excerpt':excerpt,'excerpt_sha256':sha256(excerpt.encode()).hexdigest(),'arm':tag})
            seen_ids.add(doc_id); seen_excerpts.add(excerpt); owners[owner_id] += 1; accepted += 1
        arms.append({'tag':tag,'status':'COLLECTED','returned':min(len(response.page.items),10),'accepted':accepted,
                     'quota_remaining':response.page.quota_remaining,'backoff':response.page.backoff,'rejection_counts':dict(rejected)})
        if response.page.quota_remaining <= 100 or (response.page.backoff or 0)>0:
            reason = 'QUOTA_RESERVE_OR_BACKOFF'
            break
    result = {'status':'INCOMPLETE' if reason else 'STACKEXCHANGE_INTAKE_GOLD_PENDING','reason':reason,'target':10,
              'source_counts':{'stackexchange':len(records)},'arms':arms,'records':records,
              'scope':'fresh excerpt intake only; source and gold review pending'}
    _private_create(root/'result.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--check',action='store_true'); action.add_argument('--execute',action='store_true')
    args = parser.parse_args(); old = historical()
    if args.check:
        print(json.dumps({'status':'READY_OFFLINE','historical_ids':len(old[0]),'run_exists':RUN_ROOT.exists(),'max_requests':2})); return 0
    if RUN_ROOT.exists():
        print('Run already exists; no retry.'); return 2
    result = collect(RUN_ROOT,HttpStackExchangeTransport(),*old)
    print(json.dumps({'status':result['status'],'stackexchange_count':result['source_counts']['stackexchange'],'reason':result['reason'],'result':str(RUN_ROOT/'result.json')}))
    return 1 if result['status']=='INCOMPLETE' else 0


if __name__ == '__main__':
    raise SystemExit(main())
