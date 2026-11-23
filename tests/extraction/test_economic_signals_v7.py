from src.extraction import economic_signals_v7 as v7


def fixture(form='result', dates=('2026-10-31',)):
    return {'document_id': 'ted:1', 'source': 'ted', 'title': 'Test',
            'published_at': '2026-11-01', 'excerpt': 'Supply office paper.',
            'form_type': form, 'evidence_fields': {'winner_selection_status': ['selec-w'],
            'contract_conclusion_date': list(dates)}, 'gold': 'secret'}


def answer():
    return {'document_id': 'ted:1', **{s: {'state': 'unknown', 'quote': None, 'reference': None}
                                      for s in v7.DIMENSIONS}}


def test_structured_reference_is_resolved_only_for_award():
    d = v7.project(fixture())
    a = answer()
    for s in ('contract_awarded', 'actual_payment'):
        a[s] = {'state': 'yes', 'quote': None, 'reference': 'ted_award'}
    o = v7.normalize(d, a)
    assert o['contract_awarded']['state'] == 'yes'
    assert o['contract_awarded']['evidence']['contract_conclusion_date'] == ['2026-10-31']
    assert o['actual_payment']['reason'] == 'REFERENCE_NOT_ALLOWED_FOR_DIMENSION'


def test_missing_contract_date_rejects_reference():
    a = answer()
    a['contract_awarded'] = {'state': 'yes', 'quote': None, 'reference': 'ted_award'}
    o = v7.normalize(v7.project(fixture(dates=())), a)
    assert o['contract_awarded']['reason'] == 'REFERENCE_NOT_AVAILABLE'


def test_invalid_quote_preserves_diagnostic():
    a = answer()
    a['labor_burden'] = {'state': 'yes', 'quote': 'made up', 'reference': None}
    o = v7.normalize(v7.project(fixture()), a)
    assert o['labor_burden']['reason'] == 'QUOTE_NOT_IN_EXCERPT'
    assert o['labor_burden']['submitted']['quote'] == 'made up'


def test_result_scope_does_not_establish_current_purchase_request():
    a = answer()
    a['procurement_intent'] = {'state': 'yes', 'quote': 'Supply office paper.', 'reference': None}
    o = v7.normalize(v7.project(fixture()), a)
    assert o['procurement_intent']['state'] == 'yes'
    assert o['procurement_intent']['temporal_scope'] == 'historical_result_notice'


def test_projection_does_not_include_gold():
    d = v7.project(fixture())
    assert 'secret' not in str(d)
    assert 'ted_award' in d['text']
