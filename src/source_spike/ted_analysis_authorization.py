from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Mapping

from jsonschema import Draft202012Validator

from src.contracts.validation import FORMAT_CHECKER


_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA = json.loads((_ROOT / "schemas/ted-analysis-authorization.schema.json").read_text())
_VALIDATOR = Draft202012Validator(_SCHEMA, format_checker=FORMAT_CHECKER)


def _schema_errors(value: Mapping[str, object]) -> list[str]:
    return [f"{'.'.join(map(str, error.absolute_path)) or '$'}: {error.message}" for error in sorted(_VALIDATOR.iter_errors(value), key=lambda item: tuple(map(str, item.absolute_path)))]


def _safe_destination(destination: Path, trusted_root: Path) -> None:
    if trusted_root.is_symlink():
        raise ValueError("trusted root cannot be a symlink")
    trusted = trusted_root.resolve()
    current = trusted_root
    relative = destination.parent.relative_to(trusted_root)
    for part in relative.parts:
        current = current / part
        if current.exists() and current.is_symlink():
            raise ValueError("authorization path contains symlink")
        if current.exists() and not current.is_dir():
            raise ValueError("authorization parent is not a directory")
    if trusted not in destination.resolve(strict=False).parents:
        raise ValueError("authorization path escapes trusted root")
    if destination.is_symlink():
        raise ValueError("authorization file cannot be a symlink")


def _smoke_value(path: Path) -> tuple[bytes, Mapping[str, object]]:
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, Mapping):
        raise ValueError("smoke receipt must be an object")
    if value.get("status") != "PASS" or value.get("termination_reason") != "target_reached" or value.get("accepted") != 10:
        raise ValueError("smoke receipt is not qualified")
    provenance = value.get("provenance")
    if not isinstance(provenance, Mapping):
        raise ValueError("smoke provenance is missing")
    return raw, value


def check_authorization(value: Mapping[str, object], smoke_path: Path) -> list[str]:
    errors = _schema_errors(value)
    try:
        raw, smoke = _smoke_value(smoke_path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return errors + [str(error)]
    provenance = smoke["provenance"]
    assert isinstance(provenance, Mapping)
    expected = {
        "smoke_run_id": smoke.get("run_id"), "smoke_receipt_sha256": sha256(raw).hexdigest(),
        "smoke_manifest_hash": provenance.get("manifest_hash"), "capacity_manifest_hash": provenance.get("capacity_manifest_hash"),
        "smoke_authorization_hash": provenance.get("authorization_hash"),
    }
    errors.extend(f"{key} mismatch" for key, expected_value in expected.items() if value.get(key) != expected_value)
    return errors


def init_authorization(smoke_path: Path, destination: Path, *, trusted_root: Path, authorized_at: str) -> dict[str, object]:
    _safe_destination(destination, trusted_root)
    if destination.exists():
        raise FileExistsError(f"authorization already exists: {destination}")
    raw, smoke = _smoke_value(smoke_path)
    provenance = smoke["provenance"]
    assert isinstance(provenance, Mapping)
    value: dict[str, object] = {
        "schema_version": "1.0.0", "status": "AUTHORIZED", "operational_next_action": "run_analysis",
        "smoke_run_id": smoke["run_id"], "smoke_receipt_sha256": sha256(raw).hexdigest(),
        "smoke_manifest_hash": provenance["manifest_hash"], "capacity_manifest_hash": provenance["capacity_manifest_hash"],
        "smoke_authorization_hash": provenance["authorization_hash"], "authorized_at": authorized_at,
    }
    errors = _schema_errors(value)
    if errors:
        raise ValueError("invalid authorization: " + "; ".join(errors))
    destination.parent.mkdir(parents=True, mode=0o700)
    os.chmod(destination.parent, 0o700)
    temporary = destination.with_name(f".{destination.name}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, sort_keys=True, indent=2)
            handle.write("\n")
        os.replace(temporary, destination)
        os.chmod(destination, 0o600)
    finally:
        if temporary.exists(): temporary.unlink()
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Initialize the local-only TED analysis authorization")
    parser.add_argument("command", choices=("init", "check"))
    parser.add_argument(
        "--smoke-receipt",
        type=Path,
        default=_ROOT / "artifacts/source-spike/ted-real-smoke/qualification.json",
    )
    parser.add_argument(
        "--authorization",
        type=Path,
        default=_ROOT / "artifacts/source-spike/ted-analysis-authorization/authorization.json",
    )
    args = parser.parse_args(argv)
    trusted_root = _ROOT / "artifacts/source-spike"
    try:
        if args.command == "init":
            init_authorization(
                args.smoke_receipt,
                args.authorization,
                trusted_root=trusted_root,
                authorized_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            )
        else:
            if args.authorization.is_symlink() or not args.authorization.is_file():
                raise ValueError("authorization is missing or unsafe")
            if args.authorization.stat().st_mode & 0o077:
                raise ValueError("authorization permissions must be 0600")
            value = json.loads(args.authorization.read_text())
            if not isinstance(value, Mapping):
                raise ValueError("authorization must be an object")
            errors = check_authorization(value, args.smoke_receipt)
            if errors:
                raise ValueError("; ".join(errors))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "FAIL", "error_code": "authorization_failed", "message": str(error)}))
        return 2
    print(json.dumps({"status": "PASS", "command": args.command, "authorization": str(args.authorization)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
