"""Score previously captured visual extraction against human-verified public truth."""
import argparse
import csv
import json
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path

from scanned_pdf_synthetic_pilot import ROOT, event, KINDS


BASE = ROOT / 'artifacts/scanned-pdf-experiment/public-pilot-20261122/llm-ten-review'


def number(value):
    try:
        result = Decimal(value.replace(',', '').strip())
        return result if result.is_finite() else None
    except InvalidOperation:
        return None


def normalized(value):
    parsed = number(value)
    return parsed if parsed is not None else ' '.join(value.casefold().split())


def load_truth(path, tables):
    expected = {(t['pdf'], str(t['page']), t['table'], str(i), c) for t in tables for i, row in enumerate(t['rows']) for c in t['columns']}
    collected = {}
    with path.open(newline='', encoding='utf-8-sig') as stream:
        for record in csv.DictReader(stream):
            key = tuple(record[name] for name in ('pdf', 'page', 'table', 'row_index', 'column'))
            if key not in expected or key in collected or record['human_status'] != 'VERIFIED' or not record['human_corrected_value'].strip():
                raise ValueError(f'Unverified, invalid or duplicate cell: {key}')
            collected[key] = record['human_corrected_value'].strip()
    if collected.keys() != expected:
        raise ValueError(f'Missing {len(expected - collected.keys())} verified cells')
    return [[[col for col in t['columns']]] + [[collected[t['pdf'], str(t['page']), t['table'], str(i), c] for c in t['columns']] for i in range(len(t['rows']))] for t in tables]


def inject(clean, index):
    corrupted = [r[:] for r in clean]
    expected = []
    for j in range(3):
        kind = KINDS[(index * 3 + j) % 5]
        row = 1 + 2 * j
        key = lambda r, c: f'{clean[r][0].casefold()}//{clean[0][c].casefold()}'
        if kind == 'label':
            if 'unknown' in [r[0].casefold() for r in clean[1:]]:
                raise ValueError('Injected label collision')
            corrupted[row][0] = 'Unknown'
            expected.append(event(kind, f'{clean[row][0].casefold()}//label'))
            continue
        cols = [c for c in range(1, len(clean[0])) if number(clean[row][c]) is not None]
        if kind == 'row_swap':
            cols = [c for c in cols if number(clean[row+1][c]) is not None and normalized(clean[row][c]) != normalized(clean[row+1][c])]
        if not cols:
            raise ValueError(f'No eligible numeric cell for {kind}')
        col = cols[0]
        if kind == 'numeric':
            corrupted[row][col] = str(number(clean[row][col]) + 1000)
            expected.append(event(kind, key(row, col)))
        elif kind == 'missing':
            corrupted[row][col] = ''
            expected.append(event(kind, key(row, col)))
        elif kind == 'row_swap':
            corrupted[row][col], corrupted[row+1][col] = corrupted[row+1][col], corrupted[row][col]
            expected.append(event(kind, key(row, col), key(row+1, col)))
        else:
            other = next((c for c in cols if normalized(clean[row][c]) != normalized(clean[row][col])), None)
            if other is None:
                raise ValueError('No distinct column swap values')
            corrupted[row][col], corrupted[row][other] = corrupted[row][other], corrupted[row][col]
            expected.append(event(kind, key(row, col), key(row, other)))
    return corrupted, expected


def compare(source, sheet):
    headers = [c.casefold() for c in source[0][1:]]
    if headers != [c.casefold() for c in sheet[0][1:]]:
        raise ValueError('Column mismatch requires manual review')
    original = {r[0].casefold(): dict(zip(headers, map(normalized, r[1:]))) for r in source[1:]}
    observed = {r[0].casefold(): dict(zip(headers, map(normalized, r[1:]))) for r in sheet[1:]}
    if len(original) != len(source)-1 or len(observed) != len(sheet)-1:
        raise ValueError('Ambiguous row labels')
    alerts = []
    for label in original.keys() - observed.keys():
        matches = [other for other in observed.keys() - original.keys() if original[label] == observed[other]]
        if len(matches) == 1 and sum(original[l] == observed[matches[0]] for l in original.keys() - observed.keys()) == 1:
            alerts.append(event('label', f'{label}//label'))
    differences = {}
    for label in original.keys() & observed.keys():
        for col in headers:
            expected, actual = original[label][col], observed[label][col]
            if expected == actual or not isinstance(expected, Decimal):
                continue
            key = f'{label}//{col}'
            if actual == '':
                alerts.append(event('missing', key))
            elif isinstance(actual, Decimal):
                differences[key] = (expected, actual)
    used = set()
    for key, (expected, actual) in differences.items():
        if key in used:
            continue
        matches = [other for other, pair in differences.items() if other != key and pair == (actual, expected)]
        if len(matches) == 1 and sum(pair == (expected, actual) for pair in differences.values()) == 1:
            other = matches[0]
            r1,c1 = key.split('//')
            r2,c2 = other.split('//')
            if r1 == r2 or c1 == c2:
                alerts.append(event('column_swap' if r1 == r2 else 'row_swap', key, other))
                used.update((key, other))
        elif not matches:
            alerts.append(event('numeric', key))
    return alerts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('verified_csv', type=Path)
    args = parser.parse_args()
    tables = json.loads((BASE / 'transcription-reviewed.json').read_text())['tables']
    clean = load_truth(args.verified_csv, tables)
    prepared = [(sheet, *inject(sheet, i)) for i, sheet in enumerate(clean)]
    out = BASE / 'human-verified-evaluation'
    out.mkdir(exist_ok=False)
    records = []
    for table, (sheet, corrupt, events) in zip(tables, prepared, strict=True):
        source = [table['columns'], *table['rows']]
        for variant, target, expected in [('clean', sheet, []), ('corrupt', corrupt, events)]:
            alerts = compare(source, target)
            counts = Counter(alerts)
            matched = [e for e in expected if counts[e] > 0]
            fp = len(alerts) - len(matched)
            records.append({'pdf': table['pdf'], 'variant': variant, 'sheet': target, 'expected': expected, 'alerts': alerts, 'tp': len(matched), 'fp': fp, 'fn': len(expected)-len(matched)})
    tp,fp,fn = [sum(r[k] for r in records) for k in ('tp','fp','fn')]
    result = {'status':'EXPLORATORY_PUBLIC_WITH_HUMAN_TRUTH','documents':len(tables),'tp':tp,'fp':fp,'fn':fn,'precision':tp/(tp+fp) if tp+fp else None,'recall':tp/(tp+fn) if tp+fn else None,'human_timing':'PENDING','business':'HOLD','records':records}
    (out / 'results.json').write_text(json.dumps(result, indent=2))
    print(json.dumps({k:v for k,v in result.items() if k!='records'},indent=2))


if __name__ == '__main__':
    main()
