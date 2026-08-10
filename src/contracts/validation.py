"""Runtime validation for JSON contracts with semantic format checks."""

from datetime import datetime
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator, FormatChecker


FORMAT_CHECKER = FormatChecker()


@FORMAT_CHECKER.checks("uri")
def is_public_http_uri(value: object) -> bool:
    if not isinstance(value, str) or any(character.isspace() for character in value):
        return False

    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        parsed.port
    except ValueError:
        return False

    return parsed.scheme in {"http", "https"} and hostname is not None


@FORMAT_CHECKER.checks("date-time")
def is_timezone_aware_datetime(value: object) -> bool:
    if not isinstance(value, str):
        return False

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def validate_contract(instance: object, schema: dict) -> None:
    """Validate an instance against a Draft 2020-12 contract."""
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(
        schema,
        format_checker=FORMAT_CHECKER,
    ).validate(instance)
