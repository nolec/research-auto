from __future__ import annotations

import json

from src.source_spike.github_labeling import main


def test_report_command_fails_before_labels_exist(tmp_path) -> None:
    assert main(["report-development", "--review-root", str(tmp_path)]) == 2


def test_unseal_requires_explicit_freeze_receipt(tmp_path) -> None:
    assert main(["unseal", "--review-root", str(tmp_path)]) == 3


def test_unseal_uses_requirements_declared_by_policy(tmp_path) -> None:
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps({
        "extractor_candidate_frozen": True,
        "source_labeling_rules_frozen": True,
        "explicit_unseal_receipt": True,
    }), encoding="utf-8")
    assert main([
        "unseal", "--review-root", str(tmp_path), "--freeze-receipt", str(receipt)
    ]) == 0
