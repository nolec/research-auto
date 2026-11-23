"""One-shot, bounded public TED intake for economic-signal evaluation."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import re

from src.source_spike.adapters.ted import _strings
from src.source_spike.adapters.ted_http import HttpTedTransport, TedTransportFailure
from src.source_spike.ted_contact_redaction import select_language, residual_contact_count
from src.extraction.codex_cli_diagnostic import _private_create

ROOT = Path(__file__).resolve().parents[2]
RUN_ROOT = ROOT / 'artifacts/extraction/calibration/audit-local/fresh-economic-ted-intake-20261123'
PROTOCOL = ROOT / 'docs/economic-signal-fresh-ted-intake-20261123.md'
ARMS = (('competition', 'cn-standard'), ('result', 'can-standard'))
FIELDS = ('publication-number', 'notice-identifier', 'procedure-identifier', 'buyer-identifier',
          'publication-date', 'notice-type', 'form-type', 'classification-cpv', 'notice-title',
          'description-proc', 'change-notice-version-identifier', 'winner-selection-status',
          'contract-conclusion-date')


def date_only(value):
    if not isinstance(value, str):
        return None
    try:
        if re.fullmatch(r'\d{8}', value):
            return datetime.strptime(value, '%Y%m%d').date().isoformat()
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}(?:[+-]\d{2}:\d{2})?', value):
            return datetime.strptime(value[:10], '%Y-%m-%d').date().isoformat()
    except ValueError:
        pass
    return None


def collect(root, transport, old_ids, old_procedures, old_texts):
    root.mkdir(mode=0o700, exist_ok=False)
    queries = [f'publication-date = (20260825 <> 20261122) AND form-type = {form} AND notice-type IN ({kind}) AND classification-cpv = 3019*' for form, kind in ARMS]
    _private_create(root / 'claim.json', {'queries': queries, 'fields': FIELDS, 'max_requests': 2,
                    'protocol_sha256': sha256(PROTOCOL.read_bytes()).hexdigest(), 'implementation_sha256': sha256(Path(__file__).read_bytes()).hexdigest()})
    records, arms = [], []
    seen_ids, seen_procs = set(old_ids), set(old_procedures)
    seen_excerpts = set()
    buyer_counts = Counter()
    failure = None
    for (form, kind), query in zip(ARMS, queries, strict=True):
        response = transport.fetch_notices(query=query, fields=FIELDS, page=1, page_size=10,
            scope='ALL', check_query_syntax=False, pagination_mode='PAGE_NUMBER', max_http_attempts=1,
            request_timeout_seconds=10, deadline_seconds=10, max_response_bytes=2_000_000,
            max_retries=0, base_backoff_seconds=0, max_backoff_seconds=0)
        if isinstance(response, TedTransportFailure):
            failure = response.error_code
            arms.append({'form_type': form, 'status': 'FAILED', 'error': failure})
            break
        accepted = 0
        rejected = Counter()
        for item in response.page.notices[:10]:
            if accepted >= 5:
                break
            notice, publication, procedure = (item.get(k) for k in ('notice-identifier', 'publication-number', 'procedure-identifier'))
            buyers = sorted(set(x.strip() for x in _strings(item.get('buyer-identifier')) if x.strip()))
            date = date_only(item.get('publication-date'))
            if (not all(isinstance(x, str) and re.fullmatch(r'[A-Za-z0-9-]{1,100}', x) for x in (notice, procedure))
                or not isinstance(publication, str) or not re.fullmatch(r'\d{5,8}-2026', publication)
                or not buyers or not date or not '2026-08-25' <= date <= '2026-11-22'
                or _strings(item.get('form-type')) != [form] or _strings(item.get('notice-type')) != [kind]
                or not any(c.startswith('3019') for c in _strings(item.get('classification-cpv')))
                or item.get('change-notice-version-identifier')):
                rejected['provenance_or_scope'] += 1
                continue
            doc_id = f'ted:{notice}'
            # Buyer identifiers remain in memory and are never published.
            buyer_key = tuple(buyers)
            if doc_id in seen_ids or procedure in seen_procs or buyer_counts[buyer_key] >= 2:
                rejected['duplicate_or_buyer_cap'] += 1
                continue
            title = select_language(item.get('notice-title'))
            description = select_language(item.get('description-proc'))
            words = list(re.finditer(r'\S+', description))
            excerpt = description[:words[min(len(words), 25)-1].end()] if words else ''
            if (not title or len(words) < 5 or residual_contact_count(title + ' ' + description)
                    or re.search(r'\b(?:weapon|ammunition|military|surveillance|security guard|exploit|malware|pathogen)\b', title+' '+description, re.I)):
                rejected['privacy_or_context'] += 1
                continue
            if excerpt in seen_excerpts or any(excerpt in old for old in old_texts):
                rejected['duplicate_excerpt'] += 1
                continue
            status_codes = sorted(set(x for x in _strings(item.get('winner-selection-status')) if x in {'selec-w','clos-nw','open-nw'}))
            dates = sorted(set(x for value in _strings(item.get('contract-conclusion-date')) if (x := date_only(value))))
            records.append({'source':'ted', 'document_id':doc_id, 'source_url':f'https://ted.europa.eu/en/notice/-/detail/{publication}',
                            'published_at':date, 'date_precision':'date', 'title':title, 'excerpt':excerpt,
                            'excerpt_sha256':sha256(excerpt.encode()).hexdigest(), 'form_type':form,
                            'observed_fields':{'winner_selection_status':status_codes,'contract_conclusion_date':dates}})
            seen_ids.add(doc_id); seen_procs.add(procedure); seen_excerpts.add(excerpt)
            buyer_counts[buyer_key] += 1
            accepted += 1
        arms.append({'form_type':form, 'status':'COLLECTED', 'returned':min(len(response.page.notices),10), 'accepted':accepted, 'rejection_counts':dict(rejected)})
    result = {'status':'INCOMPLETE' if failure else 'TED_INTAKE_GOLD_PENDING', 'reason':failure,
              'target':10, 'source_counts':{'ted':len(records)}, 'arms':arms,
              'records':records, 'scope':'fresh excerpt intake only; source and gold review pending'}
    _private_create(root / 'result.json', result)
    return result


def historical():
    manifest = json.loads((ROOT / 'configs/extraction/development-baseline-v1.json').read_text())
    ids, procedures, texts = set(), set(), []
    for paths in manifest['sources'].values():
        rows = json.loads((ROOT / paths['qualified_run'] / 'collection-result.json').read_text())['items']
        for row in rows:
            ids.add(row['document_id'])
            if row.get('source') == 'ted' and row.get('thread_id'):
                procedures.add(row['thread_id'])
            texts.append(row['text'])
    return ids, procedures, texts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--check', action='store_true')
    action.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    old = historical()
    if args.check:
        print(json.dumps({'status':'READY_OFFLINE','historical_ids':len(old[0]),'run_exists':RUN_ROOT.exists(),'max_requests':2}))
        return 0
    if RUN_ROOT.exists():
        print('Run already exists; no retry.')
        return 2
    result = collect(RUN_ROOT, HttpTedTransport(), *old)
    print(json.dumps({'status':result['status'],'ted_count':result['source_counts']['ted'],'reason':result['reason'],'result':str(RUN_ROOT/'result.json')}))
    return 1 if result['status']=='INCOMPLETE' else 0


if __name__ == '__main__':
    raise SystemExit(main())
