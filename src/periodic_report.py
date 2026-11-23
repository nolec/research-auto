"""Offline periodic-report pilot; final row dispositions feed every output."""
import argparse
import json
from datetime import date, timedelta
from pathlib import Path

from src.spreadsheet_pilot import reconcile, export_review_package


MAX_EXACT_QUANTITY = 999_999_999_999_999


def build_report(paths, *, key, date_field, category_field, quantity_field, frequency):
    fields = (key, date_field, category_field, quantity_field)
    if frequency not in ('weekly', 'monthly') or len(set(fields)) != 4:
        raise ValueError('Invalid frequency or non-distinct report fields')
    result = reconcile(paths, key)
    headers = result['headers']
    if len(headers) > 15 or any(field not in headers for field in fields):
        raise ValueError('Report requires mapped fields and at most 15 columns')
    date_ix, category_ix, quantity_ix = (headers.index(field) for field in fields[1:])
    accepted, summary = [], {}
    exceptions = list(result['exceptions'])
    for entry in result['accepted']:
        row = entry['values']
        reason = None
        try:
            day = date.fromisoformat(row[date_ix])
            if day.isoformat() != row[date_ix]:
                raise ValueError('Noncanonical date')
        except ValueError:
            reason = 'invalid_date'
        category = row[category_ix].strip()
        raw = row[quantity_ix]
        if reason is None and not category:
            reason = 'missing_category'
        if reason is None and (not raw.isascii() or not raw.isdecimal()):
            reason = 'invalid_quantity'
        if reason:
            exceptions.append({**entry, 'reason': reason})
            continue
        digits = raw.lstrip('0') or '0'
        if len(digits) > 15:
            raise ValueError('Quantity outside exact Excel scope')
        quantity = int(digits)
        period = day.isoformat()[:7] if frequency == 'monthly' else (day - timedelta(days=day.weekday())).isoformat()
        item = summary.setdefault(period, {'total': 0, 'rows': 0, 'categories': {}})
        if item['total'] + quantity > MAX_EXACT_QUANTITY:
            raise ValueError('Period total outside exact Excel scope')
        item['total'] += quantity
        item['rows'] += 1
        item['categories'][category] = item['categories'].get(category, 0) + quantity
        accepted.append(entry)
    return {**result, 'accepted': accepted, 'exceptions': exceptions, 'frequency': frequency,
            'summary': dict(sorted(summary.items())), 'report_mapping': dict(zip(('key','date','category','quantity'),fields))}


def export_report_package(result, directory):
    if 'summary' not in result or 'frequency' not in result:
        raise ValueError('Expected a periodic report result')
    export_review_package(result, directory, xlsx=True, report_summary=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ('key', 'date-field', 'category-field', 'quantity-field'):
        parser.add_argument('--'+field, required=True)
    parser.add_argument('--frequency', choices=('weekly','monthly'), required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('files', type=Path, nargs='+')
    a = parser.parse_args()
    try:
        report = build_report(a.files, key=a.key, date_field=a.date_field,
            category_field=a.category_field, quantity_field=a.quantity_field, frequency=a.frequency)
        export_report_package(report, a.output)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps({k:len(report[k]) for k in ('accepted','duplicates','exceptions')}))


if __name__ == '__main__':
    main()
