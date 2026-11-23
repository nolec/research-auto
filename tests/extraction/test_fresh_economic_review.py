import hashlib
import importlib.util
import json

import pytest


def test_review_snapshot_is_prediction_free_and_deduplicated(tmp_path):
    assert importlib.util.find_spec('src.extraction.fresh_economic_review') is not None
    from src.extraction.fresh_economic_review import build_snapshot, render
    text='A buyer needs ordinary office supplies.'
    row={'source':'ted','document_id':'ted:fixture','source_url':'https://ted.europa.eu/en/notice/-/detail/123456-2026',
         'published_at':'2026-11-10','title':'<script>not executable</script>', 'excerpt':text,
         'excerpt_sha256':hashlib.sha256(text.encode()).hexdigest(), 'form_type':'result',
         'observed_fields':{'winner_selection_status':['selec-w'],'contract_conclusion_date':['2026-11-09']},
         'prediction':'DONT_INCLUDE'}
    source=tmp_path/'source.json'; source.write_text(json.dumps({'status':'TED_INTAKE_GOLD_PENDING','records':[row]}))
    snapshot=build_snapshot([source],{'ted':1},set(),[])
    assert len(snapshot['records'])==1 and 'prediction' not in snapshot['records'][0]
    assert 'DONT_INCLUDE' not in render(snapshot,'a'*64)
    assert '<script>not executable</script>' not in render(snapshot,'a'*64)
    assert snapshot['records'][0]['evidence_fields']['winner_selection_status']==['selec-w']
    with pytest.raises(ValueError): build_snapshot([source,source],{'ted':2},set(),[])
    with pytest.raises(ValueError): build_snapshot([source],{'ted':1},{'ted:fixture'},[])
