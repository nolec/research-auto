from datetime import date

import pytest


AS_OF = date(2026, 11, 23)


def source(index, *, recent=True):
    return {'id': f'doc-{index}', 'url': f'https://example.org/{index}', 'role': 'buyer',
            'kind': 'archived_summary', 'published_date': '2026-11-01' if recent else '2026-07-01',
            'summary': f'Buyer {index} needs reconciliation. Tried a spreadsheet and failed. '
                       'They paid for a reconciliation tool. They lost three hours. Posted an open brief.'}


def candidate(records):
    return {'id': 'g1', 'name': 'Reconciliation',
            'delivery_hypothesis': {'mode': 'ONLINE_POSSIBLE', 'reason': '파일 전달 가능'},
            'references': [{'source_id': r['id'], 'url': r['url'], 'role': r['role'],
                            'kind': r['kind'], 'published_date': r['published_date'],
                            'evidence_field': 'summary', 'evidence': r['summary'].split('.')[0],
                            'economic_signals': {'document_id': r['id'], 'actual_payment': {'state': 'yes'}},
                            'gap': 'PERSISTING'} for r in records]}


def evidence(record, kind, quote):
    return {'evidence_id': record['id'] + '-' + kind, 'document_id': record['id'],
            'source_url': record['url'], 'published_at': record['published_date'] + 'T00:00:00Z',
            'author_hash': 'author-' + record['id'], 'community': 'example',
            'evidence_group_id': 'group-' + record['id'], 'kind': kind, 'quote': quote,
            'interpretation': 'reviewed on the cited source for this task', 'confidence': 1}


def test_real_candidates_show_signals_without_upgrading_them_to_verified_evidence():
    from src.extraction import candidate_assessment as assessment

    rows = [source(1), source(2)]
    rows[0]['source_evidence'] = {'estimate': {'amount': '50', 'currency': 'EUR',
                                                'stage': 'PROCUREMENT_ESTIMATE', 'url': rows[0]['url']}}
    for row in rows:
        row['source_procedure_id'] = 'one-procedure'
    result = assessment.assess_candidate(candidate(rows), {r['id']: r for r in rows}, AS_OF)
    assert result['decision'] == 'HOLD'
    assert result['evidence_status'] == 'INSUFFICIENT_EVIDENCE'
    assert result['actionability'] == result['online_founder_fit'] == 'UNKNOWN'
    assert result['recurrence']['recent_source_count'] == 1
    assert result['recurrence']['verified_independent_author_count'] is None
    assert result['economics']['verified_money_count'] == 0
    assert result['economics']['model_signal_counts']['actual_payment'] == 1
    assert result['economics']['public_procurement_estimates'][0]['amount'] == '50'
    assert result['solution']['verified_gap_count'] == 0 and result['solution']['model_gap_outcomes'] == {'PERSISTING': 1}
    assert result['execution']['delivery_hypothesis']['mode'] == 'ONLINE_POSSIBLE'


def test_source_bound_review_can_reach_review_and_cost_gate_stays_separate():
    from src.extraction import candidate_assessment as assessment

    rows = [source(i) for i in range(10)]
    reviewed = [evidence(r, 'problem', r['summary'].split('.')[0]) for r in rows]
    for row in rows[:2]:
        reviewed += [evidence(row, 'loss', 'lost three hours'),
                     evidence(row, 'money', 'paid for a reconciliation tool'),
                     evidence(row, 'solution_gap', 'Tried a spreadsheet and failed')]
    reviewed += [evidence(rows[0], 'alternative', 'Tried a spreadsheet'),
                 evidence(rows[0], 'customer_channel', 'Posted an open brief')]
    review = {'evidence': reviewed, 'checks': {'counter': 'CLEAR', 'blocker': 'CLEAR',
             'scope': 'Reconcile two CSV exports', 'online': True, 'solo': True, 'initial_cost_krw': 500000}}
    by_id = {r['id']: r for r in rows}
    result = assessment.assess_candidate(candidate(rows), by_id, AS_OF, review)
    assert result['evidence_status'] == 'EVIDENCE_BACKED' and result['actionability'] == 'ACTIONABLE'
    assert result['online_founder_fit'] == 'PASS' and result['decision'] == 'REVIEW'
    review['checks']['initial_cost_krw'] = 500001
    over_budget = assessment.assess_candidate(candidate(rows), by_id, AS_OF, review)
    assert over_budget['actionability'] == 'ACTIONABLE' and over_budget['online_founder_fit'] == 'FAIL'
    assert over_budget['decision'] == 'REJECT'


def test_assessment_refuses_unmatched_quotes_and_losing_date_provenance():
    from src.extraction import candidate_assessment as assessment

    row = source(1)
    records = {row['id']: row}
    real = candidate([row])
    review = {'evidence': [evidence(row, 'money', 'fabricated payment')], 'checks': {}}
    with pytest.raises(ValueError, match='review evidence'):
        assessment.assess_candidate(real, records, AS_OF, review)
    real['references'][0]['published_date'] = '2026-11-02'
    with pytest.raises(ValueError, match='reference'):
        assessment.assess_candidate(real, records, AS_OF)
