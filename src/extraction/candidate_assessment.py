"""Apply PRD evidence and actionability gates to a saved V2 discovery run.

Model signals are shown as leads. Optional source-bound human evidence can
satisfy a gate. This produces a review queue, separate from official promotion.
"""

import argparse
from collections import Counter, defaultdict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from pathlib import Path
import re

from src.contracts.validation import validate_contract
from src.extraction import opportunity_slice as rules
from src.extraction.economic_signals_v7 import DIMENSIONS
from src.source_spike.fresh_integrated_discovery import canonical, digest


MIN_SOURCE_LINKS = 3
MAX_INITIAL_COST_KRW = 500_000
_EVIDENCE_SCHEMA = json.loads((Path(__file__).resolve().parents[2] / 'schemas/evidence.schema.json').read_text())


def _unit(record):
    procedure = record.get('source_procedure_id')
    return f"{record['url'].split('/')[2]}:{procedure}" if procedure else canonical(record['url'])


def _recent(record, as_of):
    published = date.fromisoformat(record['published_date'])
    return as_of - timedelta(days=89) <= published <= as_of


def _candidate_sources(candidate, records):
    sources, demand, models, gaps = {}, {}, defaultdict(set), defaultdict(set)
    for ref in candidate['references']:
        record = records[ref['source_id']]
        field, quote = ref['evidence_field'], ref['evidence']
        if (any(ref[k] != record[k] for k in ('url', 'role', 'kind', 'published_date'))
                or field not in ('summary', 'followup') or not quote.strip() or quote not in record.get(field, '')):
            raise ValueError(f"candidate reference mismatch: {record['id']}")
        sources[record['id']] = record
        if record['role'] != 'alternative':
            unit = _unit(record)
            demand.setdefault(unit, record)
            for key in DIMENSIONS:
                if ref['economic_signals'].get(key, {}).get('state') == 'yes':
                    models[key].add(unit)
            gaps[ref['gap']].add(unit)
    for ref in candidate.get('alternative_links', []):
        record = records[ref['source_id']]
        if record['role'] != 'alternative' or record['url'] != ref['url']:
            raise ValueError(f"alternative reference mismatch: {record['id']}")
        sources[record['id']] = record
    return sources, demand, {k: len(v) for k, v in models.items()}, {k: len(v) for k, v in gaps.items()}


def _reviewed_evidence(review, sources):
    by_kind, identities, seen = defaultdict(list), {}, set()
    for row in review.get('evidence', []):
        validate_contract(row, _EVIDENCE_SCHEMA)
        record = sources.get(row['document_id'])
        evidence_id = row['evidence_id']
        enriched = (record or {}).get('source_evidence', {})
        texts = [((record or {}).get(k) or '') for k in ('summary', 'followup')]
        texts += [section['text'] for section in enriched.get('sections', [])]
        if (record is None or row['source_url'] != record['url']
                or row['published_at'][:10] != record['published_date'] or evidence_id in seen
                or not any(row['quote'] in text and row['quote'].strip() for text in texts)):
            raise ValueError(f'review evidence has no matching source quote: {evidence_id}')
        if record['role'] == 'alternative' and row['kind'] in ('problem', 'loss', 'money', 'willingness_to_pay', 'solution_gap'):
            raise ValueError(f'alternative alone cannot support buyer evidence: {evidence_id}')
        identity = (row['author_hash'], row['evidence_group_id'])
        if identities.setdefault(record['id'], identity) != identity:
            raise ValueError(f"inconsistent review evidence identity: {record['id']}")
        seen.add(evidence_id)
        by_kind[row['kind']].append(row)
    return by_kind


def _by_unit(rows, sources):
    distinct = {}
    for row in rows:
        distinct.setdefault(_unit(sources[row['document_id']]), row)
    return list(distinct.values())


def _estimates(sources):
    estimates = {}
    for record in sources.values():
        estimate = record.get('source_evidence', {}).get('estimate')
        if estimate is None:
            continue
        try:
            amount = Decimal(estimate['amount'])
        except (InvalidOperation, KeyError, TypeError) as error:
            raise ValueError('invalid procurement estimate') from error
        if (record['role'] != 'buyer' or estimate.get('url') != record['url']
                or estimate.get('stage') != 'PROCUREMENT_ESTIMATE'
                or not amount.is_finite() or amount <= 0 or not re.fullmatch(r'[A-Z]{3}', estimate.get('currency', ''))):
            raise ValueError('invalid procurement estimate')
        estimates.setdefault(_unit(record), {'source_id': record['id'], **estimate})
    return list(estimates.values())


def _execution(checks, reviewed, hypothesis):
    scope = checks.get('scope', '')
    online, solo = checks.get('online'), checks.get('solo')
    cost = checks.get('initial_cost_krw')
    blocker = checks.get('blocker', 'UNKNOWN')
    if (not isinstance(scope, str) or any(x is not None and type(x) is not bool for x in (online, solo))
            or (cost is not None and (type(cost) is not int or cost < 0))
            or blocker not in ('UNKNOWN', 'CLEAR', 'BLOCKER') or (blocker == 'CLEAR' and reviewed['blocker'])):
        raise ValueError('invalid execution review')
    blocked = blocker == 'BLOCKER' or bool(reviewed['blocker'])
    fail_fit = online is False or solo is False or (cost is not None and cost > MAX_INITIAL_COST_KRW)
    fit = ('FAIL' if fail_fit else 'PASS' if online and solo and cost is not None and scope.strip()
           and reviewed['customer_channel'] else 'UNKNOWN')
    fields = {'actor': bool(reviewed['problem']), 'scope': bool(scope.strip()),
              'customer_channel': bool(reviewed['customer_channel']), 'blocker_review': blocker == 'CLEAR',
              'online': online is not None, 'solo': solo is not None, 'initial_cost_krw': cost is not None}
    return {'delivery_hypothesis': hypothesis, 'reviewed_scope': scope or None, 'customer_channel': fields['customer_channel'],
            'blocked': blocked, 'blocker_review': blocker, 'online': online, 'solo': solo, 'initial_cost_krw': cost,
            'maximum_cost_krw': MAX_INITIAL_COST_KRW, 'fit': fit,
            'missing': [key for key, supplied in fields.items() if not supplied]}


def assess_candidate(candidate, records, as_of, review=None):
    sources, demand, model_signals, model_gaps = _candidate_sources(candidate, records)
    review = review or {}
    checks = review.get('checks', {})
    reviewed = _reviewed_evidence(review, sources)
    counter = checks.get('counter', 'UNKNOWN')
    if counter not in ('UNKNOWN', 'CLEAR', 'CRITICAL') or (counter == 'CRITICAL' and not reviewed['counter']):
        raise ValueError('invalid counter-evidence review')

    recent = sum(_recent(record, as_of) for record in demand.values())
    problems = _by_unit(reviewed['problem'], sources)
    reviewed_recent = sum(_recent(sources[row['document_id']], as_of) for row in problems)
    authors = len({row['author_hash'] for row in problems}) if problems else None
    groups = rules._conservative_group_count([{'evidence': row} for row in problems]) if problems else None
    links = len({canonical(row['source_url']) for row in problems})
    money = len(_by_unit(reviewed['money'] + reviewed['willingness_to_pay'], sources))
    loss = len(_by_unit(reviewed['loss'], sources))
    gap_count = len(_by_unit(reviewed['solution_gap'], sources))
    thresholds = ((authors or 0, rules.MIN_INDEPENDENT_AUTHORS, 'independent_authors'),
                  (groups or 0, rules.MIN_INDEPENDENT_GROUPS, 'independent_groups'),
                  (reviewed_recent, rules.MIN_RECENT_CASES, 'reviewed_recent_cases'),
                  (links, MIN_SOURCE_LINKS, 'reviewed_source_links'),
                  (loss, rules.MIN_LOSS_OBSERVATIONS, 'reviewed_loss'),
                  (money, rules.MIN_MONEY_OBSERVATIONS, 'reviewed_money'))
    evidence_missing = [label for value, minimum, label in thresholds if value < minimum]
    if counter == 'UNKNOWN':
        evidence_missing.append('counter_evidence_review')
    if counter == 'CRITICAL':
        evidence_status = 'CONFLICTING_EVIDENCE'
    elif recent < rules.MIN_RECENT_CASES:
        evidence_status = 'INSUFFICIENT_EVIDENCE'
    else:
        evidence_status = 'NEEDS_REVIEW' if evidence_missing else 'EVIDENCE_BACKED'

    execution = _execution(checks, reviewed, candidate['delivery_hypothesis'])
    actionability_missing = [key for key in execution['missing'] if key in ('actor', 'scope', 'customer_channel', 'blocker_review')]
    if not reviewed['alternative']:
        actionability_missing.append('observed_current_solution')
    if gap_count < rules.MIN_SOLUTION_GAPS:
        actionability_missing.append('reviewed_solution_gaps')
    actionability = 'NOT_ACTIONABLE' if execution['blocked'] else 'UNKNOWN' if actionability_missing else 'ACTIONABLE'
    reject = evidence_status == 'CONFLICTING_EVIDENCE' or actionability == 'NOT_ACTIONABLE' or execution['fit'] == 'FAIL'
    eligible = evidence_status == 'EVIDENCE_BACKED' and actionability == 'ACTIONABLE' and execution['fit'] == 'PASS'
    return {'id': candidate['id'], 'name': candidate['name'], 'decision': 'REJECT' if reject else 'REVIEW' if eligible else 'HOLD',
            'evidence_status': evidence_status, 'evidence_missing': evidence_missing, 'counter_evidence': counter,
            'actionability': actionability, 'actionability_missing': actionability_missing, 'online_founder_fit': execution['fit'],
            'recurrence': {'source_count': len(demand), 'recent_source_count': recent,
                           'reviewed_recent_case_count': reviewed_recent, 'verified_independent_author_count': authors,
                           'verified_independent_group_count': groups, 'minimum_recent_cases': rules.MIN_RECENT_CASES},
            'economics': {'verified_money_count': money, 'verified_loss_count': loss,
                          'model_signal_counts': model_signals, 'public_procurement_estimates': _estimates(sources)},
            'solution': {'verified_current_solution_count': len(_by_unit(reviewed['alternative'], sources)),
                         'verified_gap_count': gap_count, 'minimum_gap_count': rules.MIN_SOLUTION_GAPS,
                         'model_gap_outcomes': model_gaps}, 'execution': execution,
            'references': candidate['references'], 'reviewed_evidence': review.get('evidence', []),
            'source_details': {key: row['source_evidence'] for key, row in sources.items() if 'source_evidence' in row}}


def _load(path):
    raw = path.read_bytes()
    return json.loads(raw), sha256(raw).hexdigest()


def assess_run(intake_path, analysis_path, *, enrichment_path=None, review_path=None):
    intake, intake_hash = _load(intake_path)
    analysis, analysis_hash = _load(analysis_path)
    records = {row['id']: row for row in intake['records']}
    if (len(records) != intake['documents'] or digest(intake['records']) != intake['records_sha256']
            or analysis['intake_sha256'] != intake_hash or analysis['documents'] != len(records)
            or analysis['status'] != 'REPLAY_COMPLETE'):
        raise ValueError('intake or analysis binding mismatch')
    input_hashes = {'intake': intake_hash, 'analysis': analysis_hash}
    if enrichment_path:
        enrichment, input_hashes['enrichment'] = _load(enrichment_path)
        before, after = enrichment['baseline'], enrichment['enriched']
        if (any(enrichment['input_sha256'][key] != value for key, value in (('intake', intake_hash), ('analysis', analysis_hash)))
                or len({row['id'] for row in before}) != len(before)):
            raise ValueError('enrichment binding mismatch')
        for old, new in zip(before, after, strict=True):
            if records.get(old['id']) != old or any(new.get(k) != v for k, v in old.items() if k != 'summary'):
                raise ValueError('enrichment changed source identity')
            records[old['id']] = {**old, 'source_evidence': new['source_evidence']}
    reviews, reviewer = {}, None
    if review_path:
        review, input_hashes['review'] = _load(review_path)
        reviewer = review['reviewer']
        if review['analysis_sha256'] != analysis_hash or not isinstance(reviewer, str) or not reviewer.strip():
            raise ValueError('review binding or reviewer mismatch')
        reviews = review['candidates']
    ids = {row['id'] for row in analysis['candidates']}
    if len(ids) != len(analysis['candidates']) or set(reviews) - ids:
        raise ValueError('duplicate candidate or review references unknown candidate')
    as_of = date.fromisoformat(intake['window'][-1])
    candidates = [assess_candidate(row, records, as_of, reviews.get(row['id'])) for row in analysis['candidates']]
    return {'status': 'REVIEW_QUEUE', 'as_of': as_of.isoformat(), 'input_sha256': input_hashes,
            'documents': len(records), 'reviewer': reviewer, 'official_top20': None,
            'decision_counts': dict(Counter(row['decision'] for row in candidates)), 'candidates': candidates}


def render(report):
    lines = ['# 실제 후보 판정', '', f"기준일 {report['as_of']} · 입력 {report['documents']}건 · 후보 {len(report['candidates'])}개",
             '', '모델 신호와 계약 추정액은 참고로 표시합니다. 원문 인용과 기준별 누락 항목은 `result.json`에 있습니다.', '',
             '| 후보 | 최근 출처 | 검증 지출·손실 | 검증 대안 한계 | 근거 / 실행 / 온라인 | 판정과 이유 |',
             '| --- | ---: | ---: | ---: | --- | --- |']
    for c in report['candidates']:
        name = c['name'].replace('|', r'\|').replace('\n', ' ')
        recent = c['recurrence']['recent_source_count']
        reason = {
            'INSUFFICIENT_EVIDENCE': f'최근 출처 {recent}/{rules.MIN_RECENT_CASES}건',
            'CONFLICTING_EVIDENCE': '중요 반증 확인',
            'NEEDS_REVIEW': '근거 검토 필요',
        }.get(c['evidence_status'], '실행 조건 확인 필요' if c['decision'] == 'HOLD' else '검토 기준 충족')
        if c['actionability'] == 'NOT_ACTIONABLE':
            reason = '실행 제약 확인'
        elif c['online_founder_fit'] == 'FAIL':
            reason = '온라인·1인 납품 또는 비용 조건 미충족'
        lines.append(f"| {c['id']} {name} | {recent} | "
                     f"{c['economics']['verified_money_count']} · {c['economics']['verified_loss_count']} | "
                     f"{c['solution']['verified_gap_count']} | {c['evidence_status']} / {c['actionability']} / "
                     f"{c['online_founder_fit']} | {c['decision']} · {reason} |")
    return '\n'.join(lines) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('intake', 'analysis', 'out-dir', 'enrichment', 'review'):
        parser.add_argument(f'--{name}', type=Path, required=name in ('intake', 'analysis', 'out-dir'))
    args = parser.parse_args(argv)
    try:
        report = assess_run(args.intake, args.analysis, enrichment_path=args.enrichment, review_path=args.review)
        markdown = render(report)
        args.out_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
        (args.out_dir / 'review.md').write_text(markdown, encoding='utf-8')
        (args.out_dir / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.error(str(error))
    print(json.dumps({'candidates': len(report['candidates']), 'decisions': report['decision_counts']}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
