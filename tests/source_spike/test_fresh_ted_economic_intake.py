import importlib.util
import json
from types import SimpleNamespace

import pytest
from src.source_spike.adapters.ted_http import TedTransportSuccess, TedTransportFailure, TedPage


def test_fresh_ted_intake_bounds_and_rejects_duplicate_and_contact(tmp_path):
    assert importlib.util.find_spec('src.source_spike.fresh_ted_economic_intake') is not None
    from src.source_spike.fresh_ted_economic_intake import collect

    def notice(i, form, kind, description='Supply of paper and office stationery for daily administrative use.'):
        return {'publication-number': f'{800000+i}-2026', 'notice-identifier': f'notice-{i}',
                'procedure-identifier': f'procedure-{i}', 'buyer-identifier': [f'buyer-{i}'],
                'publication-date': '20261110', 'form-type': form, 'notice-type': kind,
                'classification-cpv': ['30192000'], 'notice-title': {'eng': 'Office supplies'},
                'description-proc': {'eng': description}, 'winner-selection-status': ['selec-w'] if form=='result' else []}

    calls = []
    def fetch(**kwargs):
        calls.append(kwargs)
        is_result = 'form-type = result' in kwargs['query']
        form, kind = ('result', 'can-standard') if is_result else ('competition', 'cn-standard')
        base = 100 if is_result else 0
        items = [notice(base+i, form, kind, f'Supply requirement {base+i} for ordinary office administrative stationery.') for i in range(8)]
        if not is_result:
            items[1]['description-proc'] = {'eng': 'Contact someone@example.test for office supplies.'}
        return TedTransportSuccess(TedPage(items, len(items), 1, False, 'fixture', None), 1, 0, 100)

    result = collect(tmp_path / 'run', SimpleNamespace(fetch_notices=fetch), {'ted:notice-0'}, set(), [])
    assert result['source_counts']['ted'] == 10
    assert len(calls) == 2
    assert all(c['page_size'] == 10 and c['max_retries'] == 0 for c in calls)
    data = (tmp_path / 'run' / 'result.json').read_text()
    assert 'someone@example.test' not in data and 'buyer-' not in data
    assert 'ted:notice-0' not in data
    assert sum(r['form_type']=='result' for r in result['records']) == 5
    with pytest.raises(FileExistsError):
        collect(tmp_path / 'run', SimpleNamespace(fetch_notices=fetch), set(), set(), [])
    assert len(calls) == 2


def test_fresh_ted_intake_stops_after_transport_failure(tmp_path):
    from src.source_spike.fresh_ted_economic_intake import collect
    calls = []
    def fail(**kwargs):
        calls.append(kwargs)
        return TedTransportFailure('network_error', 1, 0, 0)
    result = collect(tmp_path / 'run', SimpleNamespace(fetch_notices=fail), set(), set(), [])
    assert len(calls) == 1
    assert result['status'] == 'INCOMPLETE'
    assert result['source_counts']['ted'] == 0
