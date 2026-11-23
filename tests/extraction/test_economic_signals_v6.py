import json

from src.extraction import economic_signals_v6 as v6


def record():
    return {'document_id': 'ted:1', 'source': 'ted', 'title': 'Test',
            'published_at': '2026-11-01', 'excerpt': 'Supply office paper.',
            'form_type': 'result', 'evidence_fields': {'winner_selection_status': ['selec-w'],
            'contract_conclusion_date': ['2026-10-31']}, 'gold': 'secret'}


def answer():
    return {'document_id': 'ted:1', **{s: {'state': 'unknown', 'quote': None} for s in v6.DIMENSIONS}}


def test_projection_excludes_gold_and_preserves_observed_fields():
    d = v6.project(record())
    assert 'secret' not in json.dumps(d)
    assert 'gold' not in d
    assert 'Supply office paper.' in d['text']
    assert 'winner_selection_status=selec-w' in d['text']


def test_award_evidence_cannot_be_reused_as_payment():
    d = v6.project(record())
    a = answer()
    for key in ('contract_awarded', 'actual_payment'):
        a[key] = {'state': 'yes', 'quote': 'winner_selection_status=selec-w'}
    r = v6.normalize(d, a)
    assert r['contract_awarded']['state'] == 'yes'
    assert r['actual_payment']['state'] == 'invalid'


def test_invalid_quote_is_not_unknown():
    a = answer()
    a['labor_burden'] = {'state': 'yes', 'quote': 'three hours'}
    assert v6.normalize(v6.project(record()), a)['labor_burden']['state'] == 'invalid'


def test_diagnostic_comparison_reports_differences_not_accuracy():
    d = v6.project(record())
    a = answer()
    a['contract_awarded'] = {'state': 'yes', 'quote': 'winner_selection_status=selec-w'}
    output = v6.normalize(d, a)
    result = v6.compare([output], [{'row': 1, 'yes': {'procurement_intent': 'Supply office paper.'}}])
    assert result['differences'] == [
        {'row': 1, 'dimension': 'procurement_intent', 'proposal': 'yes', 'prediction': 'unknown'},
        {'row': 1, 'dimension': 'contract_awarded', 'proposal': 'unknown', 'prediction': 'yes'}]
    assert result['scope'] == 'assisted_agreement_only'
