import importlib.util
import json

import pytest

from src.extraction import codex_cli_diagnostic as cli
from src.extraction.development_slice import DevelopmentInference, DevelopmentGoldSidecar


@pytest.fixture
def sample():
    documents = tuple({'document_id': f'fixture:{i}', 'source': 'github',
                       'title': 'Synthetic', 'text': 'I cannot export.',
                       'published_at': '2026-01-01T00:00:00Z',
                       'source_url': 'https://example.test'} for i in range(40))
    labels = tuple({'document_id': doc['document_id'], 'problem_signal': True,
                    'money_signal': False, 'money_signal_type': None,
                    'usable_evidence': True, 'noise': False} for doc in documents)
    inference = DevelopmentInference(documents, {'selected_count': 40,
        'inference_corpus_sha256': cli._digest(documents), 'source_spike_reserved_emitted': 0})
    gold = DevelopmentGoldSidecar(labels, {'selected_count': 40,
        'gold_sidecar_sha256': cli._digest(labels)})
    return inference, gold


def test_new_run_stops_on_failure_without_overwriting(tmp_path, sample):
    spec = importlib.util.find_spec('src.extraction.codex_cli_development_v2')
    assert spec is not None, 'new versioned runner required'
    from src.extraction.codex_cli_development_v2 import run_batch
    inference, gold = sample
    attempts = []

    def fail(document, timeout):
        attempts.append(document['document_id'])
        raise cli.CliContractError('CLI_NONZERO_EXIT')

    run = tmp_path / 'new-run'
    result = run_batch(run, inference, gold, fail, {}, {})
    assert result['status'] == 'INCOMPLETE'
    assert result['attempted'] == 1
    assert result['not_attempted'] == 39
    assert len(attempts) == 1

    def abstain(document, timeout):
        value = {key: None for key in json.loads(cli.SCHEMA_PATH.read_text())['required']}
        value.update(document_id=document['document_id'], abstention_reason='fixture')
        return value, {'input_tokens': 1, 'output_tokens': 1}

    complete = run_batch(tmp_path / 'complete', inference, gold, abstain, {}, {},
                         run_id='codex-cli-gpt-6.2-sol-development-v3')
    assert complete['run_id'] == 'codex-cli-gpt-6.2-sol-development-v3'
    assert json.loads((tmp_path / 'complete' / 'claim.json').read_text())['run_id'] == complete['run_id']
    assert complete['status'] == 'MEASURED'
    assert complete['attempted'] == 40
    assert complete['evaluation']['abstention_count'] == 40
    assert complete['evaluation']['metrics']['problem_signal']['fn'] == 40
    saved = (run / 'result.json').read_bytes()
    assert json.loads(saved)['status'] == 'INCOMPLETE'
    with pytest.raises(FileExistsError):
        run_batch(run, inference, gold, fail, {}, {})
    assert (run / 'result.json').read_bytes() == saved
    assert len(attempts) == 1


@pytest.mark.parametrize('failure', ['schema', 'local_schema', 'tool'])
def test_v4_counts_invalid_output_but_stops_on_tool_events(tmp_path, sample, failure):
    from src.extraction.codex_cli_development_v2 import run_batch
    inference, gold = sample

    def call(document, timeout):
        if document['document_id'] == 'fixture:7':
            if failure == 'tool':
                raise cli.CliContractError('CLI_TOOL_EVENT')
            if failure == 'schema':
                raise cli.CliContractError('CLI_OUTPUT_SCHEMA_INVALID', validation={
                    'stage': 'semantic', 'field': 'evidence_end', 'rule': 'SPAN_BOUNDS'})
            return {'document_id': document['document_id']}, {}
        output = {key: None for key in json.loads(cli.SCHEMA_PATH.read_text())['required']}
        output.update(document_id=document['document_id'], abstention_reason='fixture')
        return output, {}

    root = tmp_path / 'v4'
    result = run_batch(root, inference, gold, call, {}, {},
                       run_id='codex-cli-gpt-6.2-sol-development-v4', continue_invalid=True)
    rows = json.loads((root / 'progress.json').read_text())['rows']
    if failure == 'tool':
        assert result['status'] == 'INCOMPLETE'
        assert result['attempted'] == 8
        assert rows[7]['state'] == 'failed'
        assert 'evaluation' not in result
    else:
        assert result['status'] == 'MEASURED'
        assert result['attempted'] == 40
        assert result['valid_outputs'] == 39
        assert result['evaluation']['invalid_count'] == 1
        assert result['evaluation']['abstention_count'] == 39
        assert result['evaluation']['metrics']['problem_signal']['fn'] == 40
        assert result['output_hash_scope'] == 'evaluation_projection_with_invalid_markers'
        assert rows[7]['state'] == 'invalid'
        if failure == 'schema':
            assert rows[7]['validation']['field'] == 'evidence_end'

