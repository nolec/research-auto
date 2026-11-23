"""Render a bounded, offline evidence pilot as a non-promoting review packet."""

from __future__ import annotations

import argparse
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import sys

from src.extraction.evidence_pilot import review_membership, summarize_pilot, validate_manifest


REAL_MODE = 'separate-session structured AI annotations'
MODES = (REAL_MODE, 'synthetic')


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n').encode('utf-8')


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate JSON key: {key}')
        result[key] = value
    return result


def _load(path):
    raw = path.read_bytes()
    return raw, json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_object)


def _h(value):
    return escape('UNKNOWN' if value is None else str(value), quote=True)


def _table(headers, rows):
    return ('<div class="scroll"><table><thead><tr>' + ''.join(f'<th>{_h(h)}</th>' for h in headers)
            + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join(f'<td>{_h(v)}</td>' for v in row)
                                             + '</tr>' for row in rows) + '</tbody></table></div>')


def _details(title, pairs):
    return f'<h3>{_h(title)}</h3><dl>' + ''.join(f'<dt>{_h(k)}</dt><dd>{_h(v)}</dd>' for k, v in pairs) + '</dl>'


def _quote(ref):
    if ref is None:
        return '<p>인용 없음 / No quote</p>'
    return f'<blockquote>{_h(ref["quote"])}</blockquote><small>Offsets: {_h(ref["start"])}–{_h(ref["end"])}</small>'


def render(packet):
    arms = packet['arms']
    header = '''<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>Evidence pilot · 검토 전용</title><style>
:root{font-family:system-ui,sans-serif;color:#172b42;background:#f4f7fb;line-height:1.6}
body{max-width:1000px;margin:2rem auto;padding:0 1rem}section,article{background:white;border:1px solid #cbd5e1;border-radius:12px;padding:1rem 1.4rem;margin:1rem 0}
h1,h2,h3{line-height:1.3}h1{font-size:2rem}h2{font-size:1.35rem}h3{font-size:1.1rem}
.badge{background:#fce5c4;color:#713800;padding:.5rem .8rem;border-radius:6px;font-weight:bold;display:inline-block}
.warning{border-left:5px solid #b45309;padding:.75rem;background:#fff7ed}table{width:100%;border-collapse:collapse}th,td{padding:.5rem;text-align:left;border-bottom:1px solid #e2e8f0;vertical-align:top}th{background:#edf2f7}.scroll{overflow-x:auto}
dl{display:grid;grid-template-columns:minmax(7rem,1fr) 3fr;gap:.25rem .75rem}dt{font-weight:600}dd{margin:0;overflow-wrap:anywhere}blockquote,pre{white-space:pre-wrap;overflow-wrap:anywhere;margin:.5rem 0;padding:.75rem;background:#f1f5f9;border-left:4px solid #64748b}a{color:#125aa3;overflow-wrap:anywhere}small{color:#475569}summary{cursor:pointer;font-weight:600}
@media(max-width:550px){dl{display:block}dd{margin-bottom:.5rem}}
</style></head><body>'''
    content = [header, '<h1>근거 파일럿 · Evidence pilot</h1>',
               '<p class="badge">PILOT_REVIEW_ONLY · HOLD</p> <strong>Actionability: UNKNOWN · Growth: UNKNOWN</strong>',
               '<p>공식 Opportunity Card가 아닙니다. 자동 승격 없음 / Not a production opportunity.</p>',
               f'<p>실행 / Run: {_h(packet["run_id"])} · 입력 모드 / Input mode: {_h(packet["extraction_mode"])}</p>',
               '<section><h2>후보 · Candidate</h2>',
               _details('정의 / Definition', [(k, packet[k]) for k in ('candidate_id', 'actor', 'task', 'failure', 'reviewer', 'review_kind')]),
               '<p class="warning">' + ('AI_PROPOSAL — AI 제안만 존재; 사람 검토 결과가 아닙니다 / AI proposals, not human review findings.'
                                         if packet['review_kind'] == 'AI_PROPOSAL' else
                                         'HUMAN — 입력에 기록된 사람 검토 선언 / Human review assertions supplied in input; not independently authenticated by this CLI.') + '</p>',
               '<p>원본 확인 및 인용 의미 확인 표시는 입력 선언입니다. 이 CLI는 실제 출처나 검토자의 신원을 확인하지 않습니다. / Source and meaning flags are input assertions, not independent verification.</p>',
               _details('고정 프로토콜 / Locked protocol', [(k, packet[k]) for k in ('source', 'as_of', 'window_start', 'window_end', 'protocol_hash')]),
               '</section><section><h2>표본 비교 · Sampling comparison</h2>',
               _table(('Arm', 'Query', 'Method', 'Cap', 'Input occurrences', 'Human direct / reviewed', 'AI proposed direct / proposals'),
                      [(name, packet['arm_protocol'][name]['query'], packet['arm_protocol'][name]['sampling_method'],
                        packet['arm_protocol'][name]['cap'], arm['row_count'],
                        f'{arm["direct_eligible_count"]}/{arm["reviewed_denominator"]}' + (' — UNAVAILABLE / 비교 불가' if not arm['reviewed_denominator'] else ''),
                        f'{arm["proposed_direct_count"]}/{arm["proposal_count"]}' + (' — UNAVAILABLE / 제안 없음' if not arm['proposal_count'] else '')) for name, arm in arms.items()]),
               '<p>Human counts are distinct cases; proposal counts are input occurrences. 0/0 means no reviewed denominator, not zero yield.</p>',
               f'<p class="warning">Comparison: {"VALID — descriptive only" if packet["comparison_valid"] else "INVALID / 비교 불가"}. {_h(packet["comparison_reason"])}</p>',
               _details('중복 및 사례 / Overlap and cases', [('Overlap', packet['overlap']), *[(k, packet[k]) for k in ('combined_unique_cases', 'review_eligible_unique_cases', 'eligible_unique_cases', 'conflicted_eligible_case_count')]]),
               '</section><section><h2>근거 기준 · Evidence gates</h2>',
               _table(('Gate', 'Required', 'Actual', 'Status'), [(k, v, packet[k], 'UNMET / 미충족' if any(d['gate'] == k for d in packet['gate_deficits']) else 'Input threshold met') for k, v in packet['gate_thresholds'].items()]),
               '<p>기준 충족 자체가 승격은 아닙니다. / Meeting an input threshold does not promote the candidate.</p>',
               '</section><section><h2>반대 근거 및 불확실성 · Counter evidence and uncertainty</h2>',
               _details('Counter assessment', [(k, packet[k]) for k in ('counter_status', 'critical_counter_document_ids', 'uncertain_counter_document_ids')]),
               '<p>NOT_ASSESSED ≠ NONE_CRITICAL. 미검토는 반대 근거가 없다는 뜻이 아닙니다.</p>',
               '<h3>입력 전체 게시일 정밀도 / Publication precision (all distinct input IDs)</h3>',
               _table(('Precision', 'Count'), packet['publication_precision_counts'].items()),
               _table(('Document ID', 'Raw publication date', 'Precision', 'Source verification input'),
                      [(r['document_id'], r['published_at'], r['precision'], r['source_verified']) for r in packet['publication_records']]),
               _table(('Unknown field', 'Count', 'Scope'), [(k, v, next(scope for scope, keys in packet['unknown_counts_scope'].items() if k in keys)) for k, v in packet['unknown_counts'].items()]),
               f'<p>{_h(packet["unknown_counts_note"])}</p>',
               _details('Conflicts and conservative groups', [('Conflicts', packet['conflicts']), ('Groups', packet['group_details'])]),
               '</section><section><h2>출처별 검토 · Source-by-source audit</h2>',
               '<p>거절·인접·미검토 항목도 포함합니다 / Rejected, adjacent and unreviewed rows are retained.</p>']
    for row in packet['rows']:
        doc, extraction = row['document'], row['extraction']
        label = 'AI proposal / AI 제안' if row['review_kind'] == 'AI_PROPOSAL' else 'Human review input / 사람 검토 입력'
        content.extend([f'<article><h3>{_h(row["arm"])} · {_h(doc["title"])}</h3>',
                        f'<p><a href="{_h(doc["source_url"])}" rel="noopener noreferrer">{_h(doc["source_url"])}</a></p>',
                        _details('출처 / Source', [('Document ID', row['document_id']), ('Source', doc['source']), ('Published', doc['published_at']), ('Source verification input', row['source_verified']), ('Metadata', row['source_metadata']), ('Thread', row['thread_id']), ('Event', row['event_id'])]),
                        '<h3>구조화 AI 추출 / Structured extraction</h3>',
                        _details('Extraction', [(k, extraction[k]) for k in ('actor', 'problem', 'context', 'consequence', 'problem_signal', 'money_signal', 'money_signal_type', 'usable_evidence', 'abstention_reason')]),
                        _quote(None if extraction['evidence_quote'] is None else {'quote': extraction['evidence_quote'], 'start': extraction['evidence_start'], 'end': extraction['evidence_end']}),
                        _details(label, [(k, row[k]) for k in ('membership', 'reason', 'quote_meaning_verified', 'reviewed', 'eligible')]),
                        _quote(row['membership_quote']),
                        _details('손실 · 결제 / Loss and economic behavior', [(k, row[k]) for k in ('loss_direct', 'loss_eligible', 'economic_kind', 'economic_reason', 'economic_eligible')]),
                        '<p>Loss quote:</p>', _quote(row['loss_quote']), '<p>Economic quote:</p>', _quote(row['economic_quote']),
                        _details('반대 근거 / Counter', [(k, row[k]) for k in ('counter_signal', 'counter_assessment', 'counter_rationale', 'counter_eligible')]),
                        _quote(row['counter_quote']),
                        f'<details><summary>원문 보기 / Preserved source text</summary><pre>{_h(doc["text"])}</pre></details></article>'])
    content.extend(['</section><section><h2>파일 및 검토 기록 · Files and audit record</h2>',
                    '<p>검토 소요 시간 및 별도 검토 소견은 아직 기록되지 않았습니다 / Audit duration and independent reviewer findings are not recorded.</p>',
                    '<p><a href="manifest.json">manifest.json</a> · <a href="review.json">review.json</a> · <a href="packet.json">packet.json</a> · <a href="receipt.json">receipt.json</a></p></section></body></html>'])
    return '\n'.join(content) + '\n'


def write_run(manifest_path, review_path, out_dir, extraction_mode):
    if extraction_mode not in MODES:
        raise ValueError('unknown extraction mode')
    manifest_raw, manifest = _load(manifest_path)
    review_raw, review = _load(review_path)
    manifest = validate_manifest(manifest)
    rows = review_membership(manifest, review)
    summary = summarize_pilot(manifest, review)
    packet = {**summary, **{k: manifest[k] for k in ('run_id', 'candidate_id', 'source', 'as_of', 'window_start', 'window_end', 'protocol_hash')},
              **{k: review[k] for k in ('actor', 'task', 'failure', 'reviewer', 'review_kind')},
              'arm_protocol': {name: {k: arm[k] for k in ('query', 'sampling_method', 'cap')} for name, arm in manifest['arms'].items()},
              'rows': rows, 'extraction_mode': extraction_mode, 'grade': 'PILOT_REVIEW_ONLY',
              'actionability': 'UNKNOWN', 'growth': 'UNKNOWN', 'decision': 'HOLD'}
    artifacts = {'manifest.json': manifest_raw, 'review.json': review_raw,
                 'packet.json': _json_bytes(packet), 'index.html': render(packet).encode('utf-8')}
    receipt = {'run_id': manifest['run_id'], 'protocol_hash': manifest['protocol_hash'],
               'review_hash': sha256(review_raw).hexdigest(), 'extraction_mode': extraction_mode,
               'review_kind': review['review_kind'],
               'artifact_hashes': {name: sha256(data).hexdigest() for name, data in artifacts.items()},
               'input_counts': {**{name: arm['row_count'] for name, arm in summary['arms'].items()},
                                'total_occurrences': len(rows), 'distinct_document_ids': len({row['document_id'] for row in rows})},
               'audit_duration_seconds': None, 'reviewer_findings': None}
    artifacts['receipt.json'] = _json_bytes(receipt)
    # All validation and rendering precedes any filesystem mutations. The final
    # directory and every file are exclusive creates; receipt is written last.
    out_dir.mkdir(parents=True, exist_ok=False)
    for name, data in artifacts.items():
        with (out_dir / name).open('xb') as file:
            file.write(data)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--review', required=True, type=Path)
    parser.add_argument('--out-dir', required=True, type=Path)
    parser.add_argument('--extraction-mode', choices=MODES, default=REAL_MODE,
                        help='declared input provenance; use synthetic for test fixtures')
    args = parser.parse_args(argv)
    try:
        write_run(args.manifest, args.review, args.out_dir, args.extraction_mode)
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(f'Pilot packet refused: {error}', file=sys.stderr)
        return 1
    print(f'PILOT_REVIEW_ONLY · HOLD: {args.out_dir}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
