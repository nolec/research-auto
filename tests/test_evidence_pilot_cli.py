import hashlib
import json
import subprocess
import sys

import pytest

from src.evidence_pilot_cli import main


def fixture(tmp_path):
    quote = '<script>alert("fixture")</script> & missing notes'
    url = 'https://example.com/item?a=1&b=2'
    doc = dict(document_id='github:one', source='github', title='<script>title</script>',
               text=quote, published_at='2026-11-01', source_url=url)
    extraction = dict(document_id='github:one', observation_type='user_problem',
                      actor='editor', problem='missing notes', context='export', consequence='notes lost',
                      evidence_quote=quote, evidence_start=0, evidence_end=len(quote),
                      problem_signal=True, money_signal=False, money_signal_type=None,
                      usable_evidence=True, confidence=0.8, abstention_reason=None)
    row = dict(document=doc, extraction=extraction, source_metadata=None, source_verified=False,
               thread_id=None, event_id=None)
    manifest = dict(run_id='synthetic-run', as_of='2026-11-20T00:00:00Z',
                    candidate_id='notes-export', source='github',
                    window_start='2026-08-22T00:00:00Z', window_end='2026-11-20T00:00:00Z',
                    arms=dict(broad=dict(query='export', sampling_method='chronological', cap=20, rows=[row]),
                              focused=dict(query='notes', sampling_method='chronological', cap=20, rows=[])))
    manifest['protocol_hash'] = hashlib.sha256(json.dumps(manifest, ensure_ascii=False, sort_keys=True,
                                                          separators=(',', ':')).encode()).hexdigest()
    review = dict(protocol_hash=manifest['protocol_hash'], candidate_id=manifest['candidate_id'],
                  actor='editor', task='export', failure='notes lost', reviewer='synthetic AI',
                  review_kind='AI_PROPOSAL', decisions={'github:one': dict(
                      membership='DIRECT', reason='Same failure <script>reason</script>', quote_meaning_verified=False,
                      membership_quote=dict(quote=quote, start=0, end=len(quote)), loss_direct=False,
                      loss_quote=None, economic_kind='UNKNOWN', economic_reason='not established', economic_quote=None,
                      counter_signal=False, counter_quote=None, counter_assessment='NOT_ASSESSED',
                      counter_rationale='not reviewed')})
    paths = [tmp_path / name for name in ('input-manifest.json', 'input-review.json')]
    for path, data in zip(paths, (manifest, review)):
        path.write_text(json.dumps(data), encoding='utf-8')
    return paths


def args(paths, out):
    return ['--manifest', str(paths[0]), '--review', str(paths[1]), '--out-dir', str(out),
            '--extraction-mode', 'synthetic']


def test_packet_and_receipt(tmp_path):
    paths = fixture(tmp_path)
    out = tmp_path / 'run'
    result = subprocess.run([sys.executable, '-m', 'src.evidence_pilot_cli', *args(paths, out)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    packet = json.loads((out / 'packet.json').read_text())
    assert packet['decision'] == 'HOLD'
    assert packet['grade'] == 'PILOT_REVIEW_ONLY'
    assert packet['actionability'] == packet['growth'] == 'UNKNOWN'
    assert 'review_value' not in packet
    assert packet['arms']['broad']['reviewed_denominator'] == 0
    assert packet['arms']['broad']['proposal_count'] == 1
    assert packet['publication_precision_counts']['DATE_ONLY'] == 1
    assert not packet['comparison_valid']
    assert len(packet['gate_deficits']) == 7
    html = (out / 'index.html').read_text()
    assert 'https://example.com/item?a=1&amp;b=2' in html
    assert '&lt;script&gt;alert(&quot;fixture&quot;)&lt;/script&gt; &amp; missing notes' in html
    assert '<script>' not in html
    assert 'AI_PROPOSAL' in html and 'UNAVAILABLE' in html and 'DATE_ONLY' in html
    assert '>0%<' not in html
    receipt = json.loads((out / 'receipt.json').read_text())
    assert receipt['extraction_mode'] == 'synthetic'
    assert receipt['audit_duration_seconds'] is None and receipt['reviewer_findings'] is None
    assert receipt['input_counts'] == {'broad': 1, 'focused': 0, 'total_occurrences': 1, 'distinct_document_ids': 1}
    assert receipt['review_hash'] == hashlib.sha256(paths[1].read_bytes()).hexdigest()
    assert set(receipt['artifact_hashes']) == {'manifest.json', 'review.json', 'packet.json', 'index.html'}
    for name, digest in receipt['artifact_hashes'].items():
        assert digest == hashlib.sha256((out / name).read_bytes()).hexdigest()
    for source, name in zip(paths, ('manifest.json', 'review.json')):
        assert source.read_bytes() == (out / name).read_bytes()
    other = tmp_path / 'other'
    assert main(args(paths, other)) == 0
    for name in (*receipt['artifact_hashes'], 'receipt.json'):
        assert (out / name).read_bytes() == (other / name).read_bytes()


def test_declared_real_mode(tmp_path, monkeypatch):
    paths = fixture(tmp_path)
    out = tmp_path / 'run'
    captured = []
    monkeypatch.setattr('src.evidence_pilot_cli.write_run', lambda *params: captured.append(params))
    assert main(args(paths, out)[:-2]) == 0
    assert captured[0][-1] == 'separate-session structured AI annotations'
    assert not out.exists()


@pytest.mark.parametrize('which', [0, 1])
def test_invalid_inputs_create_no_run(tmp_path, which):
    paths = fixture(tmp_path)
    paths[which].write_text('{}')
    out = tmp_path / 'unwritten'
    assert main(args(paths, out)) != 0
    assert not out.exists()


def test_duplicate_json_keys_are_rejected(tmp_path):
    paths = fixture(tmp_path)
    paths[1].write_text(paths[1].read_text().replace('{', '{"candidate_id":"different",', 1))
    out = tmp_path / 'unwritten'
    assert main(args(paths, out)) != 0
    assert not out.exists()


@pytest.mark.parametrize('kind', ['rerun', 'empty', 'nonempty', 'symlink', 'dangling'])
def test_existing_destinations_are_not_overwritten(tmp_path, kind):
    paths = fixture(tmp_path)
    out = tmp_path / 'run'
    if kind == 'rerun':
        assert main(args(paths, out)) == 0
    elif kind in {'empty', 'nonempty'}:
        out.mkdir()
        if kind == 'nonempty':
            (out / 'unrelated').write_text('preserved')
    else:
        target = tmp_path / 'target'
        if kind == 'symlink':
            target.mkdir()
        out.symlink_to(target, target_is_directory=True)
    before = {p.name: p.read_bytes() for p in out.iterdir()} if out.is_dir() else {}
    assert main(args(paths, out)) != 0
    after = {p.name: p.read_bytes() for p in out.iterdir()} if out.is_dir() else {}
    assert before == after
