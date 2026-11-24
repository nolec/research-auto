"""Frozen, source-reviewed public evidence diagnostic; not an opportunity scorer."""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator, ValidationError

from src.extraction import codex_cli_diagnostic as cli
from src.extraction import solution_gap_diagnostic as base
from src.extraction.codex_cli_development_v2 import MODEL, run_document

MANIFEST = cli.ROOT / "configs/extraction/solution-gap-holdout-v1.json"
RUN_ROOT = base.RUN_ROOT
LABEL_TYPE = "AI_REVIEWED_PURPOSIVE_PUBLIC_EVIDENCE_HOLDOUT"
FIELDS = (*base.FIELDS, "context")
SCHEMA = base.SCHEMA
PROMPT = base.PROMPT.replace("independent synthetic evidence bundle", "independent public evidence bundle") + """
Context is neutral source and speaker/date metadata, not a separate quote source.
Judge at the recorded observation time, not current product behavior; do not assume a later repair.
The scope is a proposed research question, not an asserted observed problem. Use ADJACENT
when the supplied user report concerns a materially different task. A proposed fix, accepted
answer, or identification of a cause without an observed outcome is not successful resolution.
Payment claims are self-reported, not independently verified transactions. Never quote context;
quote only the two literal excerpts, preserving their exact characters and spacing."""


def prepare(manifest=None):
    if manifest is None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest["label_type"] != LABEL_TYPE:
        raise ValueError("wrong reference provenance")
    entries = manifest["cases"]
    labels = {row["id"]: row["label"] for row in entries}
    distribution = Counter(labels.values())
    if (not 15 <= len(entries) <= 20 or len(labels) != len(entries)
            or set(distribution) != set(base.STATES) or max(distribution.values()) > 5):
        raise ValueError("invalid case distribution or duplicate id")
    sources = set()
    urls = set()
    cases = []
    for row in entries:
        fields = (*FIELDS, "source_url", "source_id", "rationale")
        if any(not isinstance(row[key], str) or not row[key].strip() for key in fields):
            raise ValueError("empty case field")
        source, url = row["source_id"], urlsplit(row["source_url"])
        canonical = (url.hostname, url.path.rstrip("/"))
        if source in sources or canonical in urls:
            raise ValueError("duplicate source")
        if url.scheme != "https" or not url.hostname or not url.path or url.username or url.password:
            raise ValueError("invalid public source URL")
        sources.add(source)
        urls.add(canonical)
        if len((row["problem"] + " " + row["followup"]).split()) > 25:
            raise ValueError("source quote budget exceeded")
        cases.append({field: row[field] for field in FIELDS})
    document = {"document_id": "solution-gap-holdout-v1", "source": "public-evidence-excerpts",
                "title": "Public solution-gap evidence pairs", "published_at": manifest["as_of"],
                "text": json.dumps(cases, ensure_ascii=False)}
    return document, labels, cases


def gate(score):
    critical = ("false_discard", "false_gap_promotion", "unsupported_paid_claim", "invalid")
    return "PASS_DEVELOPMENT_ONLY" if score["accuracy"] >= .90 and all(score[k] == 0 for k in critical) else "FAIL"


def execute(root, call):
    document, labels, cases = prepare()
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    result = {"status": "INCOMPLETE", "reason": None, "gate": "NOT_EVALUATED", "model": MODEL,
              "cases": len(cases), "label_type": LABEL_TYPE,
              "manifest_sha256": sha256(MANIFEST.read_bytes()).hexdigest(),
              "implementation_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
              "scorer_sha256": sha256(Path(base.__file__).read_bytes()).hexdigest(),
              "prompt_sha256": sha256(PROMPT.encode()).hexdigest(),
              "schema_sha256": sha256(json.dumps(SCHEMA, sort_keys=True).encode()).hexdigest(),
              "baseline_not_assessed_as_unknown": base.compare(labels, dict.fromkeys(labels, "UNKNOWN")),
              "official_opportunities": 0}
    try:
        response, _ = call(document)
        Draft202012Validator(SCHEMA).validate(response)
        if response["document_id"] != document["document_id"]:
            raise ValueError("document identity mismatch")
        predictions = base.project(cases, response["rows"])
        semantic = base.compare(labels, predictions)
        cli._private_create(root / "predictions.json", {"rows": response["rows"], "projection": predictions})
        result.update(status="MEASURED", semantic=semantic, gate=gate(semantic))
    except cli.CliContractError as error:
        result.update(reason=str(error), error_class=error.diagnostics["error_class"])
    except (ValidationError, ValueError, TypeError, KeyError):
        result.update(reason="INVALID_BATCH", error_class="UNKNOWN")
    except OSError as error:
        error_class = ("EXECUTABLE_NOT_FOUND" if isinstance(error, FileNotFoundError) else
                       "PERMISSION_ERROR" if isinstance(error, PermissionError) else "OPERATIONAL_ERROR")
        result.update(reason="CLI_OS_ERROR", error_class=error_class)
    cli._private_create(root / "result.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--check", action="store_true")
    actions.add_argument("--execute", action="store_true")
    parser.add_argument("--run-id", default="solution-gap-holdout-v1")
    args = parser.parse_args()
    if not args.run_id.startswith("solution-gap-holdout-v1") or not args.run_id.replace("-", "").isalnum():
        parser.error("invalid run id")
    root = RUN_ROOT / args.run_id
    if args.check:
        _, labels, _ = prepare()
        print(json.dumps({"status": "INPUTS_VALIDATED", "cases": len(labels), "labels": dict(Counter(labels.values())),
                          "manifest_sha256": sha256(MANIFEST.read_bytes()).hexdigest(), "run_exists": root.exists()}))
        return 0
    if root.exists():
        parser.error("run exists; use a new run id")

    def validate_document(document, response):
        if document["document_id"] != response["document_id"]:
            raise ValueError("document identity mismatch")
        base.project(json.loads(document["text"]), response["rows"])

    result = execute(root, lambda doc: run_document(doc, 180, PROMPT.encode(), json.dumps(SCHEMA).encode(),
                         allow_chronicle_startup_warning=True, semantic_validator=validate_document))
    print(json.dumps({"status": result["status"], "reason": result["reason"], "cases": result["cases"],
                      "gate": result["gate"], "semantic": result.get("semantic"), "error_class": result.get("error_class"),
                      "result": str(root / "result.json")}))
    return 0 if result["status"] == "MEASURED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
