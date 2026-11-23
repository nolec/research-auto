import importlib.util
import json
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import pytest
from src.source_spike.adapters.stackexchange_http import HttpResponse, HttpStackExchangeTransport


@pytest.mark.parametrize('quota, expected_calls, expected_count', [(999, 2, 10), (100, 1, 5)])
def test_fresh_stackexchange_intake_bounded_and_quota_safe(tmp_path, quota, expected_calls, expected_count):
    assert importlib.util.find_spec('src.source_spike.fresh_stackexchange_economic_intake') is not None
    from src.source_spike.fresh_stackexchange_economic_intake import collect
    calls = []
    def execute(request, timeout):
        query = parse_qs(urlparse(request.full_url).query)
        calls.append(query)
        tag = query['tagged'][0]
        base = 100 if tag == 'libreoffice-calc' else 0
        items = [{'question_id': base+i, 'body': f'<p>How can I format worksheet number {base+i} as a readable report?</p>',
                  'title': 'Worksheet formatting', 'content_license': 'CC BY-SA 4.0',
                  'creation_date': int(datetime(2026,11,10,tzinfo=timezone.utc).timestamp()),
                  'link': f'https://superuser.com/questions/{base+i}/worksheet',
                  'owner': {'user_id': 123456789+base+i, 'display_name':'PRIVATE_FIXTURE'}, 'tags':[tag]} for i in range(1,9)]
        if base == 0:
            items[1]['body'] = '<p>Contact someone@example.test for worksheet help.</p>'
        return HttpResponse(200,{},json.dumps({'items':items,'has_more':False,'quota_max':10000,'quota_remaining':quota}).encode())
    transport = HttpStackExchangeTransport(execute=execute)
    root = tmp_path/'run'
    result = collect(root, transport, {'stackexchange:superuser:1'}, set(), [])
    assert result['source_counts']['stackexchange'] == expected_count
    assert len(calls) == expected_calls
    assert calls[0]['tagged'] == ['microsoft-excel'] and calls[0]['pagesize'] == ['10']
    saved = (root/'result.json').read_text()
    assert 'PRIVATE_FIXTURE' not in saved and 'someone@example.test' not in saved and '123456789' not in saved
    assert all(r['content_license'] == 'CC BY-SA 4.0' for r in result['records'])
    with pytest.raises(FileExistsError):
        collect(root, transport, set(), set(), [])
    assert len(calls) == expected_calls
