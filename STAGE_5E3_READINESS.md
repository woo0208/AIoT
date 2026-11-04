# 5-E-3 정식 개발 촬영 준비 최종 검증

2026-11-04. Branch `feat/aiot-stage5e-d455-readiness`, base `dfb8534` + 본 작업의 미커밋 변경.

**판정: 5-E-3의 합성·비인체 기술 준비 검증 PASS. 6-A 정식 참가자 촬영은 HOLD / 현재 시작 불가.**
공식 IRB 승인·서면동의 및 아래 운영 조건을 확인한 기록이 없고, 이번 작업은 실제 참가자 촬영을 허가하거나 수행하지 않았다. 실제 사람의 특징 품질·측정 품질·연구 성능은 NOT_RUN이다.

Authority: `AGENTS.md`, Research Master §24~28, Decision Log EXP-003~007,
`RESEARCH_DATA_SCHEMA.md`, 5-D-3/5-D-8 동결 문서. 기존 결정·schema·원본·모델은 수정하지 않았다.
5-E-1 비인체 기술 완료와 CAP-007의 Patch 8 formal execution deferral은 별개다.

## 촬영 계획과 기존 프로그램 대응

| 항목 | 대응 및 판정 |
|---|---|
| P0 | `upright` |
| P1 | `forward_head` |
| P2 | `lean_back` |
| P3 | `lean_left` |
| P4 | `lean_right` |
| P5 | capture=`body_forward`, 평가=`lean_forward` |
| S1 | 각 참가자 round 1~3, 각 round에서 P0→P1→P2→P3→P4→P5 |
| S2 | 같은 참가자 round 4~5, 동일 순서 |
| 목표 수 | 1인 30구간, 개발2명 60구간. 첫 참조 P0 1개/인 제외 후 결측 전 상한 58구간 |
| 첫 P0 | S1 round 1 step 1을 사전 역할로 고정. 이후 P0의 품질·예측으로 교체하지 않음 |
| S2 보정 | 해당 참가자의 S1 첫 P0 key 재사용. 참조 실패 시 F0/F_cal 부적격 유지 |
| 구간 | 같은 장치 시간축에서 유지 종료 기준 `[종료−10초, 종료)`; prep·transition 제외 |
| 임계값 | F0/F_cal 공동 support 및 H 기존 공동9 support의 각각 유효 >=30, coverage >=0.5 유지 |

기존 `SEQ_CORE`/`SEQ_FULL`은 위 계획과 다르다. P5가 앞에 있고 복귀용 5초 P0가 섞여 있으며,
그대로 반복하면 정식 목표 구간과 대응하지 않는다. 이 상수와 production forward gate는 변경하지 않았다.
`record_phase(subject, round, start_info, seq, dataset_role)`는 외부 `seq`를 받으므로 기존 녹화·marker·종료 sidecar를 재사용할 수 있다.

새 `development_plan(개발2명ID, 승인된_자세별_유지초6개)`가 위 10개 take의 순서·session·round·획득 order를 만든다.
유지시간은 자동 기본값을 만들지 않고 명시 입력을 요구한다. 합성 테스트의 11초는 **시험값**이며 정식 유지시간 결정이 아니다.
실제 유지시간·휴식/세션 간격·준비/거리 안내·자세 지시문은 승인 SOP와 대조한 뒤 사용해야 한다.

촬영 후 `native_request(plan, captures)`가 지정한 개발2명 파일만 읽어 계획/producer hash/정식 dataset role/13개 prep·hold·end marker의 대응을 검사하고
기존 `generate_evaluation_input`용 요청을 메모리에 만든다. 파일 검색·카메라 시작·자동 재촬영 기능은 없다.
기존 pilot 기록을 formal로 승격하지 않으며 기존 개발 참가자와 동일인인 **신규** 촬영본만 계획에 넣는다.
기존 CLI의 전체 시퀀스·자동 품질 보고의 재촬영 권고를 정식 운영 지시로 사용하지 않는다. 추가 재촬영은 EXP-005에 따라 0회다.
촬영 중 거리 안내용 upright 기준과 F0/F_cal의 고정 S1 보정 참조는 다른 용도이며, 전자가 후자를 갱신하지 않는다.

## 연결 검증 및 결과

| 검증 | 결과 | 근거·범위 |
|---|---|---|
| 계획·라벨·S1/S2·3+2 | PASS | 신규 계획/metadata 어댑터 테스트. 불완전 계획, 초과 파일, 라벨 변경, 중단, pilot 승격 차단 |
| 원본→metadata/marker→native F0 입력 | PASS | 합성 개발2명 10개 take/60구간의 SHA 고정 입력을 기존 generator/loader로 연결 |
| 고정 참조·S2 재사용·참조 제외 | PASS | 60개 중 참조2개 제외, 나머지58개. 참가자별 클래스 support `[4,5,5,5,5,5]` 확인 |
| 마지막10초·실제 입력 분모 | PASS | 합성 각 hold 11초 중 마지막10초의 80개 전달 입력, 유효76개, coverage=76/80. 끝점 제외·prep 제외 |
| native→H5/H9 최소 연결 | PASS | 새 offline 어댑터가 기존 probe의 pose/face landmark·depth alignment·geometry 함수와 H 집계 재사용. F0와 전체 native inventory를 정확히 대조 |
| H5/H9→formal6 | PASS | 합성 H 프레임 값으로 기존 집계/bridge를 거쳐 58개 공통 key와 F0/F_cal/H5/H9/H9−F9의 6/6/5/9/8열 확인. H 시험값은 실제 센서 특징 재현/성능 근거 아님 |
| 라벨 QA gate | PASS | 같은 합성 입력도 review 미제공 시 공통 적격0개. 계획 라벨을 실제 수행 confirmed로 자동 승격하지 않음 |
| 기존 비인체 native 재생 | PASS | 동일 원본 두 번 EOF, 각각232 framesets, 전체 inventory 동일, timestamp 동일쌍6·color 재사용쌍3 유지, 폐기0 |
| 최종 코드 F0/H 원본 교차 검증 | PASS | F0와 H 각각232개, 원래 센서 시간/번호/payload hash 포함 inventory 정확 일치. 마지막10초 입력152개 |
| 비인체 결측·부적격 유지 | PASS | F0 공동 유효0/152, H 공동 유효0/152, 각각 coverage=0. H 부적격 사유30/50 유지. 사람 참조·session·confirmed를 부여하지 않음 |
| 원본·sidecar·잠금 모델 보존 | PASS | 실제 비인체 raw/sidecar 및 face/pose/mesh 모델 SHA 전후 동일 |
| 기존 formal6 개발/동결 gate 회귀 | PASS | 합성 전용 suite 포함. 실제 개발/외부4명은 사용하지 않음 |
| 실제 참가자 촬영·특징 품질·정식 학습/평가 | NOT_RUN | 이번 금지 범위. 실제 연구 점수·적격 표본 수를 추정하지 않음 |
| 프레임 누락률 | NOT_RUN | NOT_MEASURED 유지. coverage/FPS·행 index로 대신하거나 중복 제거 후 누락률을 계산하지 않음 |
| IRB·서면동의·실제 운영 release | NOT_RUN | 별도 필수 확인 조건 |

최종 관련 자동검증은 **210 tests PASS / 실패0**, `git diff --check` PASS다. 저장소 전체 감사나 독립 코드 감사는 아니다.
확장 검증 시도에서 존재하지 않는 `test_posture_geometry`, `test_posture_geometry_probe`를 잘못 지정해 import error 2개가 발생했다.
그 로그는 `attempt_with_unavailable_modules.log`에 보존했고, 실제 존재하는 관련13개 모듈을 지정한 최종 실행은 모두 통과했다.

```powershell
& 'analysis/research_h9_algorithms_20261029_7c3e91/.venv/Scripts/python.exe' -X utf8 -B -m unittest -q test_stage5e_readiness test_capture_end_timing test_capture_protocol test_f0_fcal_native test_f0_fcal_input test_f0_fcal_features test_f0_fcal_evaluation test_formal6_evaluation test_formal6_synthetic test_h5_h9_evaluation test_h9_csv_replay test_analysis_provenance test_f1_capture_analysis
```

최종 증거:

- [최종 210개 회귀 로그](analysis/READINESS_ONLY_5E3_20261104/final_210_tests.log)
- [최종 native F0/H 검증](analysis/READINESS_ONLY_5E3_20261104/final_verification/native_h_verification.json)
- [원본·모델 전후 hash](analysis/READINESS_ONLY_5E3_20261104/final_verification/native_h_source_pins.json)
- [기존 원본 두 번 재생 결과](analysis/READINESS_ONLY_5E3_20261104/reverification.json)

원본 SHA-256: `ab2eea18eb90806a28af43d09158bbd375dff8983dd837d06b677104de0da719`.

## 재사용 frameset 규칙

입력 단위는 기존 native inventory의 `frame_index`로 구분되는 **실제 전달 frameset**이다.
같은 sensor child가 재사용됐다고 입력을 삭제하거나 시간값을 +1 보정하지 않는다.
동일 sensor 번호의 timestamp/domain/형식/크기/payload가 같고, 상대 sensor의 진행이 검증되어야 한다.
모든 sensor가 그대로인 완전 재전달, 역행, clock/domain 변경, 재사용 payload 변경, 유일하지 않은 marker 연결은 차단한다.

RGB 재사용 시 F0 관측과 H의 RGB landmark 결과는 재사용한다. H의 depth geometry는 매 전달 frameset에서 다시 계산한다.
따라서 새 depth가 도착한 경우 과거 H9 벡터 전체를 캐시하지 않는다. 이 동작도 별도 합성 테스트로 확인했다.
결측 RGB/depth·검출 실패도 행과 분모에 남긴다. 각 특징군의 기존 support 조건을 만족하는 행만 그 특징군의 분자에 넣는다.
H5/H9의 기존 공동9 support와 F0/F_cal 내부 공동 support는 유지하고, 두 특징군 사이 원시 프레임 교집합을 새로 강제하지 않는다.

이 coverage는 고유 RGB 프레임 수나 독립 관측 수의 비율을 뜻하지 않는다.
센서 번호 중복 때문에 누락률을 NOT_MEASURED로 남기는 것은 frameset 기준 coverage 계산과 모순되지 않는다.
고유 RGB 단위로 분모/30개 기준을 바꾸는 정책은 이번에 채택하지 않았다.

## 6-A 시작 전 남은 필수 조건

1. 공식 IRB 승인서/version/유효기간과 신규 개발 촬영·6자세·5회·S1/S2·보관/접근/촬영 부담의 적용 범위를 확인한다. 개발2명 각각의 서면동의를 확인한다.
2. 기존 개발 참가자와 신규 정식 ID의 동일인 대응, 개발2명 roster, S1/S2·반복별 시간표를 사전 고정한다. 외부4명과의 독립성·접근 통제 및 라벨 수행 확인 담당/근거/상태 기록을 정한다.
3. 승인된 자세별 유지시간·준비/휴식·세션 간격·거리/프레이밍 지시문을 명시하고 본 계획과 대조한다. 10초 미만 장치 유지구간이나 불명확한 시간축은 unprocessed이며 후속 P0 대체/추가 재촬영으로 보충하지 않는다.
4. 새 저장 경로·여유 공간·D455/USB·원본/marker/metadata/end sidecar 보존·실패 기록·잠금 모델·사용 코드 상태/hash를 촬영 직전에 확인하고, 승인된 운영 절차로 명시적으로 촬영을 release한다. 이번 어댑터는 이 확인을 대신하는 실행 승인 UI가 아니다.
5. 기존 Foundation/EXPERIMENT_PROTOCOL 및 적용되는 실행 조건을 충족해야 한다. 이번 비인체 PASS는 CAP-007의 Patch 8 실행 보류를 해소하거나 정식 측정 품질 PASS/완료로 바꾸지 않는다.

최종 모델/전처리·코드/모델 hash 동결 및 독립 추론 release는 이후 **외부4명 접근 전** 필수 조건이다.
이를 개발2명의 신규 촬영 전에 최종 모델을 이미 선정해야 한다는 조건으로 잘못 앞당기지 않는다.
현재 외부4명 데이터는 열지 않았고, 실제 최종 모델 선정·학습·평가는 수행하지 않았다.

## 변경 파일과 동작

- `f0_fcal_native.py`: NativePackets가 현재 SDK frameset을 offline alignment에 읽기 전용으로 제공하는 3줄 추가. 원래 배열·timestamp·번호·기존 필터/판정 변경 없음.
- `stage5e_readiness.py` (신규): 개발2명 3+2 계획 및 지정 촬영 산출물→기존 native 요청 어댑터. 촬영 실행/원본 변경 없음.
- `stage5e_native_h.py` (신규): 잠금 pose/mesh 모델과 기존 probe geometry를 재사용한 offline H5/H9 추출. 전체 F0 inventory 정확 일치·EOF·hash를 확인하고 기존 집계/bridge용 sample/window/key map 반환.
- `test_stage5e_readiness.py` (신규): 합성6개 테스트. 계획·pilot 승격 차단·참조/S2·coverage·H inventory 불일치·재사용RGB/new-depth 처리·formal6 입력 및 미검토 차단 검증.
- `STAGE_5E3_READINESS.md` (신규): 본 판정·절차·조건·파일별 변경 기록.
- `analysis/READINESS_ONLY_5E3_20261104/` (신규 증거): `verify_native_h.py`, 두 번 재생 `native_recheck_1/2.json`, `reverification.json`, `source_and_model_pins_before/after.json`, `structural_tests.log`, `attempt_with_unavailable_modules.log`, `final_structural_tests.log`, `final_210_tests.log`, 최초 `native_h_verification.json`/`native_h_source_pins.json`, 최종 `final_verification/`의 같은 이름2개. 초기/중간 검증 기록을 덮어쓰지 않고 보존했다. 이 폴더는 정식 validation 실행 registry가 아니다.

기존 촬영 코드·forward gate·SEQ_CORE/SEQ_FULL·특징식·모델/seed/fold/지표·frozen schema·Decision Log는 변경하지 않았다.
실제 참가자 촬영, 외부4명 데이터 접근, 기존 원본/모델 수정, Patch 8 execution registry/ID 생성, commit/push 없음.
