# Reddit Source Feasibility Decision

> Evaluated: 2026-08-17
> CURRENT COLLECTION: NOT_ELIGIBLE
> FUTURE COMMERCIAL REUSE: NOT_ELIGIBLE

## Decision

이 문서는 법률 의견이 아니라 보수적 engineering gate다. 현재 저장소에는 Reddit for
Researchers 또는 다른 적용 가능한 접근 승인, 상업적 재사용 승인, 자동 처리 범위를
확인하는 증거가 없다. 따라서 Reddit API, fixture, adapter, smoke를 시작하지 않는다.

모델 학습과 fine-tuning은 사용하지 않는다. Embedding/indexing, LLM inference extraction,
파생 output 저장은 계획되어 있으나 해당 범위의 허용 여부를 학습 제한에서 추론하지 않고
unresolved로 유지한다.

Machine evidence의 `captured_excerpt`는 검토 당시 저장한 정책 문구 또는 간결한 요약이며,
그 hash는 저장 문자열의 무결성만 확인하고 현재 원문과의 동일성을 보증하지 않는다.

## Routing

- Compliance: `seek_compliance_clearance`
- Source Spike: `select_replacement_source`

승인 확인은 Reddit의 재진입 조건이지만 Source Spike의 critical path는 아니다.

## Re-entry conditions

1. 적용 가능한 접근 승인과 허용 목적을 기록한다.
2. 상업적 재사용과 자동 처리 범위를 공식 근거로 확인한다.
3. Reddit 데이터와 파생 output의 삭제 전파를 구현하고 검증한다.

Machine-readable authority:
`config/source-spike/feasibility/reddit.json`
