"""Compatibility and independence of the local delivery workflows."""
import ast
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SERVICES = (
    ('src.spreadsheet_pilot', 'src.services.spreadsheet'),
    ('src.periodic_report', 'src.services.periodic_report'),
    ('src.invoice_reconciliation_pilot', 'src.services.invoice_reconciliation'),
)


@pytest.mark.parametrize('old,new', SERVICES)
def test_legacy_service_imports_same_module(old, new):
    assert importlib.import_module(old) is importlib.import_module(new)


def test_report_reuses_canonical_spreadsheet():
    sheet = importlib.import_module('src.services.spreadsheet')
    report = importlib.import_module('src.services.periodic_report')
    assert report.reconcile is sheet.reconcile
    assert report.export_review_package is sheet.export_review_package


def _cli(module, *args):
    return subprocess.run([sys.executable, '-m', module, *map(str, args)],
                          cwd=ROOT, capture_output=True, text=True, check=True)


@pytest.mark.parametrize('old,new', SERVICES[:2])
def test_both_spreadsheet_and_report_clis_help(old, new):
    legacy = _cli(old, '--help').stdout
    canonical = _cli(new, '--help').stdout
    assert legacy.replace(old.rsplit('.', 1)[-1]+'.py', 'service.py').split() == canonical.replace(new.rsplit('.', 1)[-1]+'.py', 'service.py').split()


@pytest.mark.parametrize('old,new', SERVICES[:2])
def test_both_spreadsheet_and_report_clis(tmp_path, old, new):
    files = tmp_path/'source.csv'
    files.write_text('id,day,group,qty\n001,2026-09-01,A,3\n001,2026-09-01,A,3\n002,2026-09-02,B,4\n', encoding='utf-8')
    args = ['--key', 'id']
    if old.endswith('periodic_report'):
        pytest.importorskip('openpyxl')
        args += ['--date-field','day','--category-field','group','--quantity-field','qty','--frequency','monthly']
    outputs = [tmp_path/'old', tmp_path/'new']
    for mod, dest in zip((old,new),outputs):
        result = _cli(mod, *args, '--output', dest, files)
        assert json.loads(result.stdout) == {'accepted': 2, 'duplicates': 1, 'exceptions': 0}
    for item in ('review.json','clean-draft.csv','duplicates.csv','unresolved.csv'):
        assert (outputs[0]/item).read_bytes() == (outputs[1]/item).read_bytes()
    if old.endswith('periodic_report'):
        from openpyxl import load_workbook
        books = [load_workbook(path/'delivery-draft.xlsx', data_only=True) for path in outputs]
        try:
            assert books[0].sheetnames == books[1].sheetnames
            for name in books[0].sheetnames:
                assert list(books[0][name].values) == list(books[1][name].values)
        finally:
            for book in books: book.close()


def test_services_import_without_local_data_or_output(tmp_path):
    script = ';'.join(f'import {module}' for pair in SERVICES for module in pair)
    result = subprocess.run([sys.executable,'-c',script], cwd=tmp_path,
                            env={**os.environ,'PYTHONPATH':str(ROOT),'PYTHONDONTWRITEBYTECODE':'1'},
                            capture_output=True, text=True, check=True)
    assert result.stdout == result.stderr == ''
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('filename,args,expected', [
    ('spreadsheet_pilot.py', ['--help'], '--key'),
    ('invoice_reconciliation_pilot.py', [], ''),
])
def test_original_standalone_script_invocation(tmp_path, filename, args, expected):
    result = subprocess.run([sys.executable, str(ROOT/'src'/filename), *args], cwd=tmp_path,
                            env={**{k:v for k,v in os.environ.items() if k != 'PYTHONPATH'},
                                 'PYTHONDONTWRITEBYTECODE':'1'}, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert expected in result.stdout and not result.stderr


def test_scanned_order_alias():
    old = importlib.import_module('src.scanned_pdf_experiment.order')
    new = importlib.import_module('src.services.scanned_pdf.order')
    assert old is new
    from src.scanned_pdf_experiment.numeric_reread import parse_number
    assert new.parse_number is parse_number


def test_scanned_order_resource_resolution(tmp_path):
    order = importlib.import_module('src.services.scanned_pdf.order')
    assert order.OCR_SCRIPT.resolve() == ROOT/'src/scanned_pdf_experiment/local_ocr.cjs'
    assert order.OCR_SCRIPT.is_file()
    for template, name in [('scanned_pdf_order_map.html', 'map.html'), ('scanned_pdf_order_review.html', 'review.html')]:
        dest = tmp_path/name
        order.html_packet(dest, template, {'example': '<demo>'})
        text = dest.read_text(encoding='utf-8')
        assert '__PAYLOAD__' not in text
        assert '"example": "\\u003cdemo>"' in text


def test_scanned_order_both_clis():
    old = _cli('src.scanned_pdf_experiment.order', '--help').stdout
    new = _cli('src.services.scanned_pdf.order', '--help').stdout
    assert old == new and '{prepare,extract,deliver}' in old


ENGINE = ('src.contracts', 'src.extraction', 'src.source_spike',
          'src.research_console', 'src.evidence_pilot_cli')
DELIVERY = ('src.services', *(old for old, _ in SERVICES), 'src.scanned_pdf_experiment.order')


def _matches(name, prefixes):
    return any(name == p or name.startswith(p+'.') for p in prefixes)


def _imports(path, root):
    package = '.'.join(path.relative_to(root).parts[:-1])
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
        if isinstance(node, ast.Import):
            names.update(item.name for item in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ''
            if node.level:
                module = importlib.util.resolve_name('.'*node.level + module, package)
            names.add(module)
            names.update(f'{module}.{item.name}' for item in node.names)
    return names


def _boundary_violations(root):
    errors = []
    for path in sorted((root/'src').rglob('*.py')):
        module = '.'.join(path.relative_to(root).with_suffix('').parts)
        imports = _imports(path, root)
        if _matches(module, ENGINE):
            forbidden = {n for n in imports if _matches(n, DELIVERY)}
        elif _matches(module, ('src.services',)):
            forbidden = {n for n in imports if _matches(n, ENGINE+('experiments',))}
            forbidden |= {n for n in imports if _matches(n, ('src.scanned_pdf_experiment',)) and not (
                module == 'src.services.scanned_pdf.order' and _matches(n, ('src.scanned_pdf_experiment.numeric_reread',)))}
        else:
            continue
        errors.extend((str(path.relative_to(root)), name) for name in sorted(forbidden))
    for location in ('src/services', 'experiments'):
        errors.extend((str(path.relative_to(root)), 'generated file')
                      for path in (root/location).rglob('*')
                      if path.is_file() and path.suffix.lower() in {'.pdf','.png','.xlsx'})
    return errors


def test_engine_delivery_and_experiment_boundaries():
    assert _boundary_violations(ROOT) == []


@pytest.mark.parametrize('filename,source,expected',[
    ('src/extraction/test_module.py','from src.services import spreadsheet','src.services'),
    ('src/source_spike/test_module.py','from src import periodic_report','src.periodic_report'),
    ('src/services/test_module.py','from src.extraction import rule_baseline','src.extraction'),
    ('src/services/test_module.py','from ..source_spike import collection','src.source_spike'),
    ('src/services/test_module.py','import src.scanned_pdf_experiment.numeric_reread','src.scanned_pdf_experiment.numeric_reread'),
    ('experiments/output.pdf','not a real PDF','generated file'),
])
def test_boundary_guard_detects_injected_violation(tmp_path, filename, source, expected):
    path = tmp_path/filename
    path.parent.mkdir(parents=True)
    path.write_text(source, encoding='utf-8')
    assert (filename,expected) in _boundary_violations(tmp_path)
