# V1 Product Specification

## 1. 성공 기준

매일 실행했을 때 각 기회에 대해 다음 질문에 답할 수 있어야 한다.

1. 사람들이 실제로 반복해서 겪는 문제인가?
2. 해결하지 않으면 시간·돈·매출·리스크 중 무엇을 잃는가?
3. 이미 돈을 쓰거나 지불 의사를 표현했는가?
4. 현재 대안은 무엇이며 어떤 불만이 있는가?
5. 최근 수요가 증가하고 있는가?

모든 주장에는 원문 링크와 게시 시점이 연결되어야 한다. 근거가 없는 LLM 추론은 별도로 표시하고 점수 산정의 직접 근거로 사용하지 않는다.

## 2. V1 데이터 소스

초기에는 접근성과 재현성을 기준으로 3~5개를 선택한다.

- Reddit 공개 게시물/API
- GitHub Issues
- GitHub Discussions
- YouTube 댓글 또는 공개 RSS/검색 결과
- 공개 웹 페이지 중 수집이 허용된 소스

소스 어댑터는 공통 문서 형식으로 변환한다. 수집 실패가 전체 파이프라인을 중단시키지 않도록 소스별 오류를 기록하고 다음 소스로 진행한다.

## 3. 표준 문서 모델

```json
{
  "id": "stable-source-id",
  "source": "reddit",
  "source_url": "https://…",
  "author_hash": "optional-anonymized-value",
  "published_at": "2026-08-09T00:00:00Z",
  "language": "ko",
  "title": "original title",
  "text": "original text",
  "engagement": {"likes": 0, "comments": 0},
  "collected_at": "2026-08-09T01:00:00Z"
}
```

원문은 보존하되 개인정보는 저장하지 않거나 해시 처리한다. 삭제된 원문은 재배포하지 않는다.

## 4. 문제 추출 결과

LLM은 문서에서 최대 3개의 문제를 추출한다. 문제는 제품 아이디어가 아니라 사용자가 겪는 상황이어야 한다.

```json
{
  "problem_statement": "쿠팡 셀러가 상품별 실제 순이익을 계산하기 어렵다",
  "pain_type": ["time", "money"],
  "money_signal": "explicit|implicit|none",
  "willingness_to_pay": "explicit|proxy|none",
  "loss_evidence": "short evidence summary",
  "current_solution": ["spreadsheet", "manual work"],
  "solution_complaints": ["complex", "data mismatch"],
  "confidence": 0.0,
  "document_id": "stable-source-id"
}
```

## 5. Problem Cluster

임베딩 유사도와 LLM 정규화를 결합해 같은 근본 문제를 하나의 클러스터로 묶는다. 클러스터에는 반드시 대표 문제 문장, 관련 문서 수, 최근 30일 수, 이전 기간 수, 증거 문서 목록이 있어야 한다.

```json
{
  "cluster_id": "problem-cluster-id",
  "problem": "정규화된 문제 문장",
  "evidence_count": 127,
  "recent_count": 88,
  "previous_count": 54,
  "growth_rate": 0.63,
  "money_signal_count": 41,
  "willingness_to_pay_count": 19,
  "current_solutions": ["…"],
  "complaints": ["…"],
  "evidence_document_ids": ["…"]
}
```

## 6. 점수 규칙

각 항목은 0~100으로 정규화한다.

`Opportunity Score = 0.20 Frequency + 0.15 Growth + 0.20 Pain + 0.20 Money Signal + 0.10 Loss + 0.05 Competition + 0.10 Solution Gap`

경쟁 점수는 “경쟁사가 많을수록 높음”이 아니라, 검증된 지출이 있으면서 불만이 존재하는 정도를 반영한다. 표본이 너무 적은 클러스터는 점수와 별개로 `low_evidence` 플래그를 갖는다.

## 7. 결과 카드

TOP 10의 각 카드에는 다음을 표시한다.

- 기회명과 Opportunity Score
- 대표 문제
- 관련 게시물 수와 최근 증가율
- 돈을 쓰는 흔적 / 지불 의사
- 손실 유형
- 현재 대안과 반복 불만
- 대표 원문 링크 3개 이상
- 다음 검증 질문 1~3개

결과는 우선 JSON과 Markdown으로 생성한다. 텔레그램·웹 UI는 결과 품질이 확인된 뒤 붙인다.

## 8. 실행 백로그

- [ ] 소스 어댑터 인터페이스와 저장 포맷 정의
- [ ] 첫 3개 공개 소스 수집기 구현
- [ ] 중복 제거·언어 감지·개인정보 최소화
- [ ] 문제 추출 프롬프트와 구조화 출력 검증
- [ ] 임베딩 기반 클러스터링 및 병합 규칙
- [ ] 신호 탐지기와 점수 계산기
- [ ] 근거 링크가 포함된 TOP 10 리포트 생성
- [ ] 샘플 데이터셋으로 골든 테스트 구축
- [ ] 매일 실행 스케줄과 실패 재시도
- [ ] 사람이 점수와 클러스터를 수정할 수 있는 피드백 루프

## 9. V1에서 하지 않는 것

- 처음부터 모든 인터넷을 수집하지 않는다.
- 근거 없이 시장 규모나 매출을 추정하지 않는다.
- 자동으로 제품을 출시하거나 광고를 집행하지 않는다.
- 로그인 우회, 비공개 데이터 수집, 약관 위반 크롤링을 하지 않는다.
- 화려한 대시보드와 해외↔한국 갭 분석은 핵심 파이프라인 검증 이후로 미룬다.
