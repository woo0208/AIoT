# 연구 6단계: 실행 전 조건·비교·진단 기준

작성일: 2026-10-28. 새 모델 학습/예측 실행 전에 작성. 실행 뒤 이 기록은 수정하지 않는다.

## 권위·범위

- 현재 사용자 지시는 기존 P01/P02의 탐색적 재평가와 M3-G 실제 트리 진단을 승인한다. formal 평가·새 촬영·6-class 승인은 아니다.
- Research Master §4/9/12, Decision Log RES-001/002, POST-001, DATA-002, EXP-001/002, FEAT-010, CAP-007/009와 Schema §0/F/G/J를 따른다. OPEN-002/003/005 및 Patch 8 실행 보류는 해제하지 않는다.
- 시작부터 존재한 미커밋 구현과 기존 결과는 변경하지 않는다. 새 스크립트·기록·결과는 이 새 폴더에만 만들며 exclusive create로 덮어쓰기를 거부한다. commit/push 하지 않는다.

## 입력·특징·표본

- captures/P01_h9_20261024_170900.csv SHA-256 `1d8f0c7e40b87f750bb4a351f52ed55b083a1c37e777a2e9088f54111ded3122`
- captures/P02_h9_20261024_173954.csv SHA-256 `6bbad505e9333e4029fe1be155e73ce745c9709077b57fda65eb49e3fc8b9f2e`
- H9 = 기존 F1~F9. H9-v2 = 기존 F1~F8+C3 (`sagittal_torso_lean_deg`). 기존 h6_offline loader와 각 집계 함수를 그대로 사용한다. F3 방향성 원형평균, 그 밖 중앙값, 공동 유효 >=30 frame 및 coverage >=50%를 유지한다. 재추출·재정규화·imputation·calibration 하지 않는다.
- primary5 = P0 upright, P1 forward_head, P2 lean_back, P3 lean_left, P4 lean_right. P5 네 구간과 PREP/TRANSITION은 학습·지표 제외. auxiliary6 실행이나 승인 참조 생성 없음.
- 비교는 두 특징집합 모두 적격인 sample_key 교집합, 동일 순서로 한다. 두 표현의 native 공동 support를 변경하지 않는다. 교집합 밖 표본 및 특징별 finite frame 수/집계 support 차이를 별도 기록한다. support가 다르면 표현의 정보 변경과 support 효과를 분리할 수 없다고 명시한다.
- 학습 전 구조 확인에서 24구간 모두 양쪽 적격, 모든 구간의 H9/H9-v2 공동 support 동일. primary5는 20구간, 참가자당 자세별 2구간이다. 실제 수와 키는 다시 검증한다. CSV row 번호는 adapter frame identity이며 canonical camera frame 번호가 아니다.

## 모델·fold·기존 결과 검증

- 참가자 단위 LOSO: P01 test/P02 train 및 P02 test/P01 train. 각 10 train/10 test, 같은 구간·라벨·순서. seed 0,1,2,3,4; 각 forest 500 trees; max_features=2; M2 lambda=0.5 고정.
- H9/H9-v2 M0/M1/M2는 rf_experiment.fit_models를 무수정 사용한다. FEAT-010 p=9, M0 학습 fold MDI만으로 rank weight를 계산한다. M1 입력 가중과 M2 split 가중 정의, bootstrap/tree seed 분리는 유지한다.
- H9-v2 M3-G는 m3_g.M3GForest를 무수정 사용한다. 다른 M3 변형이나 새 모델을 실행하지 않는다.
- 기존 h9v2_loso_primary5_20261027.json의 입력·코드 해시, 표본/행렬/라벨/fold/MDI/weights와 새 재현 예측을 확인한다. 재현 불일치가 있으면 동일 실험의 실제 트리로 간주하지 않고 중단한다. 기존 H9 6-class 결과는 직접 비교 기준으로 사용하지 않는다.

## 지표·비교 판독 (통계 검정 아님)

- 각 seed의 pooled OOF Accuracy, 기존 rf.macro_f1, P1 Recall/Precision, 정수 5x5 confusion matrix를 보존한다. seed 평균과 population SD(ddof=0), 참가자별 같은 지표와 주요 오분류(모든 비대각 오류의 내림차순)를 보고한다. Precision의 predicted support=0은 기존 구현처럼 0으로 처리한다.
- 주 비교: 같은 모델의 H9-v2 minus H9. 보조: 각 특징집합의 M2 minus M0; H9-v2 M3-G minus M0/M2. M0/M1 예측 동일성을 확인한다. 지표 차이는 percentage point로 표시한다.
- 기존 primary5 보고의 서술 기준을 계승: pooled Macro-F1 차이 >=+0.05이고 두 참가자 차이 모두 >=0이면 '개선 방향(탐색적)', <=-0.05이고 모두 <=0이면 '악화 방향(탐색적)', 그 밖은 '차이 불확실'. P1 Recall에도 같은 기준을 병기하되 표본 수와 경계값의 의미를 설명한다. 임계값에 못 미치는 차이도 수치 그대로 보고한다.
- n=2 참가자, 같은 자료로 특징·모델을 설계한 재사용 편향. seed/frame/tree 수를 독립 참가자로 취급하지 않는다. 유의성·CI·formal/generalization 주장을 하지 않는다.

## M3-G 실제 트리 진단

- 동일 H9-v2 fold의 M0/M2/M3-G를 읽어 C3 root 사용수/전체 tree 수, 전체 internal split 중 C3 비율, C3 split depth histogram(root=0), C3 포함 tree 비율, 실제 test path에서 C3 방문률과 최초 깊이를 기록한다. 후보 포함 확률(이론적 M0=2/9, M3-G=2/3)과 실제 채택 비율은 구분한다.
- 참가자/자세별 C3 구간 값, train/test 범위, 실제 threshold·노드 깊이, leaf soft probability와 예측 분포를 추적한다. root C3 tree와 나머지 tree의 probability/오류를 관찰 집단별로 요약한다. subgroup은 새 forest나 성능 최적화가 아니다.
- 각 test sample의 path depth/C3 방문수/예측 분포와 soft probability를 보존한다. 결정적 순서(seed, held-out, sample, tree index)로 M0 정답/M3-G 오답이며 M3-G root=C3인 최초 사례도 저장한다. 모든 C3 split node와 tree root를 저장해 빈도·깊이 요약을 재계산할 수 있게 한다.
- C3 경로와 잘못된 leaf/쏠림의 연관은 관측 사실로 보고할 수 있다. C3 제거/군 변경/추가 seed/다른 parameter/후향 임계값 선택은 하지 않는다. C3만이 성능 저하를 유발했다는 인과 주장이나 카메라/체형의 원인 분리는 불가하다.
- 관련 기존 synthetic test 모듈만 실행하고 전체 감사·전체 회귀는 실행하지 않는다. 새 진단은 node/path 합계, soft probability 재계산, 기존 예측 일치 등 실제 산출물 consistency check로 검증한다.

## 산출물

이 폴더의 새 실행 스크립트, 실행 전 기록, JSON(입력/코드/기존 결과 해시·support·fold·예측·지표·실제 트리 진단), REPORT.md. 마지막 보고서에서 확인 사실/원인 가설/최종 연구 상태/정식 평가 전 추가 개발 권고를 구분한다. 기존 canonical 결정·설계·구현·결과는 수정하지 않는다.
