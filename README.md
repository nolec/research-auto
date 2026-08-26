# Demand Intelligence Engine

사람들의 공개된 행동과 불만을 사업 기회로 변환하는 수요 탐지 엔진.

이 프로젝트의 첫 사용자는 외부 고객이 아니라 우리 자신이다. V1의 목표는 공개 데이터에서 반복되는 문제를 발견하고 Evidence·Actionability·Review Value를 분리해 평가한 뒤, 사람이 검토할 가치가 가장 높은 Opportunity Card TOP 20을 제공하는 것이다.

## 제품 원칙

- 아이디어를 지어내지 않고 관찰된 수요를 증거와 함께 보여준다.
- 산업을 먼저 고정하지 않는다. 데이터가 강한 문제와 시장을 발견하게 한다.
- 경쟁의 부재보다 지불 흔적과 기존 해결책에 대한 불만을 중요하게 본다.
- 공개 데이터와 공식 API를 우선하며 로그인 우회나 약관 위반 수집은 하지 않는다.
- V1은 대시보드보다 반복 실행 가능한 결과 생성에 집중한다.

## V1 흐름

`수집 → 정제 → 문제 추출 → 문제 클러스터링 → Evidence → Actionability → Review Value → TOP 20 → 사람 감사`

현재 권위 있는 제품 계약은 [`docs/prd.md`](docs/prd.md), 구현 진행 상황과 다음 작업은 [`docs/roadmap.md`](docs/roadmap.md)를 참고한다. 초기 아이디어를 정리한 [`docs/v1-spec.md`](docs/v1-spec.md)는 역사적 초안이다.

## 현재 상태

Task 1 Opportunity Card 계약은 완료됐다. Task 2 Source Spike는 GitHub, Stack Exchange, Steam, TED에서 각각 실제 analysis dataset **100/100**, 총 **400/500**을 확보한 상태로 동결했다. 네 source의 primary human review는 모두 **20/20** 완료됐고 독립 secondary는 각각 **0/5**라 official eligibility와 canonical source-quality report는 아직 deferred다. 기존 source-spike holdout은 이미 검토 과정에 노출됐으므로 extractor의 독립 평가셋이 아니라 `source_spike_reserved` 이력으로 취급한다.

Task 3는 deterministic calibration baseline, evaluator, provenance-bound metric bundle generator와 count-aware calibration gate까지 구현됐다. 네 source의 실제 artifact 경로는 versioned manifest로 고정됐으며, 원본은 Git에서 제외된 `local_ignored` custody로 유지한다. 기본 suite는 fixture만 사용하고 실제 40건 projection은 명시적인 opt-in integration으로 검증한다. 실제 `rule_v1` 40건 aggregate bundle은 implementation hash `555d9a2e…caa98`로 동결됐다. 결과는 valid 40, invalid 0, abstention 26, coverage 35%이며 Problem precision/recall은 100%/30.3%, Money는 75%/33.3%, usable evidence는 100%/42.4%다. Gate는 candidate run·evaluation report·human semantic audit를 hash로 결합하고, 네 source diagnostic의 정확한 membership과 evidence-positive 전체에 대한 blind audit를 fail-closed로 요구한다. Audit packet은 로컬 전용·0600·원자 생성이며 raw review row는 aggregate receipt에 저장하지 않는다. Gate 정책과 구현은 Checkpoint `f694a2c` 및 immutable freeze receipt에 결합됐고 Git blob 기준 독립 hash 검증과 최종 코드 리뷰를 통과했다. 전체 **551 tests**가 통과하며 local integration 1건은 기본 실행에서 의도적으로 skip된다. 아직 첫 inference profile, 모델 기반 추출, clustering, Opportunity Card, TOP 20은 구현되지 않았다.
