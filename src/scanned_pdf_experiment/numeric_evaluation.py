"""Evaluator-only scoring: uncertain alerts never count as detections."""

from collections import Counter
from typing import Iterable

from .numeric_reread import Decision


def score_numeric(expected_cells: Iterable[tuple[str, int, str]], decisions: Iterable[Decision]) -> dict:
    expected = Counter(expected_cells)
    tp = fp = uncertain = 0
    for decision in decisions:
        if decision.status == "UNCERTAIN":
            uncertain += 1
        elif decision.status == "DETECTED":
            crop = decision.candidate.crop
            key = (crop.document, crop.page, crop.cell)
            if expected[key]:
                expected[key] -= 1
                tp += 1
            else:
                fp += 1
    fn = sum(expected.values())
    return {
        "tp": tp, "fp": fp, "fn": fn, "uncertain": uncertain,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
    }
