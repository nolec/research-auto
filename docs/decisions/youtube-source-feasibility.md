# YouTube Source Feasibility Decision

> Evaluated: 2026-08-17
> VERDICT: NOT_ELIGIBLE

## Decision

YouTube adapter를 구현하지 않는다. 현재 공식 정책과 제품 계약을 함께 만족하는
보존·작성자 독립성·재현성 경로가 없으므로 네 번째 Source Spike 후보를 교체한다.

## Blocking conditions

- `B1_30_DAY_RETENTION_CONFLICTS_WITH_90_DAY_EVIDENCE`: 비인증 API Data의 30일
  보존 한도가 제품의 최근 90일 Evidence 계약보다 짧다.
- `B2_STABLE_AUTHOR_DERIVATION_NOT_EXPLICITLY_ALLOWED`: 독립 작성자를 재실행 간
  구분하기 위한 지속적 파생 식별값이 명시적으로 허용된다는 근거가 없다.
- `B3_REFRESH_CHANGES_OR_REMOVES_FROZEN_EVIDENCE`: refresh 또는 삭제가 frozen
  dataset 및 review packet에 결합된 원문 bytes를 변경하거나 제거한다.
- `B4_NO_EXECUTABLE_DELETION_AND_REFRESH_PATH`: 모든 저장값을 기한 내 갱신하거나
  삭제했다는 사실을 보장하는 실행 경로가 현재 없다.

## Gate result

| Gate | Status |
|---|---|
| Retention | fail |
| Provenance | fail |
| Author independence | unresolved |
| Deletion | unresolved |
| Reproducibility | fail |

## Re-entry condition

YouTube는 공식 compliance clearance를 확보하거나, 90일 Evidence와 stable author
independence를 정책에 맞게 유지하는 검증 가능한 lifecycle이 마련된 경우에만 다시
평가한다. 그 전에는 API key 생성, fixture 수집, adapter 구현, smoke 실행을 하지 않는다.

Machine-readable authority:
`config/source-spike/feasibility/youtube.json`
