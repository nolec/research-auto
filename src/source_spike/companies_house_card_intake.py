"""Bounded, deterministic pilot for public Companies House card payments."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
import io
import json
from pathlib import Path
import re
from urllib.request import HTTPRedirectHandler, Request, build_opener

from src.extraction.codex_cli_diagnostic import _private_create

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'artifacts/extraction/calibration/audit-local/companies-house-card-pilot-20261123'
HOST = 'https://assets.publishing.service.gov.uk/media/'
FILES = {
    '2025-01': HOST + '67adea8aa1d2c59f9ba29ac7/January_2025_GPC_spend.csv',
    '2025-02': HOST + '67d82770752bf117d6c15e7d/February_2025_GPC_spend.csv',
    '2025-03': HOST + '6814c72b359707ba3d44677d/March_2025_GPC_spend.csv',
}
MAX_BYTES = 65536
MAX_ROWS = 100
CATEGORIES = {x.casefold(): x for x in ('Software as a Service', 'Software', 'Software Licences', 'Software License',
    'IT Equipment', 'Office Equipment', 'Office Supplies', 'Stationery', 'Training', 'H & S Equipment')}
FIELDS = ('department family', 'entity', 'date', 'expense type', 'expense area', 'supplier', 'amount in sterling')


def parse_csv(raw: bytes, month: str) -> dict:
    if month not in FILES or len(raw) > MAX_BYTES:
        raise ValueError('invalid month or file size')
    try:
        decoded = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        decoded = raw.decode('cp1252')
    data = csv.reader(io.StringIO(decoded), strict=True)
    header = next(data, [])
    if tuple(s.strip().casefold() for s in header) != FIELDS:
        raise ValueError('unexpected CSV header')
    counts = Counter(rows=0, retained=0)
    records = []
    seen = set()
    for ordinal, row in enumerate(data, 1):
        if ordinal > MAX_ROWS:
            raise ValueError('row cap exceeded')
        if not row or all(not x.strip() for x in row):
            continue
        counts['rows'] += 1
        if len(row) != len(FIELDS):
            raise ValueError('invalid row shape')
        family, entity, date_raw, category, _area, _supplier, amount_raw = (x.strip() for x in row)
        if family.casefold() != 'companies house' or entity.casefold() != 'ch':
            raise ValueError('unexpected agency')
        if date_raw.casefold() in ('zero return', 'nil return') and amount_raw.casefold() == date_raw.casefold():
            counts['zero_return'] += 1
            continue
        date = datetime.strptime(date_raw, '%d/%m/%Y').date().isoformat()
        if not re.fullmatch(r'-?£?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d{1,2})?', amount_raw):
            raise ValueError('invalid amount')
        amount = Decimal(amount_raw.replace('£', '').replace(',', ''))
        if date[:7] != month:
            counts['out_of_month'] += 1
            continue
        if amount <= 0:
            counts['nonpositive'] += 1
            continue
        canonical = CATEGORIES.get(category.casefold())
        if canonical is None:
            counts['category_excluded'] += 1
            continue
        key = (date, canonical, amount)
        if key in seen:
            counts['duplicate'] += 1
            continue
        seen.add(key)
        records.append({'month': month, 'row': ordinal, 'date': date, 'expense_type': canonical,
                        'amount': f'{amount:.2f}', 'currency': 'GBP'})
        counts['retained'] += 1
    return {'counts': dict(counts), 'records': records}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_csv(url: str) -> bytes:
    if url not in FILES.values():
        raise ValueError('URL not in frozen manifest')
    opener = build_opener(NoRedirect())
    req = Request(url, headers={'Accept': 'text/csv', 'User-Agent': 'research-auto-bounded-pilot/1.0'})
    with opener.open(req, timeout=25) as response:
        if response.status != 200 or response.headers.get_content_type() not in ('text/csv', 'application/octet-stream', 'application/csv'):
            raise ValueError('unexpected HTTP response')
        content = response.read(MAX_BYTES + 1)
        if len(content) > MAX_BYTES:
            raise ValueError('response cap exceeded')
        return content


def run(out: Path, fetch=fetch_csv):
    out.mkdir(mode=0o700, exist_ok=False)
    _private_create(out / 'claim.json', {'files': FILES, 'max_bytes': MAX_BYTES, 'max_rows': MAX_ROWS,
                                       'implementation_sha256': sha256(Path(__file__).read_bytes()).hexdigest()})
    receipts = []
    records = []
    status = 'COLLECTED_GOLD_PENDING'
    for month, url in FILES.items():
        try:
            raw = fetch(url)
            result = parse_csv(raw, month)
            receipts.append({'month': month, 'source_url': url, 'counts': result['counts'],
                             'raw_sha256': sha256(raw).hexdigest()})
            records.extend({**record, 'source_url': url} for record in result['records'])
        except Exception as error:
            receipts.append({'month': month, 'source_url': url, 'status': 'FAILED', 'error_class': type(error).__name__})
            status = 'INCOMPLETE'
            break
    result = {'status': status, 'scope': 'reported card spending only; not V7 evaluation', 'files': receipts, 'records': records}
    _private_create(out / 'result.json', result)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--execute', action='store_true', required=True)
    p.parse_args()
    r = run(OUT)
    print(json.dumps({'status': r['status'], 'files_attempted': len(r['files']), 'retained': len(r['records']),
                      'result': str(OUT / 'result.json')}))
    return 0 if r['status'] == 'COLLECTED_GOLD_PENDING' else 1


if __name__ == '__main__':
    raise SystemExit(main())
