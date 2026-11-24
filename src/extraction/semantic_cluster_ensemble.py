"""Combine measured cluster proposals without transitive merging or promotion."""
from itertools import combinations
from hashlib import sha256
import json

from src.extraction import codex_cli_diagnostic as cli
from src.extraction import semantic_cluster_development as single
from src.extraction import semantic_cluster_multitask as multi
from src.extraction import semantic_problem_development as dev

OUT = dev.RUN_ROOT / "semantic-cluster-ensemble-v1"


def combine(first, second, pairs):
    proposals = []
    merged_pairs = set()
    for version, groups in (("v1", first), ("v2", second)):
        for group in groups:
            if len(group["members"]) < 2:
                continue
            members = sorted(set(group["members"]))
            if len(members) != len(group["members"]):
                raise ValueError("duplicate source membership")
            proposals.append({**group, "members": members, "version": version,
                              "status": "NEEDS_REVIEW"})
            merged_pairs.update(combinations(members, 2))
    return {"proposals": proposals, "unique_merged_pairs": len(merged_pairs),
            "semantic": single.evaluate(pairs, first + second)}


def prepare():
    records, pairs, first, bindings = multi.prepare()
    raw = (multi.RUN / "result.json").read_bytes()
    second = json.loads(raw)
    tasks_raw = (multi.RUN / "tasks.json").read_bytes()
    tasks = json.loads(tasks_raw)["tasks"]
    if second["status"] != "MEASURED" or second["bindings"] != bindings:
        raise ValueError("second experiment incomplete or changed")
    by_source = {record["id"]: record for record in records}
    if {task["source_id"] for task in tasks} != set(by_source):
        raise ValueError("task source coverage mismatch")
    for task in tasks:
        value = by_source[task["source_id"]].get(task["field"])
        if not isinstance(value, str) or not task["evidence"].strip() or task["evidence"] not in value:
            raise ValueError("task evidence no longer supported")
    groups = multi.project_groups(tasks, [
        {"name": group["name"], "members": group["task_members"]} for group in second["groups"]
    ])
    if groups != second["groups"] or single.evaluate(pairs, groups) != second["semantic"]:
        raise ValueError("second experiment projection or metrics changed")
    return {"status": "MEASURED_DEVELOPMENT_ONLY", "documents": len(records),
            "label_type": "AI_ASSISTED_PURPOSIVE_CLUSTER_DIAGNOSTIC",
            "bindings": {**bindings, "multitask_result_sha256": sha256(raw).hexdigest(),
                         "multitask_tasks_sha256": sha256(tasks_raw).hexdigest()},
            **combine(first["groups"], groups, pairs), "official_opportunities": 0}


def main():
    result = prepare()
    OUT.mkdir(mode=0o700, exist_ok=True)
    path = OUT / "result.json"
    if path.exists():
        if json.loads(path.read_text()) != result:
            raise ValueError("existing ensemble result differs")
    else:
        cli._private_create(path, result)
    print(json.dumps({"status": result["status"], "documents": result["documents"],
                      "proposals": len(result["proposals"]),
                      "unique_merged_pairs": result["unique_merged_pairs"],
                      "semantic": {k: v for k, v in result["semantic"].items() if k != "pairs"},
                      "official_opportunities": 0, "result": str(path)}))


if __name__ == "__main__":
    main()
