from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Mapping

from src.source_spike.label_ingestion import ingest_submissions
from src.source_spike.review_packet import build_review_packet_bundle, validate_review_packet_bundle
from src.source_spike.source_quality import (
    build_development_report,
    policy_sha256,
    write_development_report,
)


ROOT=Path(__file__).resolve().parents[2]
ARTIFACT_ROOT=ROOT / "artifacts/source-spike/stackexchange-analysis"


def _validate_stackexchange_review_root(review_root: Path) -> Mapping[str, object]:
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
    manifest = validate_review_packet_bundle(review_root, qualification)
    assignments = json.loads(
        (review_root / "internal/assignment-map.json").read_text(encoding="utf-8")
    )
    if not isinstance(assignments, list) or not assignments or any(
        not isinstance(value, Mapping) or value.get("source") != "stackexchange"
        for value in assignments
    ):
        raise ValueError("review packet source must be stackexchange")
    return manifest


def main(argv: list[str] | None=None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0].startswith("-"):
        arguments.insert(0, "packet")
    parser=argparse.ArgumentParser(); subparsers=parser.add_subparsers(dest="command", required=True)
    packet=subparsers.add_parser("packet"); packet.add_argument("--review-root", type=Path)
    ingest=subparsers.add_parser("ingest"); ingest.add_argument("--review-root", type=Path, required=True); ingest.add_argument("--primary", type=Path, required=True); ingest.add_argument("--secondary", type=Path, required=True)
    report=subparsers.add_parser("report-development"); report.add_argument("--review-root", type=Path, required=True)
    args=parser.parse_args(arguments)
    if args.command == "ingest":
        try:
            _validate_stackexchange_review_root(args.review_root)
            primary=[json.loads(line) for line in args.primary.read_text(encoding="utf-8").splitlines() if line]
            secondary=[json.loads(line) for line in args.secondary.read_text(encoding="utf-8").splitlines() if line]
            summary=ingest_submissions(args.review_root, primary=primary, secondary=secondary)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            print(f"Stack Exchange label ingestion failed: {error}"); return 3
        print(f"Stack Exchange labels ingested primary={summary['primary']} secondary={summary['secondary']}")
        return 0
    if args.command == "report-development":
        labels=args.review_root / "labels/development/canonical-labels.jsonl"
        if not labels.is_file():
            print("development report unavailable: canonical development labels are missing"); return 2
        try:
            packet_manifest=_validate_stackexchange_review_root(args.review_root)
            report_value=build_development_report(labels, provenance={
                "dataset_sha256": packet_manifest["dataset_sha256"],
                "manifest_hash": packet_manifest["manifest_hash"],
                "packet_file_sha256": packet_manifest["file_sha256"],
                "policy_sha256": policy_sha256(), "guide_version": "1.0.0",
            })
            write_development_report(args.review_root, report_value)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            print(f"Stack Exchange development report failed: {error}"); return 3
        print("Stack Exchange development source quality report complete; holdout remains sealed")
        return 0
    pointer_path=ARTIFACT_ROOT / "latest-qualified.json"
    if not pointer_path.is_file():
        print("Stack Exchange blind packet prerequisite failure: qualified analysis pointer is missing")
        return 3
    try: pointer=json.loads(pointer_path.read_text())
    except (OSError, json.JSONDecodeError):
        print("Stack Exchange blind packet prerequisite failure: qualified analysis pointer is malformed")
        return 3
    run=ARTIFACT_ROOT / "runs" / str(pointer.get("run_id", ""))
    if not run.is_dir():
        print("Stack Exchange blind packet prerequisite failure: qualified analysis run is missing")
        return 3
    try: qualification=json.loads((run / "qualification.json").read_text())
    except (OSError, json.JSONDecodeError):
        print("Stack Exchange blind packet prerequisite failure: qualification is malformed")
        return 3
    if pointer.get("run_id") != qualification.get("run_id"):
        print("Stack Exchange blind packet prerequisite failure: pointer run id mismatch")
        return 3
    if pointer.get("dataset_sha256") != qualification.get("dataset_sha256"):
        print("Stack Exchange blind packet prerequisite failure: pointer dataset hash mismatch")
        return 3
    destination=args.review_root or (run / "review")
    manifest=build_review_packet_bundle(run, destination)
    print(f"Stack Exchange blind packet primary=20 secondary=5 root={destination} dataset={manifest['dataset_sha256']}")
    return 0


if __name__ == "__main__": raise SystemExit(main())
