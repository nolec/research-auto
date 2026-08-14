from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Mapping

from src.source_spike.review_handoff import write_offline_review
from src.source_spike.review_packet import build_review_packet_bundle, validate_review_packet_bundle


ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_ROOT = ROOT / "artifacts/source-spike/steam-analysis"


def _qualified_run() -> tuple[Path, Mapping[str, object]]:
    pointer_path = ARTIFACT_ROOT / "latest-qualified.json"
    if not pointer_path.is_file():
        raise ValueError("qualified analysis pointer is missing")
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    if not isinstance(pointer, Mapping):
        raise ValueError("qualified analysis pointer is malformed")
    run = ARTIFACT_ROOT / "runs" / str(pointer.get("run_id", ""))
    qualification = json.loads((run / "qualification.json").read_text(encoding="utf-8"))
    if not isinstance(qualification, Mapping):
        raise ValueError("qualification is malformed")
    if pointer.get("run_id") != qualification.get("run_id"):
        raise ValueError("pointer run id mismatch")
    if pointer.get("dataset_sha256") != qualification.get("dataset_sha256"):
        raise ValueError("pointer dataset hash mismatch")
    return run, qualification


def _validate_source(review_root: Path, qualification: Mapping[str, object]) -> Mapping[str, object]:
    manifest = validate_review_packet_bundle(review_root, dict(qualification))
    assignments = json.loads(
        (review_root / "internal/assignment-map.json").read_text(encoding="utf-8")
    )
    if not isinstance(assignments, list) or not assignments or any(
        not isinstance(value, Mapping) or value.get("source") != "steam"
        for value in assignments
    ):
        raise ValueError("review packet source must be steam")
    return manifest


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0].startswith("-"):
        arguments.insert(0, "packet")
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    packet = subparsers.add_parser("packet")
    packet.add_argument("--review-root", type=Path)
    args = parser.parse_args(arguments)
    try:
        run, qualification = _qualified_run()
        destination = args.review_root or (run / "review")
        manifest = build_review_packet_bundle(run, destination)
        _validate_source(destination, qualification)
        handoff = destination / "handoff"
        handoff.mkdir(exist_ok=True)
        write_offline_review(
            destination / "packet/primary.json",
            handoff / "primary-review.html",
            title="Steam Primary Blind Review",
            review_role="primary",
        )
        write_offline_review(
            destination / "packet/secondary.json",
            handoff / "secondary-review.html",
            title="Steam Secondary Blind Review",
            review_role="secondary",
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"Steam blind packet failed: {error}")
        return 3
    print(
        "Steam blind packet primary=20 secondary=5 "
        f"root={destination} dataset={manifest['dataset_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
