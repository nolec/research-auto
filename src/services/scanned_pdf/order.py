"""Local, bounded order workflow: render -> map -> OCR -> human review -> XLSX."""
import argparse
import hashlib
import io
import base64
import json
import os
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageOps

from src.scanned_pdf_experiment.numeric_reread import parse_number

RUNTIME = Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies'
LIMIT = 100
HERE = Path(__file__).parent
OCR_SCRIPT = HERE.parents[1] / 'scanned_pdf_experiment' / 'local_ocr.cjs'


def recognize(paths, _mode):
    model = Path.home() / 'Downloads/eng.traineddata'
    modules = Path(os.environ.get('CODEX_PRIMARY_RUNTIME_NODE_MODULES', str(RUNTIME / 'node/node_modules')))
    result = subprocess.run(['node', str(OCR_SCRIPT), str(modules), str(model), *map(str, paths)], check=True, capture_output=True, text=True, timeout=180)
    readings = json.loads(result.stdout)
    return readings if isinstance(readings, list) else [readings]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, obj):
    with path.open('x', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def url(image):
    buf = io.BytesIO()
    image.save(buf, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()


def html_packet(path, template, payload):
    with path.open('x', encoding='utf-8') as f:
        f.write((HERE / template).read_text().replace('__PAYLOAD__', json.dumps(payload, ensure_ascii=False).replace('<', '\\u003c')))


def prepare(pdf, job, pages):
    if len(pages) not in (1, 2) or len(set(pages)) != len(pages) or any(type(p) is not int or p < 1 for p in pages):
        raise ValueError('Select one or two distinct positive PDF page numbers')
    if pdf.suffix.lower() != '.pdf' or not pdf.is_file() or pdf.stat().st_size > 25 * 1024 * 1024:
        raise ValueError('Select a PDF of at most 25 MB')
    renderer = shutil.which('pdftoppm') or str(RUNTIME / 'native/poppler/bin/pdftoppm')
    job.mkdir(parents=True, exist_ok=False)
    source = job / 'source.pdf'
    shutil.copyfile(pdf, source)
    records = []
    for page in pages:
        prefix = job / f'page-{page}'
        subprocess.run([renderer, '-f', str(page), '-l', str(page), '-r', '200', '-scale-to', '3000', '-png', '-singlefile', str(source.resolve()), str(prefix.resolve())], check=True, timeout=60)
        path = prefix.with_suffix('.png')
        with Image.open(path) as im:
            records.append(dict(page=page, width=im.width, height=im.height, sha256=digest(path)))
    manifest = {'source_sha256': digest(source), 'pages': records}
    write_json(job / 'manifest.json', manifest)
    payload = {'manifest': digest(job / 'manifest.json'), 'pages': [{**r, 'image': url(Image.open(job / f'page-{r["page"]}.png'))} for r in records]}
    html_packet(job / 'map.html', 'scanned_pdf_order_map.html', payload)


def grid_cells(manifest, scope):
    pages = {r['page']: r for r in manifest['pages']}
    if not isinstance(scope, list) or len(scope) != len(pages):
        raise ValueError('Map every selected page exactly once')
    seen = set()
    cells = []
    for spec in scope:
        p = spec['page']
        if type(p) is not int or p not in pages or p in seen:
            raise ValueError('Invalid page mapping')
        seen.add(p)
        page = pages[p]
        xs, ys = spec['xs'], spec['ys']
        for values, limit in ((xs, page['width']), (ys, page['height'])):
            if not isinstance(values, list) or not 2 <= len(values) <= LIMIT + 1 or any(type(v) is not int or not 0 <= v <= limit for v in values) or any(a >= b for a,b in zip(values, values[1:])):
                raise ValueError('Grid boundaries must be strictly increasing and inside the page')
        for row, (y0,y1) in enumerate(zip(ys, ys[1:]), 1):
            for col, (x0,x1) in enumerate(zip(xs, xs[1:]), 1):
                cells.append({'id': f'P{p}R{row}C{col}', 'page': p, 'row': row, 'column': col, 'box': [x0,y0,x1,y1]})
                if len(cells) > LIMIT:
                    raise ValueError('Maximum 100 numeric cells per order')
    return cells


def extract(job, mapping, reader=recognize):
    manifest = read_json(job / 'manifest.json')
    scope = read_json(mapping)
    if scope['manifest'] != digest(job / 'manifest.json') or digest(job / 'source.pdf') != manifest['source_sha256']:
        raise ValueError('Source or mapping does not match the job')
    cells = grid_cells(manifest, scope['pages'])
    pages = {}
    for r in manifest['pages']:
        path = job / f'page-{r["page"]}.png'
        if digest(path) != r['sha256']:
            raise ValueError('Page changed')
        pages[r['page']] = Image.open(path).convert('RGB')
    crops = job / 'crops'
    crops.mkdir(exist_ok=False)
    paths = []
    for cell in cells:
        crop = pages[cell['page']].crop(cell['box'])
        path = crops / f'{cell["id"]}.png'
        ImageOps.expand(ImageOps.autocontrast(crop.convert('L')).resize((crop.width*2, crop.height*2)), border=12, fill=255).save(path)
        paths.append(path.resolve())
    try:
        readings = reader(paths, '--single-line')
        if len(readings) != len(cells):
            raise ValueError('OCR output count mismatch')
    except (OSError, subprocess.SubprocessError, ValueError, RuntimeError):
        readings = [{'text': '', 'confidence': 0} for _ in cells]
    for cell, reading, path in zip(cells, readings, paths, strict=True):
        cell.update(initial=str(reading['text']), confidence=reading['confidence'], crop_sha256=digest(path))
    packet = {'source_sha256': manifest['source_sha256'], 'manifest': scope['manifest'], 'cells': cells}
    write_json(job / 'packet.json', packet)
    html_packet(job / 'review.html', 'scanned_pdf_order_review.html', {'packet': digest(job / 'packet.json'), 'cells': [{**c, 'image': url(Image.open(p))} for c,p in zip(cells,paths)], 'pages': {str(p): url(im) for p,im in pages.items()}})


def validated_rows(packet, submission, packet_hash):
    if submission.get('packet') != packet_hash:
        raise ValueError('Review belongs to a different packet')
    responses = submission.get('responses')
    expected = {c['id'] for c in packet['cells']}
    if not isinstance(responses, dict) or set(responses) != expected:
        raise ValueError('Every cell must be reviewed')
    rows = []
    for cell in packet['cells']:
        r = responses[cell['id']]
        status, raw = r.get('status'), r.get('value')
        if status not in ('confirmed', 'unreadable') or not isinstance(raw, str):
            raise ValueError('Invalid review decision')
        value = parse_number(raw)
        if status == 'confirmed' and value is None:
            raise ValueError('Confirmed cell requires a valid numeric value')
        if status == 'unreadable' and raw.strip():
            raise ValueError('Unreadable values must remain blank')
        rows.append({**cell, 'status': status, 'final': value if status == 'confirmed' else None})
    return rows


def deliver(job, review):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    packet_path = job / 'packet.json'
    packet = read_json(packet_path)
    rows = validated_rows(packet, read_json(review), digest(packet_path))
    if digest(job / 'source.pdf') != packet['source_sha256'] or digest(job / 'manifest.json') != packet['manifest']:
        raise ValueError('Source or manifest changed')
    for page in read_json(job / 'manifest.json')['pages']:
        if digest(job / f'page-{page["page"]}.png') != page['sha256']:
            raise ValueError('Page changed')
    for c in rows:
        if digest(job / 'crops' / f'{c["id"]}.png') != c['crop_sha256']:
            raise ValueError('Crop changed')
    out = job / 'delivery.xlsx'
    if out.exists():
        raise FileExistsError(out)
    wb = Workbook()
    audit = wb.active
    audit.title = 'Review'
    audit.append(['Page','Row','Column','Source bounds (px)','Initial OCR','Final value','Review status'])
    audit.freeze_panes = 'A2'
    sheets = {}
    for c in rows:
        if c['page'] not in sheets:
            sheets[c['page']] = wb.create_sheet(f'Page {c["page"]}')
        sheet = sheets[c['page']]
        # Excel preserves only 15 significant numeric digits. Keep larger values as text.
        v = c['final']
        if v is not None:
            v = str(v) if len(v.as_tuple().digits) > 15 else v
        dest = sheet.cell(c['row'], c['column'], v)
        if c['status'] == 'unreadable':
            dest.fill = PatternFill('solid', fgColor='FFF0B3')
        audit.append([c['page'],c['row'],c['column'],','.join(map(str,c['box'])),c['initial'],v,c['status']])
        # OCR is untrusted text, never an Excel formula.
        audit.cell(audit.max_row, 5).data_type = 's'
    for cell in audit[1]:
        cell.font = Font(bold=True, color='FFFFFF')
        cell.fill = PatternFill('solid', fgColor='24455F')
    for column,width in zip('ABCDEFG',[12,12,12,26,24,24,20]):
        audit.column_dimensions[column].width = width
    audit.auto_filter.ref = audit.dimensions
    wb.save(out)
    write_json(job / 'review-submission.json', read_json(review))
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('prepare'); p.add_argument('pdf', type=Path); p.add_argument('job', type=Path); p.add_argument('--pages', type=int, nargs='+', required=True)
    p = sub.add_parser('extract'); p.add_argument('job', type=Path); p.add_argument('mapping', type=Path)
    p = sub.add_parser('deliver'); p.add_argument('job', type=Path); p.add_argument('review', type=Path)
    args = parser.parse_args()
    if args.action == 'prepare':
        prepare(args.pdf, args.job, args.pages); print(args.job / 'map.html')
    elif args.action == 'extract':
        extract(args.job, args.mapping); print(args.job / 'review.html')
    else:
        print(deliver(args.job, args.review))


if __name__ == '__main__':
    main()
