"""Offline, bounded evidence-pilot inputs; source truth remains human-owned."""

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher
from hashlib import sha256
from ipaddress import ip_address, IPv6Address
import json
import re
from urllib.parse import parse_qsl, unquote, urlsplit
import unicodedata

from src.contracts.validation import is_public_http_uri, is_timezone_aware_datetime
from src.extraction.development_slice import (
    ExtractionValidationError,
    extraction_to_observation,
)


def _exact_fields(value: object, fields: set[str], name: str) -> None:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"{name} requires exactly {', '.join(sorted(fields))}")


def _nonblank(value: object, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonblank string")


def _optional_nonblank(value: object, name: str) -> None:
    if value is not None:
        _nonblank(value, name)


def _canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as error:
        raise ValueError("pilot input must be canonical JSON") from error


def _is_pilot_public_uri(value: object) -> bool:
    """Reject obvious non-public authorities offline; not an authenticity check."""
    if not is_public_http_uri(value) or any(ord(char) < 32 for char in value):
        return False
    parsed = urlsplit(value)
    if parsed.username is not None or parsed.password is not None:
        return False
    host = parsed.hostname
    if not host or "%" in host:
        return False
    try:
        # IDNA normalization also handles Unicode equivalents of a DNS dot.
        host = host.encode("idna").decode("ascii").lower().removesuffix(".")
        literal = ip_address(host)
    except (ValueError, UnicodeError):
        labels = host.split(".")
        # A numeric final label can be an alternate IPv4 literal in browsers.
        # Require a conventional qualified DNS name rather than ambiguously
        # parsed numeric names, single-label intranet hosts or local suffixes.
        return (
            len(labels) > 1
            and len(host) <= 253
            and re.fullmatch(r"[a-z][a-z0-9-]*", labels[-1]) is not None
            and all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels)
            and labels[-1] not in {
                "localhost", "local", "localdomain", "internal", "lan", "home", "corp", "intranet",
            }
            and host != "home.arpa" and not host.endswith(".home.arpa")
        )
    if isinstance(literal, IPv6Address) and literal.ipv4_mapped is not None:
        literal = literal.ipv4_mapped
    return literal.is_global and not literal.is_multicast and not literal.is_reserved


def validate_row(row: dict) -> dict:
    """Validate a preserved row and return the existing observation envelope.

    ``source_verified`` is an explicit assertion from a human, not a result of
    validating shape, URLs, or quotations. No metadata is inferred here.
    Publication date text is preserved even when it cannot support recency.
    """
    _exact_fields(row, {
        "document", "extraction", "source_metadata", "source_verified",
        "thread_id", "event_id",
    }, "row")
    if not isinstance(row["source_verified"], bool):
        raise ValueError("source_verified must be boolean")
    for field in ("thread_id", "event_id"):
        _optional_nonblank(row[field], field)

    document = row["document"]
    extraction = row["extraction"]
    if not isinstance(document, dict) or not isinstance(extraction, dict):
        raise ValueError("document and extraction must be objects")
    metadata = row["source_metadata"]
    if metadata is not None and not isinstance(metadata, dict):
        raise ValueError("source_metadata must be an object or null")

    # The existing validator owns the exact document/extraction field sets,
    # span offsets and quote equality. Additional input types are checked here
    # even when an extraction abstains (and thus has no quotation to check).
    for field in ("document_id", "source", "title"):
        _nonblank(document.get(field), f"document.{field}")
    if not isinstance(document.get("text"), str):
        raise ValueError("document.text must be a string")
    if not _is_pilot_public_uri(document.get("source_url")):
        raise ValueError("document.source_url must be a public HTTP URI")
    published_at = document.get("published_at")
    if published_at is not None and not isinstance(published_at, str):
        raise ValueError("document.published_at must be a string or null")
    # Check enum types before the adapter performs set membership (which would
    # raise TypeError for JSON arrays/objects instead of validation errors).
    for field in ("observation_type", "money_signal_type"):
        if extraction.get(field) is not None and not isinstance(extraction[field], str):
            raise ExtractionValidationError(
                f"{field} must be a string or null", rule="ENUM_TYPE", field=field,
            )
    return extraction_to_observation(document, extraction, source_metadata=metadata)


def validate_manifest(manifest: dict) -> dict:
    """Return a detached snapshot of a hash-bound, structurally valid manifest."""
    _exact_fields(manifest, {
        "run_id", "as_of", "candidate_id", "source", "window_start", "window_end",
        "arms", "protocol_hash",
    }, "manifest")
    snapshot = deepcopy(manifest)
    actual_hash = sha256(_canonical_json({
        key: value for key, value in snapshot.items() if key != "protocol_hash"
    })).hexdigest()
    if snapshot["protocol_hash"] != actual_hash:
        raise ValueError("manifest protocol_hash mismatch")
    for field in ("run_id", "candidate_id", "source"):
        _nonblank(snapshot[field], field)
    timestamps = {}
    for field in ("as_of", "window_start", "window_end"):
        value = snapshot[field]
        if not is_timezone_aware_datetime(value):
            raise ValueError(f"{field} must include a timezone")
        timestamps[field] = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if timestamps["window_start"] > timestamps["window_end"]:
        raise ValueError("window_start must not follow window_end")

    _exact_fields(snapshot["arms"], {"broad", "focused"}, "arms")
    all_rows: dict[str, bytes] = {}
    for name, arm in snapshot["arms"].items():
        _exact_fields(arm, {"query", "sampling_method", "cap", "rows"}, f"{name} arm")
        for field in ("query", "sampling_method"):
            _nonblank(arm[field], f"{name}.{field}")
        cap = arm["cap"]
        if type(cap) is not int or not 1 <= cap <= 20:
            raise ValueError(f"{name}.cap must be an integer from 1 through 20")
        if not isinstance(arm["rows"], list) or len(arm["rows"]) > cap:
            raise ValueError(f"{name}.rows must be a list within the cap")
        seen: set[str] = set()
        for row in arm["rows"]:
            observation = validate_row(row)
            document_id = observation["document_id"]
            if document_id in seen:
                raise ValueError(f"duplicate document_id within {name} arm: {document_id}")
            seen.add(document_id)
            row_json = _canonical_json(row)
            if document_id in all_rows and all_rows[document_id] != row_json:
                raise ValueError(f"conflicting cross-arm document_id: {document_id}")
            all_rows[document_id] = row_json
    return snapshot


_MEMBERSHIPS = {"DIRECT", "ADJACENT", "REJECT", "UNREVIEWED"}
_DIRECT_ECONOMIC = {"DIRECT_WTP", "DIRECT_SPEND", "DIRECT_PAID_SUBSTITUTE"}
_ECONOMIC_KINDS = _DIRECT_ECONOMIC | {"ADJACENT", "NONE", "UNKNOWN"}
_COUNTER_ASSESSMENTS = {"NOT_ASSESSED", "NONE_CRITICAL", "CRITICAL", "UNCERTAIN"}
_UNREVIEWED_DECISION = {
    "membership": "UNREVIEWED", "reason": "No membership decision issued",
    "quote_meaning_verified": False, "membership_quote": None,
    "loss_direct": False, "loss_quote": None, "economic_kind": "UNKNOWN",
    "economic_reason": "Not reviewed", "economic_quote": None,
    "counter_signal": False, "counter_quote": None, "counter_assessment": "NOT_ASSESSED",
    "counter_rationale": "Not reviewed",
}


def _enum(value: object, allowed: set[str], name: str) -> None:
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f"{name} must be one of {', '.join(sorted(allowed))}")


def _validate_quote_ref(ref: object, evidence: dict | None, required: bool, name: str) -> None:
    if ref is None and not required:
        return
    _exact_fields(ref, {"quote", "start", "end"}, name)
    if (
        not isinstance(ref["quote"], str)
        or type(ref["start"]) is not int
        or type(ref["end"]) is not int
        or ref != evidence
    ):
        raise ValueError(f"{name} must match the validated extraction quote and offsets exactly")


def _validate_decision(decision: dict, envelope: dict, review_kind: str) -> None:
    _exact_fields(decision, set(_UNREVIEWED_DECISION), "membership decision")
    for field, choices in (
        ("membership", _MEMBERSHIPS), ("economic_kind", _ECONOMIC_KINDS),
        ("counter_assessment", _COUNTER_ASSESSMENTS),
    ):
        _enum(decision[field], choices, field)
    for field in ("reason", "economic_reason", "counter_rationale"):
        _nonblank(decision[field], field)
    for field in ("quote_meaning_verified", "loss_direct", "counter_signal"):
        if not isinstance(decision[field], bool):
            raise ValueError(f"{field} must be boolean")

    observation = envelope["observation"]
    evidence = observation["evidence"] if observation is not None else None
    direct = decision["membership"] == "DIRECT"
    if direct and (
        observation is None
        or observation["annotations"]["problem_signal"] is not True
        or observation["annotations"]["usable_evidence"] is not True
    ):
        raise ValueError("DIRECT membership requires a usable extracted problem")
    if decision["quote_meaning_verified"] and evidence is None:
        raise ValueError("quote meaning cannot be verified for an abstention")
    if decision["counter_assessment"] == "CRITICAL" and not decision["counter_signal"]:
        raise ValueError("CRITICAL counter assessment requires a supporting counter signal")
    if decision["membership"] == "UNREVIEWED" and any(
        decision[field] != _UNREVIEWED_DECISION[field]
        for field in _UNREVIEWED_DECISION if field not in {"reason", "economic_reason", "counter_rationale"}
    ):
        raise ValueError("UNREVIEWED decision cannot assert review findings")
    if review_kind == "AI_PROPOSAL" and (
        decision["quote_meaning_verified"] or decision["counter_signal"]
        or decision["counter_assessment"] != "NOT_ASSESSED"
    ):
        raise ValueError("AI_PROPOSAL cannot assert human quote or counter verification")

    for field, required in (
        ("membership_quote", direct), ("loss_quote", decision["loss_direct"]),
        ("economic_quote", decision["economic_kind"] in _DIRECT_ECONOMIC | {"ADJACENT"}),
        ("counter_quote", decision["counter_signal"]),
    ):
        _validate_quote_ref(decision[field], evidence, required, field)


def review_membership(manifest: dict, review: dict) -> list[dict]:
    """Bind explicit decisions to immutable rows; never infer semantic verification.

    Returns one detached audit row per arm occurrence, including rejected,
    unreviewed and overlapping documents. Only human decisions on verified
    sources and verified quote meaning can become eligible evidence.
    """
    snapshot = validate_manifest(manifest)
    _exact_fields(review, {
        "protocol_hash", "candidate_id", "actor", "task", "failure", "reviewer", "review_kind", "decisions",
    }, "review")
    review = deepcopy(review)
    if review["protocol_hash"] != snapshot["protocol_hash"]:
        raise ValueError("review protocol_hash mismatch")
    if review["candidate_id"] != snapshot["candidate_id"]:
        raise ValueError("review candidate_id mismatch")
    for field in ("actor", "task", "failure", "reviewer"):
        _nonblank(review[field], field)
    _enum(review["review_kind"], {"HUMAN", "AI_PROPOSAL"}, "review_kind")
    decisions = review["decisions"]
    if not isinstance(decisions, dict):
        raise ValueError("review decisions must be keyed by document ID")
    known_ids = {
        row["document"]["document_id"]
        for arm in snapshot["arms"].values() for row in arm["rows"]
    }
    if not set(decisions).issubset(known_ids):
        raise ValueError("review contains an unknown document ID")

    results = []
    for arm_name in ("broad", "focused"):
        for row in snapshot["arms"][arm_name]["rows"]:
            envelope = validate_row(row)
            document_id = envelope["document_id"]
            decision = deepcopy(decisions.get(document_id, _UNREVIEWED_DECISION))
            _validate_decision(decision, envelope, review["review_kind"])
            reviewed = review["review_kind"] == "HUMAN" and decision["membership"] != "UNREVIEWED"
            verified = reviewed and row["source_verified"] and decision["quote_meaning_verified"]
            eligible = verified and decision["membership"] == "DIRECT"
            results.append({
                **row, **decision, "arm": arm_name, "document_id": document_id,
                "observation": envelope, "review_kind": review["review_kind"],
                "reviewed": reviewed, "eligible": eligible,
                "loss_eligible": eligible and decision["loss_direct"],
                "economic_eligible": eligible and decision["economic_kind"] in _DIRECT_ECONOMIC,
                "counter_eligible": verified and decision["counter_assessment"] != "NOT_ASSESSED",
            })
    return results


def _publication_timestamp(value: object) -> datetime | None:
    # A calendar date or naive timestamp is source information, but not an
    # exact publication instant. Never synthesize midnight or a timezone.
    if not isinstance(value, str) or not is_timezone_aware_datetime(value):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def _canonical_link(url: str) -> tuple:
    parsed = urlsplit(url)
    host = parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
    port = parsed.port
    if port in {80, 443}:
        port = None
    # Ignore scheme/fragment, tracking parameters, and path trailing slash;
    # retain other query parameters, which can identify distinct documents.
    query = tuple(sorted((key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
                         if not key.casefold().startswith("utm_") and key.casefold() not in {"fbclid", "gclid"}))
    return host, port, unquote(parsed.path).rstrip("/"), query


def _normalized_text(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


class _Components:
    def __init__(self, size: int):
        self.parent = list(range(size))

    def find(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, i: int, j: int) -> None:
        self.parent[self.find(j)] = self.find(i)

    def groups(self) -> list[list[int]]:
        groups: dict[int, list[int]] = {}
        for i in range(len(self.parent)):
            groups.setdefault(self.find(i), []).append(i)
        return list(groups.values())


def _case_components(rows: list[dict]) -> list[list[dict]]:
    components = _Components(len(rows))
    seen = {}
    for i, row in enumerate(rows):
        for marker in (("id", row["document_id"]), ("link", _canonical_link(row["document"]["source_url"]))):
            components.union(i, seen.setdefault(marker, i))
    return [[rows[i] for i in group] for group in components.groups()]


def _metadata(row: dict, field: str):
    return (row["source_metadata"] or {}).get(field)


def _case_identity(rows: list[dict]) -> tuple[dict, list[str]]:
    values = {
        "source": {row["document"]["source"] for row in rows},
        "author": {_metadata(row, "author_hash") for row in rows},
        "community": {_metadata(row, "community") for row in rows},
        "thread": {row["thread_id"] for row in rows},
        "event": {row["event_id"] for row in rows},
        "publication_timestamp": {_publication_timestamp(row["document"]["published_at"]) for row in rows},
        "publication_date_text": {row["document"]["published_at"] for row in rows},
        "membership": {row["membership"] for row in rows if row["reviewed"]},
        # UNKNOWN is missing assessment, not a denial. The three direct
        # classifications agree on support for the candidate's economic gate;
        # an explicit ADJACENT or NONE review disagrees with that support.
        "economic_kind": {"DIRECT" if row["economic_kind"] in _DIRECT_ECONOMIC else row["economic_kind"]
                          for row in rows if row["reviewed"] and row["quote_meaning_verified"]
                          and row["economic_kind"] != "UNKNOWN"},
    }
    # loss_direct=False means no affirmative concrete loss was established;
    # it is not an explicit assertion of no loss. There is no loss-absence
    # decision in the review contract, so do not manufacture a contradiction.
    # Dates written with equivalent timezone offsets do not conflict.
    conflicts = [field for field, entries in values.items() if len(entries - {None}) > 1
                 and field != "publication_date_text"]
    if values["publication_timestamp"] == {None} and len(values["publication_date_text"] - {None}) > 1:
        conflicts.append("publication_date_text")
    # A known value can only represent the case if every verified alias has it.
    return {field: next(iter(entries)) if len(entries) == 1 else None
            for field, entries in values.items()}, conflicts


def _case_known(identity: dict, conflicts: list[str], as_of: datetime) -> bool:
    timestamp = identity["publication_timestamp"]
    return (not conflicts and all(identity[name] is not None for name in ("source", "author", "community"))
            and (identity["thread"] is not None or identity["event"] is not None)
            and timestamp is not None and timestamp <= as_of)


def _related(left: dict, right: dict) -> bool:
    # Thread/author/community identifiers are source scoped. Event identifiers
    # are explicit shared-event assertions, so can link across sources.
    for lrow in left["rows"]:
        for rrow in right["rows"]:
            same_source = lrow["document"]["source"] == rrow["document"]["source"]
            if same_source and any(x is not None and x == y for x, y in (
                (_metadata(lrow, "author_hash"), _metadata(rrow, "author_hash")),
                (lrow["thread_id"], rrow["thread_id"]),
            )):
                return True
            if lrow["event_id"] is not None and lrow["event_id"] == rrow["event_id"]:
                return True
            ldate = _publication_timestamp(lrow["document"]["published_at"])
            rdate = _publication_timestamp(rrow["document"]["published_at"])
            community = _metadata(lrow, "community")
            if (same_source and community is not None and community == _metadata(rrow, "community")
                    and (ldate is None or rdate is None or abs(ldate - rdate) <= timedelta(days=7))):
                return True
            for ltext, rtext in ((lrow["document"]["text"], rrow["document"]["text"]),
                                (lrow["membership_quote"]["quote"], rrow["membership_quote"]["quote"])):
                ltext, rtext = _normalized_text(ltext), _normalized_text(rtext)
                if ltext and rtext and (ltext == rtext or SequenceMatcher(None, ltext, rtext, autojunk=False).ratio() >= .85):
                    return True
    return False


_PILOT_MINIMA = {"verified_author_count": 5, "known_group_count": 3, "recent_case_count": 10,
                 "loss_count": 2, "direct_economic_count": 2, "representative_source_link_count": 3,
                 "counter_status": "NONE_CRITICAL"}


def summarize_pilot(manifest: dict, review: dict) -> dict:
    """Count attributable evidence, not opportunities or statistical effects.

    Input occurrences are preserved for arm yield. Global cases collapse IDs
    and canonical links; conservative groups connect source-scoped author,
    thread, shared event, normalized text (similarity >= .85), and pairwise
    same-community publication timestamps within seven days (or unknown), transitively.
    These deterministic rules cannot prove semantic independence. Unknown or
    conflicting identity metadata does not create a known group or new signal.
    """
    rows = review_membership(manifest, review)
    as_of = _publication_timestamp(manifest["as_of"])
    start, end = (_publication_timestamp(manifest[key]) for key in ("window_start", "window_end"))
    arms = {}
    for name in ("broad", "focused"):
        arm = [row for row in rows if row["arm"] == name]
        proposals = [row for row in arm if row["review_kind"] == "AI_PROPOSAL" and row["membership"] != "UNREVIEWED"]
        # Occurrences remain auditable. If different IDs alias the same URL,
        # collapse them even within an arm; duplicate arms cannot compare.
        arm_cases = _case_components(arm)
        arms[name] = {"row_count": len(arm), "reviewed_denominator": sum(any(row["reviewed"] for row in case) for case in arm_cases),
                      "direct_eligible_count": sum(any(row["eligible"] for row in case) for case in arm_cases),
                      "reviewed_occurrence_count": sum(row["reviewed"] for row in arm),
                      "direct_eligible_occurrence_count": sum(row["eligible"] for row in arm),
                      "proposal_count": len(proposals), "proposed_direct_count": sum(row["membership"] == "DIRECT" for row in proposals)}

    unique_cases = _case_components(rows)
    publication_records = []
    for case in unique_cases:
        for document_id in sorted({row["document_id"] for row in case}):
            row = next(row for row in case if row["document_id"] == document_id)
            raw = row["document"]["published_at"]
            timestamp = _publication_timestamp(raw)
            precision = "TIMESTAMP" if timestamp is not None else "UNKNOWN"
            if precision == "UNKNOWN" and isinstance(raw, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
                try:
                    date.fromisoformat(raw)
                    precision = "DATE_ONLY"
                except ValueError:
                    pass
            publication_records.append({"document_id": document_id, "published_at": raw, "precision": precision,
                                        "source_verified": row["source_verified"]})
    overlap_cases = [case for case in unique_cases if len({row["arm"] for row in case}) == 2]
    overlap = {
        "count": len(overlap_cases),
        "document_ids": sorted({row["document_id"] for case in overlap_cases for row in case}),
        "canonical_source_links": sorted({case[0]["document"]["source_url"] for case in overlap_cases}),
    }
    unknown_counts = dict.fromkeys(("author", "community", "publication_timestamp", "date_only", "independence",
                                   "economic", "loss", "counter", "source_verification", "human_review"), 0)
    conflicts = []
    candidates = []
    for case in unique_cases:
        eligible = [row for row in case if row["eligible"]]
        unknown_counts["source_verification"] += not any(row["source_verified"] for row in case)
        unknown_counts["human_review"] += not any(row["reviewed"] for row in case)
        unknown_counts["counter"] += not any(row["counter_eligible"] for row in case)
        if not eligible:
            continue
        identity, case_conflicts = _case_identity([row for row in case if row["source_verified"]])
        ids = sorted({row["document_id"] for row in case})
        if case_conflicts:
            conflict = {"document_ids": ids, "fields": case_conflicts}
            if "economic_kind" in case_conflicts:
                conflict["economic_dispositions"] = sorted({row["economic_kind"] for row in case
                    if row["source_verified"] and row["reviewed"] and row["quote_meaning_verified"]
                    and row["economic_kind"] != "UNKNOWN"})
            conflicts.append(conflict)
        known = _case_known(identity, case_conflicts, as_of)
        for field in ("author", "community", "publication_timestamp"):
            unknown_counts[field] += identity[field] is None
        unknown_counts["date_only"] += any(record["precision"] == "DATE_ONLY" and record["document_id"] in ids
                                            for record in publication_records)
        unknown_counts["independence"] += not known
        unknown_counts["economic"] += all(row["economic_kind"] == "UNKNOWN" for row in eligible)
        unknown_counts["loss"] += not any(row["loss_eligible"] for row in eligible)
        candidates.append({"identity": identity, "known": known, "conflicts": case_conflicts,
                           "rows": eligible, "document_ids": ids,
                           "source_link": eligible[0]["document"]["source_url"]})

    components = _Components(len(candidates))
    for i, left in enumerate(candidates):
        for j in range(i):
            if _related(left, candidates[j]):
                components.union(i, j)
    group_details = []
    for indices in components.groups():
        cases = [candidates[i] for i in indices]
        known_cases = [case for case in cases if case["known"]]
        known_rows = [row for case in known_cases for row in case["rows"]]
        group_details.append({"document_ids": sorted({doc for c in cases for doc in c["document_ids"]}),
                              "known": bool(known_cases), "loss": any(row["loss_eligible"] for row in known_rows),
                              "direct_economic": any(row["economic_eligible"] for row in known_rows)})

    usable = [case for case in candidates if not case["conflicts"]]
    for name, arm in arms.items():
        # The raw occurrence count above preserves what was marked eligible,
        # while the conservative numerator excludes globally conflicting aliases.
        arm["direct_eligible_count"] = sum(any(row["arm"] == name for row in case["rows"]) for case in usable)
    authors = {(case["identity"]["source"], case["identity"]["author"]) for case in usable
               if case["identity"]["source"] is not None and case["identity"]["author"] is not None}
    links = sorted(case["source_link"] for case in usable)
    recent = [case for case in usable if case["identity"]["publication_timestamp"] is not None
              and max(start, as_of - timedelta(days=90)) <= case["identity"]["publication_timestamp"] <= min(end, as_of)]

    assessed = [row for row in rows if row["reviewed"] and row["counter_assessment"] != "NOT_ASSESSED"]
    verified_critical = [row for row in assessed if row["counter_eligible"] and row["counter_assessment"] == "CRITICAL"]
    uncertain = [row for row in assessed if not row["counter_eligible"] or row["counter_assessment"] == "UNCERTAIN"]
    # Without a candidate-level assessment field, require an explicit verified
    # NONE_CRITICAL assessment for every distinct preserved case to clear this
    # gate. A partial positive review is not an assessment of the full sample.
    if verified_critical:
        counter_status = "CRITICAL"
    elif uncertain:
        counter_status = "UNCERTAIN"
    elif assessed and all(any(row["counter_eligible"] and row["counter_assessment"] == "NONE_CRITICAL" for row in case)
                          for case in unique_cases):
        counter_status = "NONE_CRITICAL"
    else:
        counter_status = "NOT_ASSESSED"

    comparison_reasons = []
    broad, focused = manifest["arms"]["broad"], manifest["arms"]["focused"]
    if broad["sampling_method"] != focused["sampling_method"] or broad["cap"] != focused["cap"]:
        comparison_reasons.append("Sampling methods or caps differ")
    if (not arms["broad"]["reviewed_denominator"] or
            arms["broad"]["reviewed_denominator"] != arms["focused"]["reviewed_denominator"]):
        comparison_reasons.append("Human-reviewed denominators are unequal or zero")
    elif any(arm["reviewed_denominator"] != sum(any(row["arm"] == name for row in case)
                                               for case in unique_cases) for name, arm in arms.items()):
        # Equal denominators alone can conceal selectively reviewing favorable
        # cases after sampling. Both frozen arms must be reviewed completely.
        comparison_reasons.append("Complete human review of both frozen arms is required")
    if overlap_cases or len(unique_cases) != len(rows):
        comparison_reasons.append("Document or canonical-source overlap/duplicates")
    if any(row["document"]["source"] != manifest["source"] for row in rows):
        comparison_reasons.append("Actual sources do not match the locked source")
    if end > as_of or any(not row["source_verified"] or (timestamp := _publication_timestamp(row["document"]["published_at"])) is None
                          or not start <= timestamp <= end for row in rows):
        comparison_reasons.append("Actual verified publication timestamps do not establish the locked window")

    summary = {"arms": arms, "overlap": overlap, "combined_unique_cases": len(unique_cases),
               "eligible_unique_cases": len(usable), "review_eligible_unique_cases": len(candidates),
               "conflicted_eligible_case_count": len(candidates) - len(usable), "verified_author_count": len(authors),
               "known_group_count": sum(group["known"] for group in group_details), "recent_case_count": len(recent),
               "loss_count": sum(group["loss"] for group in group_details),
               "direct_economic_count": sum(group["direct_economic"] for group in group_details),
               "source_links": links, "representative_source_link_count": len(links), "counter_status": counter_status,
               "critical_counter_document_ids": sorted({row["document_id"] for row in verified_critical}),
               "uncertain_counter_document_ids": sorted({row["document_id"] for row in uncertain}),
               "unknown_counts": unknown_counts, "conflicts": conflicts, "group_details": group_details,
               "unknown_counts_scope": {"review_eligible_unique_cases": ["author", "community", "publication_timestamp", "date_only", "independence", "economic", "loss"],
                                        "all_unique_cases": ["counter", "source_verification", "human_review"]},
               "unknown_counts_note": "loss means no eligible concrete loss established; it does not establish absence of loss.",
               "publication_records": publication_records,
               "publication_precision_counts": {precision: sum(record["precision"] == precision for record in publication_records)
                                                for precision in ("TIMESTAMP", "DATE_ONLY", "UNKNOWN")},
               "comparison_valid": not comparison_reasons,
               "comparison_reason": "; ".join(comparison_reasons) + ". Descriptive counts only; no statistical or causal claim."
                   if comparison_reasons else "Matched protocol and disjoint human-reviewed arms; descriptive counts only, no statistical or causal claim.",
               "gate_thresholds": dict(_PILOT_MINIMA)}
    summary["gate_deficits"] = [{"gate": gate, "required": minimum, "actual": summary[gate]}
        for gate, minimum in _PILOT_MINIMA.items()
        if (summary[gate] < minimum if isinstance(minimum, int) else summary[gate] != minimum)]
    return summary
