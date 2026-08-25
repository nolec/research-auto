from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

from src.extraction.development_slice import (
    SourceArtifacts,
    _load_json_snapshot,
    build_development_gold_sidecar,
    build_development_inference,
    validate_extraction,
)
from src.source_spike.analysis_bundle import dataset_sha256
from src.source_spike.review_packet import build_review_packet_bundle


SOURCES = ("github", "stackexchange", "steam", "ted")


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def _canonical_digest(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def _source_artifacts(root: Path, source: str) -> SourceArtifacts:
    run = root / source / "run"
    run.mkdir(parents=True)
    items = []
    assignments = []
    for index in range(20):
        document_id = f"{source}:{index}"
        text = f"{source} concrete problem {index} " + ("evidence " * 8)
        items.append(
            {
                "document_id": document_id,
                "source": source,
                "source_item_id": str(index),
                "source_url": f"https://example.com/{source}/{index}",
                "title": f"{source} title {index}",
                "text": text,
                "published_at": "2026-01-01T00:00:00Z",
            }
        )
        assignments.append(
            {
                "document_id": document_id,
                "requires_second_review": index < 5,
                "sample_rank": index + 1,
                "source": source,
                "split": "development" if index % 2 == 0 else "holdout",
                "stratum": "fixture",
            }
        )
    (run / "raw-source-items.jsonl").write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in items),
        encoding="utf-8",
    )
    digest = dataset_sha256(items)
    _write_json(
        run / "qualification.json",
        {
            "qualified": True,
            "run_id": f"{source}-run",
            "dataset_sha256": digest,
            "manifest_hash": "a" * 64,
        },
    )
    _write_json(run / "labeling-assignments.json", assignments)
    review = run / "review"
    build_review_packet_bundle(run, review)
    mapping = json.loads((review / "internal/assignment-map.json").read_text())
    submissions = [
        {
            "assignment_id": assignment["assignment_id"],
            "problem_signal": True,
            "money_signal": source == "ted",
            "money_signal_type": "purchase" if source == "ted" else None,
            "usable_evidence": True,
            "noise": False,
        }
        for assignment in mapping
    ]
    submission_path = run / "primary.jsonl"
    submission_path.write_text(
        "".join(json.dumps(value, sort_keys=True) + "\n" for value in submissions),
        encoding="utf-8",
    )
    return SourceArtifacts(run, review, submission_path)


def _artifacts(root: Path) -> dict[str, SourceArtifacts]:
    return {source: _source_artifacts(root, source) for source in SOURCES}


def test_build_development_slice_separates_inference_and_gold(tmp_path: Path) -> None:
    artifacts = _artifacts(tmp_path)
    inference = build_development_inference(artifacts)
    gold = build_development_gold_sidecar(artifacts)

    assert len(inference.corpus) == 40
    assert len(gold.labels) == 40
    assert {value["document_id"] for value in inference.corpus} == {
        value["document_id"] for value in gold.labels
    }
    assert all(
        set(value) == {"document_id", "source", "title", "text", "published_at", "source_url"}
        for value in inference.corpus
    )
    assert all(
        set(value)
        == {
            "document_id",
            "problem_signal",
            "money_signal",
            "money_signal_type",
            "usable_evidence",
            "noise",
        }
        for value in gold.labels
    )
    assert inference.receipt["source_counts"] == {source: 10 for source in SOURCES}
    assert inference.receipt["selected_count"] == 40
    assert inference.receipt["source_spike_reserved_available"] == 40
    assert inference.receipt["source_spike_reserved_selected"] == 0
    assert inference.receipt["source_spike_reserved_emitted"] == 0
    assert inference.receipt["split_policy"] == "development_calibration_only"
    assert inference.receipt["independent_evaluation_status"] == "not_available"
    assert inference.receipt["source_qualification_sha256"] == {
        source: sha256(
            (artifacts[source].qualified_run / "qualification.json").read_bytes()
        ).hexdigest()
        for source in SOURCES
    }
    assert inference.receipt["source_packet_manifest_sha256"] == {
        source: _canonical_digest(
            json.loads(
                (
                    artifacts[source].review_root
                    / "packet/bundle-manifest.json"
                ).read_text()
            )
        )
        for source in SOURCES
    }
    assert gold.receipt["source_qualification_sha256"] == inference.receipt[
        "source_qualification_sha256"
    ]
    assert gold.receipt["source_packet_manifest_sha256"] == inference.receipt[
        "source_packet_manifest_sha256"
    ]
    assert "backend_gold_exposed" not in inference.receipt
    assert not hasattr(inference, "gold_sidecar")
    assert not hasattr(gold, "inference_corpus")


def test_json_snapshot_parses_and_hashes_the_same_single_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "qualification.json"
    raw = b'{"qualified":true,"run_id":"one"}\n'
    path.write_bytes(raw)
    original = Path.read_bytes
    reads = 0

    def counted(candidate: Path) -> bytes:
        nonlocal reads
        if candidate == path:
            reads += 1
        return original(candidate)

    monkeypatch.setattr(Path, "read_bytes", counted)
    value, fingerprint = _load_json_snapshot(path)

    assert value == {"qualified": True, "run_id": "one"}
    assert fingerprint == sha256(raw).hexdigest()
    assert reads == 1


def test_build_development_slice_is_deterministic(tmp_path: Path) -> None:
    artifacts = _artifacts(tmp_path)
    assert build_development_inference(artifacts).receipt == build_development_inference(artifacts).receipt
    assert build_development_gold_sidecar(artifacts).receipt == build_development_gold_sidecar(artifacts).receipt


def test_build_development_slice_rejects_dataset_hash_mismatch(tmp_path: Path) -> None:
    artifacts = _artifacts(tmp_path)
    target = artifacts["github"].qualified_run / "raw-source-items.jsonl"
    target.write_text(target.read_text() + target.read_text().splitlines()[0] + "\n")
    with pytest.raises(ValueError, match="dataset hash mismatch"):
        build_development_inference(artifacts)


def test_build_development_slice_rejects_tampered_assignment_map(tmp_path: Path) -> None:
    artifacts = _artifacts(tmp_path)
    mapping_path = artifacts["steam"].review_root / "internal/assignment-map.json"
    mapping = json.loads(mapping_path.read_text())
    mapping[0]["split"] = "holdout"
    mapping_path.write_text(json.dumps(mapping), encoding="utf-8")
    with pytest.raises(ValueError, match="review packet hash mismatch"):
        build_development_inference(artifacts)


def test_build_development_gold_rejects_invalid_label_types(tmp_path: Path) -> None:
    artifacts = _artifacts(tmp_path)
    submission = artifacts["github"].primary_submission
    values = [json.loads(line) for line in submission.read_text().splitlines()]
    values[0]["problem_signal"] = "yes"
    submission.write_text(
        "".join(json.dumps(value) + "\n" for value in values), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="problem_signal must be boolean"):
        build_development_gold_sidecar(artifacts)


def _valid_output(document: dict[str, object]) -> dict[str, object]:
    text = str(document["text"])
    quote = text[:20]
    return {
        "document_id": document["document_id"],
        "observation_type": "procurement_requirement"
        if document["source"] == "ted"
        else "product_feedback"
        if document["source"] == "steam"
        else "user_problem",
        "actor": "observed user",
        "problem": "A concrete observed problem",
        "context": "Public source item",
        "consequence": "The expected outcome is blocked",
        "evidence_quote": quote,
        "evidence_start": 0,
        "evidence_end": len(quote),
        "problem_signal": True,
        "money_signal": document["source"] == "ted",
        "money_signal_type": "purchase" if document["source"] == "ted" else None,
        "usable_evidence": True,
        "confidence": 0.8,
        "abstention_reason": None,
    }


def test_validate_extraction_accepts_fixture_e2e_without_gold(tmp_path: Path) -> None:
    result = build_development_inference(_artifacts(tmp_path))
    outputs = []
    for document in result.corpus:
        assert set(document).isdisjoint(
            {"problem_signal", "money_signal", "money_signal_type", "usable_evidence", "noise"}
        )
        output = _valid_output(document)
        validate_extraction(document, output)
        outputs.append(output)
    assert len(outputs) == 40


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"observation_type": "unknown"}, "observation_type"),
        ({"evidence_start": 1}, "evidence span"),
        ({"money_signal": False, "money_signal_type": "purchase"}, "money signal"),
        ({"document_id": "other:1"}, "document_id"),
    ],
)
def test_validate_extraction_rejects_invalid_output(
    tmp_path: Path, change: dict[str, object], message: str
) -> None:
    document = build_development_inference(_artifacts(tmp_path)).corpus[0]
    output = {**_valid_output(document), **change}
    with pytest.raises(ValueError, match=message):
        validate_extraction(document, output)


def test_validate_extraction_requires_clean_explicit_abstention(tmp_path: Path) -> None:
    document = build_development_inference(_artifacts(tmp_path)).corpus[0]
    output = _valid_output(document)
    output["abstention_reason"] = "insufficient evidence"
    with pytest.raises(ValueError, match="abstention"):
        validate_extraction(document, output)

    for field in set(output) - {"document_id", "abstention_reason"}:
        output[field] = None
    validate_extraction(document, output)


def test_validate_extraction_rejects_gold_contaminated_input(tmp_path: Path) -> None:
    document = dict(build_development_inference(_artifacts(tmp_path)).corpus[0])
    output = _valid_output(document)
    document["problem_signal"] = True
    with pytest.raises(ValueError, match="inference document fields"):
        validate_extraction(document, output)
