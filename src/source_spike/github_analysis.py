from __future__ import annotations

import json
from pathlib import Path

from src.source_spike.adapters.base import CollectionResult, CollectionStatus, TerminationReason
from src.source_spike.adapters.github import GitHubIssueAdapter
from src.source_spike.adapters.github_http import HttpGitHubTransport
from src.source_spike.analysis_bundle import write_run_bundle
from src.source_spike.collection import collect_source
from src.source_spike.github_analysis_manifest import validate_github_analysis_manifest
from src.source_spike.labeling import create_stratified_labeling_assignments
from src.source_spike.local_secret import load_secret


ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "config/source-spike/github-analysis.json"
COMPLIANCE_PATH = ROOT / "config/source-spike/compliance/github.json"
ARTIFACT_ROOT = ROOT / "artifacts/source-spike/github-analysis"


def exit_code_for_result(result: object) -> int:
    if getattr(result, "termination_reason") is TerminationReason.PREREQUISITE_FAILED:
        return 3
    return 0 if getattr(result, "status") is CollectionStatus.SUCCESS else 2


def publish_analysis_result(
    result: CollectionResult,
    *,
    manifest: dict[str, object],
    artifact_root: Path = ARTIFACT_ROOT,
    secrets: tuple[str, ...] = (),
) -> Path:
    qualified = (
        result.status is CollectionStatus.SUCCESS
        and result.accepted_item_count == 100
        and all(segment.accepted_item_count == 25 for segment in result.segment_results)
    )
    assignments = (
        create_stratified_labeling_assignments(
            result.items, seed=int(manifest["random_seed"])
        )
        if qualified
        else []
    )
    return write_run_bundle(
        artifact_root,
        run_id=result.run_id,
        items=result.items,
        collection_result=result.to_dict(),
        assignments=assignments,
        qualified=qualified,
        secrets=secrets,
    )


def main() -> int:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    compliance = json.loads(COMPLIANCE_PATH.read_text(encoding="utf-8"))
    try:
        local_secret = load_secret()
    except (FileNotFoundError, ValueError) as error:
        print(f"GitHub analysis prerequisite failure: {error}")
        return 3
    import os

    token = os.environ.get("GITHUB_TOKEN")
    adapter = GitHubIssueAdapter(
        HttpGitHubTransport(token=token),
        author_secret=local_secret.secret,
        compliance_record=compliance,
        manifest_validator=validate_github_analysis_manifest,
    )
    result = collect_source(
        adapter,
        manifest,
        int(manifest["target_valid_records"]),
        manifest_version=str(manifest["manifest_version"]),
    )
    destination = publish_analysis_result(
        result,
        manifest=manifest,
        secrets=tuple(value for value in (token, local_secret.secret.hex()) if value),
    )
    segments = " ".join(
        f"{segment.segment_id}={segment.accepted_item_count}/{segment.quota}"
        for segment in result.segment_results
    )
    print(
        f"GitHub analysis accepted={result.accepted_item_count}/100 "
        f"status={result.status.value} termination={result.termination_reason.value} "
        f"{segments} bundle={destination}"
    )
    return exit_code_for_result(result)


if __name__ == "__main__":
    raise SystemExit(main())
