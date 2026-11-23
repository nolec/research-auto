from pathlib import Path
from types import SimpleNamespace

import pytest

from src.scanned_pdf_experiment import holdout_intake as intake


def test_scan_preflight(tmp_path, monkeypatch):
    pdf = tmp_path / 'doc.pdf'
    pdf.write_bytes(b'fixture')
    candidate = intake.Candidate('new-01', pdf, 'https://example.com/a.pdf', (2,), 'table 1', 'Federal publication; verify separately')
    def run(args, **kwargs):
        return SimpleNamespace(stdout='2 0 image 900 800' if args[0] == 'pdfimages' else '\f')
    monkeypatch.setattr(intake.subprocess, 'run', run)
    record = intake.inspect_candidate(candidate, pdftotext=Path('pdftotext'), pdfimages=Path('pdfimages'))
    assert record['scan_preflight'] is True
    assert record['human_truth'] == 'PENDING'
    assert intake.check_cohort([record], set(), 1)['benchmark_status'] == 'PENDING'


def test_text_layer_or_no_image_rejected(tmp_path, monkeypatch):
    pdf = tmp_path / 'doc.pdf'
    pdf.write_bytes(b'fixture')
    c = intake.Candidate('new-01', pdf, 'https://example.com/a.pdf', (2,), 'table 1', 'pending rights')
    for text, images in [('embedded text', '2 0 image 900 800'), ('', '1 0 image 900 800')]:
        monkeypatch.setattr(intake.subprocess, 'run', lambda args, **kw: SimpleNamespace(stdout=images if args[0] == 'pdfimages' else text))
        assert intake.inspect_candidate(c, pdftotext=Path('pdftotext'), pdfimages=Path('pdfimages'))['scan_preflight'] is False


def test_duplicate_and_previously_seen_rejected():
    record = {'id': '1', 'sha256': 'hash', 'source_url': 'https://example.com/a.pdf', 'scan_preflight': True}
    with pytest.raises(ValueError, match='Duplicate'):
        intake.check_cohort([record, record], set())
    with pytest.raises(ValueError, match='Previously seen'):
        intake.check_cohort([record], {'hash'})
    assert intake.check_cohort([record], set())['intake_status'] == 'INCOMPLETE'
