"""Controlled, synthetic solution-gap judgment diagnostic; never promotes cards."""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

from src.extraction import codex_cli_diagnostic as cli
from src.extraction.codex_cli_development_v2 import MODEL, run_document

MANIFEST = cli.ROOT / "configs/extraction/solution-gap-diagnostic-v1.json"
RUN_ROOT = cli.ROOT / "artifacts/extraction/calibration/audit-local"
STATES = ("RESOLVED", "PERSISTING", "PAID_PERSISTING", "ADJACENT", "UNKNOWN")
GAPS = {"PERSISTING", "PAID_PERSISTING"}
LABEL_TYPE = "SYNTHETIC_CONTROLLED_DIAGNOSTIC_NOT_EXTERNAL_GOLD"
FIELDS = ("id", "scope", "problem", "followup")
ROW_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["id", "state", "problem_quote", "followup_quote"],
    "properties": {"id": {"type": "string"}, "state": {"enum": list(STATES)},
                   "problem_quote": {"type": "string"}, "followup_quote": {"type": "string"}},
}
SCHEMA = {"type": "object", "additionalProperties": False,
          "required": ["document_id", "rows"],
          "properties": {"document_id": {"type": "string"},
                         "rows": {"type": "array", "items": ROW_SCHEMA}}}
PROMPT = """Judge each independent synthetic evidence bundle against its narrow scope.
RESOLVED: explicit observed successful outcome for the same task, not just feature presence.
PERSISTING: explicit observed ongoing failure of the same task despite an existing attempted solution;
no verified linked actual payment. WILLINGNESS, quotes or awards are not actual payment.
PAID_PERSISTING: explicit actual payment for the attempted solution for this task AND observed
ongoing failure after it. Payment for another task or an advertised price does not count.
ADJACENT: the supplied alleged supporting problem or purchase observation concerns another task;
shared product, vocabulary or actor is insufficient. UNKNOWN: no supported current outcome for the
scoped problem, for example historical complaints plus new documentation, or untested features.
An unrelated alternative alone does not prove the scoped problem is adjacent or solved.
Read only supplied evidence. Do not assume that current documentation proves an actual fix, or
that an old complaint proves a current gap. Do not infer payment, independence or market viability.
For every case return its unchanged id, one state, and a nonempty exact contiguous quotation of
at most 25 words from each of problem and followup. Quotes must be the relevant evidence or
the reason for uncertainty. Return each case exactly once and no others. Return only schema JSON."""


def prepare():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest["label_type"] != LABEL_TYPE:
        raise ValueError("unexpected label provenance")
    entries = manifest["cases"]
    labels = {row["id"]: row["label"] for row in entries}
    if len(entries) != 20 or len(labels) != 20 or Counter(labels.values()) != dict.fromkeys(STATES, 4):
        raise ValueError("invalid frozen case distribution")
    cases = [{key: row[key] for key in FIELDS} for row in entries]
    if any(not isinstance(v, str) or not v.strip() for row in cases for v in row.values()):
        raise ValueError("empty case field")
    doc = {"document_id": "solution-gap-diagnostic-v1", "source": "synthetic",
           "title": "Controlled solution-gap cases", "published_at": manifest["as_of"],
           "text": json.dumps(cases, ensure_ascii=False)}
    return doc, labels, cases


def project(cases, rows):
    by_id = {case["id"]: case for case in cases}
    if len(by_id) != len(cases) or len(rows) != len(cases):
        raise ValueError("incomplete or duplicate case set")
    predictions = {}
    for row in rows:
        key = row["id"]
        if key not in by_id or key in predictions:
            raise ValueError("unexpected or duplicate prediction id")
        case = by_id[key]
        try:
            Draft202012Validator(ROW_SCHEMA).validate(row)
            for field in ("problem", "followup"):
                quote = row[field + "_quote"]
                if not quote.strip() or len(quote.split()) > 25 or quote not in case[field]:
                    raise ValueError("ungrounded quote")
            predictions[key] = row["state"]
        except (ValueError, ValidationError):
            predictions[key] = "INVALID"
    return predictions


def compare(gold, predictions):
    if not gold or set(gold) != set(predictions) or set(gold.values()) - set(STATES) or set(predictions.values()) - {*STATES, "INVALID"}:
        raise ValueError("invalid or incomplete prediction set")
    counts = Counter((label, predictions[key]) for key, label in gold.items())
    correct = sum(counts[state, state] for state in STATES)
    return {"correct": correct, "total": len(gold), "accuracy": correct / len(gold),
            "false_discard": sum(counts[state, "RESOLVED"] for state in GAPS),
            "false_gap_promotion": sum(counts[label, state] for label in STATES if label not in GAPS for state in GAPS),
            "unsupported_paid_claim": sum(counts[label, "PAID_PERSISTING"] for label in STATES if label != "PAID_PERSISTING"),
            "missed_persisting": sum(counts[label, state] for label in GAPS for state in (*STATES, "INVALID") if state not in GAPS),
            "invalid": sum(v == "INVALID" for v in predictions.values()),
            "by_label": {label: {state: counts[label, state] for state in (*STATES, "INVALID")} for label in STATES}}


def execute(root, call):
    doc, labels, cases = prepare()
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    result = {"status": "INCOMPLETE", "reason": None, "model": MODEL, "cases": len(cases),
              "label_type": LABEL_TYPE, "manifest_sha256": sha256(MANIFEST.read_bytes()).hexdigest(),
              "implementation_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
              "prompt_sha256": sha256(PROMPT.encode()).hexdigest(),
              "schema_sha256": sha256(json.dumps(SCHEMA, sort_keys=True).encode()).hexdigest(),
              "baseline_not_assessed_as_unknown": compare(labels, dict.fromkeys(labels, "UNKNOWN")),
              "official_opportunities": 0}
    try:
        response, _ = call(doc)
        Draft202012Validator(SCHEMA).validate(response)
        if response["document_id"] != doc["document_id"]:
            raise ValueError("document identity mismatch")
        predictions = project(cases, response["rows"])
        cli._private_create(root / "predictions.json", {"rows": response["rows"], "projection": predictions})
        result.update(status="MEASURED", semantic=compare(labels, predictions))
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
    parser.add_argument("--run-id", default="solution-gap-diagnostic-v1")
    args = parser.parse_args()
    if not args.run_id.startswith("solution-gap-diagnostic-v1") or not args.run_id.replace("-", "").isalnum():
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
        project(json.loads(document["text"]), response["rows"])

    result = execute(root, lambda doc: run_document(doc, 180, PROMPT.encode(), json.dumps(SCHEMA).encode(),
                         allow_chronicle_startup_warning=True, semantic_validator=validate_document))
    print(json.dumps({"status": result["status"], "reason": result["reason"], "cases": result["cases"],
                      "semantic": result.get("semantic"), "error_class": result.get("error_class"),
                      "result": str(root / "result.json")}))
    return 0 if result["status"] == "MEASURED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
