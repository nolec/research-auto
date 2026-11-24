"""Compare narrow task clustering with the original document-level partition."""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json

from jsonschema import Draft202012Validator, ValidationError

from src.extraction import codex_cli_diagnostic as cli
from src.extraction import semantic_cluster_development as single
from src.extraction import semantic_problem_development as dev

RUN = dev.RUN_ROOT / "semantic-cluster-multitask-v2"
EXTRACTION_ID = "semantic-cluster-multitask-v2-extraction"
CLUSTER_ID = "semantic-cluster-multitask-v2-grouping"
FIELDS = ("summary", "task", "obstacle", "quote")
SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["document_id", "records"],
    "properties": {
        "document_id": {"type": "string"},
        "records": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["source_id", "tasks"],
            "properties": {
                "source_id": {"type": "string"},
                "tasks": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False,
                    "required": ["description", "field", "evidence"],
                    "properties": {"description": {"type": "string"},
                                   "field": {"type": "string", "enum": list(FIELDS)},
                                   "evidence": {"type": "string"}}}},
            },
        }},
    },
}
EXTRACTION_PROMPT = """For each supplied observation, identify its independently
requested deliverables or experienced problems. A bundled request may contain
several separately requested tasks. Retain each source ID exactly once with at
least one task. Keep a single task when the described operations are steps in the
same deliverable or when the evidence is too broad to justify splitting.
Each description must capture the specific task and relevant obstacle or scope.
For each task, copy a short exact substring (at most 25 words) from one permitted
field of that source record and identify the field. Do not invent tasks or
broaden the scope beyond the supplied text. Do not infer buyers, willingness to
pay, or additional incidents. Source kinds distinguish archived summaries from
validated model extractions. Return only the schema with the unchanged document_id."""
CLUSTER_PROMPT = """Partition the supplied atomic tasks into narrow groups.
Every atomic ID must appear exactly once. Merge tasks only when every member
supports the same specific task and obstacle or explicit requested deliverable.
Preserve qualifications and distinguish different operations, even within the
same industry. Shared terms, broad goals and adjacent requirements are insufficient.
Keep uncertain tasks separate. Different tasks from the same source may belong
to different groups; never place two tasks from the same source in one group.
Use names describing the shared task, without implying new evidence, payment or
independence of buyers. Return only the schema with the unchanged document_id."""


def decompose(records, rows):
    by_id = {r["id"]: r for r in records}
    seen = set()
    atoms = []
    for row in rows:
        key = row["source_id"]
        if key not in by_id or key in seen or not row["tasks"]:
            raise ValueError("unknown, duplicate or empty source decomposition")
        seen.add(key)
        record = by_id[key]
        descriptions = set()
        for task in row["tasks"]:
            description = task["description"].strip()
            normalized = " ".join(description.casefold().split())
            evidence = task["evidence"]
            field = task["field"]
            if (not normalized or normalized in descriptions or field not in FIELDS
                    or not isinstance(record.get(field), str) or not evidence.strip()
                    or evidence not in record[field] or len(evidence.split()) > 25):
                raise ValueError("invalid or unsupported task evidence")
            descriptions.add(normalized)
            atoms.append({"id": f"task-{len(atoms)+1:03d}", "source_id": key,
                          "source": record["source"], "kind": record["kind"],
                          "description": description, "field": field, "evidence": evidence})
    if seen != set(by_id):
        raise ValueError("decomposition omitted a source")
    return atoms


def project_groups(atoms, groups):
    by_id = {a["id"]: a["source_id"] for a in atoms}
    single.validate_partition(by_id, groups)
    projected = []
    for group in groups:
        members = [by_id[key] for key in group["members"]]
        if len(members) != len(set(members)):
            raise ValueError("multiple tasks from one source in the same group")
        projected.append({"name": group["name"], "members": members,
                          "task_members": group["members"]})
    return projected


def prepare():
    records, pairs, bindings = single.prepare()
    raw = (single.RUN / "result.json").read_bytes()
    previous = json.loads(raw)
    if previous["status"] != "MEASURED" or previous["bindings"] != bindings:
        raise ValueError("original experiment missing or changed")
    single.validate_partition({r["id"] for r in records}, previous["groups"])
    if single.evaluate(pairs, previous["groups"]) != previous["semantic"]:
        raise ValueError("original experiment metric mismatch")
    return records, pairs, previous, {
        "original_run_sha256": sha256(raw).hexdigest(),
        "input_sha256": bindings["input_sha256"],
        "pairs_sha256": bindings["pairs_sha256"],
        "extraction_prompt_sha256": sha256(EXTRACTION_PROMPT.encode()).hexdigest(),
        "grouping_prompt_sha256": sha256(CLUSTER_PROMPT.encode()).hexdigest(),
        "extraction_schema_sha256": sha256(json.dumps(SCHEMA, sort_keys=True).encode()).hexdigest(),
        "grouping_schema_sha256": bindings["schema_sha256"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    records, pairs, previous, bindings = prepare()
    receipt = {"documents": len(records), "reference_pairs": len(pairs),
               "label_type": "AI_ASSISTED_PURPOSIVE_CLUSTER_DIAGNOSTIC",
               "model": dev.MODEL, "bindings": bindings, "previous": previous["semantic"]}
    if args.check:
        print(json.dumps({"status": "INPUTS_VALIDATED", **receipt, "run_exists": RUN.exists()}))
        return 0
    RUN.mkdir(mode=0o700, exist_ok=False)
    cli._private_create(RUN / "claim.json", receipt)
    stage = "decomposition"

    def call(document_id, items, prompt, schema, validate):
        doc = {"document_id": document_id, "source": "mixed", "title": "Problem observations",
               "published_at": "unknown", "text": json.dumps(items, ensure_ascii=False)}

        def check(document, output):
            Draft202012Validator(schema).validate(output)
            if document["document_id"] != output["document_id"]:
                raise ValueError("identity mismatch")
            validate(output)

        output, _ = dev.run_document(doc, 240, prompt.encode(), json.dumps(schema).encode(),
                                     allow_chronicle_startup_warning=True, semantic_validator=check)
        check(doc, output)
        return output

    try:
        output = call(EXTRACTION_ID, records, EXTRACTION_PROMPT, SCHEMA,
                      lambda response: decompose(records, response["records"]))
        atoms = decompose(records, output["records"])
        cli._private_create(RUN / "tasks.json", {"tasks": atoms})
        print(f"1/2 decomposed {len(records)} sources into {len(atoms)} tasks", flush=True)
        stage = "grouping"
        output = call(CLUSTER_ID, atoms, CLUSTER_PROMPT, single.SCHEMA,
                      lambda response: project_groups(atoms, response["groups"]))
        groups = project_groups(atoms, output["groups"])
        report = {"status": "MEASURED", **receipt, "tasks": len(atoms),
                  "multi_task_sources": sum(n > 1 for n in Counter(a["source_id"] for a in atoms).values()),
                  "groups": groups, "merged_groups": sum(len(g["members"]) > 1 for g in groups),
                  "semantic": single.evaluate(pairs, groups), "official_opportunities": 0}
        print("2/2 grouped", flush=True)
    except (cli.CliContractError, ValueError, ValidationError, OSError) as error:
        report = {"status": "INCOMPLETE", **receipt, "stage": stage, "reason": str(error)}
    cli._private_create(RUN / "result.json", report)
    print(json.dumps({k: v for k, v in report.items() if k not in ("groups", "bindings")}, ensure_ascii=False))
    return 0 if report["status"] == "MEASURED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
