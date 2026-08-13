from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.source_spike.review_packet import build_review_packet_bundle


ROOT=Path(__file__).resolve().parents[2]
ARTIFACT_ROOT=ROOT / "artifacts/source-spike/stackexchange-analysis"


def main(argv: list[str] | None=None) -> int:
    parser=argparse.ArgumentParser(); parser.add_argument("--review-root", type=Path); args=parser.parse_args(argv)
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
