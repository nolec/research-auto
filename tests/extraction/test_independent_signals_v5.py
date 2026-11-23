import importlib.util
import json

import pytest

from src.extraction import codex_cli_diagnostic as cli


def test_independent_money_survives_problem_abstention_and_bad_evidence():
    assert importlib.util.find_spec('src.extraction.independent_signals_v5') is not None
    from src.extraction.independent_signals_v5 import normalize_signals, score_signals
    doc = {'document_id': 'test', 'text': 'Budget: $50.', 'source': 'github'}
    output = {'document_id': 'test',
              'problem_signal': {'state': 'unknown', 'quote': None},
              'money_signal': {'state': 'yes', 'quote': 'Budget: $50.', 'type': 'willingness_to_pay'},
              'usable_evidence': {'state': 'yes', 'quote': 'not in source'}}
    signals = normalize_signals(doc, output)
    assert signals['problem_signal']['state'] == 'unknown'
    assert signals['money_signal'] == {'state': 'yes', 'start': 0, 'end': 12, 'type': 'willingness_to_pay'}
    assert signals['usable_evidence']['state'] == 'invalid'
    report = score_signals([doc], [{'document_id': 'test', 'problem_signal': False,
                                  'money_signal': True, 'usable_evidence': True}], [signals])
    assert report['metrics']['money_signal']['recall'] == 1
    assert report['metrics']['usable_evidence']['fn'] == 1
    assert report['invalid_count'] == 1


def test_event_parser_keeps_tool_rejection_with_new_contract():
    doc = {'document_id': 'test'}
    events = '\n'.join(json.dumps(e) for e in [
        {'type': 'thread.started'}, {'type': 'turn.started'},
        {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': '{"document_id":"test"}'}},
        {'type': 'turn.completed'},
    ])
    assert cli.parse_cli_events(events, doc, semantic_validator=lambda d, o: None) == doc
    with pytest.raises(cli.CliContractError, match='CLI_TOOL_EVENT'):
        cli.parse_cli_events(events + '\n{"type":"item.started","item":{"type":"command_execution"}}',
                             doc, semantic_validator=lambda d, o: None)
