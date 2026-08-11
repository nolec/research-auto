from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from hashlib import sha256
from typing import Literal, Mapping, Sequence


AssignmentSplit = Literal["development", "holdout"]


@dataclass(frozen=True)
class LabelingAssignment:
    source: str
    document_id: str
    split: AssignmentSplit
    requires_second_review: bool
    sample_rank: int


def _score(seed: int, purpose: str, source: str, document_id: str) -> bytes:
    value = f"{seed}\0{purpose}\0{source}\0{document_id}".encode("utf-8")
    return sha256(value).digest()


def create_labeling_assignments(
    items: Sequence[Mapping[str, object]],
    *,
    seed: int,
    sample_per_source: int = 20,
    double_review_per_source: int = 5,
) -> list[LabelingAssignment]:
    """Create reproducible screening assignments without depending on input order."""
    if sample_per_source <= 0 or sample_per_source % 2:
        raise ValueError("sample_per_source must be a positive even number")
    if double_review_per_source < 0:
        raise ValueError("double_review_per_source must be non-negative")
    if double_review_per_source > sample_per_source:
        raise ValueError("double_review_per_source cannot exceed sample_per_source")

    by_source: dict[str, list[str]] = defaultdict(list)
    seen_document_ids: set[str] = set()
    for item in items:
        source = str(item["source"])
        document_id = str(item["document_id"])
        if document_id in seen_document_ids:
            raise ValueError(f"duplicate document_id: {document_id}")
        seen_document_ids.add(document_id)
        by_source[source].append(document_id)

    assignments: list[LabelingAssignment] = []
    split_size = sample_per_source // 2
    for source in sorted(by_source):
        document_ids = by_source[source]
        if len(document_ids) < sample_per_source:
            raise ValueError(
                f"{source} has {len(document_ids)} items; {sample_per_source} required"
            )

        selected = sorted(
            document_ids,
            key=lambda document_id: (
                _score(seed, "sample", source, document_id),
                document_id,
            ),
        )[:sample_per_source]
        development = set(
            sorted(
                selected,
                key=lambda document_id: (
                    _score(seed, "split", source, document_id),
                    document_id,
                ),
            )[:split_size]
        )
        second_review = set(
            sorted(
                selected,
                key=lambda document_id: (
                    _score(seed, "double-review", source, document_id),
                    document_id,
                ),
            )[:double_review_per_source]
        )

        for rank, document_id in enumerate(selected, start=1):
            assignments.append(
                LabelingAssignment(
                    source=source,
                    document_id=document_id,
                    split=(
                        "development" if document_id in development else "holdout"
                    ),
                    requires_second_review=document_id in second_review,
                    sample_rank=rank,
                )
            )
    return assignments
