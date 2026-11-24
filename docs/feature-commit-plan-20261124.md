# 기능별 로컬 커밋 대상 — 2026-11-24

현재 세션은 `.git` 쓰기 제한이 있어 커밋하지 않았다. 아래는 사용자 로컬 터미널에서 실행할 명시 경로별 커밋 계획이다. **push하지 않는다.** 실행 전에 `git status --short`, `git rev-parse --short HEAD`와 `git diff --cached --name-only`를 확인한다. 검토한 기준 HEAD는 `0ea997e`이며, 인덱스가 비어 있어야 한다. 다른 변경이 있거나 HEAD가 변경되었다면 아래 명령을 그대로 적용하지 말고 다시 확인한다. 각 그룹에서 스테이징 내역이 해당 경로 및 의도한 삭제/이동에 정확히 일치하는 경우에만 커밋한다.

## A. 이번 구조 정리: 3개 커밋

첫 그룹은 서비스 경계 테스트가 Spreadsheet, Report 및 Scan을 함께 검사하므로 하나의 경계 커밋으로 묶는다. 다음 그룹은 독립적인 가상 진단이며, 마지막은 문서 및 전체 구조 안내다.

```sh
git add -A -- src/services/__init__.py src/services/spreadsheet.py src/services/periodic_report.py src/services/invoice_reconciliation.py src/services/scanned_pdf/__init__.py src/services/scanned_pdf/order.py src/services/scanned_pdf/scanned_pdf_order_map.html src/services/scanned_pdf/scanned_pdf_order_review.html src/spreadsheet_pilot.py src/periodic_report.py src/invoice_reconciliation_pilot.py src/scanned_pdf_experiment/order.py src/scanned_pdf_experiment/scanned_pdf_order_map.html src/scanned_pdf_experiment/scanned_pdf_order_review.html tests/test_service_boundaries.py docs/scanned-pdf-order-runbook.md docs/periodic-report-runbook.md
git diff --cached --name-status
git commit -m "refactor: isolate local delivery services with compatible entry points"
```

옛 스캔 HTML 두 개는 새 위치로 이동했으므로 Git에 삭제 또는 rename으로 표시된다. 파일 내용은 그대로다.

```sh
git add -- experiments/excel_pdf/excel_pdf_fixtures.mjs experiments/excel_pdf/excel_pdf_pilot.py experiments/excel_pdf/README.md tests/test_excel_pdf_experiment.py docs/excel-pdf-pilot-20261124.md docs/excel-pdf-demand-followup-20261124.md
git diff --cached --name-status
git commit -m "refactor: separate synthetic Excel PDF diagnostic from outputs"
```

```sh
git add -- README.md docs/project-structure.md docs/feature-commit-plan-20261124.md docs/superpowers/specs/2026-11-24-feature-boundaries-design.md docs/superpowers/plans/2026-11-24-feature-boundaries.md
git diff --cached --name-status
git commit -m "docs: record feature boundaries and local verification workflow"
```

## B. 기존 미커밋 연구 코드: 추가 4개 후보 커밋

아래는 기존에 개발되어 있던 12개 Python 소스와 해당 테스트 13개를 기능별로 구분한 것이다. 이번 리팩터링에서 소스 바이트는 변경하지 않았다. `configs/`의 ID·해시 전용 목록과 순수 합성 manifest만 기본 그룹에 포함했다. 나머지 로컬 자료에 의존하는 진단은 이 코드 커밋만으로 새로운 clone에서 모든 검증을 재현할 수 없다. 독립 실행 가능 제품으로 표시하지 않는다. **로컬 보관 목적의 코드 이력 커밋 후보**이며 외부 push 전에는 자료 공개/재현 정책을 별도로 확정해야 한다.

```sh
git add -- src/extraction/semantic_problem_development.py src/extraction/semantic_problem_holdout.py tests/extraction/test_semantic_problem_development.py tests/extraction/test_semantic_problem_holdout.py configs/extraction/semantic-problem-holdout-v1.csv
git diff --cached --name-status
git commit -m "feat: preserve semantic problem extraction diagnostics"
```

```sh
git add -- src/extraction/cluster_diagnostic.py src/extraction/semantic_cluster_development.py src/extraction/semantic_cluster_multitask.py src/extraction/semantic_cluster_ensemble.py tests/extraction/test_cluster_diagnostic.py tests/extraction/test_semantic_cluster_development.py tests/extraction/test_semantic_cluster_multitask.py tests/extraction/test_semantic_cluster_ensemble.py configs/cluster-development-pairs-v1.csv
git diff --cached --name-status
git commit -m "feat: preserve semantic clustering diagnostics"
```

```sh
git add -- src/extraction/solution_gap_diagnostic.py src/extraction/solution_gap_holdout.py src/extraction/solution_gap_holdout_v2.py tests/extraction/test_solution_gap_diagnostic.py tests/extraction/test_solution_gap_holdout.py tests/extraction/test_solution_gap_holdout_v2.py configs/extraction/solution-gap-diagnostic-v1.json
git diff --cached --name-status
git commit -m "feat: preserve solution gap diagnostic implementations"
```

```sh
git add -- src/extraction/integrated_discovery_pilot.py src/source_spike/fresh_discovery_diagnostic.py src/source_spike/fresh_integrated_discovery.py tests/extraction/test_integrated_discovery_pilot.py tests/extraction/test_integrated_discovery_pilot_v2.py tests/source_spike/test_fresh_discovery_diagnostic.py tests/source_spike/test_fresh_integrated_discovery.py
git diff --cached --name-status
git commit -m "feat: preserve integrated discovery replay and fresh intake"
```

## C. 별도로 보류할 기존 자료

기존 미커밋 설정 중 다음은 평가 라벨/설명/공개 출처 발췌를 포함하므로 공개 및 재현 정책 검토까지 원본 경로에 보존한다.

- `configs/extraction/semantic-problem-development-v1.csv`
- `configs/extraction/semantic-cluster-development-v1.csv`
- `configs/extraction/semantic-problem-holdout-v1-ai-reference.json`
- `configs/extraction/semantic-problem-holdout-v1-ko.json`
- `configs/extraction/semantic-problem-holdout-v1-ko-corrections.json`
- `configs/extraction/solution-gap-holdout-v1.json`
- `configs/extraction/solution-gap-holdout-v2.json`

이전 발견/분류/반증/구매 근거 보고서(다음 경로)는 별도 문서 커밋 후보이며 실제 원문 발췌·개인정보·재현성 조건을 확인하기 전에는 위 실행 대상에 포함하지 않는다.

- `docs/broad-buyer-expansion-20261123.md`, `docs/buyer-first-discovery-20261124.md`, `docs/buyer-first-discovery-protocol-20261124.md`
- `docs/cluster-problem-review-20261123.md`, `docs/semantic-cluster-business-review-20261123.md`, `docs/semantic-problem-holdout-review-template.html`
- `docs/engine-end-to-end-gap-audit-20261123.md`, `docs/fresh-cross-source-followup-20261124.md`, `docs/fresh-cross-source-followup-protocol-20261124.md`, `docs/fresh-integrated-discovery-protocol-20261124.md`
- `docs/solution-gap-crosscheck-20261123.md`, `docs/solution-gap-diagnostic-20261124.md`, `docs/solution-gap-holdout-20261124.md`, `docs/solution-gap-holdout-protocol-20261124.md`, `docs/solution-gap-holdout-v2-20261124.md`, `docs/solution-gap-holdout-v2-protocol-20261124.md`

`artifacts/`, `outputs/`, `generated_images/`, 고객 파일, 자격 증명, 캐시와 미검토 원문/관측은 전체 add 대상이 아니다. 특히 적용 사례의 입력·측정 결과를 지우거나 수정하지 않는다. 기존 약 507MB 스캔 실험 자료의 보존/정리 결정은 별도 작업이다. 모든 커밋 후 `git log -7 --oneline`, `git status --short`로 결과를 확인한다. 남은 로컬 자료는 실패나 삭제 대상이 아니라 의도적으로 보류한 것이다.
