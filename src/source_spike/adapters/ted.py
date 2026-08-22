from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping, Sequence

from src.source_spike.adapters.base import InvalidItem
from src.source_spike.raw_items import author_hash, canonical_text_fingerprint, normalize_text, validate_raw_source_item


@dataclass(frozen=True)
class ParsedTedNotice:
    item: Mapping[str, object] | None
    rejection: InvalidItem | None


def _strings(value: object) -> list[str]:
    if isinstance(value, str): return [value]
    if isinstance(value, Mapping): return [x for x in value.values() if isinstance(x, str)]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        result: list[str] = []
        for part in value: result.extend(_strings(part))
        return result
    return []


def parse_ted_notice(payload: Mapping[str, object], *, stratum: str, author_secret: bytes, run_id: str, adapter_version: str, collected_at: datetime) -> ParsedTedNotice:
    publication = payload.get("publication-number")
    notice_id = payload.get("notice-identifier")
    procedure = payload.get("procedure-identifier")
    if not all(isinstance(x, str) and x.strip() for x in (publication, notice_id, procedure)):
        return ParsedTedNotice(None, InvalidItem(None, "missing_item_id", ("publication, notice and procedure identifiers are required",)))
    buyers = sorted({value.strip() for value in _strings(payload.get("buyer-identifier")) if value.strip()}, key=lambda x: x.encode("utf-8"))
    if not buyers: return ParsedTedNotice(None, InvalidItem(str(notice_id), "missing_buyer_id", ("buyer identifier is required",)))
    title_values = _strings(payload.get("notice-title"))
    description_values = _strings(payload.get("description-proc"))
    title = normalize_text(title_values[0]) if title_values else None
    text = normalize_text(" ".join(title_values + description_values))
    if len(text) < 40: return ParsedTedNotice(None, InvalidItem(str(notice_id), "short_text", ("normalized notice text is shorter than 40 characters",)))
    date_value = payload.get("publication-date")
    try:
        published = datetime.fromisoformat(str(date_value)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except ValueError:
        return ParsedTedNotice(None, InvalidItem(str(notice_id), "invalid_timestamp", ("publication-date is invalid",)))
    material = "ted-buyers-v1\0" + "\0".join(buyers)
    stored = text[:20000]
    item: dict[str, object] = {
        "document_id": f"ted:{notice_id}", "source": "ted", "source_item_id": notice_id,
        "source_url": f"https://ted.europa.eu/en/notice/-/detail/{publication}", "item_type": "notice",
        "author_hash": author_hash("ted", material, author_secret), "community": stratum,
        "thread_id": procedure, "parent_id": None, "title": title, "text": stored,
        "text_fingerprint": canonical_text_fingerprint(stored), "text_length": len(stored),
        "original_text_length": len(text), "text_truncated": len(text) > len(stored),
        "published_at": published, "updated_at": None, "language": None, "engagement": {},
        "source_metadata": {}, "collected_at": collected_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "collector_version": adapter_version, "fetch_run_id": run_id,
    }
    errors = validate_raw_source_item(item)
    return ParsedTedNotice(None, InvalidItem(str(notice_id), "invalid_item", tuple(errors))) if errors else ParsedTedNotice(item, None)
