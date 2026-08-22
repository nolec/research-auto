from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping, Sequence


PLACEHOLDER = "[REDACTED_CONTACT]"
POLICY_VERSION = "ted-contact-v1"
LANGUAGE_VERSION = "ted-language-v1"
_EMAIL = re.compile(r"(?i)(?<![\w.+-])[\w.!#$%&'*+/=?^`{|}~-]+@[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,}(?![\w.-])")
_PHONE = re.compile(
    r"(?<!\w)(?:"
    r"\+\d(?:[\d ()-]{5,}\d)|"
    r"\(0\d{1,2}\)[ -]?\d{3,4}[ -]?\d{4}|"
    r"0\d{1,2}[ -]\d{3,4}[ -]\d{4}|"
    r"(?:0(?:10|11|16|17|18|19)\d{7,8}|02\d{7,8}|0[3-6]\d\d{7,8}|1[568]\d{6,7}|\d{10,15})"
    r")(?!\w)"
)


@dataclass(frozen=True)
class RedactionResult:
    text: str
    count: int


def _first_text(value: object) -> str | None:
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return next((text for item in value if (text := _first_text(item)) is not None), None)
    return None


def select_language(value: object) -> str:
    direct = _first_text(value)
    if direct is not None:
        return direct
    if not isinstance(value, Mapping):
        return ""
    by_key = {str(key): nested for key, nested in value.items()}
    for preferred in ("eng", "en"):
        matching = next((key for key in by_key if key.casefold() == preferred), None)
        if matching is not None and (text := _first_text(by_key[matching])) is not None:
            return text
    for key in sorted(by_key, key=lambda item: item.encode("utf-8")):
        if (text := _first_text(by_key[key])) is not None:
            return text
    return ""


def redact_contacts(value: str) -> RedactionResult:
    count = 0

    def replace(_: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return PLACEHOLDER

    redacted = _EMAIL.sub(replace, value)
    redacted = _PHONE.sub(replace, redacted)
    return RedactionResult(redacted, count)


def residual_contact_count(value: str) -> int:
    candidate = value.replace(PLACEHOLDER, "")
    return len(_EMAIL.findall(candidate)) + len(_PHONE.findall(candidate))
