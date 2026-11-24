from datetime import datetime, timezone
import json
from types import SimpleNamespace

import pytest

from src.source_spike import fresh_integrated_discovery as fresh


def question(qid, *, owner=1, day='2026-11-01', title='How to format a printable label?', body='I need to format several printable labels for a project.'):
    return {'question_id': qid, 'owner': {'user_id': owner, 'display_name': 'Not retained'},
            'creation_date': int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp()),
            'content_license': 'CC BY-SA 4.0', 'link': f'https://graphicdesign.stackexchange.com/questions/{qid}/label',
            'title': title, 'body': f'<p>{body}</p>'}


def notice(nid, *, buyer='org1', procedure='procedure1', day='20261101'):
    return {'notice-identifier': nid, 'publication-number': '123456-2026', 'procedure-identifier': procedure,
            'buyer-identifier': [buyer], 'publication-date': day, 'form-type': 'competition',
            'notice-type': 'cn-standard', 'classification-cpv': ['79340000'],
            'notice-title': {'eng': 'Marketing services'}, 'description-proc': {'eng': 'The buyer requires weekly design of promotional brochures.'}}


def test_selection_rejects_old_ids_unknown_dates_contacts_and_repeated_owners():
    state = fresh.Selection(old_ids={'stackexchange:graphicdesign:1'})
    items = [question(1), question(2, day='2025-01-01'), question(3, body='Send the draft to user@example.org please.'),
             question(4), question(5, body='I need to align different headings in a label.'),
             question(6, body='I want to make a printable brochure with columns.')]
    accepted, rejected = fresh.select_questions('graphicdesign', items, state)
    assert [r['id'] for r in accepted] == ['stackexchange:graphicdesign:4', 'stackexchange:graphicdesign:5']
    assert rejected == {'duplicate': 1, 'provenance': 1, 'unsafe_or_private': 1, 'author_cap': 1}
    assert all(r['role'] == 'user' and r['published_date'] == '2026-11-01' for r in accepted)
    assert all('owner' not in r and 'Not retained' not in json.dumps(r) for r in accepted)


def test_ted_rejects_known_procedure_and_does_not_infer_payment():
    state = fresh.Selection(old_procedures={'oldproc'})
    one = notice('n1', procedure='oldproc')
    two = notice('n2', procedure='newproc')
    three = {**notice('n3', procedure='otherproc'), 'publication-number': '123457-2026', 'description-proc': {'eng': 'The organization seeks design services for several quarterly catalogues.'}}
    accepted, rejected = fresh.select_notices('7934', [one, two, three], state)
    assert [r['id'] for r in accepted] == ['ted:n2', 'ted:n3']
    assert rejected == {'duplicate': 1}
    assert all(r['role'] == 'buyer' and r['budget'] is None and r['display_status'] == 'COMPETITION_NOTICE' for r in accepted)
    assert 'org1' not in json.dumps(accepted)


def test_collection_shortfall_is_not_a_completed_100_document_sample(tmp_path):
    class SE:
        def fetch_questions(self, **kwargs):
            items = [question(4)] if kwargs['site'] == 'graphicdesign' else []
            return SimpleNamespace(page=SimpleNamespace(items=items, quota_remaining=250, backoff=None))

    class TED:
        def fetch_notices(self, **kwargs):
            return SimpleNamespace(page=SimpleNamespace(notices=[]))

    root = tmp_path / 'run'
    result = fresh.collect(root, SE(), TED(), fresh.Selection(), {'model': 'fixture'})
    assert result['status'] == 'COLLECTED_PARTIAL'
    assert result['documents'] == 1
    assert result['target'] == 100
    assert len(result['arms']) == 10
    assert result['official_opportunities'] == 0
    assert json.loads((root / 'result.json').read_text()) == result
    assert result['records'][0]['kind'] == 'archived_summary'
    assert result['records'][0]['source_text_kind'] == 'PUBLIC_API_EXCERPT'
    with pytest.raises(FileExistsError):
        fresh.collect(root, SE(), TED(), fresh.Selection(), {'model': 'fixture'})


def test_partial_sample_uses_frozen_v2_and_refuses_modified_snapshot(tmp_path, monkeypatch):
    class SE:
        def fetch_questions(self, **kwargs):
            items = [question(4)] if kwargs['site'] == 'graphicdesign' else []
            return SimpleNamespace(page=SimpleNamespace(items=items, quota_remaining=250, backoff=None))

    class TED:
        def fetch_notices(self, **kwargs):
            return SimpleNamespace(page=SimpleNamespace(notices=[]))

    root = tmp_path / 'intake'
    intake = fresh.collect(root, SE(), TED(), fresh.Selection(), {'engine': fresh.frozen_engine()})

    def call(stage, items, prompt, schema):
        assert stage == 'tasks'
        return {'document_id': stage, 'records': [{'source_id': item['id'], 'tasks': []} for item in items]}

    monkeypatch.setattr(fresh.pilot, '_call', call)
    result = fresh.analyze(root, 'analysis-01')
    assert result['status'] == 'REPLAY_COMPLETE'
    assert result['sample_status'] == 'COLLECTED_PARTIAL'
    assert result['documents'] == 1
    assert result['official_opportunities'] == 0
    # An altered archived excerpt cannot be replayed with its original digest.
    intake['records'][0]['summary'] = 'different content'
    (root / 'result.json').write_text(json.dumps(intake))
    with pytest.raises(ValueError, match='altered'):
        fresh.analyze(root, 'analysis-02')
