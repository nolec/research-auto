from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Mapping

from jsonschema import Draft202012Validator

from src.contracts.validation import FORMAT_CHECKER


_HEX_FIELDS = (
    "capacity_receipt_sha256", "capacity_manifest_hash", "feasibility_hash",
    "compliance_hash", "query_set_sha256",
)
_SCHEMA = json.loads((Path(__file__).resolve().parents[2] / "schemas/ted-smoke-authorization.schema.json").read_text())
_VALIDATOR = Draft202012Validator(_SCHEMA, format_checker=FORMAT_CHECKER)


def validate_ted_smoke_authorization(
    authorization: Mapping[str, object], capacity_receipt_path: Path
) -> list[str]:
    errors: list[str] = []
    errors.extend(
        f"{'.'.join(map(str, error.absolute_path)) or '$'}: {error.message}"
        for error in sorted(_VALIDATOR.iter_errors(authorization), key=lambda value: tuple(map(str, value.absolute_path)))
    )
    if authorization.get("schema_version") != "1.0.0": errors.append("schema_version mismatch")
    if authorization.get("status") != "AUTHORIZED": errors.append("status must be AUTHORIZED")
    if authorization.get("operational_next_action") != "run_smoke": errors.append("operational_next_action must be run_smoke")
    for field in _HEX_FIELDS:
        value = authorization.get(field)
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            errors.append(f"{field} must be lowercase sha256")
    try:
        raw = capacity_receipt_path.read_bytes()
        receipt = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return errors + ["capacity receipt is unreadable"]
    if sha256(raw).hexdigest() != authorization.get("capacity_receipt_sha256"):
        errors.append("capacity receipt sha256 mismatch")
    for auth_field, receipt_field in (
        ("capacity_run_id", "run_id"), ("capacity_manifest_hash", "capacity_manifest_hash"),
        ("feasibility_hash", "feasibility_hash"), ("compliance_hash", "compliance_hash"),
    ):
        if authorization.get(auth_field) != receipt.get(receipt_field):
            errors.append(f"{auth_field} does not match capacity receipt")
    if receipt.get("status") != "PASS" or receipt.get("termination_reason") != "capacity_reached":
        errors.append("capacity receipt is not qualified")
    if not isinstance(authorization.get("authorized_at"), str): errors.append("authorized_at is required")
    return errors
