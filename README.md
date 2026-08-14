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

Task 1 Opportunity Card 계약은 완료됐다. 현재 Task 2 Source Spike를 진행 중이며, 분석용 실제 유효 레코드 진행률은 **300/500**이다. GitHub, Stack Exchange, Steam이 각각 실제 analysis dataset **100/100**을 확보했다. GitHub primary human review는 **20/20**, secondary는 **0/5**이며, Stack Exchange primary도 **20/20** 완료됐지만 독립 secondary는 **0/5**다. Stack Exchange와 Steam 결과는 각각 네 site와 네 product archetype을 동일 가중치로 구성한 실험 표본이며 official eligibility는 deferred다. Steam은 공식 public-review endpoint만 사용하는 conditional/high-risk compliance, 실제 smoke **10/10**, capacity `38/38/38/38`, privacy-qualified analysis **100/100**을 통과했고, hash-frozen primary 20/secondary 5 blind packet과 분리된 오프라인 검토 화면까지 준비됐다. Steam primary human review는 **20/20** 확정됐고 독립 secondary는 **0/5**다. Smoke records는 analysis 진행률에 포함하지 않는다.
