import json

import pytest

from src.extraction import integrated_discovery_pilot as pilot
from src.extraction import economic_signals_v7 as economic


def record(key, role, text, **extra):
    return {"id": key, "source": "Example", "url": f"https://example.org/{key}",
            "kind": "archived_summary", "role": role, "summary": text,
            "archive": "fixture", **extra}


def test_intake_excludes_blocked_deduplicates_and_strips_reference_labels():
    rows, receipt = pilot.prepare()
    assert len(rows) >= 45
    assert len({r['id'] for r in rows}) == len(rows)
    assert len({r['url'] for r in rows}) == len(rows)
    assert receipt['excluded_access'] == 13
    assert all(not {'label', 'scope', 'rationale', 'problem_key', 'fit', 'resolution'} & r.keys() for r in rows)
    assert any(r['kind'] == 'public_excerpt' for r in rows)
    assert any(r['role'] == 'alternative' for r in rows)


def test_empty_task_is_explicit_abstention_but_missing_source_is_invalid():
    rows = [record('a', 'buyer', 'Merge files'), record('b', 'user', 'Unclear')]
    output = [{'source_id': 'a', 'tasks': [{'description': 'Merge files', 'field': 'summary', 'evidence': 'Merge files'}]},
              {'source_id': 'b', 'tasks': []}]
    tasks = pilot.decompose(rows, output)
    assert [t['source_id'] for t in tasks] == ['a']
    with pytest.raises(ValueError):
        pilot.decompose(rows, output[:1])
    output[0]['tasks'][0]['evidence'] = 'invented'
    with pytest.raises(ValueError):
        pilot.decompose(rows, output)


def test_integrated_run_retains_counter_and_never_promotes_budget_or_alternative(tmp_path):
    records = [record('a', 'buyer', 'Merge files for a weekly report', budget={'low': 50, 'high': 100, 'currency': 'USD'}),
               record('b', 'user', 'Merge files', kind='public_excerpt', problem='Merge files',
                      followup='The workaround worked.', context='Same author confirmed.'),
               record('c', 'alternative', 'Merge files feature'),
               record('d', 'user', 'No clear task')]

    def call(stage, items, prompt, schema):
        if stage == 'tasks':
            return {'document_id': stage, 'records': [
                {'source_id': r['id'], 'tasks': [{'description': 'Merge files', 'field': 'summary', 'evidence': 'Merge files'}] if r['id'] != 'd' else []} for r in items]}
        if stage == 'groups':
            return {'document_id': stage, 'groups': [{'name': '파일 병합', 'members': [r['id'] for r in items],
                    'delivery_mode': 'ONLINE_POSSIBLE', 'delivery_reason': '파일 처리 결과를 온라인으로 전달할 수 있음'}]}
        if stage == 'economics':
            assert set(r['id'] for r in items) == {'task-001', 'task-002'}
            return {'document_id': stage, 'rows': [{'document_id': r['id'], **{
                s: {'state': 'yes' if s == 'procurement_intent' and r['id'] == 'task-001' else 'unknown',
                    'quote': 'Merge files' if s == 'procurement_intent' and r['id'] == 'task-001' else None,
                    'reference': None} for s in economic.DIMENSIONS}} for r in items]}
        assert stage == 'gaps'
        assert [r['id'] for r in items] == ['task-002']
        return {'document_id': stage, 'rows': [{'id': 'task-002', 'state': 'RESOLVED',
                                                'problem_quote': 'Merge files', 'followup_quote': 'worked.'}]}

    root = tmp_path / 'run'
    result = pilot.execute(root, records, {}, call)
    assert result['status'] == 'REPLAY_COMPLETE'
    assert result['official_opportunities'] == 0
    assert result['abstained_sources'] == 1
    assert len(result['candidates']) == 1
    card = result['candidates'][0]
    assert card['buyer_sources'] == 1
    assert card['demand_sources'] == 2
    assert card['alternative_sources'] == 1
    assert card['source_budget_count'] == 1
    assert card['verified_payments'] == 0
    assert card['verified_independent_buyers'] == 0
    assert card['gap_outcomes'] == {'RESOLVED': 1, 'NOT_ASSESSED': 1}
    assert card['decision'] == 'HOLD'
    assert card['delivery_hypothesis']['mode'] == 'ONLINE_POSSIBLE'
    assert card['online_founder_fit'] == 'UNKNOWN'
    assert json.loads((root / 'result.json').read_text()) == result
    review = (root / 'review.md').read_text()
    assert '파일 병합' in review
    assert 'USD 50–100' in review
    assert '해결 확인: 1' in review
    assert '독립 검증된 결제: 0' in review
    assert '온라인 제공 가능성 (가설)' in review
    assert 'prompt_sha256' in json.loads((root / 'tasks.json').read_text())


def test_invalid_partition_stops_before_candidate_generation(tmp_path):
    rows = [record('a', 'buyer', 'Merge files')]

    def call(stage, items, prompt, schema):
        if stage == 'tasks':
            return {'document_id': stage, 'records': [{'source_id': 'a', 'tasks': [
                {'description': 'Merge files', 'field': 'summary', 'evidence': 'Merge files'}]}]}
        return {'document_id': stage, 'groups': []}

    result = pilot.execute(tmp_path / 'run', rows, {}, call)
    assert result['status'] == 'INCOMPLETE'
    assert result['stage'] == 'groups'
    assert result['official_opportunities'] == 0
    assert not result.get('candidates')
