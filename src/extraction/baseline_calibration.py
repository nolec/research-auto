from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Mapping, Sequence

from jsonschema import Draft202012Validator

from src.extraction.baseline_manifest import (
    LoadedBaselineManifest,
    load_baseline_manifest,
)
from src.extraction.baseline_provenance import (
    build_rule_v1_implementation_bundle,
    canonical_digest,
)
from src.extraction.calibration_evaluator import evaluate_calibration
from src.extraction.development_slice import (
    DevelopmentGoldSidecar,
    DevelopmentInference,
    build_development_gold_sidecar,
    build_development_inference,
)
from src.extraction.rule_baseline import RuleBaselineProfile, run_rule_baseline


_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA_PATH = _ROOT / "schemas/baseline-calibration-artifacts.schema.json"
_ARTIFACT_DEFINITIONS = {
    "preflight-receipt.json": "preflightReceipt",
    "baseline-run-receipt.json": "runReceipt",
    "baseline-metrics.json": "metrics",
    "baseline-evaluation-receipt.json": "evaluationReceipt",
    "bundle-manifest.json": "bundleManifest",
}
def _schema() -> dict[str, object]:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_artifact(filename: str, value: object) -> None:
    definition = _ARTIFACT_DEFINITIONS.get(filename)
    if definition is None:
        raise ValueError(f"artifact filename is not allowed: {filename}")
    schema = _schema()
    validator = Draft202012Validator(
        {"$ref": f"#/$defs/{definition}", "$defs": schema["$defs"]}
    )
    errors = sorted(validator.iter_errors(value), key=lambda error: list(error.path))
    if errors:
        raise ValueError(f"artifact schema validation failed: {errors[0].message}")


def _require_preflight(
    loaded: LoadedBaselineManifest,
    inference: DevelopmentInference,
    gold: DevelopmentGoldSidecar,
    implementation: Mapping[str, object],
) -> dict[str, object]:
    expected_counts = {source: 10 for source in ("github", "stackexchange", "steam", "ted")}
    if loaded.receipt.get("status") != "validated":
        raise ValueError("baseline manifest must be validated")
    if loaded.receipt.get("artifact_custody") != "local_ignored":
        raise ValueError("baseline artifact custody must be local_ignored")
    if inference.receipt.get("source_counts") != expected_counts:
        raise ValueError("inference source quotas must be exactly 10 per source")
    if gold.receipt.get("source_counts") != expected_counts:
        raise ValueError("gold source quotas must be exactly 10 per source")
    if len(inference.corpus) != 40 or inference.receipt.get("selected_count") != 40:
        raise ValueError("inference must contain exactly 40 selected records")
    if len(gold.labels) != 40 or gold.receipt.get("selected_count") != 40:
        raise ValueError("gold must contain exactly 40 selected records")
    if inference.receipt.get("packet_validation") != "PASS" or gold.receipt.get(
        "packet_validation"
    ) != "PASS":
        raise ValueError("packet validation must pass")
    if inference.receipt.get("source_spike_reserved_emitted") != 0:
        raise ValueError("reserved source-spike records must remain sealed")
    if inference.receipt.get("source_dataset_sha256") != gold.receipt.get(
        "source_dataset_sha256"
    ):
        raise ValueError("inference and gold source dataset hashes differ")
    for field in (
        "source_qualification_sha256",
        "source_packet_manifest_sha256",
    ):
        if inference.receipt.get(field) != gold.receipt.get(field):
            raise ValueError(f"inference and gold {field} values differ")
    if canonical_digest(inference.corpus) != inference.receipt.get(
        "inference_corpus_sha256"
    ):
        raise ValueError("inference corpus hash mismatch")
    if canonical_digest(gold.labels) != gold.receipt.get("gold_sidecar_sha256"):
        raise ValueError("gold sidecar hash mismatch")
    receipt = {
        "schema_version": "baseline-preflight-receipt/v1",
        "status": "qualified",
        "artifact_custody": "local_ignored",
        "manifest_id": loaded.receipt["manifest_id"],
        "manifest_sha256": loaded.receipt["manifest_sha256"],
        "source_counts": expected_counts,
        "source_dataset_sha256": inference.receipt["source_dataset_sha256"],
        "source_qualification_sha256": inference.receipt[
            "source_qualification_sha256"
        ],
        "source_packet_manifest_sha256": inference.receipt[
            "source_packet_manifest_sha256"
        ],
        "selected_count": 40,
        "packet_validation": "PASS",
        "source_spike_reserved_emitted": 0,
        "inference_corpus_sha256": inference.receipt["inference_corpus_sha256"],
        "gold_sidecar_sha256": gold.receipt["gold_sidecar_sha256"],
        "implementation_bundle_sha256": implementation[
            "implementation_bundle_sha256"
        ],
        "implementation_files": implementation["files"],
    }
    validate_artifact("preflight-receipt.json", receipt)
    return receipt


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _write_file(path: Path, value: object) -> None:
    path.write_bytes(_json_bytes(value))
    with path.open("rb") as stream:
        os.fsync(stream.fileno())


def _verify_existing(target: Path, expected: Mapping[str, bytes]) -> bool:
    if not target.is_dir() or set(path.name for path in target.iterdir()) != set(expected):
        return False
    return all((target / name).read_bytes() == payload for name, payload in expected.items())


def create_baseline_bundle(
    *,
    loaded: LoadedBaselineManifest,
    inference: DevelopmentInference,
    gold: DevelopmentGoldSidecar,
    repo_root: Path,
    output_root: Path,
) -> Path:
    implementation = build_rule_v1_implementation_bundle(repo_root)
    preflight = _require_preflight(loaded, inference, gold, implementation)
    run = run_rule_baseline(
        inference,
        RuleBaselineProfile(str(inference.receipt["inference_corpus_sha256"])),
    )
    report = evaluate_calibration(inference, gold, run.outputs, run.receipt)
    implementation_hash = str(implementation["implementation_bundle_sha256"])
    preflight_hash = canonical_digest(preflight)
    run_receipt = {
        "schema_version": "baseline-run-receipt/v1",
        "variant_id": "rule_v1",
        "status": "success",
        "implementation_bundle_sha256": implementation_hash,
        "preflight_receipt_sha256": preflight_hash,
        "inference_corpus_sha256": run.receipt["inference_corpus_sha256"],
        "input_count": run.receipt["input_count"],
        "output_count": run.receipt["output_count"],
        "valid_count": run.receipt["valid_count"],
        "invalid_count": run.receipt["invalid_count"],
        "abstention_count": run.receipt["abstention_count"],
        "output_sha256": run.receipt["output_sha256"],
        "outputs_persisted": False,
        "reverification_requires_local_custody": True,
    }
    metrics = {
        "schema_version": "baseline-metrics/v1",
        "variant_id": "rule_v1",
        "input_count": len(inference.corpus),
        "coverage": report.coverage,
        "abstention_count": report.abstention_count,
        "invalid_count": report.invalid_count,
        "metrics": report.metrics,
        "source_metrics": report.source_metrics,
    }
    evaluation_receipt = {
        "schema_version": "baseline-evaluation-receipt/v1",
        "variant_id": "rule_v1",
        "status": "success",
        "implementation_bundle_sha256": implementation_hash,
        "preflight_receipt_sha256": preflight_hash,
        "upstream_run_receipt_sha256": canonical_digest(run_receipt),
        "inference_corpus_sha256": inference.receipt["inference_corpus_sha256"],
        "gold_sidecar_sha256": gold.receipt["gold_sidecar_sha256"],
        "metrics_sha256": canonical_digest(metrics),
        "input_count": len(inference.corpus),
        "outputs_persisted": False,
        "reverification_requires_local_custody": True,
    }
    values = {
        "preflight-receipt.json": preflight,
        "baseline-run-receipt.json": run_receipt,
        "baseline-metrics.json": metrics,
        "baseline-evaluation-receipt.json": evaluation_receipt,
    }
    for name, value in values.items():
        validate_artifact(name, value)
    payloads = {name: _json_bytes(value) for name, value in values.items()}
    file_hashes = {name: sha256(payload).hexdigest() for name, payload in payloads.items()}
    manifest = {
        "schema_version": "baseline-artifact-bundle/v1",
        "status": "complete",
        "implementation_bundle_sha256": implementation_hash,
        "files": file_hashes,
        "bundle_sha256": canonical_digest(file_hashes),
    }
    validate_artifact("bundle-manifest.json", manifest)
    payloads["bundle-manifest.json"] = _json_bytes(manifest)

    target = output_root / "rule-v1" / implementation_hash
    if target.exists():
        if _verify_existing(target, payloads):
            return target
        raise FileExistsError("existing baseline bundle conflicts with requested bundle")

    parent = target.parent
    parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".baseline-", dir=parent))
    try:
        for name in values:
            _write_file(temporary / name, values[name])
        _write_file(temporary / "bundle-manifest.json", manifest)
        directory_fd = os.open(temporary, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        try:
            temporary.rename(target)
        except FileExistsError:
            if _verify_existing(target, payloads):
                return target
            raise FileExistsError("concurrent baseline bundle conflicts with requested bundle")
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return target


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a frozen rule_v1 baseline metric bundle")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    if os.environ.get("RESEARCH_AUTO_RUN_LOCAL_ARTIFACT_TESTS") != "1":
        print("local artifact execution requires explicit opt-in", file=sys.stderr)
        return 2
    try:
        loaded = load_baseline_manifest(args.manifest, repo_root=_ROOT)
        inference = build_development_inference(loaded.sources)
        gold = build_development_gold_sidecar(loaded.sources)
        target = create_baseline_bundle(
            loaded=loaded,
            inference=inference,
            gold=gold,
            repo_root=_ROOT,
            output_root=args.output_root,
        )
    except (OSError, ValueError, FileExistsError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
