# Research-Auto 기능별 구조

## 경계

| 역할 | 구현 위치 | 책임 |
| --- | --- | --- |
| 엔진 입력/계약 | `src/source_spike/`, `src/contracts/` | 공개 자료 수집과 근거 계약 검증 |
| 엔진 분석 및 동결된 진단 | `src/extraction/` | 문제 추출, 경제 신호, 군집, 반증, 실험 replay |
| 엔진 실행/조회 | `src/research_console.py`, `src/evidence_pilot_cli.py` | 로컬 저장 자료 조회·검토 |
| Excel/CSV 검수 | `src/services/spreadsheet.py` | 파일 정리·충돌·중복·검수 결과 |
| 정기 보고서 | `src/services/periodic_report.py` | spreadsheet 검수 재사용 및 기간별 실적 |
| 송장 대조 | `src/services/invoice_reconciliation.py` | 송장과 입금 대조의 좁은 로컬 파일럿 |
| 스캔 PDF 주문 | `src/services/scanned_pdf/order.py` | 실제 주문 범위 선택·로컬 OCR·사람 검수·XLSX |
| 스캔 PDF 연구 | `src/scanned_pdf_experiment/` | 동결된 OCR·숫자 판단·평가; 주문 호환 경로 포함 |
| 신규 독립 실험 | `experiments/excel_pdf/` | 고정된 가상 Excel 변환 실험. 판매용 처리기 아님 |
| 기존 데모·실험 | `src/paid_pilot_demo.py`, `scripts/`, `artifacts/evidence-pilot/` 내 기존 연구 스크립트 | 역사적 실행 경로 보존; 앞으로 생성물 폴더에 실행 코드를 추가하지 않음 |
| 결과 및 근거 | `artifacts/`, `outputs/`, `generated_images/` | 실험 기록·샘플 결과·이미지. 엔진 소스와 함께 일괄 커밋하지 않음 |
| 테스트·설정 | `tests/`, `config/source-spike/`, `configs/extraction/`, `schemas/` | 계약/회귀 테스트와 수집·분석 설정 |

기존 `src/extraction/`, `src/source_spike/` 및 `src/contracts/`은 이미 해시/경로가 결합된 검증 결과를 보존하기 위해 그대로 둔다. 현재 엔진과 엔진 연구는 동일 패키지에서 별도 버전으로 실행되는 부분이 남아 있다. 향후 전면 `src/engine/` 이동은 독립적으로 마이그레이션과 기록 호환성을 검증해야 한다. `config/`는 기존 source-spike 설정, `configs/`는 추출 평가와 군집 설정의 역사적 경로이므로 이 정리에서는 통합하지 않는다.

분리 규칙: 엔진은 납품 서비스를 import하지 않고 납품 서비스는 엔진을 import하지 않는다. 정기 보고서가 `spreadsheet`를 재사용하는 것과 스캔 주문이 기존 숫자 파서·OCR 자원을 재사용하는 것은 허용된 의존이다. `tests/test_service_boundaries.py`가 정적 import 경계와 생성 파일 혼입을 검사한다.

## 실행 방법

저장소 루트에서 사용할 명령이다. 기존 Python 모듈 경로도 같은 구현 객체를 참조하므로 이전 실행 명령과 테스트를 보존한다.

| 기능 | 새 진입점 | 기존 진입점 |
| --- | --- | --- |
| 수요 탐색 UI | `python3 -m src.research_console --serve` | 동일 |
| Excel 정리 | `python3 -m src.services.spreadsheet --help` | `python3 -m src.spreadsheet_pilot --help` |
| 기간별 보고서 | `python3 -m src.services.periodic_report --help` | `python3 -m src.periodic_report --help` |
| 송장 대조 | `from src.services.invoice_reconciliation import reconcile` | `from src.invoice_reconciliation_pilot import reconcile` |
| 스캔 PDF | `python3 -m src.services.scanned_pdf.order --help` | `python3 -m src.scanned_pdf_experiment.order --help` |
| Excel→PDF 가상 실험 | [실험 실행 안내](../experiments/excel_pdf/README.md) | 이전 파일 위치는 실험 기록 참고 |

스캔 주문 작업은 [운영 가이드](scanned-pdf-order-runbook.md), 정기 보고서는 [운영 가이드](periodic-report-runbook.md) 참고. 납품은 여전히 좁은 파일 유형·범위와 사람의 검수 조건을 전제로 한다. 현재 실험 성공은 사업성 또는 공식 사업 기회 승격을 뜻하지 않는다.

## 로컬 검증과 자료 보존

2026-11-24 확인 환경에서 프레임워크 Python 3.11에는 pytest/jsonschema가 있고 openpyxl이 없었으며, 번들 Python에는 pytest/openpyxl이 있으나 jsonschema가 없었다. 따라서 전체 엔진 테스트와 XLSX 테스트를 각각 실행한다. 기존 환경을 바꾸거나 추가 설치할 필요는 없다.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -rs -p no:cacheprovider
runtime="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies"
PYTHONDONTWRITEBYTECODE=1 "$runtime/python/bin/python3" -m pytest -q -p no:cacheprovider \
  tests/test_service_boundaries.py tests/test_spreadsheet_pilot.py tests/test_periodic_report.py
```

일부 historical replay는 `artifacts/extraction/calibration/audit-local/` 및 `artifacts/evidence-pilot/`의 로컬 관측, 해시 결합 manifest를 필요로 한다. Git에서 코드만 조회해도 이전 측정 자료 전체를 얻을 수 있는 것은 아니다. 고객 데이터·원본 문서·미검토 공개 발췌·대용량 이미지·실행 산출물은 로컬에 남긴다. 기존 자료는 이번 정리에서 삭제하지 않았다.

정리 설계: [설계](superpowers/specs/2026-11-24-feature-boundaries-design.md), [실행 계획](superpowers/plans/2026-11-24-feature-boundaries.md), [기능별 커밋 대상](feature-commit-plan-20261124.md).
