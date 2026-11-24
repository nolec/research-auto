"""Bounded cross-domain fresh intake and unchanged V2 replay. No official promotion."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from src.extraction import integrated_discovery_pilot as pilot
from src.extraction import codex_cli_diagnostic as cli
from src.source_spike.adapters.stackexchange_http import HttpStackExchangeTransport, StackExchangeTransportFailure
from src.source_spike.adapters.ted_http import HttpTedTransport, TedTransportFailure
from src.source_spike.adapters.ted import _strings
from src.source_spike.fresh_ted_economic_intake import FIELDS, date_only
from src.source_spike.stackexchange_html import html_body_to_text, html_title_to_text
from src.source_spike.ted_contact_redaction import residual_contact_count, select_language

ROOT = pilot.ROOT
RUN = pilot.RUN_ROOT / 'fresh-integrated-discovery-20261124'
PROTOCOL = ROOT / 'docs/fresh-integrated-discovery-protocol-20261124.md'
FILTER = ROOT / 'config/source-spike/stackexchange-filter.json'
SITES = ('graphicdesign', 'video', 'photo', 'writing', 'webapps', 'workplace')
CPV = ('7934', '7953', '7982', '8042')
START, END = '2026-08-26', '2026-11-23'
ARM_CAP, PAGE_CAP, TARGET = 10, 50, 100
UNSAFE = re.compile(r'\b(?:exploit\w*|vulnerabilit\w*|hack\w*|malware|ransomware|credential\w*|password\w*|'
                    r'bypass\w*|private key|token leak|phishing|weapon\w*|ammunition|military|surveillance|'
                    r'attack\w*|pathogen\w*|virus\w*|biolog\w*|biohazard\w*|laborator\w*|medical|patient\w*|'
                    r'clinical|hospital|health record|personal data|social security|bank account|credit card)\b', re.I)


def digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def canonical(url):
    if not isinstance(url, str):
        return None
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        return None
    host = parsed.hostname.removeprefix('www.')
    path = parsed.path.rstrip('/')
    if host.endswith('.stackexchange.com') or host in ('superuser.com', 'stackoverflow.com', 'askubuntu.com'):
        match = re.match(r'^/questions/(\d+)(?:/|$)', path)
        if match:
            path = '/questions/' + match.group(1)
    return host, path


def norm(text):
    return ' '.join(text.casefold().split())


@dataclass
class Selection:
    old_ids: set = field(default_factory=set)
    old_urls: set = field(default_factory=set)
    old_procedures: set = field(default_factory=set)
    old_texts: set = field(default_factory=set)
    seen_ids: set = field(default_factory=set)
    seen_urls: set = field(default_factory=set)
    seen_procedures: set = field(default_factory=set)
    seen_excerpts: set = field(default_factory=set)
    owners: Counter = field(default_factory=Counter)

    def duplicate(self, key, url, excerpt, procedure=None):
        normalized = norm(excerpt)
        return (key in self.old_ids or key in self.seen_ids or canonical(url) in self.old_urls or
                canonical(url) in self.seen_urls or (procedure is not None and
                (procedure in self.old_procedures or procedure in self.seen_procedures)) or
                normalized in self.seen_excerpts or any(normalized in text for text in self.old_texts))

    def retain(self, key, url, excerpt, owners, procedure=None):
        self.seen_ids.add(key)
        self.seen_urls.add(canonical(url))
        self.seen_excerpts.add(norm(excerpt))
        self.owners.update(owners)
        if procedure:
            self.seen_procedures.add(procedure)


def history():
    """Read only retained provenance and dedup fingerprints; do not emit old texts."""
    state = Selection()
    files = set((ROOT / 'artifacts/source-spike').glob('**/collection-result.json'))
    audit = pilot.RUN_ROOT
    for name in ('result.json', 'snapshot.json', 'input.json'):
        files.update(audit.glob(f'**/{name}'))
    files.update(audit.glob('fresh-economic-intake-*.json'))
    files.update((ROOT / 'artifacts/evidence-pilot').glob('*.json'))
    files.update((ROOT / 'configs/extraction').glob('*.json'))

    def visit(value):
        if isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            keys = [value.get(k) for k in ('document_id', 'source_id', 'id')]
            relevant = any(isinstance(k, str) and k.startswith(('stackexchange:', 'ted:')) for k in keys)
            for key in keys:
                if isinstance(key, str) and key.startswith(('stackexchange:', 'ted:')):
                    state.old_ids.add(key)
            for name in ('url', 'source_url', 'link'):
                url = canonical(value.get(name))
                if url and (url[0].endswith('.stackexchange.com') or url[0] in ('superuser.com', 'stackoverflow.com', 'askubuntu.com', 'ted.europa.eu')):
                    state.old_urls.add(url)
                    relevant = True
            if relevant:
                for name in ('summary', 'text', 'excerpt', 'problem', 'followup'):
                    text = value.get(name)
                    if isinstance(text, str) and text.strip():
                        state.old_texts.add(norm(text))
                if value.get('source') == 'ted' and isinstance(value.get('thread_id'), str):
                    state.old_procedures.add(value['thread_id'])
                for name in ('procedure-identifier', 'source_procedure_id'):
                    if isinstance(value.get(name), str):
                        state.old_procedures.add(value[name])
            for item in value.values():
                if isinstance(item, (list, dict)):
                    visit(item)

    file_hashes = {}
    for path in sorted(files):
        raw = path.read_bytes()
        visit(json.loads(raw))
        file_hashes[str(path.relative_to(ROOT))] = sha256(raw).hexdigest()
    # The prior integrated replay also has source IDs expressed as external URLs.
    old, _ = pilot.prepare()
    visit(old)
    return state, {'history_files': len(files), 'history_sha256': digest(file_hashes),
                   'historical_ids': len(state.old_ids), 'historical_urls': len(state.old_urls),
                   'historical_procedures': len(state.old_procedures)}


def safe_excerpt(title, body):
    if (not title.strip() or len(body.split()) < 5 or residual_contact_count(title + ' ' + body)
            or UNSAFE.search(title + ' ' + body)):
        return None
    return ' '.join(title.split()[:15]), ' '.join(body.split()[:25])


def record(key, url, role, published, title, excerpt, arm, **extra):
    return {'id': key, 'source': urlsplit(url).hostname, 'url': url, 'role': role,
            'kind': 'archived_summary', 'source_text_kind': 'PUBLIC_API_EXCERPT',
            'summary': title + '\n' + excerpt, 'title_excerpt': title, 'excerpt': excerpt,
            'excerpt_sha256': sha256(excerpt.encode()).hexdigest(), 'published_date': published,
            'date_precision': 'DAY', 'budget': None, 'display_status': None, 'arm': arm,
            'archive': str(RUN.relative_to(ROOT) / 'result.json'), **extra}


def select_questions(site, items, state):
    rows, rejected = [], Counter()
    for item in items[:PAGE_CAP]:
        if len(rows) == ARM_CAP:
            break
        qid, creation = item.get('question_id'), item.get('creation_date')
        owner = item.get('owner')
        owner_id = owner.get('user_id') if isinstance(owner, dict) else None
        try:
            published = datetime.fromtimestamp(creation, timezone.utc).date().isoformat() if type(creation) is int else ''
        except (ValueError, OSError, OverflowError):
            published = ''
        url = f'https://{site}.stackexchange.com/questions/{qid}'
        license_value = item.get('content_license')
        if (type(qid) is not int or qid <= 0 or type(owner_id) is not int or owner_id <= 0
                or canonical(item.get('link')) != canonical(url) or not START <= published <= END
                or license_value not in ('CC BY-SA 2.5', 'CC BY-SA 3.0', 'CC BY-SA 4.0')):
            rejected['provenance'] += 1
            continue
        title = html_title_to_text(item['title']) if isinstance(item.get('title'), str) else ''
        body = html_body_to_text(item['body']) if isinstance(item.get('body'), str) else ''
        parts = safe_excerpt(title, body)
        if not parts:
            rejected['unsafe_or_private'] += 1
            continue
        key, owner_key = f'stackexchange:{site}:{qid}', ('stackexchange', site, owner_id)
        if state.duplicate(key, url, parts[1]):
            rejected['duplicate'] += 1
            continue
        if state.owners[owner_key] >= 2:
            rejected['author_cap'] += 1
            continue
        rows.append(record(key, url, 'user', published, *parts, site, content_license=license_value))
        state.retain(key, url, parts[1], [owner_key])
    return rows, dict(rejected)


def english(value):
    if not isinstance(value, dict):
        return ''
    for key in ('eng', 'en'):
        if key in value:
            return select_language({key: value[key]})
    return ''


def select_notices(prefix, items, state):
    rows, rejected = [], Counter()
    for item in items[:PAGE_CAP]:
        if len(rows) == ARM_CAP:
            break
        nid, publication, procedure = (item.get(k) for k in ('notice-identifier', 'publication-number', 'procedure-identifier'))
        buyers = sorted({x.strip() for x in _strings(item.get('buyer-identifier')) if x.strip()})
        published = date_only(item.get('publication-date'))
        if (not all(isinstance(x, str) and re.fullmatch(r'[A-Za-z0-9-]{1,100}', x) for x in (nid, procedure))
                or not isinstance(publication, str) or not re.fullmatch(r'\d{5,8}-2026', publication)
                or not buyers or not published or not START <= published <= END
                or _strings(item.get('form-type')) != ['competition'] or _strings(item.get('notice-type')) != ['cn-standard']
                or not any(c.startswith(prefix) for c in _strings(item.get('classification-cpv')))
                or item.get('change-notice-version-identifier')):
            rejected['provenance'] += 1
            continue
        parts = safe_excerpt(english(item.get('notice-title')), english(item.get('description-proc')))
        if not parts:
            rejected['unsafe_or_private'] += 1
            continue
        key, url = f'ted:{nid}', f'https://ted.europa.eu/en/notice/-/detail/{publication}'
        if state.duplicate(key, url, parts[1], procedure):
            rejected['duplicate'] += 1
            continue
        owner_keys = [('ted', x) for x in buyers]
        if any(state.owners[x] >= 2 for x in owner_keys):
            rejected['author_cap'] += 1
            continue
        rows.append(record(key, url, 'buyer', published, *parts, prefix, display_status='COMPETITION_NOTICE',
                           source_procedure_id=procedure))
        state.retain(key, url, parts[1], owner_keys, procedure)
    return rows, dict(rejected)


def frozen_engine():
    modules = (pilot, pilot.multi, pilot.cluster, pilot.economic, pilot.gap, pilot.gap_v2, cli)
    files = [Path(m.__file__) for m in modules] + [ROOT / 'src/extraction/codex_cli_development_v2.py', PROTOCOL, FILTER, Path(__file__)]
    hashes = {str(p.relative_to(ROOT)): sha256(p.read_bytes()).hexdigest() for p in files}
    return {'model': pilot.MODEL, 'version': 2, 'file_sha256': hashes, 'freeze_sha256': digest(hashes)}


def collect(root, se, ted, state, binding):
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    claim = {'window': [START, END], 'sites': list(SITES), 'cpv': list(CPV), 'target': TARGET,
             'page_cap': PAGE_CAP, 'arm_cap': ARM_CAP, 'max_requests': len(SITES) + len(CPV), 'binding': binding}
    cli._private_create(root / 'claim.json', claim)
    records, arms, reasons = [], [], []
    for site in SITES:
        reply = se.fetch_questions(site=site, page=1, page_size=PAGE_CAP, filter_id=json.loads(FILTER.read_text())['filter_id'],
                 sort='creation', order='desc', published_after=START+'T00:00:00Z', published_before=END+'T23:59:59Z',
                 max_http_attempts=1, request_timeout_seconds=15, max_total_elapsed_seconds=15,
                 max_backoff_wait_seconds=0, max_retries=0, base_backoff_seconds=0, max_backoff_seconds=0)
        if isinstance(reply, StackExchangeTransportFailure):
            reasons.append(f'stackexchange:{reply.error_code}')
            arms.append({'source': 'stackexchange', 'arm': site, 'status': 'FAILED', 'reason': reply.error_code})
            break
        rows, rejected = select_questions(site, reply.page.items, state)
        records.extend(rows)
        arms.append({'source': 'stackexchange', 'arm': site, 'returned': len(reply.page.items), 'accepted': len(rows), 'rejected': rejected})
        print(f'Stack Exchange {site}: {len(rows)}/{ARM_CAP}', flush=True)
        if reply.page.quota_remaining <= 100 or reply.page.backoff:
            reasons.append('stackexchange:quota_or_backoff')
            break
    for prefix in CPV:
        query = f'publication-date = ({START.replace("-", "")} <> {END.replace("-", "")}) AND form-type = competition AND notice-type IN (cn-standard) AND classification-cpv = {prefix}*'
        reply = ted.fetch_notices(query=query, fields=FIELDS, page=1, page_size=PAGE_CAP, scope='ALL',
                 check_query_syntax=False, pagination_mode='PAGE_NUMBER', max_http_attempts=1,
                 request_timeout_seconds=15, deadline_seconds=15, max_response_bytes=2_000_000,
                 max_retries=0, base_backoff_seconds=0, max_backoff_seconds=0)
        if isinstance(reply, TedTransportFailure):
            reasons.append(f'ted:{reply.error_code}')
            arms.append({'source': 'ted', 'arm': prefix, 'status': 'FAILED', 'reason': reply.error_code})
            break
        rows, rejected = select_notices(prefix, reply.page.notices, state)
        records.extend(rows)
        arms.append({'source': 'ted', 'arm': prefix, 'returned': len(reply.page.notices), 'accepted': len(rows), 'rejected': rejected})
        print(f'TED {prefix}: {len(rows)}/{ARM_CAP}', flush=True)
    result = {**claim, 'status': 'COLLECTED_COMPLETE' if len(records) == TARGET else 'COLLECTED_PARTIAL' if records else 'INCOMPLETE',
              'documents': len(records), 'roles': dict(Counter(r['role'] for r in records)),
              'arms': arms, 'reasons': reasons, 'records': records, 'records_sha256': digest(records),
              'official_opportunities': 0, 'scope': 'FRESH_INTAKE_ONLY'}
    cli._private_create(root / 'result.json', result)
    return result


def analyze(root, analysis_id, resume_from=None):
    raw = (root / 'result.json').read_bytes()
    intake = json.loads(raw)
    claim = json.loads((root / 'claim.json').read_text())
    records = intake['records']
    if (intake['status'] not in ('COLLECTED_COMPLETE', 'COLLECTED_PARTIAL') or not records or
            claim['binding'] != intake['binding'] or intake['binding']['engine'] != frozen_engine() or
            intake['records_sha256'] != digest(records) or intake['documents'] != len(records) or
            len(records) > TARGET or len({r['id'] for r in records}) != len(records) or
            len({canonical(r['url']) for r in records}) != len(records)):
        raise ValueError('intake empty, altered, duplicate, or frozen engine changed')
    receipt = {'evaluation_scope': 'FRESH_OUT_OF_SAMPLE_EXPLORATION', 'sample_status': intake['status'],
               'target': TARGET, 'intake_sha256': sha256(raw).hexdigest(), 'engine': intake['binding']['engine'],
               'roles': intake['roles']}
    return pilot.execute(root / analysis_id, records, receipt, pilot._call, version=2,
                         resume_from=root / resume_from if resume_from else None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--check', action='store_true')
    action.add_argument('--collect', action='store_true')
    action.add_argument('--analyze', action='store_true')
    parser.add_argument('--analysis-id', default='analysis-01')
    parser.add_argument('--resume-from')
    args = parser.parse_args()
    for value in (args.analysis_id, args.resume_from):
        if value and not re.fullmatch(r'analysis-[A-Za-z0-9-]+', value):
            parser.error('invalid analysis id')
    if args.analyze:
        try:
            result = analyze(RUN, args.analysis_id, args.resume_from)
        except (OSError, ValueError, KeyError, TypeError) as error:
            parser.error(str(error))
        keys = ('status', 'documents', 'tasks', 'groups', 'families', 'repeated_demand_groups', 'multi_source_families',
                'official_opportunities', 'sample_status', 'stage', 'reason', 'failed_request')
        print(json.dumps({**{k: result[k] for k in keys if k in result}, 'result': str(RUN/args.analysis_id/'result.json')}, ensure_ascii=False))
        return 0 if result['status'] == 'REPLAY_COMPLETE' else 1
    state, history_receipt = history()
    binding = {'engine': frozen_engine(), **history_receipt}
    if args.check:
        print(json.dumps({'status': 'READY_OFFLINE', 'target': TARGET, 'max_requests': 10,
                          **history_receipt, 'engine_sha256': binding['engine']['freeze_sha256'], 'run_exists': RUN.exists()}))
        return 0
    if RUN.exists():
        parser.error('intake already exists; preserve it')
    result = collect(RUN, HttpStackExchangeTransport(), HttpTedTransport(), state, binding)
    print(json.dumps({k: result[k] for k in ('status', 'target', 'documents', 'roles', 'arms', 'reasons', 'official_opportunities')} |
                     {'result': str(RUN/'result.json')}, ensure_ascii=False))
    return 0 if result['documents'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
