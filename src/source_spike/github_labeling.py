from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.source_spike.review_packet import (
    build_review_packet_bundle,
    validate_review_packet_bundle,
)
from src.source_spike.label_ingestion import ingest_submissions
from src.source_spike.source_quality import (
    build_development_report,
    load_source_quality_policy,
    policy_sha256,
    write_development_report,
)


ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_ROOT = ROOT / "artifacts/source-spike/github-analysis"


def _qualified_run() -> Path:
    pointer = json.loads((ARTIFACT_ROOT / "latest-qualified.json").read_text(encoding="utf-8"))
    return ARTIFACT_ROOT / "runs" / pointer["run_id"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    packet = subparsers.add_parser("packet")
    packet.add_argument("--review-root", type=Path)
    report = subparsers.add_parser("report-development")
    report.add_argument("--review-root", type=Path, required=True)
    ingest = subparsers.add_parser("ingest")
    ingest.add_argument("--review-root", type=Path, required=True)
    ingest.add_argument("--primary", type=Path, required=True)
    ingest.add_argument("--secondary", type=Path, required=True)
    unseal = subparsers.add_parser("unseal")
    unseal.add_argument("--review-root", type=Path, required=True)
    unseal.add_argument("--freeze-receipt", type=Path)
    arguments = parser.parse_args(argv)
    if arguments.command == "packet":
        run = _qualified_run()
        review_root = arguments.review_root or (run / "review")
        manifest = build_review_packet_bundle(run, review_root)
        print(f"GitHub review packet primary=20 secondary=5 root={review_root} dataset={manifest['dataset_sha256']}")
        return 0
    if arguments.command == "ingest":
        primary = [json.loads(line) for line in arguments.primary.read_text(encoding="utf-8").splitlines() if line]
        secondary = [json.loads(line) for line in arguments.secondary.read_text(encoding="utf-8").splitlines() if line]
        summary = ingest_submissions(arguments.review_root, primary=primary, secondary=secondary)
        print(f"GitHub labels ingested primary={summary['primary']} secondary={summary['secondary']}")
        return 0
    if arguments.command == "unseal":
        if arguments.freeze_receipt is None or not arguments.freeze_receipt.is_file():
            print("holdout unseal blocked: explicit freeze receipt is required")
            return 3
        receipt = json.loads(arguments.freeze_receipt.read_text(encoding="utf-8"))
        required = load_source_quality_policy()["holdout"]["unseal_requires"]
        if not all(receipt.get(key) is True for key in required):
            print("holdout unseal blocked: freeze receipt is incomplete")
            return 3
        print("holdout unseal prerequisites verified")
        return 0
    labels = arguments.review_root / "labels/development/canonical-labels.jsonl"
    if not labels.is_file():
        print("development report unavailable: canonical development labels are missing")
        return 2
    packet_manifest = validate_review_packet_bundle(arguments.review_root)
    report_value = build_development_report(
        labels,
        provenance={
            "dataset_sha256": packet_manifest["dataset_sha256"],
            "manifest_hash": packet_manifest["manifest_hash"],
            "packet_file_sha256": packet_manifest["file_sha256"],
            "policy_sha256": policy_sha256(),
            "guide_version": "1.0.0",
        },
    )
    write_development_report(arguments.review_root, report_value)
    print("GitHub development source quality report complete; holdout remains sealed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
