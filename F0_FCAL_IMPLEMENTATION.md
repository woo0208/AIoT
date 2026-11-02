# 5단계 F0 / F_cal 독립 계산 모듈

이번 산출물은 `f0_fcal_features.py`, `test_f0_fcal_features.py`, 이 보고서의 새 파일 3개다. 정식 6-class 평가를 위한 계산 준비이며 실행기 연결, 실제 CSV/녹화 읽기, 학습, 성능 평가는 수행하지 않았다. 기존 파일·5-B·H5/H9/H9−F9·RF/LR·보호된 소스/스냅샷은 수정하지 않았다. 기존 작업 트리의 변경도 유지했다. Commit/push 없음.

## 입력과 출력

- `Segment`는 참가자, recording/run/step 식별자, 사전 계획의 참가자 내 고유 `order`, 자세 라벨, 해당 안정 구간 프레임들을 받는다. 회차/재촬영 선택은 호출자 책임이며 여러 run/recording을 한 구간에 합치지 않는다. 프레임에 식별자가 있으면 구간과 일치해야 한다.
- 입력 열은 기존 `analyze_d455.py`의 `face_x`, `face_y`, `lsh_x/y`, `rsh_x/y`, `face_area_px`다. 얼굴 중심은 검출 bbox의 `(x+w/2, y+h/2)`, 면적은 `w*h`여야 한다. 머리 랜드마크 평균, oval, 실제 면적, 깊이로 대체하지 않는다. bbox가 없는 H9 CSV에서 특징을 추정하지 않는다.
- 순서는 `(xc, yc, theta1_deg, theta2_deg, theta3_deg, A)`. 기존 RF의 열 순서와 다르므로 향후 명시적인 매핑이 필요하다.
- 6-class 라벨은 저장소 이름 `upright`, `forward_head`, `body_forward`, `lean_back`, `lean_left`, `lean_right`를 보존한다. `body_forward`가 몸 전체 앞으로/lean_forward에 대응한다. 이 모듈은 클래스 병합·라벨 예측을 하지 않는다.

## 식과 불명확한 규칙의 구현 선택

근거는 `analysis/teammate_feature_ablation_20261029/f0_h5_comparison.md`의 원문 식 (6)~(9) 전사와 U1~U7, 기존 `analyze_d455.py`, `rf_experiment.py`다. 다음은 원문에서 모두 확정된 규칙이라는 주장이 아니라, 검토 가능한 이번 구현의 명시적 선택이다.

| 항목 | 이번 구현 |
|---|---|
| 좌표 | 원 영상 픽셀, 오른쪽 +x/아래쪽 +y. 얼굴과 양 어깨는 동일 해상도여야 한다. 자동 crop/resize 없음 |
| 좌우 | 참가자 해부학적 왼쪽=`lsh`, 오른쪽=`rsh`; 식 (6)/(7)을 우선해 θ2=왼쪽, θ3=오른쪽 |
| 식 (6) | `theta2 = degrees(atan((xc-xl)/(yc-yl)))` |
| 식 (7) | `theta3 = degrees(atan((xc-xr)/(yc-yr)))` |
| 식 (8) | `theta1 = theta2 + theta3`; 절댓값/원형 wrapping 없음 |
| 각도 범위 | 단순 arctan의 주값 −90°~90°. 분모 0은 ±90°를 선택하지 않고 결측. 두 점 일치도 결측 |
| 식 (9) | `A = bbox_area / participant_reference_bbox_area`; F0도 정상 참조를 쓰므로 calibration-free가 아님 |
| 구간 대표값 | 기존 `analyze_d455.med`를 직접 재사용. 유효한 원시 입력 열별 중앙값 후 각도/비율 계산. 프레임 각도의 중앙값과는 다를 수 있음 |
| F_cal | 위 동일 기본 특징 5개에서 참조 구간의 기본 특징 5개를 각각 차감. A는 동일 면적 비율 유지, `A-1`로 바꾸지 않음 |

열별 집계는 서로 다른 프레임 부분집합을 사용할 수 있다. 최소 프레임 수/coverage threshold, 공동 유효 support, trim/window를 새로 도입하지 않았다. `theta1`은 집계 좌표에서 계산한 `theta2+theta3` 관계를 유지한다.

## 사전 지정 참조와 누출 방지

1. 데이터 선택/시간 순서를 사전에 고정한 `Segment` 목록을 준비한다. `order`는 입력 나열 순서나 품질/예측 순위가 아니라 참가자별 실제 계획 순서여야 한다.
2. `first_upright_references(segments)`는 메타데이터만으로 첫 정상 구간의 정확한 `(analysis_run_id, recording_id, step)`를 제안한다. 이를 평가 전에 검토·고정하여 `fit_calibrations(segments, reference_keys)`에 명시적으로 전달한다. 누락/추가 참가자, 이후 정상 구간 지정은 오류다.
3. `fit_calibrations`는 지정한 참조 구간의 측정만 집계한다. 다른 정상/검증 구간의 측정이나 예측값을 읽어서 보정하지 않는다. 참조가 결측이어도 다음 정상 구간으로 대체하지 않는다. 이후 회차도 같은 참가자 참조를 유지한다.
4. `segment_features`는 고정된 보정 객체를 받아 결과를 만든다. 참조 구간은 F0/F_cal 모두 기본 `excluded_from_evaluation=True`; 나머지 구간은 보존한다. 제외 해제는 명시적 `exclude_references=False`로만 가능하다. 실제 표본 필터링은 향후 실행기가 이 플래그를 적용해야 한다.

검증 참가자의 **사전 지정 calibration 구간** 사용은 F0의 A 및 F_cal 비교군의 허용 입력이다. 그 참가자의 평가 구간에서 baseline을 재계산하지 않는다. 이 API는 호출자가 거짓 acquisition order나 변조한 calibration 객체를 전달하는 것까지 증명하지 못하며, 향후 실행기에 사전 고정 provenance 연결이 필요하다.

## 결측 처리

빈 값, 파싱 불가, boolean 숫자 입력, NaN/Inf, 0 이하 bbox 면적은 `None`. 명시적 `face_detected=false`, `lsh_valid=false`, `rsh_valid=false`는 해당 관측을 비운다. 플래그가 없거나 unknown이면 숫자 관측만 사용하며 깊이 유효성은 요구하지 않는다. 보간·0 채움·자동 표본 삭제 없음. 빈 구간도 결과를 보존한다.

한 어깨 결측이면 해당 θ와 θ1만 결측이고 다른 θ는 유지한다. 참조 면적 결측이면 A 결측, 참조 기본 특징 결측이면 해당 F_cal만 결측이다. `Features.missing(mode)`로 확인한다. 참조 제외와 결측은 별도 상태다. 모델 입력으로 쓰기 전 결측 표본 처리 정책은 후속 평가 설계에서 명시해야 한다.

## legacy relative와 차이

| 항목 | 기존 구현 | 새 모듈 |
|---|---|---|
| 각도 | `analyze_d455.angle_from_down`, RF `feats_from_points`: `atan2(abs(dx), shoulder_y-face_y)` | 식 (6)/(7)의 부호 있는 `atan(dx/dy)` |
| 좌우 이름 | analyze: θ3=사람 왼쪽, θ2=사람 오른쪽; RF는 화면 좌우 | θ2=사람 왼쪽, θ3=사람 오른쪽 |
| 면적 | analyze의 A_ratio는 bbox; RF `load_ours`는 oval | bbox만 사용 |
| 면적 참조 | analyze summary: 같은 녹화/회차 직전 upright; RF load_ours: 입력 녹화 첫 upright | 참가자별 사전 지정 첫 upright 하나 |
| 좌표 | RF load_ours: 1280×720을 중앙 crop 후 640×480 환산 | 입력 영상 픽셀 유지 |
| relative 참조 | RF transform: 전달된 그룹/참조 마스크에서 기본 특징 평균; 참조 없으면 원래 값 유지 | 고정 참조 구간 원시 입력 중앙값에서 특징 계산; 결측은 유지 |
| 제외 | 기존 RF relative 경로는 ref_mask를 받아 별도 nonref 지표도 계산 | 두 특징군에 동일한 참조 제외 플래그 기본 적용; 평가 지표는 계산하지 않음 |

기존 relative를 이름만 바꾼 구현이 아니며 기존 수치와 일치한다고 주장하지 않는다. 중앙값 원시 입력 집계 방식과 A를 유지한 5개 특징 차감 구조는 재사용했다.

## 검증과 남은 미확정 사항

`python -B -m unittest -v test_f0_fcal_features`: **11 tests PASS**. 모두 합성 입력으로 식/부호/좌우/면적, 상대 차감, 6-class 라벨, 제외 플래그, 고정 참조, 참가자 격리, 원시 중앙값, 결측·유효성·식별 오류를 검증한다. 모델을 학습하거나 연구 정확도를 산출하지 않았다.

원문의 U1~U7은 해결된 연구 결정으로 바꾸지 않았다. 원문 모델/다중 얼굴 선택·해상도·Ac 산출·각도 해석·구간 집계의 완전한 재현 여부는 미확정이다. 이번 명시적 구현 선택의 정식 평가 채택, 공통 표본 조건, 해상도 정합, 참조 지정 provenance, 결측 표본 정책은 실행기 연결 전에 확정해야 한다. 원 논문 5-class를 6-class로 확장한 비교이며 원 논문 실험의 동일 재현은 아니다. Canonical Decision Log/Schema와 OPEN/DEFERRED 상태를 수정하지 않았다.
