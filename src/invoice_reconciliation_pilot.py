"""Local, anonymized two-file reconciliation diagnostic. Not accounting advice."""
from __future__ import annotations

from collections import Counter, defaultdict
import csv
from decimal import Decimal
import io
import re

MAX_ROWS = 1000
MAX_BYTES = 2_000_000
INVOICE_HEADER = ('invoice_id', 'amount', 'currency')
PAYMENT_HEADER = ('payment_id', 'invoice_id', 'amount', 'currency')


def _read(text, header):
    if len(text.encode('utf-8')) > MAX_BYTES:
        raise ValueError('file size exceeded')
    reader = csv.reader(io.StringIO(text.removeprefix('\ufeff')), strict=True)
    if tuple(next(reader, [])) != header:
        raise ValueError('unexpected header')
    rows = []
    for ordinal, row in enumerate(reader, 1):
        if ordinal > MAX_ROWS or len(row) != len(header):
            raise ValueError('row limit or shape')
        item = dict(zip(header, row))
        for key in ('invoice_id', 'payment_id'):
            if key in item and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', item[key]):
                raise ValueError('nonconforming anonymized id')
        if not re.fullmatch(r'[0-9]{1,12}(?:\.[0-9]{1,2})?', item['amount']) or Decimal(item['amount']) <= 0:
            raise ValueError('unsupported amount')
        if item['currency'] not in ('USD', 'GBP', 'CAD', 'EUR', 'KRW'):
            raise ValueError('unsupported currency')
        if item['currency'] == 'KRW' and Decimal(item['amount']) % 1:
            raise ValueError('fractional KRW')
        item.update(amount=Decimal(item['amount']), row=ordinal)
        rows.append(item)
    return rows


def reconcile(invoice_csv, payment_csv):
    invoices = _read(invoice_csv, INVOICE_HEADER)
    payments = _read(payment_csv, PAYMENT_HEADER)
    if not invoices:
        raise ValueError('invoice file empty')
    i_counts = Counter(x['invoice_id'] for x in invoices)
    p_counts = Counter(x['payment_id'] for x in payments)
    currencies = {x['invoice_id']: x['currency'] for x in invoices}
    blocked = {k for k, count in i_counts.items() if count > 1}
    for p in payments:
        key = p['invoice_id']
        if p_counts[p['payment_id']] > 1 or (key in currencies and p['currency'] != currencies[key]):
            blocked.add(key)
    allocated = defaultdict(list)
    unmatched, review = [], []
    for p in payments:
        key = p['invoice_id']
        if key in blocked:
            review.append(p['row'])
        elif key not in currencies:
            unmatched.append(p['row'])
        else:
            allocated[key].append(p)
    results = []
    for inv in invoices:
        key = inv['invoice_id']
        row = {'row': inv['row'], 'invoice_id': key, 'currency': inv['currency'], 'amount': f"{inv['amount']:.2f}"}
        if key in blocked:
            row.update(state='review', balance=None, paid=None, payment_rows=[], reason='duplicate_id_or_currency_conflict')
        else:
            matched = allocated[key]
            paid = sum((p['amount'] for p in matched), Decimal(0))
            balance = inv['amount'] - paid
            state = 'matched' if balance == 0 else 'overpaid' if balance < 0 else 'partial' if paid else 'unpaid'
            row.update(state=state, balance=f'{balance:.2f}', paid=f'{paid:.2f}', payment_rows=[p['row'] for p in matched])
        results.append(row)
    return {'invoices': results, 'unmatched_payments': unmatched, 'review_payments': review,
            'counts': {'invoice_rows': len(invoices), 'payment_rows': len(payments),
                       'allocated_payment_rows': sum(map(len, allocated.values())),
                       'unmatched_payment_rows': len(unmatched), 'review_payment_rows': len(review)}}
