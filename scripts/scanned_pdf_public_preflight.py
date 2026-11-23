"""Run OCR/layout readiness on fixed public scan pages, without ground truth."""
import hashlib
import json
import subprocess
from pathlib import Path

from scanned_pdf_synthetic_pilot import ROOT, RUNTIME, MODEL, reconstruct


PAGES = {2: 5, 3: 4, 4: 8, 5: 1, 6: 6, 7: 1, 8: 1, 9: 4, 10: 4, 11: 1}


def main():
    base = ROOT / 'artifacts/scanned-pdf-experiment/public-pilot-20261122'
    out = base / 'page-preflight'
    out.mkdir(exist_ok=False)
    poppler = RUNTIME / 'native/poppler'
    records = []
    for part, page in PAGES.items():
        name = f'1950-{part:02}'
        pdf = base / 'source' / f'{name}.pdf'
        prefix = out / f'{name}-page-{page}'
        png = prefix.with_suffix('.png')
        subprocess.run([str(poppler / 'bin/pdftoppm'), '-f', str(page), '-l', str(page), '-r', '300', '-png', '-singlefile', str(pdf), str(prefix)], check=True)
        extracted = subprocess.run([str(poppler / 'poppler/bin/pdftotext'), '-f', str(page), '-l', str(page), str(pdf), '-'], check=True, capture_output=True, text=True)
        records.append({'source_url': f'https://www2.census.gov/library/publications/1950/compendia/statab/71ed/{name}.pdf', 'pdf': pdf.name, 'page': page, 'pdf_sha256': hashlib.sha256(pdf.read_bytes()).hexdigest(), 'render_sha256': hashlib.sha256(png.read_bytes()).hexdigest(), 'embedded_text_chars': len(extracted.stdout.strip()), 'image': str(png), 'human_verified_truth': False})
    (out / 'selected-pages.json').write_text(json.dumps(records, indent=2))
    result = subprocess.run(['node', str(ROOT / 'scripts/scanned_pdf_pilot_ocr.cjs'), str(MODEL), *[r['image'] for r in records]], check=True, capture_output=True, text=True, timeout=300)
    snapshots = [json.loads(line) for line in result.stdout.splitlines()]
    (out / 'ocr.json').write_text(json.dumps(snapshots, indent=2))
    for record, snapshot in zip(records, snapshots, strict=True):
        rows, bands, uncertain = reconstruct(snapshot['tsv'])
        record.update({'ocr_confidence': snapshot['confidence'], 'ocr_word_count': sum(l.startswith('5\t') for l in snapshot['tsv'].splitlines()), 'reconstructed_rows': len(rows), 'row_bands': bands, 'uncertainty': uncertain})
    summary = {'status': 'PUBLIC_LAYOUT_PREFLIGHT_ONLY', 'public_pages': len(records), 'ocr_pages': sum(r['ocr_word_count'] > 0 for r in records), 'layout_ready_pages': sum(r['reconstructed_rows'] >= 8 for r in records), 'human_verified_truth': 0, 'precision': None, 'recall': None, 'business': 'HOLD', 'records': records}
    (out / 'results.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
