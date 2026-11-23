"""Frozen source-only numeric diagnostic; no CSV, draft or truth manifest access."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from PIL import Image, ImageOps, __version__ as pillow_version

ROOT = Path(__file__).resolve().parents[1]
GEOMETRY = ROOT / 'src/scanned_pdf_experiment/holdout_numeric_geometry.json'
RUNNER = ROOT / 'scripts/scanned_pdf_pilot_ocr.cjs'
MODEL = Path.home() / 'Downloads/eng.traineddata'
MODULES = Path(os.environ.get('CODEX_PRIMARY_RUNTIME_NODE_MODULES') or Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def boxes(scope, size):
    sx, sy = size[0] / scope['view_width'], size[1] / scope['view_height']
    for i, y in enumerate(scope['centers']):
        for j, (left, right) in enumerate(scope['columns']):
            center = y + scope.get('column_y_offsets', [0, 0, 0])[j]
            half = scope['half_height']
            box = tuple(round(v*s) for v,s in zip((left, center-half, right, center+half), (sx,sy,sx,sy)))
            if not (0 <= box[0] < box[2] <= size[0] and 0 <= box[1] < box[3] <= size[1]):
                raise ValueError('Invalid cell crop')
            yield i, j, box


def recognize(paths, mode):
    proc = subprocess.run(['node', str(RUNNER), str(MODEL), mode, *map(str, paths)], check=True, capture_output=True, text=True, timeout=180, env={**os.environ, 'CODEX_PRIMARY_RUNTIME_NODE_MODULES': str(MODULES)})
    results = [json.loads(line) for line in proc.stdout.splitlines()]
    if len(results) != len(paths) or any(Path(r['image']) != p for r,p in zip(results, paths)):
        raise ValueError('OCR output mismatch')
    return [{'text': r['text'].strip(), 'confidence': r['confidence']} for r in results]


def main(source, out):
    specs = json.loads(GEOMETRY.read_text())['scopes']
    files = [GEOMETRY, Path(__file__), RUNNER, MODEL, ROOT/'src/scanned_pdf_experiment/numeric_reread.py', ROOT/'src/scanned_pdf_experiment/numeric_evaluation.py', ROOT/'scripts/scanned_pdf_holdout_numeric_evaluate.py']
    files += sorted(p for m in ('tesseract.js', 'tesseract.js-core') for p in (MODULES/m).rglob('*') if p.is_file() and (p.suffix in ('.js', '.wasm') or p.name == 'package.json'))
    sources = {s['id']: source / f"{s['id']}-crop-{s['crop']}.png" for s in specs}
    out.mkdir(exist_ok=False)
    freeze = {'status':'EXPLORATORY_SAME_ENGINE_ONLY', 'node':subprocess.check_output(['node','-v'],text=True).strip(), 'pillow':pillow_version, 'hashes':{str(p):digest(p) for p in [*files,*sources.values()]}, 'first':'3x resized grayscale crop, white border 20, RAW_LINE', 'second':'original grayscale crop, SINGLE_LINE', 'fault_schedule':'row indices 0/3/6, columns 0/1/2, first numeric fallback in cyclic column order; +1000', 'read_confidence_threshold':80}
    (out/'freeze.json').write_text(json.dumps(freeze,indent=2))
    all_cells = []
    for s in specs:
        folder = out/s['id']; folder.mkdir()
        im = Image.open(sources[s['id']]).convert('L')
        cells, first_paths, raw_paths = [], [], []
        for i,j,box in boxes(s,im.size):
            raw = im.crop(box); p = folder/f'{i}-{j}.png'; raw.save(p)
            first = folder/f'{i}-{j}-first.png'; ImageOps.expand(raw.resize((raw.width*3,raw.height*3)),border=20,fill=255).save(first)
            cells.append({'id':s['id'],'row':i,'column':j,'crop_bbox':box,'crop_sha256':digest(p),'path':str(p)})
            raw_paths.append(p); first_paths.append(first)
        first = recognize(first_paths,'--raw-line')
        second = recognize(raw_paths,'--single-line')
        all_cells.extend({**cell,'first':a,'second':b} for cell,a,b in zip(cells,first,second,strict=True))
        print(s['id'],len(cells),flush=True)
    (out/'source-readings.json').write_text(json.dumps(all_cells,indent=2))


if __name__ == '__main__':
    main(*(Path(a).resolve() for a in sys.argv[1:]))
