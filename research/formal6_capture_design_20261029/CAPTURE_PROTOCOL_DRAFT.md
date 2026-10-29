# 정식 6인 촬영 프로토콜 초안

작성일: 2026-10-29. 상태: **DRAFT / 미승인·미실행 / 수집 시작용 문서 아님**.

제출 IRB 연구계획서·동의서·승인/보완 통지 원문과 별도 공통 촬영 규칙 문서는 현재 작업 폴더와 연결 문서 세션에서 확인되지 않았다. 아래의 “기존 규칙”은 저장소의 코드·Research Master·Decision Log에서 확인한 내용이며 **IRB 제출 내용과 같다고 확인한 것이 아니다**. 실제 차이와 승인 확인 항목은 [IRB_PROTOCOL_DIFF.md](IRB_PROTOCOL_DIFF.md)를 따른다.

## 1. 설계 범위와 상태

| 구분 | 내용 | 상태 |
|---|---|---|
| 사용자 요청 설계 | 6명×6자세×자세별 5회, 3회+2회 두 세션 | 이번 문서의 설계 제안 |
| 연구 분할 | 학습/개발 2명, 참가자 독립 보류 검증 4명 | 배정·독립성 확인 전 제안 |
| 촬영 공통 규칙 | 기존 full sequence, 전방 이동 face-only 8~12cm, 기존 입력 profile | 저장소 사실; 정식 환경 적합성/IRB 일치 여부 별도 |
| 정식 6-class 주 평가 | 기존 primary5를 대체할 수 있는지 | 연구 결정·IRB 범위 확인 전, 자동 변경 아님 |
| 정식 수집 | IRB 범위·윤리/동의·Foundation/프로토콜 freeze·실행 조건 | 미확인/미충족 조건이 남아 있으며 시작하지 않음 |

CAP-007/009의 Patch 8 실행 보류, EXP-002의 정식 수집 전 Foundation 완료 및 EXPERIMENT_PROTOCOL freeze 요구를 유지한다. 이 초안은 OPEN-002/003/005를 해소하거나 촬영 코드/SEQ_CORE/SEQ_FULL을 수정하지 않는다.

## 2. 목표 수량과 표본 단위

**반복 1회**는 여섯 목표 자세가 각각 한 번 들어가는 계획된 full-series 한 회차다. 프레임이나 복귀 upright 한 개를 반복 1회로 세지 않는다.

| 대상 | 참가자 | 1인 목표 구간 | 총 목표 구간 | 자세별 총 목표 구간 |
|---|---:|---:|---:|---:|
| 학습/개발 집단 | 2 | 6×5=30 | 60 | 10 |
| 독립 보류 검증 집단 | 4 | 6×5=30 | 120 | 20 |
| 전체 정식 설계 | 6 | 30 | **180** | **30** |

이는 **계획된 목표 구간 수**다. 실제 시도 수·취소/실패 수·라벨 확인 수·분석 적격 수는 따로 기록하며 180개가 유효하게 확보됐다고 미리 주장하지 않는다. 프레임 수와 seed 반복으로 참가자 수를 늘리지 않는다.

기존 파일럿 P01/P02는 별도 pilot 자료다. 이들의 이미 찍힌 구간을 정식 180개에 포함하거나 formal로 승격하지 않는다. 신규 정식 6명의 실제 모집/기존 파일럿과의 인물 중복 여부는 아직 확인되지 않았다. 개발 2명이 파일럿과 같은 사람인지도 별도로 확인하며, 외부 검증 4명은 개발·파일럿 탐색과 참가자 단위로 독립이어야 한다.

## 3. 기존 full sequence와 목표 구간의 대응

현재 `capture_d455.py`의 SEQ_FULL은 9개 hold와 각 hold 앞 4초 prep로 구성된다. **이 순서를 바꾸거나 새 촬영 명령을 실행하지 않는다.** 아래는 재사용을 검토하는 설계 대응표다.

| 기존 step | 원래 capture label | hold 초 | 설계상 역할 | 평가 라벨 |
|---:|---|---:|---|---|
| 1 | upright | 20 | 주 P0 목표 구간 1개 | P0 / upright |
| 2 | forward_head | 10 | P1 목표 구간 1개 | P1 / forward_head |
| 3 | upright | 5 | 복귀·직전 reference용; 추가 P0 학습 표본으로 세지 않음 | 원본 upright 유지, auxiliary-reference 역할 구분 |
| 4 | body_forward | 10 | P5 목표 구간 1개 | P5 / lean_forward로 분석 alias 대응 |
| 5 | upright | 5 | 복귀용; 목표 표본 수 제외 | 원본 upright 유지 |
| 6 | lean_back | 10 | P2 목표 구간 1개 | P2 / lean_back |
| 7 | lean_left | 10 | P3 목표 구간 1개 | P3 / lean_left |
| 8 | lean_right | 10 | P4 목표 구간 1개 | P4 / lean_right |
| 9 | upright | 5 | 복귀용; 목표 표본 수 제외 | 원본 upright 유지 |

따라서 1인 5회차에서 raw hold는 45개지만 목표 구간은 30개이고 auxiliary upright는 15개다. 전체 6명은 raw hold 270개, 목표 180개, auxiliary upright 90개다. raw를 삭제하는 것이 아니라 분석 역할을 사전에 구분하는 제안이다. 기존 writer/header/summary 의미를 수정하지 않는다.

원본 capture의 `body_forward`와 분석기 `lean_forward`의 alias는 유지하며 P5를 P1으로 합치지 않는다. 기존 full sequence의 자세 순서는 고정되어 있어 순서·학습·피로와 자세의 효과가 교란될 수 있다. 무작위화/순서 균형화가 필요하면 별도 프로토콜 변경 검토 대상으로 남기고 SEQ_FULL을 임의 변경하지 않는다.

## 4. 두 세션 3+2회 구성

실제 참가자 ID는 발급하지 않는다. 다음 F01…F06 및 session 표기는 **설계 자리표시자**이며 실제 모집·등록·실행 기록이 아니다.

| 세션 | 참가자 내 전역 repeat/round | 1인 목표 구간 | 6명 목표 구간 | 학습 2명 / 검증 4명 |
|---|---|---:|---:|---:|
| S1 | 1, 2, 3 | 18 | 108 | 36 / 72 |
| S2 | 4, 5 | 12 | 72 | 24 / 48 |
| 합계 | 1…5 | 30 | 180 | 60 / 120 |

전체 참가자-세션은 6명×2세션=12개(학습/개발 4개, 보류검증 8개)다. 한 사람의 S1/S2를 각각 새 사람으로 세지 않는다.

- S2에서 round를 다시 1로 시작하지 않는다. canonical round는 `"1"`…`"5"`의 양의 정수 문자열이며 실제 시도 횟수가 아닌 사전 계획 measurement slot이다.
- S1/S2 간 날짜·간격·휴식·중단 기준은 IRB 원문/참가자 부담 검토 후 수집 전에 고정한다. 같은 날인지 다른 날인지는 아직 확정하지 않는다.
- S2는 장비·좌석·자세 안내를 다시 확인하고 실제 설치/거리/profile을 기록한다. 이전 세션의 upright reference를 가져오지 않는다. 각 recording 내 직전 upright 규칙과 face-only reference를 유지한다.
- 세션을 train/test로 나누지 않는다. 한 참가자의 두 세션과 다섯 반복은 모두 같은 연구 분할에 속한다.
- 세션 차이는 사라지는 오차가 아니라 기록·보고할 요인이다. 전체 결과 외에 S1/S2 결과를 별도로 보고하되 세션을 새 참가자로 세지 않는다.

## 5. 실현 가능성과 소요시간

기존 코드 상수의 산술 계산만 수행했다. full sequence hold 합계 85초 + prep 9×4초=**121초/회차**다. 이는 실측 방문 시간이나 IRB 승인 시간의 확인값이 아니다.

| 항목 | 순수 sequence 시간 하한 |
|---|---:|
| S1 3회차 | 363초 = 6분 03초 |
| S2 2회차 | 242초 = 4분 02초 |
| 1인 5회차 | 605초 = 10분 05초 |
| 6인 합계 | 3,630초 = 60분 30초 |

여기에 안내·동의 확인·설치·거리 맞춤·반복 사이 휴식·두 번째 방문 준비·라벨 확인·파일 확인·기술적 실패 처리가 추가된다. 기존 거리 안내의 정상 유지 2초+countdown 3초 외에도 거리를 맞추는 시간은 가변적이므로 방문 시간을 10분 05초로 잡지 않는다.

세션 소요시간의 예산식은 `T_session = 121×회차수 + 세션별 설치/설명 + 회차별 guide + 회차 사이 휴식 + 확인/중단/허용 재시도 시간`이다. 각 항의 길이와 참가자당 총 방문 부담은 IRB 원문과 대조해 확정해야 한다.

**판정:** 횟수 배분과 기존 sequence를 연결하는 문서상 구성은 가능하지만, 정식 운영 가능/승인 완료 판정은 아니다. S1에 18개 목표 구간이 집중되는 부담, 재착석에 따른 세션 차이, 촬영 간격, 설치 재현성, 실제 device/profile, 5회 반복 허용 범위가 확인되지 않았다. 이러한 확인 없이 시간을 줄이기 위해 hold/prep/gate를 바꾸거나 수집을 시작하지 않는다.

## 6. P0/P1/P5 정의와 라벨 검증 제안

임상 진단명이나 알고리즘 예측값을 정답 라벨로 사용하지 않는다. 아래 관찰 정의는 현재 안내 문구를 구체화한 **검토용 운영 정의**이며, 제출 IRB/공통 촬영 규칙과의 일치는 미확인이다.

| 라벨 | 현재 안내에 따른 의도 | 확인할 관찰 | 혼동/보류 사례 |
|---|---|---|---|
| P0 upright | 허리를 펴고 정해진 화면 표시점 보기 | 시작 기준 자세·머리/상체 정면·편안한 지속 가능 여부 | 이미 머리/몸통이 전진한 시작 자세, 전환 중 구간, 기준 자세 미확인 |
| P1 forward_head | 등·어깨는 기준 자세를 유지하고 머리 전체를 수평 전진; 시선·고개 각도 유지 | 머리 전진이 주 동작인지, 상체 전체 전진과 구별되는지 | 고개 숙임/젖힘·회전 또는 몸통 전진이 섞여 P1/P5를 구별하기 어려움 |
| P5 body_forward / lean_forward | 머리만이 아니라 등·어깨를 포함한 상체 전체를 앞으로 | 머리와 상체가 함께 이동한 의도인지 | 머리만 전진해 P1에 가까움, 동작 의도나 유지 구간 미확인 |

P1과 P5 모두 기존 **직전 upright 대비 face-only 0.08~0.12m inclusive** 조건을 적용하는 방향을 유지한다. 이 동일 얼굴 이동 gate만으로 두 자세의 ground-truth 라벨이 결정되지는 않는다. 어깨/골반 이동량·비율·C3 각도를 새로운 hard capture gate나 정답 생성 threshold로 추가하지 않는다(CAP-001/002/009).

P2는 뒤로 기울임, P3/P4는 참가자 자신의 왼쪽/오른쪽으로 상체를 기울이되 고개를 돌리지 않는 기존 안내를 따른다. 거울형 UI 좌우와 참가자 좌우가 뒤바뀌지 않도록 관찰자 안내에서 확인한다. code의 live 안내 상수를 새 정식 라벨 허용 threshold로 승격하지 않는다.

라벨 검증 절차 제안:

1. 촬영 지시 라벨과 실제 검토 라벨을 구분하고 모델 점수/예측을 보지 않는 검토자가 확인한다.
2. 계획된 검토자 2인의 독립 확인과 불일치 시 사전 지정 판정 절차를 제안한다. 인력·열람 권한·영상 이용 허용 범위는 수집 전에 확인한다.
3. `confirmed / ambiguous / mismatch / not_reviewable`와 이유를 기록한다. 불일치 자료의 제외·재시도·판정 규칙은 연구 정책으로 사전 고정하며 모델 예측에 맞춰 라벨을 바꾸지 않는다.
4. 재검토용 RGB/영상/이미지는 IRB·동의·보관 범위가 허용할 때만 사용한다. 영상이 허용되지 않으면 현장 관찰과 확인 가능한 기록 방식의 한계를 먼저 정하고, 추가 카메라/측면 영상 저장을 임의 도입하지 않는다.
5. 얼굴 이동 gate의 증거, 동작/라벨 확인, 영상/depth 관측 품질, 분석 eligibility를 각각 별개로 기록한다. 코드 gate PASS를 올바른 P1/P5 수행의 충분조건으로 취급하지 않는다.

## 7. 유효 구간 정의 — 수집 전 freeze가 필요한 제안

raw에서는 prep/transition·hold·복귀 구간을 모두 보존한다. 분석 대상은 위 목표 step 6개만 선택하는 방안을 제안하며, 선택 권위와 analysis lineage를 별도로 연결해야 한다.

**후보 W1:** 각 목표에서 10초의 고정 분석 창을 쓰고, 주 P0는 20초 hold의 마지막 10초 `[hold_start+10s, hold_end)`, P1/P5/P2/P3/P4는 각 10초 hold `[hold_start, hold_end)`를 사용한다. 이는 동일 구간 길이를 위한 구체적 **미승인 후보**이며 현재 집계·trim 동작에 적용하지 않는다. 기존 전체 hold를 쓰는 방안과 비교해 하나를 데이터 열람 전에 연구 결정/IRB 대조 후 고정해야 한다. 불리한 frame을 피하려고 창을 움직이지 않는다.

이 분석 창 후보는 production forward gate의 기존 final window·reference·분모를 바꾸지 않는다. gate의 계산 증거는 원래 protocol 그대로 평가한다. 분석 창, H9 공통 유효 frame support, 라벨 확인을 서로 구분한다.

H9의 기존 ≥30 common-valid frames 및 ≥50% coverage는 현재 집계기의 eligibility 사실이다. 정식 포함 정책으로 채택할지와 선택한 특징 구성의 결측 처리는 사전 확인이 필요하다. 이 수치를 새 촬영 acceptance gate로 추가하거나 C3/depth 결측을 임의 보간하지 않는다. valid 구간이 부족해도 성공 5개를 채울 때까지 무제한 재촬영하지 않는다.

## 8. 기록 항목 정의

다음은 **연구 운영 매핑 설계안**이다. 실제 레코드·참가자 명부·Registry·execution_id를 만들지 않는다. 고정 `frames-schema/1.0.0`, `summary-schema/1.0.0`, selection/lineage 필드에 새 열을 임의 추가하지 않는다.

| 구분 | 기록할 항목 | 정의/경계 |
|---|---|---|
| 연구/문서 | 연구 식별자, 적용 IRB/동의서 version, protocol/selection policy version | 문서 근거 확인 후 사용; 이 draft명을 실행 protocol_version으로 쓰지 않음 |
| 참가자 | `subject`/participant ID, 연구 분할, 실제 인물 중복 확인 | F01…F06은 자리표시자. 실명 연결표는 분리·권한 제한; ID만으로 role 추정 금지 |
| 세션 | session_id, session ordinal S1/S2, 시작/종료 ISO 시각·offset, 장소/설치/담당자 | 예: FORMAL6-F01-S1은 형식 예시일 뿐 실제 발급 아님. session은 participant나 round를 대체하지 않음 |
| 반복 | repeat_id, canonical `round`, planned repeat ordinal | 전체 참가자 내 1…5 유지; S1=1…3, S2=4…5; 실패 시도 횟수와 구분 |
| 촬영 시도 | recording_id, 원본 파일 경로/크기/SHA-256, attempt 상태/중단 이유 | 기존 `<subject>_r<round>_<timestamp>_<uuid>` 형식 유지. 재시도는 새 recording_id, 실패 ID 재사용 금지 |
| 단계/라벨 | 기존 step, capture label, analysis alias, target/reference 역할, 지시/검토 라벨 | step 1/2/4/6/7/8을 목표에 대응; 원래 upright/reference의 raw 라벨 보존 |
| 시간/구간 | prep/hold marker, 지시 시작/종료, 실제 유지 시작/종료, 분석 창 후보/확정 경계, frame index 범위 | UTC/host/device clock을 분리; exact source frame 목록/마스크와 analysis run을 연결 |
| 라벨 QA | 검토자 pseudonym, 상태/불일치·판정 이유, 검토 근거 reference | classifier 예측을 정답 근거로 쓰지 않음; 영상 열람은 승인 범위 내 |
| 카메라 | 장치 serial/firmware, 요청·실제 color/depth profile/format/FPS, depth scale, intrinsics/extrinsics, align | 기존 요청 color1280×720 BGR8 / depth848×480 Z16 / 15FPS / align=color; 실장치 값을 관측 전 채우지 않음 |
| 설치/환경 | 카메라 높이·각도·고정 상태, 좌석/책상, 거리 기준점·실제 관측, 조명·가림·복장 관련 관찰 | 기존 0.70~0.80m는 초기 안내 범위, 정식 적합 거리의 검증 결과가 아님. 세션마다 기록 |
| 코드/모델 | git commit/dirty, script/model SHA-256, MediaPipe lock, 환경 버전 | 승인된 실행 코드/모델의 정확한 identity; 현재 파일 hash로 과거 촬영 환경 추정 금지 |
| 품질/유효성 | face-only gate 증거, 누락/검출/depth validity, 분석 common support, coverage, 제외 이유 | capture quality·label QA·scientific inclusion을 분리; `formal` role 자체는 포함 승인 아님 |
| 선택/분석 | selection event/manifest reference, analysis_run_id, frames/hash, aggregation spec, input frame indices | 기존 frozen provenance/selection 계약 재사용; engineering H9→canonical lineage 연결은 별도 검증 필요 |

여섯 사람을 같은 승인된 정식 수집 절차로 촬영한다면 원천 `dataset_role=formal`과 분석상 `train_development / heldout_external` 구분을 별도로 설계한다. 보류 검증 4명이라고 자동으로 `dataset_role=external`로 바꾸지 않는다. Schema의 external은 수입/다른 수집 조건의 자료 역할이며 analysis split과 같지 않다.

## 9. 실패·누락·재촬영 처리의 미확정 항목

계획 slot은 `(dataset_role, subject, round)`이며 같은 round 재시도는 새 recording_id와 explicit recapture relation으로 구별한다. “시도번호가 늘었으므로 round도 늘리기”로 실패를 숨기지 않는다. 전체 round 재촬영/부분 자세 재촬영 허용 여부, 최대 회수·부담, ok_with_warnings 포함, 기술 실패와 라벨 불확실성 처리, 최종 선정 근거는 OPEN-005와 scientific selection policy에서 수집 전에 결정해야 한다. 이번 초안은 그 값을 임의 확정하지 않는다.

공통 결측/누락은 실제 유효 수로 보고한다. 추가 수집이 필요하면 사전 정한 승인 범위/선택 규칙을 확인하고, 결과·정답률이 좋은 촬영본만 선택하지 않는다.

## 10. 실제 시작 전 남은 확인

제출 IRB 원문·승인/보완 범위, **5회 반복 및 두 세션의 부담**, **알고리즘/특징 변경 범위**, 정식 6-class 연구 결정, 모집/분할·동의/보관, 분석 창/라벨/포함 정책, Foundation/Patch 8 및 실행 승인 조건, 정확한 배포 코드/모델·lineage 연결을 확인하기 전에는 수집을 시작하지 않는다. 승인 여부는 이 문서가 판정하지 않는다.

근거: [Decision Log](../../docs/research/RESEARCH_DECISION_LOG.md) CAP-001/002/007/009, DATA-001/002, EXP-001/002, OPEN-005; [Schema](../../RESEARCH_DATA_SCHEMA.md) §A/B/F/G/H; [capture_d455.py](../../capture_d455.py)의 POSTURES/SEQ_FULL/PREP_SEC/profile; [기존 평가 체계](../evaluation_framework_20261029/README.md).
