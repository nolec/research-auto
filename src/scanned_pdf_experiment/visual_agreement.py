"""Numeric visual-read agreement, without fabricated confidence scores."""
from dataclasses import dataclass
from typing import Callable, Iterable

from .numeric_reread import NumericCandidate, SourceCrop, parse_number


@dataclass(frozen=True)
class VisualReading:
    text: str
    crop_sha256: str


@dataclass(frozen=True)
class VisualDecision:
    candidate: NumericCandidate
    status: str
    reason: str
    reread: VisualReading | None


def confirm_visual(candidates: Iterable[NumericCandidate], reread: Callable[[SourceCrop], VisualReading | None]) -> list[VisualDecision]:
    """Keep disagreement visible; a rereader only receives the source crop."""
    cache = {}
    result = []
    for c in candidates:
        first, sheet = parse_number(c.first_value), parse_number(c.sheet_value)
        reading = None
        if first is None or sheet is None:
            status, reason = 'UNCERTAIN', 'INVALID_NUMERIC_INPUT'
        elif first == sheet:
            status, reason = 'NO_ALERT', 'FIRST_READ_MATCHES_SHEET'
        else:
            # Cache by exact source bytes, not document variant. The reader cannot
            # see sheet values and the same source may occur in multiple variants.
            key = c.crop.digest
            if key not in cache:
                try:
                    cache[key] = reread(c.crop)
                except (OSError, TimeoutError, RuntimeError, ValueError):
                    cache[key] = None
            reading = cache[key]
            if reading is None:
                status, reason = 'UNCERTAIN', 'REREAD_UNAVAILABLE'
            elif reading.crop_sha256 != key:
                status, reason = 'UNCERTAIN', 'CROP_BINDING_MISMATCH'
            elif parse_number(reading.text) is None:
                status, reason = 'UNCERTAIN', 'INVALID_REREAD'
            elif parse_number(reading.text) != first:
                status, reason = 'UNCERTAIN', 'READS_DISAGREE'
            else:
                status, reason = 'DETECTED', 'READS_AGREE_ON_DISCREPANCY'
        result.append(VisualDecision(c,status,reason,reading))
    return result
