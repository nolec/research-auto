"""Frozen v1 confirmation policy for localized numeric discrepancies.

The rereader sees a source crop only, never the spreadsheet or answer key.
This policy does not classify row swaps, column swaps, missing cells or labels.
"""

from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
from math import isfinite
import re
from typing import Callable, Iterable


POLICY_VERSION = "numeric-agreement-v1"
MIN_CONFIDENCE = 80.0
_NUMBER = re.compile(r"[+-]?(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]+)?")


def parse_number(value: str) -> Decimal | None:
    value = value.strip()
    if not _NUMBER.fullmatch(value):
        return None
    return Decimal(value.replace(",", ""))


@dataclass(frozen=True)
class SourceCrop:
    document: str
    page: int
    cell: str
    bbox: tuple[int, int, int, int]
    png: bytes

    def __post_init__(self) -> None:
        x0, y0, x1, y1 = self.bbox
        if not self.document or self.page < 1 or not self.cell or not (0 <= x0 < x1 and 0 <= y0 < y1) or not self.png:
            raise ValueError("Invalid localized source crop")

    @property
    def digest(self) -> str:
        return sha256(self.png).hexdigest()


@dataclass(frozen=True)
class NumericCandidate:
    crop: SourceCrop
    first_value: str
    sheet_value: str


@dataclass(frozen=True)
class Reading:
    text: str
    confidence: float
    crop_sha256: str


@dataclass(frozen=True)
class Decision:
    candidate: NumericCandidate
    status: str
    reason: str
    reread: Reading | None


def confirm_numeric(
    candidates: Iterable[NumericCandidate],
    reread: Callable[[SourceCrop], Reading],
) -> list[Decision]:
    """Confirm only independently agreeing numeric reads; cache per source cell.

    Disagreements or unavailable evidence stay visible, including when the
    second reading matches the spreadsheet. No source or sheet is corrected.
    """
    cache: dict[SourceCrop, Reading | None] = {}
    decisions = []
    for candidate in candidates:
        crop = candidate.crop
        first = parse_number(candidate.first_value)
        sheet = parse_number(candidate.sheet_value)
        reading = None
        if first is None or sheet is None:
            status, reason = "UNCERTAIN", "INVALID_NUMERIC_INPUT"
        elif first == sheet:
            status, reason = "NO_ALERT", "FIRST_READ_MATCHES_SHEET"
        else:
            if crop not in cache:
                try:
                    cache[crop] = reread(crop)
                except (OSError, TimeoutError, RuntimeError, ValueError):
                    cache[crop] = None
            reading = cache[crop]
            if reading is None:
                status, reason = "UNCERTAIN", "REREAD_UNAVAILABLE"
            elif reading.crop_sha256 != crop.digest:
                status, reason = "UNCERTAIN", "CROP_BINDING_MISMATCH"
            elif not isfinite(reading.confidence) or not MIN_CONFIDENCE <= reading.confidence <= 100:
                status, reason = "UNCERTAIN", "LOW_OR_INVALID_CONFIDENCE"
            elif parse_number(reading.text) is None:
                status, reason = "UNCERTAIN", "INVALID_REREAD"
            elif parse_number(reading.text) != first:
                status, reason = "UNCERTAIN", "READS_DISAGREE"
            else:
                status, reason = "DETECTED", "READS_AGREE_ON_DISCREPANCY"
        decisions.append(Decision(candidate, status, reason, reading))
    return decisions
