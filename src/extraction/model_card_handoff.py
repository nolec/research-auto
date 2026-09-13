"""Same-process custody boundary from one-shot model calibration to reviewable cards."""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import socket
import tempfile
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Callable, Mapping, Sequence
from uuid import uuid4

from jsonschema import ValidationError

from src.contracts.validation import validate_contract
from src.extraction.model_runner import ModelCalibrationFailure, ModelCalibrationRun
from src.extraction.opportunity_slice import render_card_markdown


_ROOT = Path(__file__).resolve().parents[2]
_CARD_SCHEMA = json.loads((_ROOT / "schemas/opportunity-card.schema.json").read_text())
_PREFLIGHT_SCHEMA = json.loads(
    (_ROOT / "schemas/model-provider-preflight-receipt.schema.json").read_text()
)
_RECEIPT_SCHEMA = json.loads(
    (_ROOT / "schemas/model-backed-card-generation-receipt.schema.json").read_text()
)
_FAILURE_RECEIPT_SCHEMA = json.loads(
    (_ROOT / "schemas/model-backed-card-generation-failure-receipt.schema.json").read_text()
)
_STATE_RECEIPT_SCHEMA = json.loads(
    (_ROOT / "schemas/model-backed-card-generation-state-receipt.schema.json").read_text()
)
_POLICY_VERSION = "model-backed-card-generation-v1"

CalibrationRunner = Callable[[], ModelCalibrationRun]
CardBuilder = Callable[
    [tuple[dict[str, object], ...], Mapping[str, object]],
    Sequence[Mapping[str, object]],
]


class HandoffBlocked(RuntimeError):
    """The one-shot pipeline stopped without publishing a candidate artifact set."""


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _digest(value: object) -> str:
    return sha256(_canonical_bytes(value)).hexdigest()


def _write_private(path: Path, payload: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def _classify_existing_reservation(destination: Path) -> None:
    marker = destination / "state-receipt.json"
    try:
        receipt = json.loads(marker.read_text())
        validate_contract(receipt, _STATE_RECEIPT_SCHEMA)
    except (OSError, json.JSONDecodeError, ValidationError):
        raise HandoffBlocked("artifact_destination_exists") from None
    if (destination / "receipt.json").exists() or (
        destination / "failure-receipt.json"
    ).exists():
        raise HandoffBlocked("artifact_destination_exists")
    try:
        descriptor = os.open(destination / ".handoff.lock", os.O_RDWR)
    except OSError:
        raise HandoffBlocked("artifact_destination_orphaned") from None
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(descriptor)
        raise HandoffBlocked("artifact_destination_active") from None
    fcntl.flock(descriptor, fcntl.LOCK_UN)
    os.close(descriptor)
    raise HandoffBlocked("artifact_destination_orphaned")


def _reserve_destination(
    destination: Path, preflight_receipt: Mapping[str, object]
) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.mkdir(destination, 0o700)
    except FileExistsError:
        _classify_existing_reservation(destination)
    descriptor: int | None = None
    try:
        descriptor = os.open(
            destination / ".handoff.lock",
            os.O_RDWR | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        marker = {
            "schema_version": "model-backed-card-generation-state-receipt/v1",
            "status": "IN_PROGRESS",
            "preflight_receipt_sha256": _digest(preflight_receipt),
            "owner_token": uuid4().hex,
            "owner_host": socket.gethostname(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        validate_contract(marker, _STATE_RECEIPT_SCHEMA)
        _write_private(
            destination / "state-receipt.json",
            json.dumps(marker, sort_keys=True, indent=2).encode() + b"\n",
        )
        return descriptor
    except Exception as error:
        if descriptor is not None:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)
        for name in ("state-receipt.json", ".handoff.lock"):
            path = destination / name
            if path.exists():
                path.unlink()
        try:
            destination.rmdir()
        except OSError:
            pass
        raise HandoffBlocked("reservation_publication_failed") from error


def _release_reservation(destination: Path, descriptor: int) -> None:
    lock_path = destination / ".handoff.lock"
    if lock_path.exists():
        lock_path.unlink()
    fcntl.flock(descriptor, fcntl.LOCK_UN)
    os.close(descriptor)


def _artifact_bytes(
    cards: Sequence[Mapping[str, object]], markdown: str
) -> tuple[bytes, bytes]:
    return (
        json.dumps(cards, ensure_ascii=False, sort_keys=True, indent=2).encode() + b"\n",
        markdown.encode() + b"\n",
    )


def _publish_artifacts(
    destination: Path,
    *,
    cards_bytes: bytes,
    markdown_bytes: bytes,
    receipt: Mapping[str, object],
) -> None:
    temporary = Path(tempfile.mkdtemp(prefix=".publish-", dir=destination))
    try:
        _write_private(temporary / "cards.json", cards_bytes)
        _write_private(temporary / "cards.md", markdown_bytes)
        _write_private(
            temporary / "receipt.json",
            json.dumps(receipt, sort_keys=True, indent=2).encode() + b"\n",
        )
        for name in ("cards.json", "cards.md", "receipt.json"):
            os.rename(temporary / name, destination / name)
        (destination / "state-receipt.json").unlink()
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def _publish_failure_receipt(
    destination: Path,
    *,
    reason: str,
    preflight_receipt: Mapping[str, object],
    model_receipt: Mapping[str, object] | None,
) -> None:
    receipt: dict[str, object] = {
        "schema_version": "model-backed-card-generation-failure-receipt/v1",
        "status": "BLOCKED",
        "reason": reason,
        "preflight_receipt_sha256": _digest(preflight_receipt),
        "model_outputs_persisted": False,
        "raw_responses_persisted": False,
    }
    if model_receipt is not None:
        receipt["model_run_receipt_sha256"] = _digest(model_receipt)
        output_hash = model_receipt.get("output_sha256")
        if isinstance(output_hash, str):
            receipt["model_output_sha256"] = output_hash
    validate_contract(receipt, _FAILURE_RECEIPT_SCHEMA)
    for name in ("cards.json", "cards.md", "receipt.json"):
        path = destination / name
        if path.exists():
            path.unlink()
    _write_private(
        destination / "failure-receipt.json",
        json.dumps(receipt, sort_keys=True, indent=2).encode() + b"\n",
    )
    marker = destination / "state-receipt.json"
    if marker.exists():
        marker.unlink()


def _validate_preflight(receipt: Mapping[str, object]) -> None:
    try:
        validate_contract(dict(receipt), _PREFLIGHT_SCHEMA)
    except ValidationError as error:
        raise HandoffBlocked("preflight_contract_invalid") from error
    if (
        receipt.get("status") != "PASS"
        or receipt.get("metric_claim_unchanged") is not True
        or receipt.get("structured_output_valid") is not True
        or receipt.get("semantic_sanity_valid") is not True
        or not isinstance(receipt.get("resolved_model"), str)
        or receipt.get("request_count", 0) < 1
    ):
        raise HandoffBlocked("preflight_not_pass")


def _validate_model_run(
    run: ModelCalibrationRun, preflight_receipt: Mapping[str, object]
) -> None:
    receipt = run.receipt
    if (
        receipt.get("schema_version") != "model-calibration-run-receipt/v1"
        or receipt.get("status") != "success"
        or receipt.get("outputs_persisted") is not False
        or receipt.get("raw_responses_persisted") is not False
        or receipt.get("output_count") != len(run.outputs)
        or receipt.get("valid_count") != len(run.outputs)
        or receipt.get("invalid_count") != 0
        or receipt.get("requested_model") != preflight_receipt.get("requested_model")
        or receipt.get("profile_sha256") != preflight_receipt.get("profile_sha256")
        or receipt.get("prompt_sha256") != preflight_receipt.get("prompt_sha256")
        or receipt.get("output_schema_sha256")
        != preflight_receipt.get("output_schema_sha256")
        or receipt.get("resolved_models") != [preflight_receipt.get("resolved_model")]
    ):
        raise HandoffBlocked("model_run_not_eligible")
    if receipt.get("output_sha256") != _digest(run.outputs):
        raise HandoffBlocked("model_output_hash_mismatch")


def _validate_cards(
    cards: Sequence[Mapping[str, object]], model_receipt: Mapping[str, object]
) -> list[dict[str, object]]:
    if len(cards) < 3:
        raise HandoffBlocked("insufficient_card_count")
    requested_model = model_receipt.get("requested_model")
    prompt_sha = model_receipt.get("prompt_sha256")
    model_sources = set(model_receipt.get("sources", []))
    normalized: list[dict[str, object]] = []
    observed_sources: set[str] = set()
    for card in cards:
        value = dict(card)
        try:
            validate_contract(value, _CARD_SCHEMA)
        except ValidationError as error:
            raise HandoffBlocked("card_contract_invalid") from error
        sources = value.get("source_versions")
        if not isinstance(sources, Mapping):
            raise HandoffBlocked("card_provenance_invalid")
        observed_sources.update(str(source) for source in sources)
        if (
            value.get("model_version") != requested_model
            or value.get("prompt_version") != prompt_sha
            or value.get("policy_version") != _POLICY_VERSION
        ):
            raise HandoffBlocked("card_provenance_invalid")
        normalized.append(value)
    if not model_sources or observed_sources != model_sources:
        raise HandoffBlocked("card_source_membership_mismatch")
    return normalized


def _execute_reserved_handoff(
    *,
    preflight_receipt: Mapping[str, object],
    run_calibration: CalibrationRunner,
    build_cards: CardBuilder,
    artifact_root: Path,
) -> dict[str, object]:
    run: ModelCalibrationRun | None = None
    try:
        run = run_calibration()
    except ModelCalibrationFailure as error:
        _publish_failure_receipt(
            artifact_root,
            reason="calibration_not_success",
            preflight_receipt=preflight_receipt,
            model_receipt=error.receipt,
        )
        raise HandoffBlocked("calibration_not_success") from error
    except Exception as error:
        _publish_failure_receipt(
            artifact_root,
            reason="calibration_unexpected_failure",
            preflight_receipt=preflight_receipt,
            model_receipt=None,
        )
        raise HandoffBlocked("calibration_unexpected_failure") from error
    try:
        _validate_model_run(run, preflight_receipt)
        try:
            built_cards = build_cards(run.outputs, run.receipt)
        except Exception as error:
            raise HandoffBlocked("card_build_failed") from error
        cards = _validate_cards(built_cards, run.receipt)
        markdown = "\n\n---\n\n".join(render_card_markdown(card) for card in cards)
        cards_bytes, markdown_bytes = _artifact_bytes(cards, markdown)
    except HandoffBlocked as error:
        _publish_failure_receipt(
            artifact_root,
            reason=str(error),
            preflight_receipt=preflight_receipt,
            model_receipt=run.receipt,
        )
        raise
    receipt = {
        "schema_version": "model-backed-card-generation-receipt/v1",
        "status": "CANDIDATE_ONLY",
        "policy_version": _POLICY_VERSION,
        "preflight_receipt_sha256": _digest(preflight_receipt),
        "model_run_receipt_sha256": _digest(run.receipt),
        "model_output_sha256": run.receipt["output_sha256"],
        "cards_sha256": sha256(cards_bytes).hexdigest(),
        "markdown_sha256": sha256(markdown_bytes).hexdigest(),
        "card_count": len(cards),
        "artifacts": ["cards.json", "cards.md"],
        "model_outputs_persisted": False,
        "raw_responses_persisted": False,
        "promotion_allowed": False,
        "source_eligibility_required": True,
    }
    validate_contract(receipt, _RECEIPT_SCHEMA)
    try:
        _publish_artifacts(
            artifact_root,
            cards_bytes=cards_bytes,
            markdown_bytes=markdown_bytes,
            receipt=receipt,
        )
    except Exception as error:
        _publish_failure_receipt(
            artifact_root,
            reason="artifact_publication_failed",
            preflight_receipt=preflight_receipt,
            model_receipt=run.receipt,
        )
        raise HandoffBlocked("artifact_publication_failed") from error
    return receipt


def execute_same_process_card_handoff(
    *,
    preflight_receipt: Mapping[str, object],
    run_calibration: CalibrationRunner,
    build_cards: CardBuilder,
    artifact_root: Path,
) -> dict[str, object]:
    """Consume model outputs in memory and publish only cards plus aggregate hashes."""
    _validate_preflight(preflight_receipt)
    descriptor = _reserve_destination(artifact_root, preflight_receipt)
    try:
        return _execute_reserved_handoff(
            preflight_receipt=preflight_receipt,
            run_calibration=run_calibration,
            build_cards=build_cards,
            artifact_root=artifact_root,
        )
    finally:
        _release_reservation(artifact_root, descriptor)
