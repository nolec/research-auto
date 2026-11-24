"""Temporal-outcome revision; score prior regression and fresh evidence separately."""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator, ValidationError

from src.extraction import solution_gap_holdout as v1
from src.extraction import solution_gap_diagnostic as base
from src.extraction import codex_cli_diagnostic as cli
from src.extraction.codex_cli_development_v2 import MODEL, run_document

MANIFEST = cli.ROOT / "configs/extraction/solution-gap-holdout-v2.json"
SCHEMA = v1.SCHEMA
RUN_ROOT = v1.RUN_ROOT
PROMPT = v1.PROMPT + """
Temporal outcome decision rule (applies to both positive and negative conclusions):
Distinguish (A) an initial problem or description of its cause, (B) a concrete relevant
remedy actually applied or tried, and (C) observed outcome after that attempt. Before
labeling PERSISTING or RESOLVED, establish B and C for the scoped task. A cause diagnosis,
description of the same original symptom, intent to try, suggested setting, deployment
announcement without an observed test, or accepted-answer marker is not B plus C.
If the only scoped evidence is A and no attempted remedy with observed outcome is
established, choose UNKNOWN, even when the original problem was clearly real. If the
scope specifically asks about a proposed remedy, assess that remedy rather than earlier
unrelated attempts. Conversely, an explicit failed relevant repair/retry is usable
evidence of persistence at the observation time; later untested suggestions do not erase
that observed failure. A purchased solution actually used for this task that still fails
after payment is a relevant attempted solution, so retain PAID_PERSISTING when the
user's payment and subsequent failure are explicit. A successful workaround is RESOLVED
for the narrow task it demonstrably achieves, not for broader functionality. Do not
merge different users' states; a different user's same-task direct trial is evidence for
that trial only, not proof that the initial author was helped. Follow the exact scope."""


def prepare(fresh_manifest=None):
    old = json.loads(v1.MANIFEST.read_text(encoding="utf-8"))
    fresh = (json.loads(MANIFEST.read_text(encoding="utf-8")) if fresh_manifest is None
             else fresh_manifest)
    _, old_labels, old_cases = v1.prepare(old)
    _, new_labels, new_cases = v1.prepare(fresh)

    def identities(manifest):
        ids = {row["source_id"] for row in manifest["cases"]}
        urls = {(urlsplit(row["source_url"]).hostname, urlsplit(row["source_url"]).path.rstrip("/"))
                for row in manifest["cases"]}
        return ids, urls

    old_ids, old_urls = identities(old)
    new_ids, new_urls = identities(fresh)
    if old_ids & new_ids or old_urls & new_urls or set(old_labels) & set(new_labels):
        raise ValueError("regression and fresh source or id overlap")
    if len({urlsplit(row["source_url"]).hostname for row in fresh["cases"]}) < 3:
        raise ValueError("insufficient fresh platform coverage")
    # Interleave without exposing cohort membership or labels as extra fields.
    cases = []
    for index in range(max(len(old_cases), len(new_cases))):
        if index < len(old_cases):
            cases.append(old_cases[index])
        if index < len(new_cases):
            cases.append(new_cases[index])
    document = {"document_id": "solution-gap-holdout-v2", "source": "public-evidence-excerpts",
                "title": "Public solution-gap evidence pairs", "published_at": fresh["as_of"],
                "text": json.dumps(cases, ensure_ascii=False)}
    return document, {"regression": old_labels, "fresh": new_labels}, cases


def gate(regression, fresh, h10_corrected):
    return ("PASS_DEVELOPMENT_ONLY" if h10_corrected and
            v1.gate(regression) == v1.gate(fresh) == "PASS_DEVELOPMENT_ONLY" else "FAIL")


def execute(root, call):
    document, gold, cases = prepare()
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    result = {"status": "INCOMPLETE", "reason": None, "gate": "NOT_EVALUATED", "model": MODEL,
              "cases": len(cases), "label_type": v1.LABEL_TYPE,
              "manifest_sha256": sha256(MANIFEST.read_bytes()).hexdigest(),
              "regression_manifest_sha256": sha256(v1.MANIFEST.read_bytes()).hexdigest(),
              "implementation_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
              "v1_implementation_sha256": sha256(Path(v1.__file__).read_bytes()).hexdigest(),
              "scorer_sha256": sha256(Path(base.__file__).read_bytes()).hexdigest(),
              "prompt_sha256": sha256(PROMPT.encode()).hexdigest(),
              "schema_sha256": sha256(json.dumps(SCHEMA, sort_keys=True).encode()).hexdigest(),
              "official_opportunities": 0}
    try:
        response, _ = call(document)
        Draft202012Validator(SCHEMA).validate(response)
        if response["document_id"] != document["document_id"]:
            raise ValueError("document identity mismatch")
        predictions = base.project(cases, response["rows"])
        scores = {cohort: base.compare(labels, {key: predictions[key] for key in labels})
                  for cohort, labels in gold.items()}
        corrected = predictions["h10"] == "UNKNOWN"
        cli._private_create(root / "predictions.json", {"rows": response["rows"], "projection": predictions})
        result.update(status="MEASURED", **scores, h10_corrected=corrected,
                      gate=gate(scores["regression"], scores["fresh"], corrected))
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
    parser.add_argument("--run-id", default="solution-gap-holdout-v2")
    args = parser.parse_args()
    if not args.run_id.startswith("solution-gap-holdout-v2") or not args.run_id.replace("-", "").isalnum():
        parser.error("invalid run id")
    root = RUN_ROOT / args.run_id
    if args.check:
        _, gold, cases = prepare()
        print(json.dumps({"status": "INPUTS_VALIDATED", "cases": len(cases),
                          "distribution": {key: dict(Counter(labels.values())) for key, labels in gold.items()},
                          "manifest_sha256": sha256(MANIFEST.read_bytes()).hexdigest(), "run_exists": root.exists()}))
        return 0
    if root.exists():
        parser.error("run exists; use a new run id")

    def validate_document(document, response):
        if document["document_id"] != response["document_id"]:
            raise ValueError("document identity mismatch")
        base.project(json.loads(document["text"]), response["rows"])

    result = execute(root, lambda doc: run_document(doc, 240, PROMPT.encode(), json.dumps(SCHEMA).encode(),
                         allow_chronicle_startup_warning=True, semantic_validator=validate_document))
    print(json.dumps({"status": result["status"], "reason": result["reason"], "cases": result["cases"],
                      "gate": result["gate"], "h10_corrected": result.get("h10_corrected"),
                      "regression": result.get("regression"), "fresh": result.get("fresh"),
                      "error_class": result.get("error_class"), "result": str(root / "result.json")}))
    return 0 if result["status"] == "MEASURED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
