"""Compare fixed OCR passes on public development cells; retain all evidence."""
import json
import subprocess
from collections import Counter
from pathlib import Path

from PIL import Image, ImageOps

from scanned_pdf_scoped_cells import normalize, check_row_totals
from scanned_pdf_synthetic_pilot import ROOT, MODEL


def select_consensus(passes):
    votes = Counter(p['value'] for p in passes if p['value'] is not None and p['confidence'] >= 60)
    if not votes:
        return None, 'UNCERTAIN'
    value, count = votes.most_common(1)[0]
    confident = {p['value'] for p in passes if p['confidence'] >= 80 and p['value'] is not None}
    if count >= 2 and confident == {value}:
        return value, 'READ'
    return None, 'UNCERTAIN'


def run_pass(images, mode):
    result = subprocess.run(['node', str(ROOT / 'scripts/scanned_pdf_pilot_ocr.cjs'), str(MODEL), mode, *map(str, images)], capture_output=True, text=True, check=True, timeout=180)
    return [json.loads(line) for line in result.stdout.splitlines()]


def main():
    base = ROOT / 'artifacts/scanned-pdf-experiment/public-pilot-20261122'
    source = base / 'scoped-cell-development'
    out = base / 'ocr-consensus-development'
    out.mkdir(exist_ok=False)
    summary = []
    for scope, total, components in [('development', 'Gross', ['Land', 'Inland water']), ('new-page', 'Total', ['Gold coin', 'Silver coin', 'Minor coin'])]:
        original = json.loads((source / scope / 'cells.json').read_text())
        scope_out = out / scope
        scope_out.mkdir()
        variants = {'contrast': [], 'binary': []}
        for index, cell in enumerate(original):
            image = Image.open(cell['image']).convert('L')
            contrasted = ImageOps.autocontrast(image, cutoff=1)
            for name, variant in [('contrast', contrasted), ('binary', contrasted.point(lambda x: 255 if x >= 160 else 0))]:
                path = scope_out / f'{index:03}-{name}.png'
                variant.save(path)
                variants[name].append(path)
        passes = [('contrast', run_pass(variants['contrast'], '--raw-line')), ('binary', run_pass(variants['binary'], '--single-line'))]
        cells = []
        for index, old in enumerate(original):
            readings = [{'mode': 'original', 'raw': old['raw'], 'confidence': old['confidence'], 'value': old['value']}]
            for name, snapshots in passes:
                snapshot = snapshots[index]
                raw = snapshot['text'].strip()
                readings.append({'mode': name, 'raw': raw, 'confidence': snapshot['confidence'], 'value': normalize(raw, old['numeric'])})
            value, status = select_consensus(readings)
            cells.append({**old, 'old_value': old['value'], 'old_status': old['status'], 'value': value, 'status': status, 'passes': readings})
        checks = check_row_totals(cells, total, components)
        counts = dict(Counter(c['status'] for c in checks))
        (scope_out / 'cells.json').write_text(json.dumps(cells, indent=2))
        (scope_out / 'arithmetic-checks.json').write_text(json.dumps(checks, indent=2))
        summary.append({'scope': scope, 'cells': len(cells), 'original_read': sum(c['old_status'] == 'READ' for c in cells), 'consensus_read': sum(c['status'] == 'READ' for c in cells), 'newly_read': sum(c['old_status'] != 'READ' and c['status'] == 'READ' for c in cells), 'now_uncertain': sum(c['old_status'] == 'READ' and c['status'] != 'READ' for c in cells), 'changed_accepted': sum(c['old_status'] == c['status'] == 'READ' and c['old_value'] != c['value'] for c in cells), 'arithmetic': counts, 'human_verified': False})
    (out / 'results.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
