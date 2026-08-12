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
    stratum: str | None = None


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


def create_stratified_labeling_assignments(
    items: Sequence[Mapping[str, object]],
    *,
    seed: int,
    stratum_field: str = "community",
    sample_per_stratum: int = 5,
    development_count: int = 10,
    double_review_count: int = 5,
) -> list[LabelingAssignment]:
    """Select a deterministic balanced sample across source strata."""
    if sample_per_stratum <= 0:
        raise ValueError("sample_per_stratum must be positive")
    by_stratum: dict[str, list[tuple[str, str]]] = defaultdict(list)
    seen: set[str] = set()
    for item in items:
        document_id = str(item["document_id"])
        if document_id in seen:
            raise ValueError(f"duplicate document_id: {document_id}")
        seen.add(document_id)
        by_stratum[str(item[stratum_field])].append((str(item["source"]), document_id))
    selected: list[tuple[str, str, str]] = []
    for stratum in sorted(by_stratum):
        values = sorted(
            by_stratum[stratum],
            key=lambda value: (_score(seed, f"stratum:{stratum}", *value), value[1]),
        )
        if len(values) < sample_per_stratum:
            raise ValueError(f"{stratum} has {len(values)} items; {sample_per_stratum} required")
        selected.extend((source, document_id, stratum) for source, document_id in values[:sample_per_stratum])
    total = len(selected)
    if not 0 <= development_count <= total:
        raise ValueError("development_count must fit the selected sample")
    if not 0 <= double_review_count <= total:
        raise ValueError("double_review_count must fit the selected sample")
    development = {
        value[1]
        for value in sorted(
            selected,
            key=lambda value: (_score(seed, "stratified-split", value[0], value[1]), value[1]),
        )[:development_count]
    }
    second_review = {
        value[1]
        for value in sorted(
            selected,
            key=lambda value: (_score(seed, "stratified-double-review", value[0], value[1]), value[1]),
        )[:double_review_count]
    }
    ranked = sorted(
        selected,
        key=lambda value: (_score(seed, "stratified-rank", value[0], value[1]), value[1]),
    )
    return [
        LabelingAssignment(
            source=source,
            document_id=document_id,
            split="development" if document_id in development else "holdout",
            requires_second_review=document_id in second_review,
            sample_rank=rank,
            stratum=stratum,
        )
        for rank, (source, document_id, stratum) in enumerate(ranked, start=1)
    ]
