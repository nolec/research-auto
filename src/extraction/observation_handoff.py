"""Information-preserving pre-handoff only; never cluster, judge, or publish."""
from __future__ import annotations

from copy import deepcopy
from typing import Mapping

from src.extraction import development_slice

# Required consumer fields not supplied by the current extraction observation contract.
# This is a contract gap, not a finding that the information is absent in the world.
_UNSUPPLIED_CONSUMER_FIELDS = (
    "problem_key",
    "productizable_scope",
    "evidence.evidence_id",
    "evidence.author_hash",
    "evidence.community",
    "evidence.evidence_group_id",
    "evidence.kind",
    "evidence.interpretation",
)


def prepare_cluster_handoff(
    document: Mapping[str, object], extraction: Mapping[str, object]
) -> dict[str, object]:
    """Validate once, preserve the observation, and stop before any consumer call.

    No ready path is supported by this contract. In particular, a single observation
    does not supply author identity, independence, or a productizable scope.
    Invalid extractions propagate the existing validation exception unchanged.
    """
    snapshot = deepcopy(
        development_slice.extraction_to_observation(document, extraction)
    )
    abstained = snapshot["status"] == "ABSTAINED"
    return {
        "status": "ABSTAINED" if abstained else "NEEDS_INFORMATION",
        "document_id": snapshot["document_id"],
        "input_snapshot": snapshot,
        "consumer_input": None,
        "cards": None,
        "missing_fields": [] if abstained else list(_UNSUPPLIED_CONSUMER_FIELDS),
        "downstream_status": "NOT_RUN",
    }
