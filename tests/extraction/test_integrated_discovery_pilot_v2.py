import json
import subprocess
import sys

import pytest

from src.extraction import integrated_discovery_pilot as pilot
from src.extraction import economic_signals_v7 as economic


def source(key, role, summary, **extra):
    return {'id': key, 'source': 'example.org', 'url': f'https://example.org/{key}',
            'kind': 'archived_summary', 'role': role, 'summary': summary, 'archive': 'fixture', **extra}


def test_followup_quote_is_accepted_only_for_literal_public_excerpt():
    rows = [source('a', 'user', 'I paid.', kind='public_excerpt', followup='Conversion still fails.')]
    output = [{'source_id': 'a', 'tasks': [{'description': 'PDF 변환 실패', 'field': 'followup',
                                           'evidence': 'Conversion still fails.'}]}]
    atoms = pilot.decompose(rows, output, version=2)
    assert atoms[0]['field'] == 'followup'
    assert atoms[0]['evidence'] == 'Conversion still fails.'
    with pytest.raises(ValueError):
        pilot.decompose(rows, output)
    with pytest.raises(ValueError):
        pilot.decompose([{**rows[0], 'kind': 'archived_summary'}], output, version=2)
    output[0]['tasks'][0]['evidence'] = 'Invented.'
    with pytest.raises(ValueError):
        pilot.decompose(rows, output, version=2)


def test_v2_preserves_narrow_groups_recovers_paid_followup_and_links_alternatives(tmp_path):
    records = [source('a', 'buyer', 'Generate and name certificates.', budget={'low': 50, 'high': 100, 'currency': 'USD'}),
               source('b', 'user', 'I paid.', kind='public_excerpt', problem='I paid.',
                      followup='Export still fails.', context='Same author reports a failed export.'),
               source('c', 'alternative', 'Bulk export and file naming.'),
               source('d', 'alternative', 'Calendar booking.')]

    def call(stage, items, prompt, schema):
        if stage == 'tasks':
            assert next(r for r in items if r['id'] == 'b')['followup'] == 'Export still fails.'
            return {'document_id': stage, 'records': [
                {'source_id': 'a', 'tasks': [{'description': '증명서 생성', 'field': 'summary', 'evidence': 'Generate'},
                                             {'description': '파일명 지정', 'field': 'summary', 'evidence': 'name certificates'}]},
                {'source_id': 'b', 'tasks': [{'description': '내보내기 실패', 'field': 'followup', 'evidence': 'Export still fails.'}]},
                {'source_id': 'c', 'tasks': [{'description': '일괄 내보내기와 파일명', 'field': 'summary', 'evidence': 'Bulk export and file naming.'}]},
                {'source_id': 'd', 'tasks': [{'description': '예약', 'field': 'summary', 'evidence': 'Calendar booking.'}]}]}
        if stage == 'groups':
            return {'document_id': stage, 'groups': [{'name': r['description'], 'members': [r['id']],
                    'delivery_mode': 'ONLINE_POSSIBLE', 'delivery_reason': '디지털 작업'} for r in items]}
        if stage == 'economics':
            return {'document_id': stage, 'rows': [{'document_id': r['id'], **{
                s: {'state': 'yes' if s == 'actual_payment' and r['id'] == 'task-003' else 'unknown',
                    'quote': 'I paid.' if s == 'actual_payment' and r['id'] == 'task-003' else None,
                    'reference': None} for s in economic.DIMENSIONS}} for r in items]}
        if stage == 'gaps':
            assert [r['id'] for r in items] == ['task-003']
            return {'document_id': stage, 'rows': [{'id': 'task-003', 'state': 'PAID_PERSISTING',
                    'problem_quote': 'I paid.', 'followup_quote': 'Export still fails.'}]}
        if stage == 'families':
            assert {r['id'] for r in items} == {'group-001', 'group-002', 'group-003'}
            return {'document_id': stage, 'families': [{'name': '문서 일괄 처리', 'members': [r['id'] for r in items],
                                                       'reason': '증명서 생성, 이름 지정, 내보내기'}]}
        assert stage == 'alternatives'
        return {'document_id': stage, 'rows': [
            {'alternative_task_id': 'task-004', 'matches': [
                {'group_id': 'group-002', 'relation': 'DIRECT_FEATURE_MATCH', 'reason': '파일명 기능'},
                {'group_id': 'group-003', 'relation': 'PARTIAL_FEATURE_MATCH', 'reason': '일괄 내보내기 기능, 실패 해결 여부 불명'}], 'reason': '기능 일치'},
            {'alternative_task_id': 'task-005', 'matches': [], 'reason': '예약은 문서 처리와 다름'}]}

    result = pilot.execute(tmp_path / 'v2', records, {}, call, version=2)
    assert result['status'] == 'REPLAY_COMPLETE'
    assert result['groups'] == 5
    assert result['repeated_demand_groups'] == 0
    assert result['paid_persisting_sources'] == 1
    assert result['paid_persisting_source_ids'] == ['b']
    assert result['public_excerpt_assessed_sources'] == 1
    assert result['linked_alternative_sources'] == 1
    assert result['unlinked_alternative_sources'] == 1
    assert result['official_opportunities'] == 0
    family = result['business_families'][0]
    assert family['demand_sources'] == 2  # a appears in two narrow groups but counts once
    assert family['buyer_sources'] == 1
    assert family['source_budget_count'] == 1
    assert family['alternative_sources'] == 1  # linked to two distinct groups but counts once
    assert family['gap_source_counts']['PAID_PERSISTING'] == 1
    assert family['decision'] == 'HOLD'
    assert family['group_ids'] == ['group-001', 'group-002', 'group-003']
    assert all(c['demand_sources'] == 1 for c in result['candidates'])
    assert all(c['verified_payments'] == 0 for c in result['candidates'])
    review = (tmp_path / 'v2' / 'review.md').read_text()
    assert '문서 일괄 처리' in review
    assert '결제 진술 후 실패 지속' in review
    assert '[b](https://example.org/b)' in review
    assert '미연결 대체 제품 출처: 1건' in review
    assert json.loads((tmp_path / 'v2' / 'result.json').read_text()) == result


def test_family_partition_and_alternative_links_reject_unknown_or_duplicate_ids():
    groups = [{'id': 'group-001'}, {'id': 'group-002'}]
    with pytest.raises(ValueError):
        pilot.project_families(groups, [{'name': 'A', 'members': ['group-001'], 'reason': 'A'}])
    with pytest.raises(ValueError):
        pilot.project_families(groups, [{'name': 'A', 'members': ['group-001', 'group-001', 'group-002'], 'reason': 'A'}])
    alternatives = [{'id': 'task-001'}]
    with pytest.raises(ValueError):
        pilot.project_alternatives(groups, alternatives, [{'alternative_task_id': 'task-001', 'matches': [
            {'group_id': 'group-999', 'relation': 'DIRECT_FEATURE_MATCH', 'reason': 'Unknown group'}], 'reason': 'match'}])
    with pytest.raises(ValueError):
        pilot.project_alternatives(groups, alternatives, [])
    with pytest.raises(ValueError):
        pilot.project_alternatives(groups, alternatives, [{'alternative_task_id': 'task-001', 'matches': [
            {'group_id': 'group-001', 'relation': 'DIRECT_FEATURE_MATCH', 'reason': 'match'},
            {'group_id': 'group-001', 'relation': 'PARTIAL_FEATURE_MATCH', 'reason': 'duplicate'}], 'reason': 'match'}])


def test_v2_check_binds_same_input_to_v1_baseline():
    completed = subprocess.run([sys.executable, '-m', 'src.extraction.integrated_discovery_pilot',
                                '--version', '2', '--check'], text=True, capture_output=True, check=True)
    receipt = json.loads(completed.stdout)
    assert receipt['status'] == 'INPUTS_VALIDATED'
    assert receipt['documents'] == 55
    assert receipt['baseline']['tasks'] == 51
    assert receipt['baseline']['groups'] == 49
    assert receipt['baseline']['paid_persisting_sources'] == 0
    assert receipt['baseline']['public_excerpt_assessed_sources'] == 11
    assert len(receipt['baseline_sha256']) == 64


def _abstentions(stage, items):
    return {'document_id': stage, 'records': [{'source_id': r['id'], 'tasks': []} for r in items]}


def test_v2_batches_independent_extraction_and_validates_all_sources(tmp_path):
    records = [source(f's{i:02d}', 'user', 'Unclear request.') for i in range(25)]
    seen = []

    def call(stage, items, prompt, schema):
        assert stage == 'tasks'
        if len(items) > 12:
            raise pilot.cli.CliContractError('CLI_TIMEOUT')
        seen.extend(r['id'] for r in items)
        return _abstentions(stage, items)

    root = tmp_path / 'batch'
    result = pilot.execute(root, records, {}, call, version=2)
    assert result['status'] == 'REPLAY_COMPLETE'
    assert result['abstained_sources'] == 25
    assert seen == [r['id'] for r in records]
    assert [len(json.loads(p.read_text())['input']) for p in sorted(root.glob('tasks-*.json'))] == [12, 12, 1]


def test_timeout_restart_reuses_only_valid_completed_requests(tmp_path):
    records = [source(f's{i:02d}', 'user', 'Unclear request.') for i in range(25)]
    prior = tmp_path / 'prior'

    def fail(stage, items, prompt, schema):
        if items[0]['id'] != 's00':
            raise pilot.cli.CliContractError('CLI_TIMEOUT')
        return _abstentions(stage, items)

    failed = pilot.execute(prior, records, {}, fail, version=2)
    assert failed['failed_request'] == 'tasks-02'
    assert failed['completed_requests'] == ['tasks-01']
    original = (prior / 'tasks-01.json').read_bytes()
    seen = []

    def recover(stage, items, prompt, schema):
        seen.extend(r['id'] for r in items)
        return _abstentions(stage, items)

    root = tmp_path / 'resume'
    result = pilot.execute(root, records, {}, recover, version=2, resume_from=prior)
    assert result['status'] == 'REPLAY_COMPLETE'
    assert seen == [r['id'] for r in records[12:]]
    assert result['reused_requests'] == ['tasks-01']
    assert (prior / 'tasks-01.json').read_bytes() == original
    assert (root / 'tasks-01.json').exists()


def test_batch_cannot_return_an_id_from_a_different_batch(tmp_path):
    records = [source(f's{i:02d}', 'user', 'Unclear request.') for i in range(25)]

    def call(stage, items, prompt, schema):
        response = _abstentions(stage, items)
        response['records'][0]['source_id'] = 's24'
        return response

    result = pilot.execute(tmp_path / 'invalid', records, {}, call, version=2)
    assert result['status'] == 'INCOMPLETE'
    assert result['failed_request'] == 'tasks-01'
    assert result['completed_requests'] == []
    assert 'candidates' not in result


def test_resume_rejects_changed_snapshot_and_tampered_receipt(tmp_path):
    records = [source(f's{i:02d}', 'user', 'Unclear request.') for i in range(13)]
    prior = tmp_path / 'prior'

    def fail(stage, items, prompt, schema):
        if items[0]['id'] == 's12':
            raise pilot.cli.CliContractError('CLI_TIMEOUT')
        return _abstentions(stage, items)

    pilot.execute(prior, records, {}, fail, version=2)
    calls = []

    def recover(stage, items, prompt, schema):
        calls.append(stage)
        return _abstentions(stage, items)

    modified = [{**records[0], 'summary': 'Different request.'}, *records[1:]]
    with pytest.raises(ValueError, match='same input'):
        pilot.execute(tmp_path / 'changed', modified, {}, recover, version=2, resume_from=prior)
    receipt = prior / 'tasks-01.json'
    receipt.write_bytes(receipt.read_bytes() + b' ')
    result = pilot.execute(tmp_path / 'tampered', records, {}, recover, version=2, resume_from=prior)
    assert result['status'] == 'INCOMPLETE'
    assert result['reason'] == 'resume receipt hash mismatch'
    assert result['completed_requests'] == []
    assert not calls
