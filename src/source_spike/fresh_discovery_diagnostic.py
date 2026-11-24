"""Observe a fresh V2 replay without changing its frozen inference or validation."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import re

from src.source_spike import fresh_integrated_discovery as fresh


def run(root, analysis_id, resume_from=None):
    for value in (analysis_id, resume_from):
        if value is not None and not re.fullmatch(r'analysis-[A-Za-z0-9-]+', value):
            raise ValueError('invalid analysis id')
    if (root / analysis_id).exists():
        raise FileExistsError('analysis already exists; preserve prior attempt')
    trace_root = root / f'{analysis_id}-diagnostics'
    trace_root.mkdir(mode=0o700, exist_ok=False)
    original = fresh.pilot._call
    sequence = 0

    def observe(stage, items, prompt, schema):
        nonlocal sequence
        sequence += 1
        path = trace_root / f'request-{sequence:03d}.json'
        binding = {'stage': stage, 'input': items, 'prompt_sha256': sha256(prompt.encode()).hexdigest(),
                   'schema_sha256': sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest()}
        try:
            output = original(stage, items, prompt, schema)
        except (fresh.cli.CliContractError, ValueError, OSError) as error:
            fresh.cli._private_create(path, {**binding, 'reason': str(error)})
            raise
        # Save the exact response BEFORE the original runner validates semantic evidence.
        fresh.cli._private_create(path, {**binding, 'output': output})
        return output

    fresh.pilot._call = observe
    try:
        result = fresh.analyze(root, analysis_id, resume_from)
    finally:
        fresh.pilot._call = original
    fresh.cli._private_create(trace_root / 'receipt.json', {
        'analysis_id': analysis_id, 'requests_observed': sequence, 'status': result['status'],
        'failed_request': result.get('failed_request'), 'reason': result.get('reason'),
        'scope': 'OBSERVATION_ONLY_UNCHANGED_FROZEN_ENGINE'})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--analysis-id', default='analysis-02')
    parser.add_argument('--resume-from')
    args = parser.parse_args()
    try:
        result = run(fresh.RUN, args.analysis_id, args.resume_from)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.error(str(error))
    keys = ('status', 'documents', 'tasks', 'groups', 'families', 'repeated_demand_groups', 'multi_source_families',
            'official_opportunities', 'sample_status', 'stage', 'reason', 'failed_request')
    print(json.dumps({**{k: result[k] for k in keys if k in result},
                      'result': str(fresh.RUN / args.analysis_id / 'result.json'),
                      'diagnostics': str(fresh.RUN / f'{args.analysis_id}-diagnostics')}, ensure_ascii=False))
    return 0 if result['status'] == 'REPLAY_COMPLETE' else 1


if __name__ == '__main__':
    raise SystemExit(main())
