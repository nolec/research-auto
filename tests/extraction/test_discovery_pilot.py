import copy
import json

import pytest

from src.extraction.discovery_pilot import build, render


@pytest.fixture
def sample(tmp_path):
    sources = ['github','stackexchange','steam','ted']
    spec = {'mode':'CHATGPT_ASSISTED_EXPLORATION_NOT_PROVIDER_CALIBRATION', 'as_of':'2026-11-22T00:00:00+09:00', 'runs':{}, 'annotations':[]}
    paths = {}
    for source in sources:
        spec['runs'][source] = source
        rows = []
        for index in range(10):
            identifier = f'{source}:{index}'
            rows.append({'document_id':identifier,'source':source,'source_url':'https://example.com/'+identifier,'published_at':'2026-08-01T00:00:00Z','text':'Need software to manage licenses.','author_hash':'a','community':'test'})
            spec['annotations'].append([identifier,'procurement','license','License management','Need software','solicitation'] if source=='ted' else [identifier,'abstain',None,None,None,'none'])
        path=tmp_path/source
        path.write_text(json.dumps({'source':source,'run_id':source,'items':rows}))
        paths[source]=path
    return spec,paths


def test_discovery_artifact_cannot_promote(sample):
    result=build(*sample)
    assert result['documents']==40 and len(result['abstained'])==30
    card=result['candidates'][0]
    assert card['observations']==10 and card['distinct_author_hashes']==1
    assert card['recent_cases']==0 and card['solicitations']==10
    assert card['decision']=='HOLD' and card['actual_payment']=='UNKNOWN'
    assert result['official_top20'] is None and result['verified_opportunities']==0
    assert 'Not an independent evaluation' in render(result)


def test_reject_unbound_quote_and_missing_document(sample):
    spec,paths=sample
    wrong=copy.deepcopy(spec)
    wrong['annotations'][-1][4]='fabricated'
    with pytest.raises(ValueError,match='Quote'):
        build(wrong,paths)
    wrong=copy.deepcopy(spec)
    wrong['annotations'].pop()
    with pytest.raises(ValueError,match='exactly once'):
        build(wrong,paths)
