from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

import src.extraction.baseline_calibration as baseline_calibration

from src.extraction.baseline_calibration import (
    create_baseline_bundle,
    main,
    validate_artifact,
)
from src.extraction.baseline_manifest import LoadedBaselineManifest
from src.extraction.baseline_provenance import RULE_V1_IMPLEMENTATION_PATHS
from src.extraction.development_slice import (
    DevelopmentGoldSidecar,
    DevelopmentInference,
)


def _digest(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def _inputs() -> tuple[LoadedBaselineManifest, DevelopmentInference, DevelopmentGoldSidecar]:
    corpus = tuple(
        {
            "document_id": f"{source}:{index}",
            "source": source,
            "title": f"Document {index}",
            "text": "The service fails and we need to purchase a replacement.",
            "published_at": "2026-01-01T00:00:00Z",
            "source_url": f"https://example.com/{source}/{index}",
        }
        for source in ("github", "stackexchange", "steam", "ted")
        for index in range(10)
    )
    labels = tuple(
        {
            "document_id": value["document_id"],
            "problem_signal": True,
            "money_signal": True,
            "money_signal_type": "purchase",
            "usable_evidence": True,
            "noise": False,
        }
        for value in corpus
    )
    source_counts = {source: 10 for source in ("github", "stackexchange", "steam", "ted")}
    dataset_hashes = {source: sha256(source.encode()).hexdigest() for source in source_counts}
    qualification_hashes = {
        source: sha256(f"qualification:{source}".encode()).hexdigest()
        for source in source_counts
    }
    packet_hashes = {
        source: sha256(f"packet:{source}".encode()).hexdigest()
        for source in source_counts
    }
    inference = DevelopmentInference(
        corpus,
        {
            "source_counts": source_counts,
            "selected_count": 40,
            "source_spike_reserved_emitted": 0,
            "source_dataset_sha256": dataset_hashes,
            "source_qualification_sha256": qualification_hashes,
            "source_packet_manifest_sha256": packet_hashes,
            "inference_corpus_sha256": _digest(corpus),
            "packet_validation": "PASS",
        },
    )
    gold = DevelopmentGoldSidecar(
        labels,
        {
            "source_counts": source_counts,
            "selected_count": 40,
            "source_dataset_sha256": dataset_hashes,
            "source_qualification_sha256": qualification_hashes,
            "source_packet_manifest_sha256": packet_hashes,
            "gold_sidecar_sha256": _digest(labels),
            "packet_validation": "PASS",
        },
    )
    loaded = LoadedBaselineManifest(
        {},
        {
            "manifest_id": "fixture-v1",
            "artifact_custody": "local_ignored",
            "manifest_sha256": "a" * 64,
            "status": "validated",
        },
    )
    return loaded, inference, gold


def _implementation_files(root: Path) -> None:
    for relative in RULE_V1_IMPLEMENTATION_PATHS:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative + "\n", encoding="utf-8")


def test_bundle_is_aggregate_only_schema_valid_and_idempotent(tmp_path: Path) -> None:
    loaded, inference, gold = _inputs()
    _implementation_files(tmp_path)
    output_root = tmp_path / "artifacts"

    first = create_baseline_bundle(
        loaded=loaded,
        inference=inference,
        gold=gold,
        repo_root=tmp_path,
        output_root=output_root,
    )
    second = create_baseline_bundle(
        loaded=loaded,
        inference=inference,
        gold=gold,
        repo_root=tmp_path,
        output_root=output_root,
    )

    assert first == second
    assert {path.name for path in first.iterdir()} == {
        "preflight-receipt.json",
        "baseline-run-receipt.json",
        "baseline-metrics.json",
        "baseline-evaluation-receipt.json",
        "bundle-manifest.json",
    }
    for path in first.glob("*.json"):
        value = json.loads(path.read_text(encoding="utf-8"))
        validate_artifact(path.name, value)
    persisted = "\n".join(path.read_text(encoding="utf-8") for path in first.glob("*.json"))
    assert "source_url" not in persisted
    assert "evidence_quote" not in persisted
    assert '"outputs_persisted":false' in persisted
    assert '"reverification_requires_local_custody":true' in persisted
    preflight = json.loads((first / "preflight-receipt.json").read_text())
    assert set(preflight["implementation_files"]) == set(RULE_V1_IMPLEMENTATION_PATHS)
    assert preflight["source_qualification_sha256"] == inference.receipt[
        "source_qualification_sha256"
    ]
    assert preflight["source_packet_manifest_sha256"] == inference.receipt[
        "source_packet_manifest_sha256"
    ]
    manifest = json.loads((first / "bundle-manifest.json").read_text(encoding="utf-8"))
    for name, expected_hash in manifest["files"].items():
        assert sha256((first / name).read_bytes()).hexdigest() == expected_hash
    assert _digest(manifest["files"]) == manifest["bundle_sha256"]


def test_preflight_rejects_bad_quota_before_writing(tmp_path: Path) -> None:
    loaded, inference, gold = _inputs()
    _implementation_files(tmp_path)
    bad = DevelopmentInference(
        inference.corpus,
        {**inference.receipt, "source_counts": {"github": 40}},
    )

    with pytest.raises(ValueError, match="source quotas"):
        create_baseline_bundle(
            loaded=loaded,
            inference=bad,
            gold=gold,
            repo_root=tmp_path,
            output_root=tmp_path / "artifacts",
        )
    assert not (tmp_path / "artifacts").exists()


def test_existing_conflicting_bundle_is_never_overwritten(tmp_path: Path) -> None:
    loaded, inference, gold = _inputs()
    _implementation_files(tmp_path)
    output_root = tmp_path / "artifacts"
    target = create_baseline_bundle(
        loaded=loaded,
        inference=inference,
        gold=gold,
        repo_root=tmp_path,
        output_root=output_root,
    )
    (target / "baseline-metrics.json").write_text("{}", encoding="utf-8")

    with pytest.raises(FileExistsError, match="conflicts"):
        create_baseline_bundle(
            loaded=loaded,
            inference=inference,
            gold=gold,
            repo_root=tmp_path,
            output_root=output_root,
        )
    assert (target / "baseline-metrics.json").read_text(encoding="utf-8") == "{}"


def test_partial_write_is_cleaned_without_publishing_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loaded, inference, gold = _inputs()
    _implementation_files(tmp_path)
    calls = 0
    original = baseline_calibration._write_file

    def fail_second_write(path: Path, value: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected write failure")
        original(path, value)

    monkeypatch.setattr(baseline_calibration, "_write_file", fail_second_write)
    output_root = tmp_path / "artifacts"
    with pytest.raises(OSError, match="injected"):
        create_baseline_bundle(
            loaded=loaded,
            inference=inference,
            gold=gold,
            repo_root=tmp_path,
            output_root=output_root,
        )

    target_parent = output_root / "rule-v1"
    assert target_parent.is_dir()
    assert list(target_parent.iterdir()) == []


def test_schema_rejects_unknown_nested_fields() -> None:
    with pytest.raises(ValueError, match="schema"):
        validate_artifact(
            "baseline-metrics.json",
            {
                "schema_version": "baseline-metrics/v1",
                "variant_id": "rule_v1",
                "input_count": 40,
                "coverage": 1.0,
                "abstention_count": 0,
                "invalid_count": 0,
                "metrics": {"problem_signal": {"raw_text": "forbidden"}},
                "source_metrics": {},
            },
        )


def test_cli_requires_explicit_local_custody_opt_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("RESEARCH_AUTO_RUN_LOCAL_ARTIFACT_TESTS", raising=False)

    exit_code = main(
        ["--manifest", str(tmp_path / "missing.json"), "--output-root", str(tmp_path)]
    )

    assert exit_code == 2
    assert "explicit opt-in" in capsys.readouterr().err
