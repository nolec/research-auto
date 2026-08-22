from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Mapping, Sequence

from src.source_spike.review_handoff import build_offline_review_html
from src.source_spike.review_packet import build_review_packet_bundle, validate_review_packet_bundle


ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_ROOT = ROOT / "artifacts/source-spike/ted-analysis"
_HANDOFF_FILES = frozenset({"review.html", "submission-template.jsonl"})


def _qualified_run() -> tuple[Path, Mapping[str, object]]:
    pointer_path = ARTIFACT_ROOT / "latest-qualified.json"
    if pointer_path.is_symlink() or not pointer_path.is_file():
        raise ValueError("qualified analysis pointer is missing or unsafe")
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    if not isinstance(pointer, Mapping):
        raise ValueError("qualified analysis pointer is malformed")
    run = ARTIFACT_ROOT / "runs" / str(pointer.get("run_id", ""))
    if run.is_symlink() or not run.is_dir():
        raise ValueError("qualified analysis run is missing or unsafe")
    qualification = json.loads((run / "qualification.json").read_text(encoding="utf-8"))
    if not isinstance(qualification, Mapping) or qualification.get("qualified") is not True:
        raise ValueError("qualification is malformed or not qualified")
    if pointer.get("run_id") != qualification.get("run_id"):
        raise ValueError("pointer run id mismatch")
    if pointer.get("dataset_sha256") != qualification.get("dataset_sha256"):
        raise ValueError("pointer dataset hash mismatch")
    return run, qualification


def _validate_ted_source(review_root: Path, qualification: Mapping[str, object]) -> Mapping[str, object]:
    manifest = validate_review_packet_bundle(review_root, dict(qualification))
    assignments = json.loads(
        (review_root / "internal/assignment-map.json").read_text(encoding="utf-8")
    )
    if not isinstance(assignments, list) or len(assignments) != 20 or any(
        not isinstance(value, Mapping) or value.get("source") != "ted"
        for value in assignments
    ):
        raise ValueError("review packet source must be ted with 20 assignments")
    return manifest


def _submission_template(packet: Sequence[Mapping[str, object]], *, role: str) -> str:
    rows = []
    for value in packet:
        assignment_id = value.get("assignment_id")
        if not isinstance(assignment_id, str) or not assignment_id:
            raise ValueError("review packet assignment is malformed")
        rows.append(
            {
                "assignment_id": assignment_id,
                "reviewer_id": "",
                "reviewer_independence_asserted": role == "primary",
                "problem_signal": None,
                "money_signal": None,
                "money_signal_type": None,
                "structural_money_signal": None,
                "usable_evidence": None,
                "noise": None,
                "external_context_used": False,
                "label_reason": "",
                "labeled_at": "",
            }
        )
    return "".join(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n" for value in rows)


def _write_isolated_handoff(
    packet_path: Path,
    destination: Path,
    *,
    role: str,
    title: str,
) -> None:
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    if not isinstance(packet, list):
        raise ValueError("review packet must be a JSON array")
    html = build_offline_review_html(packet, title=title, review_role=role)
    template = _submission_template(packet, role=role)
    expected = {"review.html": html, "submission-template.jsonl": template}
    if destination.exists():
        if destination.is_symlink() or not destination.is_dir():
            raise ValueError(f"{role} handoff path is unsafe")
        observed = {path.name for path in destination.iterdir()}
        if observed != _HANDOFF_FILES:
            raise ValueError(f"{role} handoff file allowlist mismatch")
        for name, content in expected.items():
            path = destination / name
            if path.is_symlink() or not path.is_file() or path.read_text(encoding="utf-8") != content:
                raise ValueError(f"{role} handoff content drift")
        return
    temporary = destination.with_name(f".{destination.name}.tmp")
    if temporary.exists():
        raise ValueError(f"temporary {role} handoff already exists")
    try:
        temporary.mkdir(parents=True)
        for name, content in expected.items():
            (temporary / name).write_text(content, encoding="utf-8")
        os.replace(temporary, destination)
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0].startswith("-"):
        arguments.insert(0, "packet")
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    packet_command = subparsers.add_parser("packet")
    packet_command.add_argument("--review-root", type=Path)
    args = parser.parse_args(arguments)
    try:
        run, qualification = _qualified_run()
        destination = args.review_root or (run / "review")
        manifest = build_review_packet_bundle(run, destination)
        _validate_ted_source(destination, qualification)
        _write_isolated_handoff(
            destination / "packet/primary.json",
            destination / "handoff-primary",
            role="primary",
            title="TED Primary Blind Review",
        )
        _write_isolated_handoff(
            destination / "packet/secondary.json",
            destination / "handoff-secondary",
            role="secondary",
            title="TED Secondary Blind Review",
        )
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"TED blind packet failed: {error}")
        return 3
    print(
        "TED blind packet primary=20 secondary=5 "
        f"root={destination} dataset={manifest['dataset_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
