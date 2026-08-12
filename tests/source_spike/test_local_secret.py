from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.source_spike.local_secret import check_secret, init_secret, load_secret


def test_init_creates_once_with_mode_0600_and_check_returns_fingerprint(tmp_path: Path) -> None:
    path = tmp_path / ".env.local"

    initialized = init_secret(path)

    assert len(initialized.secret) == 32
    assert path.stat().st_mode & 0o777 == 0o600
    assert check_secret(path).fingerprint == initialized.fingerprint
    with pytest.raises(FileExistsError):
        init_secret(path)


def test_load_prefers_environment_then_local_and_never_auto_creates(tmp_path: Path) -> None:
    path = tmp_path / ".env.local"
    local_hex = "11" * 32
    path.write_text(f"RESEARCH_AUTO_AUTHOR_SECRET_HEX={local_hex}\n", encoding="utf-8")
    os.chmod(path, 0o600)

    assert load_secret(path, environ={}).secret == bytes.fromhex(local_hex)
    assert load_secret(path, environ={"RESEARCH_AUTO_AUTHOR_SECRET_HEX": "22" * 32}).secret == bytes.fromhex("22" * 32)
    missing = tmp_path / "missing.env"
    with pytest.raises(FileNotFoundError):
        load_secret(missing, environ={})
    assert not missing.exists()


@pytest.mark.parametrize("content", ["", "OTHER=value\n", "RESEARCH_AUTO_AUTHOR_SECRET_HEX=abcd\n"])
def test_check_rejects_missing_or_short_secret(tmp_path: Path, content: str) -> None:
    path = tmp_path / ".env.local"
    path.write_text(content, encoding="utf-8")
    os.chmod(path, 0o600)
    with pytest.raises(ValueError):
        check_secret(path)


def test_check_rejects_secret_file_with_broad_permissions(tmp_path: Path) -> None:
    path = tmp_path / ".env.local"
    path.write_text(f"RESEARCH_AUTO_AUTHOR_SECRET_HEX={'11' * 32}\n", encoding="utf-8")
    os.chmod(path, 0o644)

    with pytest.raises(ValueError, match="0600"):
        check_secret(path)


def test_check_rejects_symlink_and_non_regular_path(tmp_path: Path) -> None:
    target = tmp_path / "secret.env"
    target.write_text(f"RESEARCH_AUTO_AUTHOR_SECRET_HEX={'11' * 32}\n", encoding="utf-8")
    os.chmod(target, 0o600)
    link = tmp_path / ".env.local"
    link.symlink_to(target)

    with pytest.raises(ValueError, match="symlink"):
        check_secret(link)

    directory = tmp_path / "secret-directory"
    directory.mkdir(mode=0o700)
    with pytest.raises(ValueError, match="regular file"):
        check_secret(directory)
