# Head Orientation Engineering 측정 검토 보고서

- 문서 상태: **ENGINEERING / NON-FORMAL / REPRODUCIBLE CSV REVIEW**
- 분석·재현 기준 Checkpoint: `5960201fa8aa13ede9974ad1f0c691832ea47bbb` (CSV 생성 당시 코드 정체성은 미검증, §1.1)
- 기준 브랜치: `feat/posture-3d-visualization`
- 측정일: `2026-10-10` (CSV `timestamp_utc` 기준)
- 문서화일: `2026-10-10`
- 데이터 위치: `data/engineering/head_orientation/` (로컬·Git ignored)

## 1. 목적과 권위 경계

이 문서는 D455 Head Orientation engineering probe로 얻은 로컬 CSV를 분석·재현 기준 Checkpoint `5960201`을 기준으로 다시 계산해, 현재까지 관찰된 동작을 재현 가능하게 기록한다. CSV를 생성한 코드가 이 Checkpoint와 동일하다는 뜻은 아니다(§1.1). 이번 검토는 문서화 작업이며 probe 코드, 테스트, CSV, 실험 알고리즘 및 연구 계약을 변경하지 않는다.

~~~text
engineering measurement / diagnostic evidence
!= formal research data
!= Patch 8 formal D455 validation evidence
!= F0/F1/F2 feature freeze
!= M0/M1/M2 성능 평가
!= 논문용 정식 성능 검증
~~~

CSV의 `artifact_kind`도 각각 `exploratory-posture-geometry-engineering-measurement`와 `exploratory-face-pipeline-engineering-diagnostic`다. 이 CSV는 `frames-schema/1.0.0` canonical frame artifact가 아니며 recording/analysis provenance, 사전 등록된 동작 marker, 반복 참가자 설계 또는 ground-truth 각도를 포함하지 않는다. 따라서 F0/F1/F2, M0/M1/M2, Patch 8 protocol/threshold, production forward gate 또는 frozen schema를 변경하는 근거로 사용하지 않는다.

### 1.1 코드 Provenance 경계

- §3의 주 근거 7개 measurement CSV의 `timestamp_utc`는 `2026-10-10T10:39:37.297Z`(첫 run 첫 행, 19:39:37 KST)부터 `2026-10-10T11:14:53.693Z`(마지막 run 마지막 행, 20:14:53 KST)까지다.
- Checkpoint `5960201`의 commit 시각은 `2026-10-10T20:29:51+09:00`(`11:29:51Z`)이다. 따라서 주 근거 CSV는 모두 이 commit이 만들어지기 **이전**에 수집되었다.
- 주 근거 14개 CSV에는 Git commit, working-tree dirty 상태, code hash 또는 probe version을 기록한 column이 없다.
- 그러므로 촬영 당시 실행된 working tree의 정확한 코드 정체성은 **검증되지 않았다(unknown)**. 실행 코드가 `5960201`과 byte 단위로 동일했다고 단정하지 않는다. §10 보조 CSV의 생성 코드 정체성도 검증하지 않았다.
- `5960201`은 이 문서의 column 의미 해석과 수치 재계산을 위한 **분석·재현 기준 Checkpoint**로만 사용하며, CSV 생성 코드의 provenance 증거가 아니다.

## 2. 재계산 방법

### 2.1 시간·프레임·유효율

- 프레임 수: CSV header를 제외한 data row 수.
- 측정 시간: 마지막 `device_timestamp_ms`에서 첫 `device_timestamp_ms`를 뺀 값.
- elapsed time: `(row.device_timestamp_ms - first.device_timestamp_ms) / 1000`.
- Face orientation 유효: `face_matrix_valid == true`.
- face diagnostic 유효: `face_pipeline_status == MATRIX_VALID`.
- 구간 표기: `[a, b)`는 `a <= elapsed_s < b`인 반개구간이다.
- 구간 대표값: 해당 구간의 finite value 중앙값. 결측값을 0으로 대체하지 않았다.
- 변화량: condition 중앙값에서 직전 또는 명시된 neutral 중앙값을 뺀 값이다. 반올림 전 중앙값으로 계산하므로 표의 반올림 값끼리 뺀 결과와 마지막 자리가 다를 수 있다.

검토한 7개 measurement/diagnostic 쌍은 행 수가 같고, 행 순서대로 비교한 `device_timestamp_ms` 전체 시퀀스(원문 문자열 기준)가 정확히 일치했다. 즉 모든 i에 대해 measurement CSV의 i번째 data row와 diagnostic CSV의 i번째 data row가 같은 timestamp를 가진다. 두 파일 모두 timestamp는 감소하지 않는다.

**Timestamp 제한사항:** `device_timestamp_ms`는 frame 고유 식별자가 아니다. 7쌍 중 6쌍은 시작부의 처음 2~4개 행이 같은 timestamp를 공유하고 그 직후 큰 간격이 있으며, yaw comparison 쌍에는 run 중간의 동일 timestamp 2행도 있다.

| 쌍 | 시작부 동일 timestamp 행 | 직후 간격(ms) | 그 밖의 동일 timestamp |
|---|---:|---:|---|
| cold/far start | 3 | 679.054 | 없음 |
| near start | 3 | 679.030 | 없음 |
| near→far→near | 3 | 678.732 | 없음 |
| yaw comparison | 2 | 679.100 | data row 983·984 (elapsed 66.066 s) |
| chin up/down comparison | 4 | 812.224 | 없음 |
| head translation comparison | 없음 | — | 없음 |
| head-forward isolation | 2 | 678.341 | 없음 |

중복과 시작부 간격을 제외한 인접 행 간격은 7개 파일 모두 중앙값 약 66.7 ms(전체 범위 52.080–81.276 ms)였다.

- 따라서 timestamp 단독으로 모든 frame을 고유하게 식별할 수 없다. Measurement–diagnostic 행 대응은 timestamp join이 아니라 두 파일의 같은 행 순서에 의존한다.
- Diagnostic CSV의 `frame_index`(1부터 연속)와 `mediapipe_timestamp_ms`는 각 diagnostic CSV 안에서 고유했지만 measurement CSV에는 없다. Measurement CSV의 `timestamp_utc`는 각 파일 안에서 고유했지만 diagnostic CSV에는 없다. 두 파일에 공통인 고유 frame key는 없다.
- Elapsed 0은 중복된 첫 timestamp이며 elapsed에는 시작부 간격(약 0.68–0.81 s)이 포함된다. 이 문서의 안정 구간은 모두 elapsed 1 s 이후에서 시작하므로 시작부 중복 행을 포함하지 않는다. Yaw neutral 3 `[63, 69)`의 n=90에는 elapsed 66.066 s의 동일 timestamp 두 행이 각각 별도 행으로 포함된다.
- 중복 행은 제거·병합하지 않았다. 중복과 초기 불연속의 원인은 CSV만으로 확인할 수 없다.

### 2.2 안정 구간 선택

CSV에는 동작 이름이나 전환 시각 marker가 없다. 아래 안정 구간과 동작 순서는 파일명 및 2초 단위 중앙값에서 확인되는 plateau를 기준으로 **사후 선택·추정**했다. 전환 구간, 시작 settling, 종료 동작은 제외했다. 따라서 구간 중앙값은 재계산 가능하지만 각 plateau의 동작 이름은 CSV가 직접 기록한 사실이 아니다.

이 사후 구간 선택은 engineering 비교에는 사용할 수 있지만 preregistered formal protocol이나 독립적인 ground truth를 대신하지 않는다.

### 2.3 부호와 단위

- `face_matrix_pitch_deg`, `face_matrix_yaw_deg`, `face_matrix_roll_deg`: MediaPipe transformation matrix에서 산출한 camera-relative exploratory angle. 실제 해부학적 각도가 아니다.
- probe 구현상 positive pitch는 얼굴이 image-up 방향으로 향하는 회전, positive yaw는 image-right 방향으로 향하는 회전이다. 이 부호 해석은 분석 기준 Checkpoint `5960201`의 구현 기준이며, 촬영 당시 코드와의 동일성은 §1.1과 같이 미검증이다.
- `nose_forward_normalized_by_shoulder_width_3d`: shoulder midpoint보다 카메라 쪽에 있는 nose의 상대 전방 위치를 3D shoulder width로 나눈 exploratory ratio다.
- `sagittal_torso_lean_deg`: 정면 D455의 upper-body geometry로 만든 exploratory proxy이며 실제 척추각이 아니다.

## 3. 주 근거 CSV와 무결성 식별자

SHA-256은 이 문서의 수치를 어느 로컬 byte artifact에서 계산했는지 식별하기 위한 값이다. CSV를 연구 데이터 계약으로 승격하는 schema hash가 아니다.

| 실험 | CSV 경로 | 행 | 시간(s) | SHA-256 |
|---|---|---:|---:|---|
| cold/far start measurement | `data/engineering/head_orientation/eng_distance_cold_start_01.csv` | 292 | 19.895 | `08d5498148d0e2a916c10917163df51d5a8c31f9feb677e780aea26147fc8741` |
| cold/far start face diagnostic | `data/engineering/head_orientation/eng_face_cold_start_01.csv` | 292 | 19.895 | `373c7f539cfde2615e4e8ce4224b6634ac299f058417a7d7fb5e53e1268b3fc9` |
| near start measurement | `data/engineering/head_orientation/eng_distance_near_start_01.csv` | 301 | 20.495 | `5163daf19ce36bf1a80c8b604d27c28acaa7af25d400781f77049251656c15a2` |
| near start face diagnostic | `data/engineering/head_orientation/eng_face_near_start_01.csv` | 301 | 20.495 | `a204e3fc601ae636118854f0d62c1d85cf6710666fa3e52ac44e8c628879b8da` |
| near→far→near measurement | `data/engineering/head_orientation/eng_distance_near_to_far_02.csv` | 272 | 18.696 | `cae7016e9fa2827c4e110d3dd6b0bb62aedbe4c2ee31118d8f877c974f6c671d` |
| near→far→near face diagnostic | `data/engineering/head_orientation/eng_face_near_to_far_02.csv` | 272 | 18.696 | `94972f8cea410174a8ec0806f9e98fea2d7a6ee1a1d27f1d5df673bf068eddfd` |
| yaw comparison | `data/engineering/head_orientation/eng_yaw_orientation_compare_01.csv` | 1,291 | 86.549 | `f7dc890362c2ae0f011a9ddf43842fba2547c6c9f3ce5d579ca234a611ff431b` |
| yaw face diagnostic | `data/engineering/head_orientation/eng_yaw_orientation_face_diag_01.csv` | 1,291 | 86.549 | `ea51e2c0faf456f86033a340e82f624b3db61e555de51232bdffb8ab535361ad` |
| chin up/down comparison | `data/engineering/head_orientation/eng_pitch_orientation_compare_01.csv` | 1,193 | 80.077 | `402d97d4c2e68388fe3ef4effe3082d99910be4b0d35f843f59a21d82cb83a5e` |
| pitch face diagnostic | `data/engineering/head_orientation/eng_pitch_orientation_face_diag_01.csv` | 1,193 | 80.077 | `5ec166e0df4c0906275e89c08baef50de1e611fb3275736ea58364523f0194b6` |
| head translation comparison | `data/engineering/head_orientation/eng_head_translation_compare_01.csv` | 936 | 62.384 | `56261e0fc91060280e8b27ff02e508cb00a3ee3a0bec2f34eb1a3f8b8aedcaa7` |
| translation face diagnostic | `data/engineering/head_orientation/eng_head_translation_face_diag_01.csv` | 936 | 62.384 | `1877b6b7add885d62b8960f9a3d027c37c8a0fa7304e0d12687496f78cd525a6` |
| head-forward isolation 재측정 | `data/engineering/head_orientation/eng_head_forward_isolation_02.csv` | 473 | 32.037 | `495b5c218ef734caa0da3a926d5b5b0df399212e62f956d504a3b6bc532b0031` |
| isolation face diagnostic | `data/engineering/head_orientation/eng_head_forward_isolation_face_02.csv` | 473 | 32.037 | `0056b902ea0d096c29923ac5297c5b250490567f078ebf38137d1cfc1a6434ff` |

**`_02` take 사용 경위:** near→far→near(§4)와 head-forward isolation(§8)은 `_02` suffix 파일을 분석 근거로 사용했다. 문서화 시점에 `data/engineering/head_orientation/`과 사용자 홈 디렉터리(최대 깊이 8, 임시 폴더 제외)를 파일명 패턴 `*near_to_far*`, `*forward_isolation*`으로 검색했지만 위 표의 `_02` 파일 외에 대응하는 `_01` 파일(`eng_distance_near_to_far_01.csv`, `eng_face_near_to_far_01.csv`, `eng_head_forward_isolation_01.csv`, `eng_head_forward_isolation_face_01.csv`)은 확인되지 않았다. 저장소 추적 파일에도 해당 take에 대한 기록이 없다. 따라서 `_01` take가 존재했는지, 존재했다면 왜 분석에서 빠졌는지, `_02`가 어떤 경위로 선택되었는지는 **unknown**이다. 이 문서는 제외 사유를 추정하지 않는다. §8의 "재측정"은 §7 대비 조건을 바꾼 측정이라는 뜻으로만 사용하며 `_01` take의 존재를 전제하지 않는다.

## 4. Face 초기 검출: cold/far start와 near start

### 4.1 목적과 동작 순서

목적은 probe 시작 위치에 따라 FaceLandmarker matrix availability가 달라지는지, 가까운 위치에서 검출된 뒤 먼 위치로 이동할 때 availability가 유지되는지를 확인하는 것이다.

~~~text
cold/far start: 먼 위치 유지 → 종료 직전 카메라 쪽 접근
near start: 가까운 위치에서 시작 → 같은 범위 유지
near-to-far: 가까운 위치 → 먼 위치 plateau → 가까운 쪽으로 복귀
~~~

동작명은 파일명과 nose depth plateau에 근거한 추정이다. 별도 거리 기준자 또는 동작 marker는 없다.

### 4.2 전체 유효율

| run | 프레임 | 시간(s) | pose valid | matrix valid | matrix 유효율 |
|---|---:|---:|---:|---:|---:|
| cold/far start | 292 | 19.895 | 292/292 | 6/292 | 2.05% |
| near start | 301 | 20.495 | 301/301 | 300/301 | 99.67% |
| near→far→near | 272 | 18.696 | 272/272 | 272/272 | 100.00% |

### 4.3 안정 구간

| run / 구간 | elapsed `[s)` | n | nose Z 중앙값(m) | matrix valid | 관찰 |
|---|---:|---:|---:|---:|---|
| cold/far start / far | `[1, 17)` | 240 | 1.291 | 0/240 | pose와 nose depth는 있었지만 face matrix는 없었음 |
| cold/far start / final approach | `[19.55, 20)` | 6 | 0.813 | 6/6 | 종료 직전 가까워진 6개 frame에서 matrix가 나타남 |
| near start / stable | `[2, 18)` | 240 | 0.882 | 240/240 | 안정 구간 전부 matrix valid |
| near→far→near / initial near | `[1, 3)` | 30 | 0.704 | 30/30 | matrix valid |
| near→far→near / far plateau | `[6, 13)` | 104 | 1.321 | 104/104 | initial near 대비 nose Z `+0.617 m`, matrix 유지 |
| near→far→near / return | `[17, 18.5)` | 23 | 0.908 | 23/23 | matrix 유지; 최초 near와 동일 거리 복귀는 아님 |

### 4.4 해석

**실제 관찰:** 이 3개 run에서는 먼 위치에서 cold start한 경우 far 안정 구간의 face matrix가 0/240이었고, 가까운 위치에서 시작한 run은 거의 즉시 유효해졌다. 가까운 위치에서 matrix가 유효해진 뒤 먼 plateau로 이동한 별도 run에서는 104/104 frame이 계속 유효했다.

**분석상 추정:** 측정 순서 또는 detector의 이전 상태가 far-range availability와 관련됐을 가능성이 있다.

**검증되지 않은 가설:** MediaPipe FaceLandmarker 내부 tracking이 near acquisition 이후 far detection을 유지시켰다는 설명은 이 CSV만으로 확인할 수 없다. API 내부 상태, detector/tracker 전환, confidence 또는 독립 반복이 기록되지 않았기 때문이다. `cold`와 `tracked` 조건도 같은 run의 무작위 교차 설계가 아니다.

## 5. Yaw orientation 비교

### 5.1 목적과 동작 순서

목적은 face matrix yaw가 좌우 방향 변화에 방향성 있게 반응하는지, 같은 구간에서 pitch/roll 및 head lateral position이 얼마나 함께 변하는지 확인하는 것이다.

주 비교 CSV는 1,291 frames / 86.549 s이며 measurement와 diagnostic 모두 matrix valid가 1,291/1,291 (100.00%)였다.

~~~text
neutral → positive-yaw → negative-yaw → neutral
→ positive-yaw 반복 → neutral → negative-yaw 반복 → neutral
~~~

`positive/negative`는 probe의 camera-relative 부호다. 실제 참가자 기준 left/right 명칭은 CSV에 기록되지 않아 사용하지 않는다. `[12, 30)`에는 명확한 회전 plateau로 분류하지 않은 준비·중간 상태가 있어 주 비교에서 제외했다.

### 5.2 안정 구간 중앙값

| 구간 | elapsed `[s)` | n | matrix yaw(°) | 기준 대비 Δyaw(°) | matrix pitch(°) | matrix roll(°) | nose dx / shoulder |
|---|---:|---:|---:|---:|---:|---:|---:|
| neutral 1 | `[4, 12)` | 120 | 0.282 | 기준 | -8.131 | 1.561 | -0.052 |
| positive-yaw 1 | `[30, 35)` | 75 | 26.061 | +25.779 vs neutral 1 | -5.199 | 3.747 | 0.117 |
| negative-yaw 1 | `[38, 43)` | 75 | -39.233 | -39.515 vs neutral 1 | -7.208 | -1.489 | -0.347 |
| neutral 2 | `[46, 51)` | 75 | -4.528 | 기준 | -8.898 | 1.979 | -0.088 |
| positive-yaw 2 | `[54, 59)` | 75 | 24.356 | +28.885 vs neutral 2 | -7.570 | 3.494 | 0.113 |
| neutral 3 | `[63, 69)` | 90 | -2.590 | 기준 | -9.032 | 1.210 | -0.071 |
| negative-yaw 2 | `[71, 75)` | 60 | -33.449 | -30.860 vs neutral 3 | -8.153 | -1.948 | -0.307 |
| neutral 4 | `[78, 83)` | 75 | -5.907 | return | -9.395 | 0.705 | -0.098 |

### 5.3 해석

**실제 관찰:** 두 positive-yaw plateau는 각 preceding neutral보다 `+25.779°`, `+28.885°`, 두 negative-yaw plateau는 `-39.515°`, `-30.860°` 변했다. matrix yaw 부호와 nose lateral ratio도 같은 방향으로 변했다. 모든 주 안정 구간에서 matrix는 100% 유효했다.

**분석상 추정:** 이 run에서는 matrix yaw가 좌우 머리 방향을 구분하는 engineering signal로 동작했다. 다만 neutral 중앙값이 `0.282°`에서 `-5.907°` 범위로 이동했고 pitch/roll도 함께 변했으므로 완전한 단일축 회전이나 zero-calibrated absolute angle로 해석하지 않는다.

**축 간 동반 변화(Yaw→Pitch, Yaw→Roll):** §5.2 표의 각 yaw plateau를 같은 preceding neutral과 비교하면 matrix pitch 변화는 `+2.931°`, `+0.923°`, `+1.329°`, `+0.880°`로 같은 구간의 |Δyaw| `25.779°`~`39.515°`보다 훨씬 작았다. 반면 matrix roll도 positive-yaw 1·2에서 `+2.186°`, `+1.515°`, negative-yaw 1·2에서 `-3.049°`, `-3.158°` 변했다. Roll 변화 크기(`1.515°`~`3.158°`)는 같은 구간 pitch 변화 크기(`0.880°`~`2.931°`)와 같은 자릿수였고 negative-yaw 두 plateau에서는 pitch 변화보다 컸으며, 이 run의 네 plateau에서는 부호가 yaw 방향을 따랐다. 따라서 이 run에서 yaw 동작 중 matrix pitch 변화가 Δyaw에 비해 작았다는 관찰(Yaw→Pitch 간섭이 작음)은 유지하지만, yaw/pitch/roll 회전축 전체가 서로 독립적이라고 주장하지 않는다. Roll 변화가 실제 머리 기울임에서 왔는지, matrix에서 Euler angle을 분해하는 과정의 축 간 결합에서 왔는지는 ground truth 없이 구분할 수 없다.

**확정 불가:** 실제 회전각과의 정확도, bias, repeatability tolerance, 해부학적 yaw, 사람/거리/조명 일반화는 ground truth와 반복 설계가 없어 확정할 수 없다.

## 6. Chin up/down orientation 비교

### 6.1 목적과 동작 순서

목적은 matrix pitch와 기존 chin/ear 기반 `exploratory_head_pitch_deg`가 턱을 위·아래로 움직인 구간에서 같은 방향의 변화를 보이는지 비교하는 것이다.

주 비교 CSV는 1,193 frames / 80.077 s이며 measurement와 diagnostic 모두 matrix valid가 1,193/1,193 (100.00%)였다.

~~~text
neutral → chin up → neutral → chin down → neutral
~~~

### 6.2 안정 구간 중앙값

| 구간 | elapsed `[s)` | n | matrix pitch(°) | 기준 대비 Δ(°) | legacy exploratory pitch(°) | 기준 대비 Δ(°) | matrix yaw(°) | torso lean(°) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| neutral before up | `[24, 32)` | 120 | -6.782 | 기준 | -70.588 | 기준 | 0.878 | -16.458 |
| chin up | `[36, 43)` | 105 | 20.307 | +27.089 | -37.674 | +32.913 | 0.421 | -16.799 |
| neutral before down | `[48, 55)` | 105 | -11.648 | 기준 | -75.448 | 기준 | 2.583 | -16.076 |
| chin down | `[58, 65)` | 105 | -30.971 | -19.323 | -103.605 | -28.158 | 2.122 | -15.903 |
| neutral return | `[69, 76)` | 105 | -5.631 | return | -64.864 | return | 0.697 | -16.718 |

### 6.3 해석

**실제 관찰:** chin-up 구간에서 matrix pitch와 legacy exploratory pitch는 각각 `+27.089°`, `+32.913°` 증가했고, chin-down 구간에서는 각각 `-19.323°`, `-28.158°` 감소했다. torso lean 중앙값 변화는 각 기준 대비 `-0.341°`, `+0.173°`였다.

**분석상 추정:** 두 pitch 표현은 이 한 run에서 턱 상하 동작의 방향을 일관되게 반영했다. Matrix 값은 legacy 값보다 neutral offset이 작았지만, 이것은 정확도가 더 높다는 증거가 아니다.

**확정 불가:** 실제 각도 오차, cervical anatomical pitch, 측정 선형성, 축 간 cross-talk, 장거리 안정성 및 개인별 neutral calibration 불필요성은 확정할 수 없다. Neutral 자체가 run 안에서 `-11.648°`에서 `-5.631°`까지 달라졌다.

## 7. Head translation 비교

### 7.1 목적과 동작 순서

목적은 머리의 앞/뒤 위치 변화에서 relative head-forward metric이 변하고 face orientation matrix는 상대적으로 얼마나 유지되는지 확인하는 것이다.

주 비교 CSV는 936 frames / 62.384 s이며 measurement와 diagnostic 모두 matrix valid가 936/936 (100.00%)였다.

~~~text
neutral → head-forward translation → neutral
→ head-backward translation → neutral
~~~

### 7.2 안정 구간 중앙값

| 구간 | elapsed `[s)` | n | nose forward / 3D shoulder | ear-mid forward / 3D shoulder | matrix pitch(°) | matrix yaw(°) | torso lean(°) | shoulder Z(m) | nose Z(m) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| neutral before forward | `[14, 23)` | 135 | 0.309 | 0.201 | -5.698 | 1.293 | -14.574 | 1.355 | 1.233 |
| head-forward translation | `[26, 33)` | 105 | 0.481 | 0.397 | -8.355 | 1.489 | -9.962 | 1.317 | 1.128 |
| neutral before backward | `[36, 41)` | 75 | 0.303 | 0.192 | -8.494 | 2.258 | -14.137 | 1.358 | 1.240 |
| head-backward translation | `[44, 51)` | 105 | 0.222 | 0.120 | -7.881 | 3.699 | -14.055 | 1.344 | 1.258 |
| neutral return | `[54, 59)` | 75 | 0.323 | 0.230 | -9.465 | 2.578 | -13.180 | 1.350 | 1.222 |

Forward condition과 직전 neutral의 변화량:

~~~text
nose forward / 3D shoulder   +0.172
ear-mid forward / shoulder   +0.196
matrix pitch                 -2.658°
matrix yaw                   +0.195°
torso lean                   +4.611°
shoulder Z                   -0.038 m
nose Z                       -0.105 m
~~~

Backward condition과 직전 neutral의 변화량:

~~~text
nose forward / 3D shoulder   -0.081
ear-mid forward / shoulder   -0.072
matrix pitch                 +0.612°
matrix yaw                   +1.441°
torso lean                   +0.081°
shoulder Z                   -0.014 m
nose Z                       +0.018 m
~~~

### 7.3 해석

**실제 관찰:** relative head-forward metric은 forward 구간에서 증가하고 backward 구간에서 감소했다. 그러나 forward 구간에는 shoulder Z `-38 mm`와 torso lean `+4.611°`가 함께 변했다.

**분석상 추정:** relative head-forward metric은 이 run에서 앞/뒤 위치 변화에 민감했지만, 최초 forward 비교는 head-only translation을 충분히 격리하지 못했다. 이것이 §8 재측정의 근거다.

**확정 불가:** 이 run은 Translation/Pitch 독립성 또는 head/trunk 완전 분리를 증명하지 않는다. Forward 구간의 matrix pitch도 `-2.658°` 변했고 몸통·어깨 동반 이동이 있었다. 이 `-2.658°`는 직전 neutral 기준 값이며, 다른 neutral 기준에서는 크기와 부호가 달라진다(§8.4).

## 8. Head-forward isolation 재측정

### 8.1 목적과 동작 순서

목적은 §7의 동반 torso/shoulder 이동을 줄인 조건에서 head-forward metric, nose depth, shoulder depth, torso proxy와 matrix orientation을 다시 비교하는 것이다.

재측정 CSV는 473 frames / 32.037 s이며 measurement와 diagnostic 모두 matrix valid가 473/473 (100.00%)였다.

~~~text
초기 거리 settling → neutral → head forward → neutral return
~~~

### 8.2 안정 구간 중앙값

| 구간 | elapsed `[s)` | n | nose forward / 3D shoulder | ear-mid forward / 3D shoulder | matrix pitch(°) | matrix yaw(°) | torso lean(°) | shoulder Z(m) | nose Z(m) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| neutral before | `[5, 13)` | 120 | 0.275 | 0.178 | -7.596 | 1.313 | -17.113 | 1.337 | 1.231 |
| head forward | `[16, 21)` | 75 | 0.388 | 0.300 | -10.090 | 0.478 | -16.394 | 1.336 | 1.182 |
| neutral return | `[23, 30)` | 105 | 0.268 | 0.172 | -10.665 | 1.428 | -17.784 | 1.348 | 1.243 |

Head-forward condition과 직전 neutral의 변화량:

~~~text
nose forward / 3D shoulder   +0.113
ear-mid forward / shoulder   +0.123
matrix pitch                 -2.494°
matrix yaw                   -0.835°
torso lean                   +0.719°
shoulder Z                   -0.001 m  (계산값 -0.00125 m)
nose Z                       -0.049 m
~~~

Neutral return과 최초 neutral의 차이:

~~~text
nose forward / 3D shoulder   -0.007
shoulder Z                   +0.011 m
nose Z                       +0.012 m
matrix pitch                 -3.069°
torso lean                   -0.671°
~~~

### 8.3 해석

**실제 관찰:** 재측정의 head-forward 구간에서는 nose Z가 약 `49 mm` 가까워졌고 shoulder midpoint Z 변화는 약 `1.25 mm`였다. 상대 head-forward 두 지표는 `+0.113`, `+0.123` 증가했다. 이는 §7 forward 조건의 shoulder Z 변화 `-38 mm`보다 동반 shoulder translation이 작았던 한 사례다.

**분석상 추정:** 이 재측정은 relative head-forward signal을 torso translation과 더 잘 분리한 engineering 사례다.

**확정 불가:** 완전한 Translation/Pitch 독립성을 증명하지 않는다. 같은 구간에서 matrix pitch가 `-2.494°`, torso proxy가 `+0.719°` 변했고, 단일 참가자·분석 take 1개(`_02`, 선택 경위 unknown — §3)이며 외부 motion ground truth가 없다. Neutral return의 matrix pitch도 최초 neutral과 약 `-3.069°` 달랐으며, matrix pitch 변화량은 비교 neutral 선택에 따라 부호까지 달라진다(§8.4).

### 8.4 Neutral 기준 선택에 따른 matrix pitch 변화량 민감도

§7.2와 §8.2의 변화량은 직전 neutral 기준이다. 독립 감사에서 제기된 기준 민감도를 원본 CSV로 재확인하기 위해, 같은 안정 구간 중앙값을 그대로 쓰고 비교 기준만 바꿔 matrix pitch 변화량을 다시 계산했다.

| 조건 | 직전 neutral | 이후 neutral | Δ 직전 기준(°) | Δ 이후 기준(°) | Δ 양쪽 평균 기준(°) | 이후 − 직전 neutral(°) |
|---|---|---|---:|---:|---:|---:|
| §7 head-forward translation | neutral before forward `[14, 23)` | neutral before backward `[36, 41)` | -2.658 | +0.138 | -1.260 | -2.796 |
| §7 head-backward translation | neutral before backward `[36, 41)` | neutral return `[54, 59)` | +0.612 | +1.584 | +1.098 | -0.972 |
| §8 head forward (isolation) | neutral before `[5, 13)` | neutral return `[23, 30)` | -2.494 | +0.575 | -0.960 | -3.069 |

**실제 관찰:** 두 forward 조건의 matrix pitch 변화량은 직전 neutral 기준으로 `-2.658°`, `-2.494°`이지만 이후 neutral 기준으로는 `+0.138°`, `+0.575°`로 부호가 바뀌고, 양쪽 평균 기준으로는 `-1.260°`, `-0.960°`다. 직전과 이후 neutral 자체가 `-2.796°`, `-3.069°` 달랐기 때문이다. Backward 조건은 세 기준 모두 양수였지만 크기가 `+0.612°`~`+1.584°`로 달랐다. 직전 neutral 기준 값은 §7.2·§8.2와 같으며 기존 수치를 대체하지 않는다.

**확정 불가:** 따라서 이 두 실험의 matrix pitch 변화량은 기준에 따라 "forward 동안 약 2.5° 감소"로도, "작은 양의 변화"로도 읽힐 수 있다. Neutral 사이의 차이가 실제 머리 회전에서 왔는지, 정면 자세로 정확히 돌아오지 못한 복귀 차이인지, 시간에 따른 센서/모델 drift인지는 동작 marker나 외부 기준 없이 분리할 수 없다. 이 문서는 세 기준 중 어느 하나를 정답으로 선택하지 않으며, §7·§8의 matrix pitch 수치를 head-forward 동작 중 실제 머리 pitch 회전량의 추정치로 사용하지 않는다.

## 9. 실제 관찰, 추정, 미검증 가설의 종합 구분

### 9.1 실제 관찰된 결과

1. Cold/far-start 안정 구간에서는 pose와 nose depth가 240/240 유효했지만 face matrix는 0/240이었고, near-start 안정 구간에서는 240/240 유효했다.
2. Near에서 시작해 far plateau로 이동한 run에서는 far의 nose Z 중앙값이 `1.321 m`까지 증가했지만 matrix가 104/104 유지됐다.
3. Yaw comparison의 두 positive/negative plateau에서 matrix yaw는 neutral 대비 각 방향으로 큰 부호 변화가 반복됐다.
4. Chin up/down에서 matrix pitch와 legacy exploratory pitch는 같은 방향으로 변했다.
5. Translation comparison에서 relative head-forward metric은 forward에서 증가하고 backward에서 감소했다.
6. Isolation 재측정에서는 nose Z 약 `-49 mm` 변화와 동시에 shoulder Z 변화가 약 `-1.25 mm`였고 relative head-forward metric이 증가했다.

### 9.2 분석 과정에서 추정한 내용

1. 동작 순서와 안정 구간 이름은 파일명과 signal plateau에서 사후 추정했다.
2. Matrix yaw/pitch는 이 참가자·이 환경의 engineering run에서 head orientation에 방향성 있게 반응한 것으로 해석했다.
3. Isolation 재측정은 최초 translation comparison보다 head/trunk confounding을 줄인 사례로 해석했다.

### 9.3 아직 검증되지 않은 가설

1. Near acquisition 이후 FaceLandmarker 내부 tracking 때문에 far-range matrix가 유지된다.
2. Matrix angle이 실제 물리적·해부학적 head angle을 정확하게 측정한다.
3. Matrix orientation과 translation 또는 torso motion을 완전히 독립적으로 분리할 수 있다.
4. 참가자별 neutral/calibration 없이 같은 offset과 threshold를 모든 사람에게 일반화할 수 있다.
5. 이 engineering signal을 사용하면 정식 posture classification 성능이 개선된다.
6. Matrix yaw·pitch·roll 회전축이 서로 완전히 독립적이다(§5.3: yaw 동작 중 roll 동반 변화 관찰).

## 10. 보조 CSV 검토와 주 분석 제외 사유

### 10.1 같은 head-orientation 폴더의 초기 진단 run

다음 로컬 CSV도 header, 행 수, 시간축 및 matrix validity를 확인했다.

~~~text
eng_face_pipeline_diag_03.csv
eng_face_pipeline_yaw_left_02.csv
eng_face_pipeline_yaw_left_03.csv
eng_face_pipeline_yaw_right_02.csv
eng_matrix_chin_down_01.csv
eng_matrix_chin_up_01.csv
eng_matrix_head_backward_01.csv
eng_matrix_head_forward_01.csv
eng_matrix_neutral_01.csv
eng_matrix_neutral_diagnostic_02.csv
eng_matrix_neutral_diag_03.csv
eng_matrix_yaw_left_01.csv
eng_matrix_yaw_left_02.csv
eng_matrix_yaw_left_03.csv
eng_matrix_yaw_right_01.csv
eng_matrix_yaw_right_02.csv
~~~

초기 matrix run 다수는 matrix valid가 0%이거나 매우 낮았고, `eng_matrix_head_backward_01.csv`는 70.79%, `eng_matrix_neutral_diag_03.csv`는 82.37%였다. 따라서 이들은 pipeline troubleshooting의 역사적 engineering evidence로 유지하고, 100% valid인 후속 comparison CSV의 구간 중앙값에 합치거나 결측을 보간하지 않았다.

### 10.2 저장소 루트의 이전 geometry CSV

다음 로컬·untracked 파일군도 schema와 기본 availability를 확인했다.

~~~text
eng_{neutral,head_forward,body_forward,recline,
     tilt_left,tilt_right,yaw_left,yaw_right}_{01,02,03}.csv
eng_head_pitch_smoke_01.csv
~~~

앞의 24개는 34-field 초기 geometry schema이고 `eng_head_pitch_smoke_01.csv`는 101 fields다. 모두 `face_matrix_valid` 및 matrix orientation angle column이 없어 이번 matrix-based Head Orientation 비교의 수치 근거에서는 제외했다. 원본 파일은 이동·삭제·수정하지 않았고 Git에 추가하지 않았다.

## 11. 남은 한계와 필요한 후속 검증

- 참가자 수, 반복 수, 환경·거리·조명 조건이 formal design으로 통제되지 않았다.
- CSV에 동작 marker, 실제 각도계, optical tracking 또는 독립 translation ground truth가 없다.
- 안정 구간은 결과를 본 뒤 선택했으며 사전 등록된 window가 아니다.
- 각 조건의 neutral offset과 return 값이 완전히 같지 않아 drift, 자세 재현 오차, 센서/모델 변동을 분리할 수 없다. §7·§8의 matrix pitch 변화량은 비교 neutral 선택에 따라 부호까지 달라진다(§8.4).
- CSV에 생성 코드 정체성(Git commit, dirty 상태, code hash)이 기록되지 않았고 CSV는 Checkpoint `5960201` commit 이전에 수집되어, 촬영 당시 코드와 `5960201`의 동일성을 확인할 수 없다(§1.1).
- Near→far→near와 head-forward isolation은 `_02` take만 분석했으며 `_01` take의 존재 여부와 `_02` 선택 경위는 unknown이다(§3).
- `device_timestamp_ms`에는 중복과 초기 불연속이 있어 frame 고유 key가 아니며, measurement–diagnostic 대응은 행 순서에 의존한다(§2.1).
- Face cold/near 비교는 randomized crossover나 동일 조건 반복이 아니므로 순서 효과와 내부 tracking 원인을 분리할 수 없다.
- Angle 값은 camera-relative exploratory output이며 anatomical angle 또는 임상 측정값이 아니다.
- Head-forward isolation도 pitch/torso 변화가 0이 아니므로 완전한 독립성 증거가 아니다.
- Engineering 결과만으로 개인별 calibration이 불필요하다고 일반화할 수 없다. F1/F2의 zero-personal-calibration 연구 요구와 실제 다인 validation은 별개다.
- 이 자료는 Patch 8 formal execution, formal research collection, classifier accuracy, sensitivity/specificity 또는 논문용 성능 검증을 완료하지 않는다.

후속 formal 연구가 필요하다면 동작 marker, 사전 고정 window, 반복 take/참가자, 독립 물리 기준, 조건 순서 균형화 및 미리 고정한 acceptance metric이 필요하다. 그 설계는 기존 OPEN/DEFERRED 연구 결정 및 Patch 8 authority를 변경하지 않는 별도 결정으로 수행해야 한다.

## 12. 재현 체크리스트

1. 분석·재현 기준 Checkpoint `5960201fa8aa13ede9974ad1f0c691832ea47bbb`를 column 의미 해석 기준으로 사용한다. 이 Checkpoint가 CSV 생성 코드라는 뜻은 아니다(§1.1).
2. §3의 경로와 SHA-256이 일치하는지 확인한다.
3. CSV는 UTF-8로 읽고 header를 제외한 row 수를 센다.
4. 첫 `device_timestamp_ms`를 elapsed 0으로 둔다.
5. §2.1의 half-open window와 finite-only rule을 적용한다.
6. 각 column의 중앙값을 계산하고 §2.1의 기준 구간을 빼 변화량을 계산한다.
7. Measurement/diagnostic 쌍의 전체 `device_timestamp_ms` sequence가 행 순서대로 동일한지 확인한다. Timestamp는 중복이 있어 고유 key가 아니므로 timestamp join으로 행을 대응시키지 않는다(§2.1).
8. 결측을 0 또는 보간값으로 대체하지 않는다.
9. 결과를 engineering evidence로만 해석하고 canonical 연구 artifact 또는 formal result로 승격하지 않는다.
