from __future__ import annotations

import argparse
import os
import secrets
import stat
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Mapping


VARIABLE = "RESEARCH_AUTO_AUTHOR_SECRET_HEX"
DEFAULT_PATH = Path(__file__).resolve().parents[2] / ".env.local"


@dataclass(frozen=True)
class LocalSecret:
    secret: bytes
    fingerprint: str
    source: str


def _validated(value: str, *, source: str) -> LocalSecret:
    try:
        secret = bytes.fromhex(value)
    except ValueError as error:
        raise ValueError(f"{VARIABLE} must be valid hex") from error
    if len(secret) < 32:
        raise ValueError(f"{VARIABLE} must encode at least 32 bytes")
    return LocalSecret(secret, sha256(secret).hexdigest()[:16], source)


def check_secret(path: Path = DEFAULT_PATH) -> LocalSecret:
    if not path.exists():
        raise FileNotFoundError(f"local secret file does not exist: {path}")
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode):
        raise ValueError("local secret file must not be a symlink")
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError("local secret path must be a regular file")
    if stat.S_IMODE(metadata.st_mode) != 0o600:
        raise ValueError("local secret file permissions must be exactly 0600")
    values: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{VARIABLE}="):
            values.append(line.split("=", 1)[1].strip())
    if len(values) != 1:
        raise ValueError(f"local secret file must contain exactly one {VARIABLE}")
    return _validated(values[0], source=str(path))


def init_secret(path: Path = DEFAULT_PATH) -> LocalSecret:
    path.parent.mkdir(parents=True, exist_ok=True)
    value = secrets.token_hex(32)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(f"{VARIABLE}={value}\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise
    os.chmod(path, 0o600)
    return _validated(value, source=str(path))


def load_secret(
    path: Path = DEFAULT_PATH, *, environ: Mapping[str, str] = os.environ
) -> LocalSecret:
    value = environ.get(VARIABLE)
    return _validated(value, source="environment") if value else check_secret(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage the local Source Spike author hash secret")
    parser.add_argument("command", choices=("init", "check"))
    parser.add_argument("--path", type=Path, default=DEFAULT_PATH)
    arguments = parser.parse_args(argv)
    try:
        local = init_secret(arguments.path) if arguments.command == "init" else check_secret(arguments.path)
    except (FileExistsError, FileNotFoundError, ValueError) as error:
        print(f"secret {arguments.command} failed: {error}")
        return 2
    print(f"secret {arguments.command} ok source={local.source} fingerprint={local.fingerprint}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
