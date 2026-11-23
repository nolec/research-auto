"""Exploratory OCR with manually selected cell geometry; no ground-truth access."""
import csv
import json
import re
import subprocess
from decimal import Decimal
from pathlib import Path

from PIL import Image, ImageOps

from scanned_pdf_synthetic_pilot import ROOT, MODEL


def normalize(text, numeric):
    text = text.strip()
    if numeric:
        text = re.sub(r'\s|,', '', text)
        return text if re.fullmatch(r'[+-]?\d+(?:\.\d+)?', text) else None
    text = re.sub(r'[.\-–_]+$', '', text).strip()
    return text or None


def check_row_totals(cells, total_column, component_columns):
    """Flag inconsistent or incomplete declared sums without inferring values."""
    by_row = {}
    for cell in cells:
        by_row.setdefault(cell['row'], {})[cell['column']] = cell
    checks = []
    for row, fields in sorted(by_row.items()):
        required = [fields.get(name) for name in (total_column, *component_columns)]
        if any(cell is None or cell['status'] != 'READ' or cell['value'] is None for cell in required):
            checks.append({'row': row, 'status': 'INCOMPLETE'})
            continue
        total, *components = [Decimal(cell['value']) for cell in required]
        difference = total - sum(components)
        checks.append({'row': row, 'status': 'CONSISTENT' if difference == 0 else 'INCONSISTENT', 'difference': str(difference)})
    return checks


def read_scope(image_path, columns, row_centers, out):
    image = Image.open(image_path).convert('L')
    out.mkdir(parents=True, exist_ok=False)
    cells = []
    for index, y in enumerate(row_centers):
        for col, (name, left, right) in enumerate(columns):
            box = (left, y - 13, right, y + 13)
            if not (0 <= box[0] < box[2] <= image.width and 0 <= box[1] < box[3] <= image.height):
                raise ValueError(f'Cell outside source image: {box}')
            crop = image.crop(box)
            crop = ImageOps.expand(crop.resize((crop.width * 3, crop.height * 3)), border=20, fill=255)
            path = out / f'{index:02}-{col:02}.png'
            crop.save(path)
            cells.append({'row': index, 'column': name, 'numeric': col > 0, 'bbox': box, 'image': str(path)})
    result = subprocess.run(['node', str(ROOT / 'scripts/scanned_pdf_pilot_ocr.cjs'), str(MODEL), '--single-line', *[cell['image'] for cell in cells]], capture_output=True, text=True, check=True, timeout=180)
    for cell, line in zip(cells, result.stdout.splitlines(), strict=True):
        snapshot = json.loads(line)
        value = normalize(snapshot['text'], cell['numeric'])
        cell.update(raw=snapshot['text'].strip(), value=value, confidence=snapshot['confidence'], status='READ' if value is not None and snapshot['confidence'] >= 80 else 'UNCERTAIN')
    with (out / 'cells.json').open('x') as stream:
        json.dump(cells, stream, indent=2)
    with (out / 'review.csv').open('x', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['row', 'column', 'ocr_value', 'confidence', 'status', 'human_corrected_value'])
        writer.writerows([c['row'], c['column'], c['value'], c['confidence'], c['status'], ''] for c in cells)
    return cells


def main():
    base = ROOT / 'artifacts/scanned-pdf-experiment/public-pilot-20261122'
    out = base / 'scoped-cell-development'
    out.mkdir(exist_ok=False)
    specs = [
        ('development', '1950-02-page-5.png', [('State', 140, 448), ('Gross', 458, 565), ('Land', 580, 701), ('Inland water', 712, 817)], [1486, 1510, 1535, 1560, 1585, 1610, 1642, 1668, 1692, 1718]),
        ('new-page', '1950-06-page-11.png', [('Year', 154, 220), ('Total', 371, 485), ('Gold coin', 500, 615), ('Silver coin', 626, 725), ('Minor coin', 738, 837)], [1233, 1258, 1283, 1308, 1333, 1358, 1383, 1408, 1433, 1458]),
    ]
    (out / 'scopes.json').write_text(json.dumps(specs, indent=2))
    summary = []
    arithmetic = {}
    for name, image, columns, centers in specs:
        cells = read_scope(base / 'page-preflight' / image, columns, centers, out / name)
        arithmetic[name] = check_row_totals(cells, columns[1][0], [column[0] for column in columns[2:]])
        summary.append({'scope': name, 'image': image, 'rows': len(centers), 'columns': len(columns), 'cells': len(cells), 'read': sum(c['status'] == 'READ' for c in cells), 'uncertain': sum(c['status'] == 'UNCERTAIN' for c in cells), 'human_verified': False})
    (out / 'arithmetic-checks.json').write_text(json.dumps(arithmetic, indent=2))
    (out / 'results.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
