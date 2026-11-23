"""Exploratory synthetic pilot. No public or human-reviewed benchmark claims."""
import csv
import hashlib
import io
import json
import random
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies'
MODEL = Path.home() / 'Downloads/eng.traineddata'
KINDS = ['numeric', 'row_swap', 'column_swap', 'missing', 'label']


def write_csv(path, rows):
    with path.open('w', newline='') as stream:
        csv.writer(stream).writerows(rows)


def event(kind, *cells):
    return kind, tuple(sorted(cells))


def generate(out, seed=20261122):
    rng = random.Random(seed)
    records = []
    for i in range(10):
        doc = out / f'doc-{i+1:02}'
        doc.mkdir()
        headers = ['Item', 'Units', 'Price', 'Stock']
        labels = ['Alpha', 'Bravo', 'Charlie', 'Delta', 'Echo', 'Foxtrot', 'Golf', 'Hotel'] if seed == 20261122 else ['Amber', 'Birch', 'Cedar', 'Dune', 'Elm', 'Fern', 'Grove', 'Hazel']
        values = iter(rng.sample(range(110, 990), 24))
        clean = [headers] + [[label, *[str(next(values)) for _ in range(3)]] for label in labels]
        corrupt = [row[:] for row in clean]
        events = []
        # Three disjoint row groups for each document, balanced across five event types.
        for j in range(3):
            kind = KINDS[(i * 3 + j) % 5]
            r = 1 + j * 2
            cell = lambda row, col: f'{clean[row][0].lower()}//{headers[col].lower()}'
            if kind == 'numeric':
                corrupt[r][1] = str(int(corrupt[r][1]) + 1000)
                events.append(event(kind, cell(r, 1)))
            elif kind == 'row_swap':
                corrupt[r][1], corrupt[r+1][1] = corrupt[r+1][1], corrupt[r][1]
                events.append(event(kind, cell(r, 1), cell(r+1, 1)))
            elif kind == 'column_swap':
                corrupt[r][1], corrupt[r][2] = corrupt[r][2], corrupt[r][1]
                events.append(event(kind, cell(r, 1), cell(r, 2)))
            elif kind == 'missing':
                corrupt[r][1] = ''
                events.append(event(kind, cell(r, 1)))
            else:
                corrupt[r][0] = 'Unknown'
                events.append(event(kind, cell(r, 0).replace('//item', '//label')))
        font = ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf', 36 if i < 6 else 30)
        image = Image.new('RGB', (1400, 1100), 'white')
        draw = ImageDraw.Draw(image)
        xs = [80, 480 + i * 3, 760, 1060]
        for row_num, row in enumerate(clean):
            y = 100 + row_num * 100
            if i % 3 == 1:
                draw.line((50, y+70, 1350, y+70), fill='#aaaaaa', width=2)
            if i % 3 == 2 and row_num % 2:
                draw.rectangle((50, y-10, 1350, y+65), fill='#eeeeee')
            for x, value in zip(xs, row):
                draw.text((x, y), value, font=font, fill='black')
        if i >= 8:
            image = image.filter(ImageFilter.GaussianBlur(1.2))
        pdf = doc / 'source.pdf'
        image.save(pdf, resolution=150)
        subprocess.run([str(RUNTIME / 'native/poppler/bin/pdftoppm'), '-r', '150', '-png', '-singlefile', str(pdf), str(doc / 'scan')], check=True)
        write_csv(doc / 'a.csv', clean)
        write_csv(doc / 'b.csv', corrupt)
        records.append({'doc': doc, 'events': events})
    return records


def reconstruct(tsv):
    fields = ['level', 'page_num', 'block_num', 'par_num', 'line_num', 'word_num', 'left', 'top', 'width', 'height', 'conf', 'text']
    words = [row for row in csv.DictReader(io.StringIO(tsv), fieldnames=fields, delimiter='\t') if row.get('level') == '5' and row.get('text', '').strip()]
    groups = []
    for word in sorted(words, key=lambda w: int(w['top']) + int(w['height']) / 2):
        center = int(word['top']) + int(word['height']) / 2
        if not groups or abs(center - groups[-1][0]) > 25:
            groups.append((center, []))
        groups[-1][1].append(word)
    if not groups:
        return {}, 0, 1
    header = sorted(groups[0][1], key=lambda w: int(w['left']))
    # The first header identifies the label column by position. Its text is not
    # used to identify any cell; numeric column headers still require confidence.
    if len(header) != 4 or any(float(w['conf']) < 80 for w in header[1:]):
        return {}, 0, 1
    anchors = [int(w['left']) for w in header]
    columns = [w['text'].lower() for w in header]
    rows = {}
    uncertainty = 0
    for _, group in groups[1:]:
        fields = {}
        for word in group:
            index = min(range(4), key=lambda n: abs(anchors[n] - int(word['left'])))
            if float(word['conf']) < 80 or index in fields or abs(anchors[index] - int(word['left'])) > 100:
                uncertainty += 1
                continue
            fields[index] = word['text']
        if 0 not in fields or fields[0].lower() in rows:
            uncertainty += 1
            continue
        rows[fields[0].lower()] = {columns[n]: fields[n] for n in range(1, 4) if n in fields}
    return rows, len(groups)-1, uncertainty


def compare(source, row_count, sheet):
    headers = [x.lower() for x in sheet[0][1:]]
    observed = {row[0].lower(): dict(zip(headers, row[1:])) for row in sheet[1:]}
    general = int(row_count != len(observed)) + int(any(not v.isdecimal() for row in observed.values() for v in row.values()))
    if source and sum(int(v) for row in source.values() for v in row.values() if v.isdecimal()) != sum(int(v) for row in observed.values() for v in row.values() if v.isdecimal()):
        general += 1
    alerts = []
    for label in source.keys() - observed.keys():
        matches = [key for key in observed.keys() - source.keys() if source[label] == observed[key] and len(source[label]) == len(headers)]
        if len(matches) == 1 and sum(source[row] == observed[matches[0]] for row in source.keys() - observed.keys()) == 1:
            alerts.append(event('label', f'{label}//label'))
    differences = {}
    for label in source.keys() & observed.keys():
        for col in headers:
            expected, actual = source[label].get(col), observed[label].get(col)
            if expected is None or not expected.isdecimal() or expected == actual:
                continue
            key = f'{label}//{col}'
            if actual == '':
                alerts.append(event('missing', key))
            elif actual and actual.isdecimal():
                differences[key] = (expected, actual)
    used = set()
    for key, (expected, actual) in differences.items():
        if key in used:
            continue
        matches = [other for other, pair in differences.items() if other != key and pair == (actual, expected)]
        if len(matches) == 1:
            other = matches[0]
            if sum(pair == (expected, actual) for pair in differences.values()) != 1:
                continue
            r1, c1 = key.split('//')
            r2, c2 = other.split('//')
            if r1 == r2 or c1 == c2:
                alerts.append(event('column_swap' if r1 == r2 else 'row_swap', key, other))
                used.update((key, other))
                continue
        if not matches:
            alerts.append(event('numeric', key))
    return alerts, general


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--seed', type=int, default=20261122)
    parser.add_argument('--run-id', default='synthetic-pilot-20261122')
    args = parser.parse_args()
    if Path(args.run_id).name != args.run_id or args.run_id in ('.', '..'):
        parser.error('run-id must be a single directory name')
    out = ROOT / 'artifacts/scanned-pdf-experiment' / args.run_id
    out.mkdir(parents=True, exist_ok=False)
    records = generate(out, args.seed)
    truth = {r['doc'].name: r['events'] for r in records}
    (out / 'truth.json').write_text(json.dumps(truth, indent=2))
    hashes = {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest() for p in out.glob('doc-*/*')}
    (out / 'input-hashes.json').write_text(json.dumps(hashes, indent=2))
    run = subprocess.run(['node', str(ROOT / 'scripts/scanned_pdf_pilot_ocr.cjs'), str(MODEL), *[str(r['doc'] / 'scan.png') for r in records]], check=True, capture_output=True, text=True, timeout=180)
    snapshots = [json.loads(line) for line in run.stdout.splitlines()]
    (out / 'ocr.json').write_text(json.dumps(snapshots, indent=2))
    evaluate(out, records, snapshots, 'results.json')


def evaluate(out, records, snapshots, filename):
    results = []
    for record, snapshot in zip(records, snapshots, strict=True):
        doc = record['doc']
        source, count, uncertain = reconstruct(snapshot['tsv'])
        for variant in ('a', 'b'):
            with (doc / f'{variant}.csv').open() as stream:
                alerts, general = compare(source, count, list(csv.reader(stream)))
            expected = set(record['events'] if variant == 'b' else [])
            predicted = set(alerts)
            results.append({'doc': doc.name, 'variant': variant, 'expected': sorted(expected), 'alerts': sorted(predicted), 'tp': sorted(expected & predicted), 'fp': sorted(predicted - expected), 'fn': sorted(expected - predicted), 'baseline_general': general, 'uncertain': uncertain, 'ocr_confidence': snapshot['confidence']})
    tp, fp, fn = [sum(len(r[key]) for r in results) for key in ('tp', 'fp', 'fn')]
    summary = {'status': 'EXPLORATORY_SYNTHETIC_ONLY', 'documents': len(records), 'variants': len(results), 'tp': tp, 'fp': fp, 'fn': fn, 'precision': tp/(tp+fp) if tp+fp else None, 'recall': tp/(tp+fn), 'baseline_localized_tp': 0, 'baseline_general_flagged': sum(r['baseline_general'] > 0 for r in results), 'per_type': {k: {metric: sum(e[0] == k for r in results for e in r[metric]) for metric in ('tp', 'fp', 'fn')} for k in KINDS}, 'human': 'PENDING', 'business': 'HOLD', 'results': results}
    with (out / filename).open('x') as stream:
        json.dump(summary, stream, indent=2)
    print(json.dumps({k: v for k, v in summary.items() if k != 'results'}, indent=2))


if __name__ == '__main__':
    main()
