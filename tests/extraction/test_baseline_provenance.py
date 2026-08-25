from pathlib import Path

import pytest

from src.extraction.baseline_provenance import (
    RULE_V1_IMPLEMENTATION_PATHS,
    build_implementation_bundle,
    build_rule_v1_implementation_bundle,
)


def test_implementation_bundle_changes_when_any_file_changes(tmp_path: Path) -> None:
    files = (tmp_path / "one.py", tmp_path / "two.json")
    files[0].write_text("first\n", encoding="utf-8")
    files[1].write_text("{}\n", encoding="utf-8")
    first = build_implementation_bundle(tmp_path, files)

    files[0].write_text("changed\n", encoding="utf-8")
    second = build_implementation_bundle(tmp_path, files)

    assert first["implementation_bundle_sha256"] != second["implementation_bundle_sha256"]
    assert set(first) == {
        "schema_version",
        "files",
        "implementation_bundle_sha256",
    }
    with pytest.raises(ValueError, match="missing"):
        build_implementation_bundle(tmp_path, (*files, tmp_path / "missing.py"))


def test_implementation_bundle_rejects_outside_and_duplicate_files(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    inside = root / "inside.py"
    inside.write_text("pass\n", encoding="utf-8")
    outside = tmp_path / "outside.py"
    outside.write_text("pass\n", encoding="utf-8")

    with pytest.raises(ValueError, match="inside"):
        build_implementation_bundle(root, (outside,))
    with pytest.raises(ValueError, match="duplicates"):
        build_implementation_bundle(root, (inside, inside))


def test_rule_v1_identity_requires_the_frozen_implementation_file_set(
    tmp_path: Path,
) -> None:
    for relative in RULE_V1_IMPLEMENTATION_PATHS:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative + "\n", encoding="utf-8")

    identity = build_rule_v1_implementation_bundle(tmp_path)

    assert set(identity["files"]) == set(RULE_V1_IMPLEMENTATION_PATHS)
    (tmp_path / RULE_V1_IMPLEMENTATION_PATHS[0]).unlink()
    (tmp_path / "decoy.py").write_text("pass\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing"):
        build_rule_v1_implementation_bundle(tmp_path)
