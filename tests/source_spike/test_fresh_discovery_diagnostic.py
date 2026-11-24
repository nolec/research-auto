import json

from src.source_spike import fresh_integrated_discovery as fresh
from src.source_spike import fresh_discovery_diagnostic as diagnostic


def test_observer_preserves_rejection_and_saves_exact_failed_response(tmp_path, monkeypatch):
    record = {'id': 'example:1', 'kind': 'archived_summary', 'role': 'user',
              'source': 'example.org', 'url': 'https://example.org/1', 'summary': 'Original source text.',
              'archive': 'fixture'}
    binding = {'engine': fresh.frozen_engine()}
    root = tmp_path / 'intake'
    root.mkdir()
    fresh.cli._private_create(root / 'claim.json', {'binding': binding})
    fresh.cli._private_create(root / 'result.json', {'status': 'COLLECTED_PARTIAL', 'records': [record],
        'records_sha256': fresh.digest([record]), 'documents': 1, 'binding': binding, 'roles': {'user': 1}})
    output = {'document_id': 'tasks', 'records': [{'source_id': 'example:1', 'tasks': [
        {'description': 'Unclear task', 'field': 'summary', 'evidence': 'Invented evidence.'}]}]}

    def fake_call(stage, items, prompt, schema):
        return output

    monkeypatch.setattr(fresh.pilot, '_call', fake_call)
    result = diagnostic.run(root, 'analysis-02')
    assert result['status'] == 'INCOMPLETE'
    assert result['reason'] == 'invalid or unsupported task evidence'
    assert result['completed_requests'] == []
    trace = json.loads((root / 'analysis-02-diagnostics' / 'request-001.json').read_text())
    assert trace['output'] == output
    assert trace['stage'] == 'tasks'
    assert trace['input'][0]['summary'] == 'Original source text.'
    assert fresh.pilot._call is fake_call
