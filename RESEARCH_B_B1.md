# 연구 B — B1 수동 측정 수요에 따른 RGB-D 처리 (1차 구현)

2026-11-16. 상태: **구현 / 합성 구조 검증; 실제 절감·정확도 유지 UNVERIFIED**.
현재 사용자 요청에 따른 비정식 engineering 후보이며 공식 평가·B6·CAP-007/009·Patch 8 HOLD는 유지한다.
과거 Decision Log·Master·Schema·촬영·연구 A 산출물은 변경하지 않는다. 새 정식 schema나 execution registry도 없다.

## 확인한 근거와 비용

권한은 AGENTS.md, `docs/research/AIoT_RESEARCH_MASTER.md`, `docs/research/RESEARCH_DECISION_LOG.md`
(CAP-007~009, EXP-003~007), `RESEARCH_DATA_SCHEMA.md`다. 현재 구현 사실은
`posture_geometry_probe.py`, `posture_geometry.py`, `e0_fs3.py`, `f1_sample_aggregator.py`,
`e0_model.py`와 연구 A의 `compare_pilot120_feature_sets.py`/`compare_six_feature_svm_knn.py`에서 확인했다.

보존된 실제 E0 완료 실행 A/D는 `analysis/E0_GUIDED_REVIEW_20261109/REPORT.md` 및
그 `local_private/review.json`이 가리키는 두 `timing/diagnostics.json`을 읽었다.
아래는 **과거 E0 비용 관측**이며 B1 추정 성능이나 CSV 기반 재실험 결과가 아니다.

|단계|A p95 (ms)|D p95 (ms)|호출/경계 해석|
|---|---:|---:|---|
|RGB-D 수신 대기|30.260|30.864|8273/8690회; 센서 대기, 순수 CPU 비용 아님|
|Align|4.240|4.227|8271/8688회; 현재는 추론 전 실행|
|Pose|13.030|11.971|매 처리 프레임, VIDEO tracking 이미 사용|
|FaceLandmarker|6.064|6.073|같은 RGB/mp.Image/타임스탬프 공유, VIDEO tracking 이미 사용|
|Depth geometry + 후보 특징 계산|0.628|0.602|한 context에 depth 샘플링·deprojection·기하 계산 포함|
|FS3 특징 검사/선택|0.0083|0.0095|매 처리 프레임|
|10초 집계|0.460|0.436|각 30회|
|Scaler|0.240|0.225|각 30회|
|SVM|0.170|0.131|각 30회; 주 절감 대상으로 삼을 근거 없음|
|UI 이미지 생성·제출|12.436|12.394|물리적 화면 표시 완료 시간 아님|
|HighGUI waitKey/event|15.756|17.521|최대 527/1095ms; 긴 정지 원인은 미확정|

수신 후 전체 처리 p95는 51.530/52.895ms, FPS 14.958/14.947이다. 단계 분위수를 더하거나
그 비율로 전체 비용을 분해하지 않는다. 과거 로그에는 Tk poll 경계가 없으므로 전체 루프 비용을
소급 계산하지 않는다. 새 비교에서는 기존 공통 Tk/전체 루프 계측을 쓴다.

## 방식 비교와 선정

|후보|정확도 위험|난이도|실제 생략 대상 / 판단|
|---|---|---|---|
|움직임/예측 안정성으로 측정 중 프레임 감축|미세 P0/P1 변화·지연·support 변경 위험 큼|높음|Pose/Face/Align까지 가능하나 원본 재검증·허용 손실 기준이 없어 미선정|
|Pose 미검출 시 Face/Depth 생략|검출 복귀 때 Face tracking 이력 변화|중간|Pose 자체는 계속 실행, 절감은 미검출 조건에 한정; 우선하지 않음|
|불필요 geometry만 축소|H9 공통 support 보존 확인 필요|중간|관측된 geometry 비용이 상대적으로 작고 Pose/Face/Align은 남음|
|**B1: 수동 hold 수요 없는 구간 생략**|측정 중 샘플 감소 없음; 유휴 후 tracking 재개 영향은 미검증|낮음|**유휴 Align·Pose·Face·Depth·특징 검사와 RGB→MP 변환 생략**|

기존 E0는 arm/active가 없어도 모든 연산을 수행하고, `E0Session.accept()`에서야 hold 미요청을
확인해 집계를 생략한다. 그러므로 수신·원시 메타데이터 관측 직후, `align.process()` 전에
수요를 확인하면 영상 연산을 실제로 호출하지 않을 수 있다. 센서 스트림은 계속 배수한다.
고정 FPS·motion threshold·confidence threshold·이전 특징/예측 캐시는 추가하지 않는다.

B1의 적용 범위는 **수동 10초 측정 경로**다. 상시 자동 자세 모니터링이나 측정 중 가속의
해결책으로 주장하지 않는다. 유휴가 없으면 이 방식의 주 절감 대상도 없다. 영상 전처리와
geometry overlay도 유휴 때 사라지므로 절감 전부를 신경망 추론에 귀속하지 않는다.

## 실행·상태·보존 계약

- 기본 `run_probe()`/`run_e0_check.py`/E0Session/연구 A는 기존대로다.
  선택 인자 `rgbd_policy=None`은 기존 처리 경로를 유지한다.
  새 실행기 `--variant E0`는 공통 관측만 추가하고 모든 프레임을 처리한다.
- B1 IDLE: RGB-D 수신·원시 번호/시간 관측·자원 계측·Tk/HighGUI 이벤트는 계속한다.
  현재 원시 RGB에 `features/prediction unavailable`을 표시한다. 이전 geometry 화면은 재사용하지 않는다.
  로그 상태 `b1_idle_skipped`, `measurement_available=false`; 특징/예측/callback을 생성하지 않는다.
  FULL에서도 `measurement_available`은 원래 H9 공동 관측이 유효할 때만 true다.
- Start/Enter 후 첫 입력부터 FULL. `armed` 또는 `active`이면 매 프레임 기존 경로를 전부 실행한다.
  `[first,first+10000ms)` 및 종료 확인용 전체 처리 프레임도 보존한다. 취소/완료 후 다음 입력부터 IDLE.
- FS3의 F1/F3/F4/F5/F6/F7/F8, SVM-FS3-V0-T0 및 artifact/Scaler hash,
  H9 9열 공동 support·30개/50%·중앙값/원형평균·결측 처리·평가/LOSO 로직은 변경하지 않는다.
- 누락 특징은 누락으로 전달하고 보간·0 대체·이전 값 사용은 없다. 시간 중복/역행 취소·수동 재시작은
  기존 E0 처리다. MP용 단조 timestamp 어댑터와 원시 장치 timestamp 검사는 기존 경계를 유지한다.
- 추론/Align/미리보기 오류는 실패로 저장하고 SDK를 정리한다. 실패를 성공이나 자동 재시도로 바꾸지 않는다.
  gate는 다른 특징 소비자/callback·추가 3D·RF/H9/원본 writer와 함께 쓰지 못한다.
- `make_config()` 그대로 RGB1280×720 / Depth848×480 / 15FPS. raw 기록 인자는 전달하지 않는다.
  모델은 기존 explicit hash binding으로 로드할 뿐 재학습하지 않는다.

## 실행 명령 (이번 작업에서는 check-only와 합성 테스트만 실행)

```powershell
python -X utf8 -B run_research_b.py --check-only --variant E0
python -X utf8 -B run_research_b.py --check-only --variant B1
```

향후 별도 지시로 허용된 비정식 D455 engineering 점검에서만 다음 명령을 수동 실행한다.
각 출력 경로는 새 경로여야 한다. 자동 촬영·자동 자세 시작·참가자 평가 명령이 아니다.
기존 binding은 연결/비용용 fold0 artifact이며 최종 120학습 배포 모델로 승격하지 않는다.

```powershell
python -X utf8 -B run_research_b.py --live --variant E0 --duration-seconds 300 --mode summary --output-dir analysis/RESEARCH_B/local_private/e0_01
python -X utf8 -B run_research_b.py --live --variant B1 --duration-seconds 300 --mode summary --output-dir analysis/RESEARCH_B/local_private/b1_01
python -X utf8 -B research_b_report.py --run analysis/RESEARCH_B/local_private/e0_01
python -X utf8 -B research_b_report.py --run analysis/RESEARCH_B/local_private/b1_01
```

`--live` 없이 출력 폴더/카메라/GUI를 만들지 않는다. 실제 실행은 Start/Enter로 안정 10초,
T로 취소, Q로 종료한다. 새 참가자 촬영을 선행조건으로 두지 않는다.
기존 raw RGB-D가 있는 경우 동일 입력 재생 검토가 우선이며, 이 1차 구현에는 raw 재생 실행기는 없다.

실측 비교 시 같은 PC/전원/장치 profile·모델/Scaler hash·UI(waitKey)·계측 모드·자원 주기(기존 1초)·
buffer(기존 256)·지속시간·수동 hold/유휴 일정으로 새 E0와 비교한다. 계측이 다른 과거 E0를
새 B1의 직접 대조군으로 쓰지 않는다. 반복 비교 계획은 300초, 새 프로세스 3쌍,
순서 E0/B1 → B1/E0 → E0/B1이다. 수동 시작 시간과 실제 demand/idle 수를 보고해 작업량 차이를
숨기지 않는다. 이번에 이 실측이나 참가자 절차를 실행/승인한 것은 아니다.

## 계측·정확도 보고

`summary.json`, `segments.jsonl`, `resources.jsonl`, `timing/diagnostics.json`과 bounded checkpoint를
재사용한다. 상세 모드만 frames/raw timing을 보관한다. 새 수치 로그는 Git 제외 `local_private/` 아래 둔다.
원본 영상·Depth·랜드마크·특징값은 저장하지 않는다.

- 모든 루프·수신/전체 처리/유휴 미리보기 수와 FPS를 분리한다. 미리보기 FPS를 추론 FPS로 세지 않는다.
- 기존 전체 루프 및 수신 후 지연 p50/p95/p99를 유지하고 FULL/IDLE, FULL-demand/FULL-idle
  완료 지연도 분리한다. FULL-demand에는 최초 재개·종료 확인 프레임도 포함한다. 유휴 비중 때문에
  전체 p95만 낮아지는 경우를 측정 중 가속으로 해석하지 않는다.
- Align/Pose/Face/Depth/집계/Scaler/SVM/UI의 실제 context 호출 수와 시간 분포를 보고한다.
  예외로 끝난 호출도 시간 표본에 포함된다. CPU/RSS 통계는 기존 ResourceMonitor 그대로다.
- 번호 gap·중복·reset·domain 경계는 원시 스트림에서 관측한다. `gaps/(gaps+advances)`는 동일
  스트림 내부 양의 번호 증가량을 분모로 한 **host 관측 진단 비율**이며 정식 누락률 명세가 아니다.
  중복·역행·번호 재사용·경계·메타데이터 부재가 한 번이라도 있으면 비율은 NOT_MEASURED.
  의도적 B1 생략은 별도 계수다. 실제 센서 생성/SDK 내부 drop률은 계속 NOT_MEASURED다.
- 정답이 없으면 Accuracy/Macro-F1/P0/P1 Recall은 NOT_MEASURED다. 과거 CSV, 안내 순서나
  이전 E0 결과를 정답으로 자동 전환하지 않는다.
- 독립 확인 정답이 별도로 있을 때만 아래 선택적 sidecar를 사용한다. 이 파일의 생성이나 실제
  평가를 이번에 수행하지 않았다. 동일 summary SHA-256과 모든 구간(실패 포함)을 요구한다.
  지표는 연구 A와 같은 sklearn 고정 6-class / percent 정의다. 예측 성공 구간만 점수화하며
  전체/실패 수·prediction coverage를 반드시 표시한다. 실제 support가 없는 Recall은 N/A,
  6-class Macro-F1은 INCOMPLETE/미산출이다. 고정6 진단 점수는 별도로 표시한다.

```json
{
  "summary_sha256": "<해당 summary.json의 SHA-256>",
  "source": "independent_observation",
  "segments": [
    {"segment_index": 1, "label": 0, "confirmed": true}
  ]
}
```

```powershell
python -X utf8 -B research_b_report.py --run analysis/RESEARCH_B/local_private/b1_01 --labels analysis/RESEARCH_B/local_private/confirmed_labels.json
```

별도 실행의 summary-bound 정답만으로 동일 입력/공통 적격 표본 비교를 증명하지는 못한다.
분류 정확도 차이를 결론내리기 전 동일 입력·구간 정합성과 공통 적격 집합을 확인해야 한다.

## 검증과 다음 작업

합성 SDK/입력/시계/기학습 상태 대역만 사용했다. 실제 영상·학습·정답평가·실측 절감 수치 생성은 없다.
신규 `test_research_b.py`는 유휴 실제 호출0, 시작 즉시 복귀, 취소/재시작, 종료 경계,
E0/B1 동일 10초 집계와 Scaler 입력/예측, 결측/오래된 값 비사용, timestamp 중복 복구,
invalid pair/timeout/단계별 예외 cleanup, 호출 수/지연 분리, gap 불확실성, 정답 binding과
클래스 누락, check-only 무생성 및 금지 소비자 차단을 검증한다.

다음 작업은 (1) 기존 raw 가용성 확인, (2) 허용된 동일 작업량의 비정식 engineering 비교,
(3) 재개 직후 특징 가용성/지연/추적 복귀 및 P0/P1 정확도 위험 검증이다.
상시 추론 중 처리 생략은 원본 근거와 허용 손실 기준이 생기기 전 구현·튜닝하지 않는다.
성능 향상, 정확도 유지, CPU/RSS 절감, 센서 누락 개선, 실측 p50/p95/p99는 모두 **미검증**이다.

### 실제 수행한 검증 결과

- 최종 관련 회귀 **138 PASS** (신규 B1 17개 포함). 명령:

```powershell
python -X utf8 -B -m pytest -q -p no:cacheprovider test_research_b.py test_e0_fs3.py test_e0_p2.py test_e0_p3.py test_e0_e1_ui.py test_run_e0_check.py test_e0_guided_panel.py test_h9_probe_integration.py test_probe_timing.py test_performance_output.py test_h9_probe_timing.py
```

- 실제 기존 artifact의 E0/B1 check-only **둘 다 PASS**, 카메라/GUI/출력 폴더 무생성.
- 보존된 E0 A/D **842파일 SHA-256 전부 일치**, 불일치 0.
- 루트 68개 `test_*.py`를 명시 수집하고 `--continue-on-collection-errors`로 실행한 넓은 회귀:
  **1187 PASS / 13 FAIL / 1 SKIP / 수집 ERROR 1**, subtests 2245 PASS. 전체 회귀 PASS로 보고하지 않는다.
- 13 FAIL은 `test_hipless_candidates.py` 1개(기존 CSV 호출의 필수 인자 누락)와
  `test_patch7_integrity.py` 12개(Windows backslash provenance fixture 경로 불일치)다.
  동일 13개를 `git show HEAD:posture_geometry_probe.py`로 가져온 **변경 전 모듈을 메모리에서만 로드**해
  재실행해 모두 동일 실패를 확인했다. 작업 파일을 되돌리거나 기존 이슈를 수정하지 않았다.
- 수집 ERROR는 기존 `test_mesh_avatar_integration.py`의 `test_f1_demo_rf` import 대상 부재다.
  처음 시도한 무제한 재귀 수집은 `analysis/` 안의 과거 테스트 복사본 이름 충돌/누락 의존성으로
  수집 단계에서 실패했으므로 위 루트 명시 수집 결과와 구분한다.
- 신규 Python 파일 및 수정 모듈 AST 구문 검사, `git diff --check` PASS.

이번 변경은 `posture_geometry_probe.py`의 opt-in gate/공통 관측 hook 추가와 신규
`research_b.py`, `run_research_b.py`, `research_b_report.py`, `test_research_b.py`, 이 문서다.
작업 시작 때부터 있던 `E0_INSTRUMENTATION.md`, `capture_six_pilot.py` 등의 변경은 손대지 않았다.
실제 D455·참가자 평가·학습·공식 실행·Commit/Push는 수행하지 않았다. 기존 HEAD `e0b2440` 유지.
