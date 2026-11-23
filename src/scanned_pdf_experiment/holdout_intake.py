"""Read-only intake checks for new public scanned document candidates.

This is an eligibility preflight, not a truth verifier or benchmark runner.
The selected page and table scope must be specified independently of OCR output.
"""

from dataclasses import dataclass
from hashlib import file_digest
from pathlib import Path
import subprocess


@dataclass(frozen=True)
class Candidate:
    identifier: str
    pdf: Path
    source_url: str
    pages: tuple[int, ...]
    table_scope: str
    rights_basis: str


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return file_digest(stream, 'sha256').hexdigest()


def inspect_candidate(candidate: Candidate, *, pdftotext: Path, pdfimages: Path) -> dict:
    if not candidate.identifier or not candidate.source_url.startswith('https://'):
        raise ValueError('Candidate requires identifier and HTTPS provenance')
    if not candidate.table_scope.strip() or not candidate.rights_basis.strip():
        raise ValueError('Explicit table scope and rights evidence required')
    if not 1 <= len(candidate.pages) <= 2 or any(p < 1 for p in candidate.pages):
        raise ValueError('Scope must use one or two positive PDF page numbers')
    if len(set(candidate.pages)) != len(candidate.pages):
        raise ValueError('Duplicate selected pages')
    if not candidate.pdf.is_file():
        raise FileNotFoundError(candidate.pdf)
    initial_digest = digest(candidate.pdf)
    pages = []
    for page in candidate.pages:
        flags = ['-f', str(page), '-l', str(page)]
        extracted = subprocess.run([str(pdftotext), *flags, str(candidate.pdf), '-'], check=True, capture_output=True, text=True, timeout=60)
        images = subprocess.run([str(pdfimages), *flags, '-list', str(candidate.pdf)], check=True, capture_output=True, text=True, timeout=60)
        image_count = sum(1 for line in images.stdout.splitlines() if len(line.split()) > 2 and line.split()[0] == str(page) and line.split()[2] == 'image')
        pages.append({'page': page, 'embedded_text_chars': len(extracted.stdout.strip()), 'image_count': image_count})
    if digest(candidate.pdf) != initial_digest:
        raise ValueError('Source changed during inspection')
    return {
        'id': candidate.identifier, 'source_url': candidate.source_url,
        'sha256': initial_digest, 'table_scope': candidate.table_scope,
        'rights_basis': candidate.rights_basis, 'pages': pages,
        'scan_preflight': all(p['embedded_text_chars'] == 0 and p['image_count'] > 0 for p in pages),
        'visual_review': 'PENDING', 'human_truth': 'PENDING',
    }


def check_cohort(records: list[dict], previously_seen: set[str], expected_count: int = 10) -> dict:
    if expected_count < 1:
        raise ValueError('Expected count must be positive')
    hashes = [r['sha256'] for r in records]
    ids = [r['id'] for r in records]
    urls = [r['source_url'] for r in records]
    if len(set(hashes)) != len(hashes) or len(set(ids)) != len(ids) or len(set(urls)) != len(urls):
        raise ValueError('Duplicate holdout source, digest or identifier')
    if set(hashes) & previously_seen:
        raise ValueError('Previously seen document bytes in holdout')
    eligible = sum(r['scan_preflight'] is True for r in records)
    return {'candidates': len(records), 'scan_preflight_passed': eligible,
            'intake_status': 'SCAN_PREFLIGHT_COMPLETE' if eligible == len(records) == expected_count else 'INCOMPLETE',
            'benchmark_status': 'PENDING', 'business': 'HOLD'}
