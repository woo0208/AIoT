# H9-v2 / M3-G P01·P02 탐색적 LOSO — 실행 전 고정 사항

작성: 2026-10-27, 모델 실행 **전**. 이 파일은 결과를 본 뒤 수정하지 않는다.

## 범위·권위
- 데이터 역할: P01/P02 = pilot/development (DATA-002, Master §9.1). H9-v2·M3-G 설계에 이미 사용된 자료이므로 독립 확증·일반화 성능으로 보고하지 않는다 (H9_v2_feature_design §185, M3 design §8.1.1).
- 클래스: `primary5` (P0~P4). P5(lean_forward/body_forward)는 학습·지표에서 제외 (POST-001).
- `auxiliary6`: 실행하지 않음. Decision Log(이 worktree 및 feat/rf-loso-prediction-audit 등 로컬 사본)에 6-class 보조 실험 승인 기록이 없음. 승인 참조를 생성하지 않는다.
- 코드: 작업 트리의 `h9_v2_loso.py` 무수정 사용 (SHA-256 ca0eba97…). 500 trees, max_features=2, seeds 0~4, M2 λ=0.5, FEAT-010 p=9 rank weights.
- 입력 (이전 H9 파일럿 분석과 동일 선택, SHA-256 기록값 일치 확인):
  - captures/P01_h9_20261024_170900.csv (1d8f0c7e…)
  - captures/P02_h9_20261024_173954.csv (6bbad505…)

## 보고 지표
1. pooled OOF Accuracy / Macro-F1: seed 평균 ± seed SD(ddof=0)
2. 참가자별 Accuracy / Macro-F1 (seed 평균), 참가자 동등 평균 Macro-F1
3. P1 Recall / Precision (pooled, seed별 → 평균)
4. P1→P0, P0→P1 오류 수 (seed별 정수, 5 seed 평균, 참가자별)
5. 전체 정수 confusion matrix (seed별) — JSON에 보존

## 비교와 서술 기준 (사전 고정, 통계 검정 아님)
- 주 비교: M3-G − M0. 보조: M3-G − M2, M2 − M0. M1은 재현 축(M0와 동일성 점검).
- 표본 1개 = pooled 1/N, 참가자 내 1/(N/2). 아래 서술 라벨을 사용한다.
  - "개선 방향(탐색적)": pooled Macro-F1 차이 ≥ +0.05 AND 두 참가자 모두 참가자별 Macro-F1 차이 ≥ 0
  - "악화 방향(탐색적)": pooled Macro-F1 차이 ≤ −0.05 AND 두 참가자 모두 ≤ 0
  - 그 외: "차이 불확실"
  - P1 Recall 차이도 같은 방식으로 병기한다.
- n=2 참가자: 유의성·CI·일반화 주장 없음. seed 반복은 독립 표본이 아님.
- 기존 H9 결과(h6_pilot_20261024_174708.json)는 6-class이므로 5-class 결과와 직접 비교하지 않는다. 문맥 참고로만 인용하며 "H9→H9-v2 표현 개선"은 이 실행으로 식별 불가로 보고한다.
- 결과를 보고 특징·파라미터·입력 파일·클래스 집합을 바꾸지 않는다. 재실행으로 seed/결과를 고르지 않는다.
