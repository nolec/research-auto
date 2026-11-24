"""Prediction-free review and frozen-prompt evaluation of 40 held-out saved documents."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from hashlib import sha256
import json
from pathlib import Path

from src.extraction import semantic_problem_development as dev
from src.extraction.rule_baseline import _extract
from src.research_console import ROOT, runs

MANIFEST = ROOT / "configs/extraction/semantic-problem-holdout-v1.csv"
BASE = dev.RUN_ROOT / "semantic-problem-holdout-v1"
TEMPLATE = ROOT / "docs/semantic-problem-holdout-review-template.html"
KOREAN_SUMMARIES = ROOT / "configs/extraction/semantic-problem-holdout-v1-ko.json"
KOREAN_CORRECTIONS = ROOT / "configs/extraction/semantic-problem-holdout-v1-ko-corrections.json"


def prepare():
    with MANIFEST.open() as stream:
        entries = list(csv.DictReader(stream))
    ids = {entry["document_id"] for entry in entries}
    with dev.MANIFEST.open() as stream:
        development = list(csv.DictReader(stream))
    with (ROOT / "configs/cluster-development-pairs-v1.csv").open() as stream:
        pairs = list(csv.DictReader(stream))
    excluded_ids = {row["document_id"] for row in development} | {
        row[side] for row in pairs for side in ("left", "right")}
    excluded_hashes = {row["text_sha256"] for row in development} | {
        row[side + "_sha256"] for row in pairs for side in ("left", "right")}
    hashes = {entry["text_sha256"] for entry in entries}
    if len(entries) != 40 or len(ids) != 40 or len(hashes) != 40 or ids & excluded_ids or hashes & excluded_hashes:
        raise ValueError("holdout overlaps prior reviewed cases or has duplicate entries")
    versions = {}
    dates = {}
    for path in runs():
        for row in json.loads(path.read_text())["items"]:
            key = row["document_id"]
            if key not in ids:
                continue
            doc = {field: row[field] for field in ("document_id", "source", "title", "text", "published_at")}
            if key in versions and any(versions[key][field] != doc[field]
                                       for field in ("source", "title", "text")):
                raise ValueError(f"conflicting document: {key}")
            versions[key] = doc
            dates.setdefault(key, set()).add(doc["published_at"])
    documents = []
    for entry in entries:
        doc = versions[entry["document_id"]]
        if sha256(doc["text"].encode()).hexdigest() != entry["text_sha256"]:
            raise ValueError("source changed")
        # The archived TED runs disagree on their publication date metadata.
        # Date is irrelevant to this semantic test; retain uncertainty.
        if len(dates[doc["document_id"]]) > 1:
            doc["published_at"] = "unknown"
        documents.append(doc)
    if Counter(doc["source"] for doc in documents) != dict.fromkeys(("github", "stackexchange", "steam", "ted"), 10):
        raise ValueError("source counts changed")
    binding = {"documents": documents, "prompt": dev.PROMPT, "schema": dev.SCHEMA, "model": dev.MODEL}
    digest = sha256(json.dumps(binding, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return documents, digest


def korean_summaries():
    original = KOREAN_SUMMARIES.read_bytes()
    summaries = json.loads(original)
    corrections = json.loads(KOREAN_CORRECTIONS.read_text())
    if not set(corrections) <= set(summaries):
        raise ValueError("summary correction membership mismatch")
    summaries.update(corrections)
    digest = sha256(json.dumps(summaries, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return summaries, digest


def read_labels(documents, digest, payload):
    labels = payload.get("labels")
    if (payload.get("snapshot_sha256") != digest or not isinstance(labels, dict)
            or set(labels) != {d["document_id"] for d in documents}
            or any(state not in dev.STATES for state in labels.values())):
        raise ValueError("wrong snapshot or incomplete/invalid review")
    if payload.get("presentation", "original") not in ("original", "ai_summary_ko", "ai_source_review"):
        raise ValueError("unknown review presentation")
    if payload.get("presentation") == "ai_source_review":
        reasons = payload.get("reasons")
        if (not isinstance(reasons, dict) or set(reasons) != set(labels)
                or any(not isinstance(reason, str) or not reason.strip() for reason in reasons.values())):
            raise ValueError("AI source review requires reasons for all labels")
    if payload.get("presentation") == "ai_summary_ko" and payload.get("presentation_sha256") not in (
        sha256(KOREAN_SUMMARIES.read_bytes()).hexdigest(), korean_summaries()[1]
    ):
        raise ValueError("summary presentation changed")
    return labels


def review_label_type(payload):
    return {
        "original": "USER_REVIEWED_HOLDOUT",
        "ai_summary_ko": "USER_REVIEWED_AI_SUMMARIZED_HOLDOUT",
        "ai_source_review": "AI_REVIEWED_HELDOUT_DIAGNOSTIC",
    }[payload.get("presentation", "original")]


def render(documents, digest, *, korean=False):
    data = {"records": documents, "hash": digest, "presentation": "original"}
    if korean:
        summaries, summary_digest = korean_summaries()
        if set(summaries) != {doc["document_id"] for doc in documents}:
            raise ValueError("summary membership mismatch")
        data.update(records=[{**doc, "summary_ko": summaries[doc["document_id"]]} for doc in documents],
                    presentation="ai_summary_ko", presentation_sha256=summary_digest)
    payload = json.dumps(data, ensure_ascii=False)
    payload = payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return TEMPLATE.read_text().replace("/*__PAYLOAD__*/ null", payload, 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--review", action="store_true")
    action.add_argument("--execute", action="store_true")
    parser.add_argument("--labels", type=Path)
    args = parser.parse_args()
    documents, digest = prepare()
    if args.review:
        BASE.mkdir(mode=0o700, exist_ok=True)
        path = BASE / "review-ko-v2.html"
        html = render(documents, digest, korean=True)
        if path.exists():
            if path.read_text() != html:
                raise ValueError("existing review differs from frozen snapshot")
        else:
            with path.open("x", encoding="utf-8") as stream:
                stream.write(html)
        print(json.dumps({"status": "HUMAN_REVIEW_PENDING", "documents": 40,
                          "snapshot_sha256": digest, "review": str(path)}))
        return 0
    if args.labels is None:
        parser.error("--labels is required for comparison")
    raw = args.labels.read_bytes()
    payload = json.loads(raw)
    gold = read_labels(documents, digest, payload)
    baseline = dev.compare(gold, {doc["document_id"]: "yes" if _extract(doc)["problem_signal"] else "unknown"
                                  for doc in documents})
    labels_hash = sha256(raw).hexdigest()
    root = BASE / ("run-" + labels_hash[:16])
    BASE.mkdir(mode=0o700, exist_ok=True)
    schema = json.dumps(dev.SCHEMA, sort_keys=True).encode()
    result = dev.execute(root, documents, gold, baseline,
                         lambda doc: dev.run_document(doc, 120, dev.PROMPT.encode(), schema,
                                                        allow_chronicle_startup_warning=True,
                                                        semantic_validator=dev.validate),
                         manifest=MANIFEST, label_type=review_label_type(payload),
                         label_binding={"snapshot_sha256": digest, "labels_sha256": labels_hash,
                                        "presentation": payload.get("presentation", "original"),
                                        "presentation_sha256": payload.get("presentation_sha256"),
                                        "labels": gold})
    print(json.dumps({**result, "result": str(root / "result.json")}))
    return 0 if result["status"] == "MEASURED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
