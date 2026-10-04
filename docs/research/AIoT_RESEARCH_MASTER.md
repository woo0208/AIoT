# AIoT Research Master

- 문서 버전: `v1.6`
- 기준일: `2026-10-04`
- 상태: **CURRENT / Living Document**
- 권장 위치: `docs/research/AIoT_RESEARCH_MASTER.md`
- 역할: **현재 연구 방향·범위·용어·로드맵의 Single Source of Truth**
- 관련 문서:
  - `RESEARCH_DATA_SCHEMA.md` — 데이터 계약. Patch 4 exact frame contract는 `DATA-003`에 따라 `frames-schema/1.0.0`으로 frozen되었고 commit `110cce6`에서 구현 완료. 그 밖의 future schema는 해당 Decision Log status를 확인
  - `docs/research/RESEARCH_DECISION_LOG.md` — 의사결정 이력
  - `docs/history/*` — 과거 상태·소급 복원
  - `docs/foundation/*` — Foundation 변경 기록
  - 향후 `docs/experiments/EXPERIMENT_PROTOCOL.md` — 실제 실험 절차

---

# 0. 이 문서의 역할

이 문서는 과거 개발 이력을 다시 설명하는 문서가 아니다.

질문:

> **“2026-10-04 현재 이 연구는 무엇을 연구하고 있으며, 무엇이 확정되어 있고, 무엇이 아직 미확정인가?”**

에 답하는 문서다.

문서별 권위 범위는 다음과 같이 나눈다.

| 종류 | 권위 범위 |
|---|---|
| 실제 Git/source/test | 현재 구현 사실 |
| `AIoT_RESEARCH_MASTER.md` | 현재 연구 목적·역할·운영 로드맵 |
| `RESEARCH_DATA_SCHEMA.md` | 구현된 데이터/provenance 계약과 future 설계안을 함께 담은 schema 문서. 구현 사실은 Git/source/test가 우선하며, Patch 4 exact frame contract는 `DATA-003`에 따라 `frames-schema/1.0.0`으로 frozen되었고 commit `110cce6`에서 구현 완료 |
| `RESEARCH_DECISION_LOG.md` | 왜 현재 결론에 도달했는지에 대한 의사결정 이력 |
| History/Foundation records | 과거 상태와 각 변경의 근거 |
| Experiment Protocol | formal/external 실험 실행 절차 |

충돌 시 임의로 하나를 선택하지 않는다.

```text
구현 사실 충돌
→ Git/source/test 우선

연구 역할·현재 방향 충돌
→ Research Master 확인

데이터 형식 충돌
→ RESEARCH_DATA_SCHEMA 확인
→ Patch 4 exact frame contract이면 `DATA-003` + Schema §F 확인
→ 그 밖의 아직 구현되지 않은 future design이면 Decision Log status도 함께 확인

결정 이유/변경 이력 충돌
→ Decision Log + 해당 Foundation Record 확인
```

2026-10-01 Patch 4 Design Freeze에서 `DATA-003`이 `OPEN-001`을 해소했다.
따라서 `RESEARCH_DATA_SCHEMA.md` §F의 `frames-schema/1.0.0` exact 60-field contract는
**frozen-and-implemented** 상태다. Python 구현, hardening, 171-test 검증과 독립 software audit는
commit `110cce6`에서 완료됐다.

```text
legacy 31-field ordered prefix
+ Patch 4 metadata/state 17 fields
+ bilateral hip raw-observation 12 fields
= total 60 fields
```

Design Freeze 자체와 구현 완료는 별개 milestone이다. 구현 완료는 F1/F2 feature formula 확정,
formal collection 승인, 실제 D455 validation 완료 또는 새 capture acceptance gate 도입을 의미하지 않는다.

2026-10-04 `PROV-004`에서 Patch 4.5 MediaPipe Model Artifact Lock contract를 Design Freeze했고,
commit `aef7f34`에서 구현을 완료했다. 기존 171 tests와 신규 Patch 4.5 tests 33개가 모두 유지되어
총 `204 tests PASS`를 확인했으며, 독립 Claude Opus READ-ONLY audit 결과는
`PASS WITH MINOR FINDINGS / ACCEPT WITH MINOR NOTES`였다. BLOCKER/IMPORTANT finding은 없고,
Foundation Record `docs/foundation/PATCH_04_5_mediapipe_model_artifact_lock.md`를 작성했다.
Patch 4.5 documentation closure는 commit `26daf50`에서 완료됐고,
closure status-sync는 commit `9e657ac`, main merge는 commit `15128ff`에서 완료됐다.
Patch 4.5는 현재 main에 반영된 완료 상태다.

2026-10-04 `PROV-005`에서 Patch 5 End-to-End Lineage Hardening contract를 Design Freeze했고,
Design Freeze commit `d4dc23f` 이후 implementation commit `dd0464e`에서 구현을 완료했다.
pre-implementation baseline `204 tests PASS`, 신규 Patch 5 targeted tests `48 PASS`,
최종 전체 `252 tests PASS`를 확인했다.
독립 Claude Opus READ-ONLY audit 결과는 `PASS WITH MINOR FINDINGS`,
`BLOCKER 0 / IMPORTANT 0 / MINOR 6`, implementation commit recommendation `YES`였다.
6개 MINOR는 `docs/foundation/PATCH_05_end_to_end_lineage_hardening.md`의 closure disposition에 따라
Patch 5 contract blocker가 아닌 residual/limitation/note로 수용한다.
Patch 5 documentation closure 이후 merge commit `ae86d58`에서 `main` 통합을 완료했고,
merge 직후 전체 `252 tests PASS`를 재확인했다. 현재 다음 required Foundation scope는 Patch 6 Selection Manifest / Recapture Inclusion이다.

이미 구현·검증된 Patch 1~4.5 provenance/schema/model-lock 동작은 그대로 유지한다.
Patch 5는 `summary-schema/1.0.0`, `rf-sample-lineage/1.0.0`,
`rf-experiment-provenance/1.0.0`을 구현했지만 Patch 6 selection policy를 선행 구현하지 않았다.
그 밖의 future/unimplemented schema section은 현재 구현 완료를 뜻하지 않으며,
각 설계의 confirmed/open status는 해당 Decision Log entry를 따른다.

---

# 1. 현재 프로젝트 상태

## 1.1 Repository 기준

본 v1.6 / Patch 5 main-integration alignment의 **canonical baseline**:

```text
current canonical branch: main
Patch 4.5 main integration baseline: 15128ff
Patch 4 main merge: d923b23 = merge: complete Patch 4 frame schema foundation
Patch 4 status sync: 872dfe6
Patch 4 documentation closure: 144a264
Patch 4 implementation: 110cce6
Patch 4 state: complete / 171 tests PASS / independent audits PASS

Patch 4.5 Design Freeze: 6b69255
Patch 4.5 implementation: aef7f34
Patch 4.5 software verification: 204 tests PASS
Patch 4.5 independent audit: PASS WITH MINOR FINDINGS / ACCEPT WITH MINOR NOTES
Patch 4.5 BLOCKER / IMPORTANT: none
Patch 4.5 Foundation Record: created
Patch 4.5 documentation closure: DONE — 26daf50
Patch 4.5 closure status sync: DONE — 9e657ac
Patch 4.5 main merge: DONE — 15128ff = merge: complete Patch 4.5 model artifact lock foundation
Patch 4.5 state: COMPLETE / main integrated / 204 tests PASS

Patch 5 branch base: 0f8bb81 = docs: sync Patch 4.5 main merge status
Patch 5 Design Freeze: d4dc23f
Patch 5 implementation: dd0464e
Patch 5 pre-implementation baseline: 204 tests PASS
Patch 5 targeted tests: 48 PASS
Patch 5 final software verification: 252 tests PASS
Patch 5 independent audit: PASS WITH MINOR FINDINGS
Patch 5 BLOCKER / IMPORTANT / MINOR: 0 / 0 / 6
Patch 5 implementation commit recommendation: YES
Patch 5 Foundation Record: docs/foundation/PATCH_05_end_to_end_lineage_hardening.md
Patch 5 documentation closure: DONE — 0ed2954
Patch 5 main merge: DONE — ae86d58 = merge: complete Patch 5 end-to-end lineage hardening foundation
Patch 5 post-merge verification: 252 tests PASS
Patch 5 origin/main sync: DONE — ae86d5875c8fe3200b3b2c1dd26c48256e01105f
Patch 5 state: COMPLETE / MAIN-INTEGRATED / 252 tests PASS
```

`110cce6`은 Patch 4 software implementation의 기준점이고,
`144a264`는 Patch 4 documentation/authority closure, `872dfe6`은 Patch 4 status sync,
`d923b23`은 Patch 4를 `main`에 반영한 merge 기준점이다.

Patch 4.5는 `d923b23`에서 시작한 feature branch에서 `PROV-004`를 Design Freeze했고,
commit `6b69255`에 Design Freeze 문서를 고정한 뒤 commit `aef7f34`에서 구현했다.
documentation closure는 commit `26daf50`, closure status-sync는 commit `9e657ac`에서 완료했고,
commit `15128ff`에서 `main`에 최종 병합했다.
현재 Patch 4.5의 canonical main integration 기준점은 `15128ff`이다.

Research document canonicalization의 이전 기준점은 commit `f97530c`이며,
History/Foundation canonicalization 기준점 `474733c`는 해당 기록의 역사적 provenance로 유지한다.

Foundation 구현 상태:

```text
Prelude   algorithm / evaluation / capture hardening   완료
Patch 1   capture recording provenance                 완료
Patch 2   forward gate evidence                        완료
Patch 3   analysis provenance                          완료
Patch 4   canonical fixed frame schema + hip           구현·hardening·software audit·main merge 완료
Patch 4.5 MediaPipe model artifact lock                구현·204-test 검증·독립 audit·Foundation Record·documentation closure·main merge 완료
Patch 5   end-to-end lineage hardening                 구현·252-test 검증·독립 audit·Foundation Record·documentation closure·main merge·post-merge 252-test 검증 완료
```

Patch 3 canonical record에는 commit `1cdc528` 계열에서 `146 tests PASS`가 기록되어 있고,
그 이후 review baseline `474733c`까지 Python source 변경이 없음을 확인했다.
본 canonicalization 검토에서는 read-only 원칙 때문에 tests를 재실행하지 않는 독립 audit도 수행했다.

Patch 4는 commit `110cce6`에서 `frames-schema/1.0.0`을 구현했고,
post-hardening 기준 `171 tests PASS`, 초기 독립 READ-ONLY audit PASS,
targeted READ-ONLY re-audit PASS를 완료했다.

Patch 4.5는 commit `aef7f34`에서 `mediapipe-model-lock/1.0.0`을 구현했다.
기존 171 tests와 신규 33 tests를 합한 `204 tests PASS`를 확인했고,
독립 Claude Opus READ-ONLY audit에서도 `204 tests PASS`,
`PASS WITH MINOR FINDINGS / ACCEPT WITH MINOR NOTES`를 받았다.
4개 MINOR는 integrity bypass 또는 PROV-004 위반이 아니며 closure blocker로 취급하지 않는다.

Patch 5는 Design Freeze commit `d4dc23f`와 `PROV-005`를 기준으로 commit `dd0464e`에서 구현했다.
`summary-schema/1.0.0` exact 52 fields, raw SHA identity collision rejection,
immutable RF input resolution, `rf-sample-lineage/1.0.0`,
`rf-experiment-provenance/1.0.0`을 구현했다.
기존 204 tests와 신규 48 tests를 합한 `252 tests PASS`를 확인했고,
독립 Claude Opus READ-ONLY audit 결과는 `PASS WITH MINOR FINDINGS`,
BLOCKER 0 / IMPORTANT 0 / MINOR 6이었다.
MINOR 6건은 canonical summary/RF lineage contract를 깨지 않는 residual/portability/dependency/test-coverage/semantic/diagnostic note로 disposition했다.
Patch 5는 Patch 6 selection manifest나 retake scientific selection을 구현하지 않았다.

Patch 8의 formal D455 hardware end-to-end validation은 아직 완료하지 않았다.
다만 2026-10-02 실제 D455로 Early Hardware Preflight를 수행했으며,
이는 non-formal engineering evidence로만 유지하고 Patch 8 또는 formal research evidence로 승격하지 않는다.

History/Foundation 기존 6개 문서는 READ-ONLY 독립 검토와 canonicalization을 완료했고,
위 baseline commit에 canonical filename으로 반영되어 있다.
해당 파일 내부에는 canonicalization 직전의 `최종 후보 v2 / Final Candidate v2` 및 pending-review 상태 문구가 역사적 snapshot으로 일부 남아 있으나,
현재 canonical status의 근거는 baseline commit `474733c`와 그 canonical filename 반영이다.

---

## 1.2 현재 단계 한 줄 요약

Patch 4 `frames-schema/1.0.0` 구현·hardening·software audit·documentation closure와 main merge까지 완료했다.

2026-10-02 실제 D455 Early Hardware Preflight를 수행했으며,
이는 engineering preflight evidence로만 유지하고 Patch 8 formal hardware validation 또는 formal research data로 사용하지 않는다.

2026-10-04 `PROV-004`에서 Patch 4.5 MediaPipe Model Artifact Lock의 Design Freeze를 완료했고,
commit `aef7f34`에서 구현했다. 기존 171 tests + 신규 33 tests = `204 tests PASS`를 확인했으며,
독립 Claude Opus READ-ONLY audit 결과는 `PASS WITH MINOR FINDINGS / ACCEPT WITH MINOR NOTES`,
BLOCKER/IMPORTANT 0건이다.

`docs/foundation/PATCH_04_5_mediapipe_model_artifact_lock.md` Foundation Record를 작성했고,
documentation closure commit `26daf50`, closure status-sync commit `9e657ac`,
branch push와 final review, main merge commit `15128ff`까지 완료했다.
main merge 후 전체 `204 tests PASS`를 다시 확인했고 `origin/main` push도 완료했다.

Patch 5는 `PROV-005` / Design Freeze commit `d4dc23f` 이후 implementation commit `dd0464e`에서 완료했다.
204 baseline + 48 targeted = `252 tests PASS`이며,
독립 READ-ONLY audit은 `PASS WITH MINOR FINDINGS`, BLOCKER/IMPORTANT 0건이다.
`docs/foundation/PATCH_05_end_to_end_lineage_hardening.md`에서 6개 MINOR의 closure disposition을 기록했다.
Patch 5 documentation closure commit `0ed2954`, main merge commit `ae86d58`, post-merge `252 tests PASS`, `origin/main` 동기화까지 완료했다.

현재 다음 required Foundation milestone은 Patch 6 Selection Manifest / Recapture Inclusion이다.

아직 F1/F2 핵심 수식을 구현하는 단계가 아니다.

---

# 2. 연구의 출발점과 현재 프레이밍

선행 연구:

**Classification Algorithm for Sitting Postures Using Weighted Random Forest**
Lee, Choi, Kim, 2025, *IET Image Processing*

초기 핵심 질문:

> 원 논문의 input weighting이 실제 Random Forest 분할을 바꾸는가?
> 그렇지 않다면 split-selection score에 feature weight를 직접 반영하면 개선되는가?

초기 연구는 분류기 개량에 초점이 컸다.

현재까지의 실험과 교수 피드백을 반영한 프레이밍은 다음과 같다.

```text
초기:
M1 input weighting
→ M2 split weighting으로 알고리즘 개량

현재:
M0 / M1 / M2 비교는 유지
+
환경·좌표계에 민감한 특징 표현 문제를 별도 연구
+
calibration-free body-relative 2D geometry(F1)
+
RGB-D 기반 3D body geometry(F2)
```

따라서 M2를 폐기하지 않는다.

그러나 현재 연구의 최종 주장을:

```text
"M2가 반드시 더 좋다"
```

로 미리 정하지 않는다.

실험 결과는 목표값이 아니라 증거다.

---

# 3. 현재 Research Questions

## RQ1 — Input weighting의 실질적 효과

> 원 논문식 input feature weighting(M1)은 동일 구현의 일반 RF(M0)와 실제로 다른 예측을 만드는가?

현재 증거는 provenance 수준을 구분한다.

```text
현재 repository synthetic tests
→ 동일 seed/조건에서 M0 == M1 구조적 sanity를 지원

원 논문 공개 데이터 / MultiPosture의 dataset-level 동일 prediction
→ historical preliminary / external observation
→ 현재 repository에는 해당 결과 artifact가 없음
```

현재 해석:

> 현재 구현 구조와 과거 예비 관찰 모두 M1과 M0의 차이가 작거나 없을 가능성을 지지하지만,
> dataset-level 결과는 현재 frozen code로 재실행되기 전까지 현재 재현 결과로 주장하지 않는다.

원 논문의 보고 결과 자체가 잘못됐다고 단정하지 않는다.

---

## RQ2 — Split weighting의 효과

> feature importance를 split-selection score에 직접 반영한 M2는 실제 split을 변경하며, 분류 성능 또는 안정성을 개선하는가?

현재 증거:

```text
split 동작 변화
→ 확인

안정적인 성능 향상
→ 현재까지 확인되지 않음
```

M2는 계속 비교 대상이다.

최종 방법의 주인공으로 사전 확정하지 않는다.

---

## RQ3 — 새 환경에서의 성능 저하 원인

> 원 논문 계열 특징이 새로운 사람·카메라·설치 환경에서 약해지는 원인은 무엇인가?

현재 안전한 표현:

> **예비 실험에서는 화면상 절대 위치 또는 좌표계/설치 조건에 민감한 특징 표현의 영향이 분류기 weighting 차이보다 크게 관찰됐다.**

다음과 같이 일반화하지 않는다.

```text
"병목은 무조건 분류기가 아니라 특징이다"
```

또한 과거 `0.40 → 0.844` 관찰은
현재 코드·정책 기준으로 재실행하기 전까지 최종 결과로 사용하지 않는다.

---

## RQ4 — Calibration-free 2D upper-body geometry

> 개인별 사전 upright calibration 없이, 현재 frame의 upper-body landmark 관계를 body-relative / skeletal geometry로 표현한 F1이 환경 변화에 더 강한 표현을 제공하는가?

상태:

```text
연구 방향 확정
정확한 수식 미확정
feature count 미확정
normalization 미확정
missing policy 미확정
```

---

## RQ5 — RGB-D / 3D geometry

> F1에 RGB-D / metric 3D upper-body geometry와 sagittal-plane candidate family를 추가한 F2가,
> 2D만으로 구분하기 어려운 head-forward relative to trunk / whole-trunk-forward / whole-body translation confounding을 추가로 설명할 수 있는가?

상태:

```text
upper-body sagittal/body-relative 3D candidate family 평가 방향 확정
head-forward / trunk-forward / whole-body translation confounder 분석 요구 확정
exact landmark set / graph / 3D feature / trunk-axis / projection 정의 미확정
F2 feature count 미확정
p > 6 rank_weights policy 미확정이며 F2 전용 문제가 아님
```

정면 D455에서 계산한 trunk geometry는 anatomical/clinical `actual spine angle`로 주장하지 않는다.

---

# 4. Model Axis

## M0 — Baseline Random Forest

- 일반 Random Forest
- 기존 Gini decrease 기반 split
- 공정 비교의 baseline

---

## M1 — Original Paper-Style Input Weighting

- feature value에 양수 weight를 적용한 뒤 RF에 입력
- 기존 연구 재현/비교 대상
- 현재 sanity check에서 M0와 동일 prediction을 보이는 현상을 유지

M1을 임의로 삭제하지 않는다.

---

## M2 — Split-Score Weighted Random Forest

현재 구현 핵심:

```text
Score
=
[(1-λ) + λ·w_j/mean(w)] × ΔGini
```

역할:

```text
기존 weighting 아이디어를 split selection에 직접 반영했을 때
실제 tree 구조 및 성능이 어떻게 달라지는지 비교
```

현재 상태:

```text
split 변화: 확인
안정적 성능 향상: 미확인
```

M2의 λ나 weight 정책을 원하는 결과에 맞춰 튜닝하지 않는다.

---

# 5. Feature Axis

## 5.1 F0 — Original Baseline Feature Set

역할:

```text
원 논문 재현 및 baseline 비교
```

기존 값·전처리·평가 경로를 보존한다.

F0을 calibration-free라고 재해석하지 않는다.

---

## 5.2 F_cal — Legacy Calibration/Relative Comparison

이전 코드의 `relative` 계열 비교를 연구상 별도 분류한 것.

특징:

```text
participant / round별 upright reference 사용 가능
```

역할:

```text
비교군
ablation
기존 relative 접근의 장단점 확인
```

**최종 제안 방법의 필수 inference 단계가 아니다.**

---

## 5.3 F1 — Calibration-Free Body-Relative / Upper-Body Skeletal 2D Geometry

확정 방향:

```text
개인별 사전 정상 자세 측정 불필요
현재 frame의 신체 지점 관계 사용
body-relative
2D upper-body skeletal geometry candidate family
```

현재 핵심 원재료 방향:

```text
face/head
left shoulder
right shoulder
left hip
right hip
```

추가 research candidate raw observations:

```text
left/right elbow
left/right wrist
```

`DATA-003`에 따라 `frames-schema/1.0.0`에서는 elbow/wrist를 `exclude-and-version-later`로 freeze했다.
이는 F1/F2 model feature 채택 여부를 결정한 것이 아니며, 향후 연구상 필요성이 확인되면 explicit schema-version update로 추가한다.

미확정:

```text
정확한 feature formula
정확한 feature count
normalization
missing-data policy
derived geometry 조합
```

현재 `all / invariant / relative`를 이름만 바꿔 F1으로 취급하지 않는다.

---

## 5.4 F2 — F1 + RGB-D / 3D Body Geometry

확정 방향:

```text
F1의 calibration-free 원칙 유지
F1의 upper-body skeletal/body-relative representation을 확장
depth / RGB-D 정보를 추가
metric 3D upper-body geometry와 sagittal-plane geometry를 candidate family로 평가
head-forward relative to trunk / whole-trunk-forward / whole-body translation confounding을 분석
개인 upright reference를 숨은 필수 입력으로 사용하지 않음
```

후보 개념 예시는 다음과 같으나 **formula 확정이 아니다**.

```text
head–shoulder depth relation
shoulder–hip depth relation
trunk-axis / trunk-inclination proxy
head-to-trunk relative relation
```

미확정:

```text
exact landmark set / skeletal graph or edge structure
정확한 3D feature formula
exact sagittal coordinate/projection convention
exact trunk-axis / representative points
exact angle / ratio
feature count
normalization
depth-derived geometry
missing depth 처리
classifier inclusion / feature selection
```

정면 D455 기반 proxy를 실제 척추각(spine angle) 직접 측정으로 표현하지 않는다.

---

# 6. Calibration 정책

다음 세 개를 반드시 구분한다.

### A. Capture sequence의 upright

- 자세 sequence의 한 단계
- 현재 face-only forward gate의 reference로 사용
- 촬영 품질 관리 목적

### B. F_cal의 upright reference

- legacy relative feature 계산
- 비교/ablation 목적

### C. F1/F2 inference

- 개인별 정상 자세를 먼저 측정하도록 요구하지 않음
- 이전 upright 값 또는 개인별 정상 자세 통계를 숨은 필수 입력으로 사용하지 않음
- 이 `zero-personal-calibration` requirement는 F1/F2에 적용하며, 기존 F0/F_cal의 legacy upright/reference 동작을 calibration-free로 재해석하지 않음

따라서:

> **촬영 sequence에 upright가 존재한다는 사실과, 최종 모델이 개인 upright calibration에 의존한다는 것은 별개다.**

---

# 7. Canonical Observation 방향

## 7.1 Raw / Derived / Model Feature 분리

세 계층을 섞지 않는다.

```text
1. Canonical Raw Observations
   실제 detector/sensor에서 관측하거나 추출한 값

2. Derived Geometry
   raw 관측값으로 계산한 신체 기하

3. Model Features
   F0 / F_cal / F1 / F2에서 실제 classifier에 넣는 입력
```

예:

```text
left_hip_x_px
left_hip_y_px
left_hip_depth_m
     ↓
shoulder-hip vector / trunk geometry
     ↓
F1 또는 F2 feature
```

raw schema에 특정 연구 가설의 derived feature를 미리 박아 넣지 않는다.

Upper-body skeletal representation 역시 같은 계층 원칙을 따른다.

```text
Raw Observation
(head/face, shoulder, hip, optional elbow/wrist candidate)
        ↓
Derived Geometry
(head-relative, trunk, symmetry, arm configuration, sagittal geometry 후보)
        ↓
Selected Model Feature
(F1/F2에서 실제 채택한 subset만)
```

모든 landmark 좌표·angle·ratio를 RF에 자동 투입하지 않는다.

---

## 7.2 현재 반드시 확보하려는 body raw observations

F1/F2 연구를 위해 최소 다음 body structure를 보존한다.

```text
face/head
양쪽 shoulder
양쪽 hip
```

hip는 핵심 raw observation 후보가 아니라 **필수 방향**이다.

단:

```text
모든 frame에서 값이 non-null이어야 한다
```

는 뜻이 아니다.

관찰을 시도하고 validity/missing을 명시적으로 기록한다.

---

## 7.3 Elbow / Wrist

현재 확정된 scope:

```text
primary 5-class classifier의 필수/core feature로 자동 승격하지 않음
auxiliary upper-body / ergonomic context 후보
raw observation 저장 여부와 model feature 사용 여부를 분리
arm-up/down을 새 posture class로 자동 추가하지 않음
```

`DATA-003`에 따라 `frames-schema/1.0.0`에서는 elbow/wrist를 **exclude-and-version-later**로 freeze했다.
빈 예약 열도 두지 않으며, 향후 필요성이 확인되면 explicit frame-schema version update로 추가한다.
이 결정은 elbow/wrist가 formal 촬영에서 항상 RGB/depth coverage를 가진다는 보장이 아니며,
formal framing/coverage 위험은 `OPEN-005` / `OPEN-006`의 protocol·hardware-validation 경로에서 별도로 다룬다.

Elbow/wrist를 향후 저장하더라도 F1/F2 또는 primary classifier에 반드시 사용한다는 뜻은 아니다.

desk/keyboard 높이와 elbow/forearm 관계는 필요 시 auxiliary contextual metric으로 검토할 수 있으나,
현재 연구를 전체 workstation ergonomic assessment로 확대하지 않는다.

---

## 7.4 Face bbox vs contour/oval — Secondary Exploratory Candidate

현재 분석에는 이미 다음 관측/계산값이 존재한다.

```text
face_area_px
oval_area_px
oval_size_cm2
box_to_oval
```

따라서 rectangular face bounding box와 facial contour/oval 표현의 차이를
**secondary / exploratory analysis candidate**로 검토할 수 있다.

후보 질문:

```text
bbox가 facial contour/oval을 얼마나 거칠게 근사하는가?
resolution / pixel localization / contour representation에 따라 차이가 어떻게 변하는가?
이 차이가 F0 계열 absolute/area feature의 한계를 설명하는 데 의미가 있는가?
```

현재 확정하지 않는 것:

```text
exact area-error formula
exact evaluation metric
F1/F2 feature 포함 여부
최종 논문 채택 여부
```

이 항목은 camera calibration/known-target requirement가 아니며 core contribution으로 사전 확정하지 않는다.

---

# 8. Capture Invariants

현재 unrelated Patch에서 변경하지 않는 기본 동작:

```text
RGB:   1280×720 BGR8, 15 FPS
Depth: 848×480 Z16, 15 FPS

forward target:
0.08 ~ 0.12 m
양 경계 포함

forward validation:
face-only

generic body fallback:
일반 거리 표시/기록에는 유지 가능
forward hard gate 통과 근거로 사용 금지
```

final gate의 현재 주요 규칙:

```text
reference:
직전 hold upright

reference fallback:
부족한 직전 upright를 더 오래된 upright로 대체하지 않음

valid face:
mode == "face" and distance_m is not None

minimum valid fraction:
0.5

final window:
1.0 < t < phase_duration_s - 0.5
```

어깨 이동량 자체를 새 hard acceptance criterion으로 추가하지 않는다.

어깨/hip 움직임은 연구 관찰 대상과 촬영 acceptance criterion을 구분한다.

---

# 9. Data Roles

## 9.1 `pilot`

용도:

```text
프로토콜 개발
코드 개발
feature hypothesis 탐색
문제 발견
```

기존 P01/P02 및 기존 통제되지 않은 팀 촬영 자료는 pilot/development로 취급한다.

좋은 결과가 나왔다는 이유로 formal로 승격하지 않는다.

---

## 9.2 `formal`

용도:

```text
사전에 고정한 정식 수집 protocol로 획득한 controlled data
```

`formal`이라는 role 자체가:

```text
quality pass
최종 실험 포함
```

을 의미하지 않는다.

실패한 formal recording도 provenance에 남는다.

최종 포함 여부는 selection policy/manifest가 결정한다.

---

## 9.3 `external`

용도:

```text
다른 수집 조건에서 확보한 최종 또는 별도 평가 자료
```

특히 final different-condition external set은:

```text
method freeze 이전 열람/튜닝 금지
```

원칙으로 관리한다.

결과를 본 뒤 F1/F2 수식·threshold·selection 기준을 수정하지 않는다.

---

# 10. 현재 데이터/실험 트랙

## [A] Original Paper Data

역할:

```text
원 논문 baseline 재현
M0/M1/M2 비교
기존 feature 조건에서 sanity check
```

과거 연구 메모의 대표 관찰:

```text
M0 / M1 / M2 ≈ 0.960
```

현재 repository에는 이 수치의 원 결과 artifact가 포함되어 있지 않으므로
**historical preliminary result**로만 취급한다.
현재 정책 변경 후 필요한 값은 새 코드로 재산출한다.

---

## [B] MultiPosture

역할:

```text
원 논문 데이터와 병합하지 않는 별도 공개 데이터 비교 트랙
M0/M1/M2 구조적 비교
M1=M0 현상 재확인
```

원 논문과 라벨/feature 정의가 완전히 같다고 취급하지 않는다.

---

## [C] Legacy Own Pilot

예:

```text
P01
P02
기존 team-shot recordings
```

역할:

```text
문제 발견
feature hypothesis
capture protocol 개발
pipeline validation
```

정식 final validation 자료가 아니다.

---

## [D] New Controlled Formal

Foundation 완료 후 현재 protocol로 새로 수집할 controlled data.

용도는 formal experiment protocol에서 확정한다.

Foundation이 미완성인 상태에서 대규모 formal 수집을 시작하지 않는다.

---

## [E] Final External / Different-Condition

method freeze 이후에만 최종 평가에 사용한다.

```text
결과 확인
→ method 수정
```

의 루프를 만들지 않는다.

---

# 11. 현재까지의 Evidence와 해석 제한

## 11.1 M1 vs M0

현재 repository의 source/test로 확인된 구조적 sanity는:

```text
동일 seed/조건에서 M0 == M1
```

이다.

과거 실험에서는 **두 tested dataset에서 동일 prediction**이 관찰되었다고 기록되어 있으나,
해당 dataset-level result artifact는 현재 repository에 포함되어 있지 않다.
따라서 그 관찰은 historical experiment evidence로 유지하고 필요 시 현재 frozen code로 재실행한다.

원 논문의 0.98 결과가 틀렸다고 단정하는 근거로 사용하지 않는다.

---

## 11.2 M2

현재:

```text
tree split behavior 변화
→ 확인

stable gain
→ 미확인
```

따라서 M2를 실패 또는 성공으로 단정하지 않는다.

---

## 11.3 Legacy Own-Data Feature Comparison

과거 파일럿에서 대표적으로:

```text
all       ≈ 0.400
invariant ≈ 0.844
relative  ≈ 0.756
```

이 관찰됐다.

하지만:

- RNG isolation
- reduced-feature rank-weight policy
- relative non-reference evaluation
- metric/drop logging

등이 이후 보강됐다.

따라서 이 수치는:

```text
historical preliminary observation
```

으로만 유지한다. 현재 repository에는 해당 수치를 독립 재현할 원 결과 artifact가 포함되어 있지 않으므로,
최종 논문 수치로 사용하기 전 현재 code/policy로 재실행한다.

---

## 11.4 Stereo / Depth Pilot

기존 2명 파일럿에서는 depth/body movement가 유망한 신호로 관찰됐다는 historical note가 있다.
현재 repository에는 해당 pilot의 독립 검증 가능한 결과 artifact가 포함되어 있지 않으므로 hypothesis-generating evidence로만 취급한다.

그러나:

```text
2명 pilot
```

만으로 일반화하지 않는다.

특히 특정 shoulder/face ratio 자체를
F2의 최종 공식으로 자동 확정하지 않는다.

---

# 12. Evaluation Integrity

다음 원칙을 유지한다.

```text
실험 결과는 목표값이 아니다.
원하는 accuracy에 맞춰 code/parameter를 수정하지 않는다.
```

formal comparison 전에 고정해야 할 항목:

```text
evaluation split
seed list
λ selection rule
feature definitions
missing policy
inclusion/exclusion
selection manifest
model artifact lock
```

현재 방향:

```text
LOSO 기반 participant generalization 유지
λ 또는 다른 hyperparameter의 선택 규칙은 held-out final/external 결과를 보지 않도록 사전 동결
multiple seeds 사용
```

현재 코드가 λ grid를 탐색·보고하는 것과 **formal λ selection rule이 구현·동결되었다는 것은 별개**다.
정확한 λ selection rule, seed 목록·반복 수·formal metric set은
`EXPERIMENT_PROTOCOL.md`에서 최종 동결한다.

---

# 13. Provenance / Lineage 원칙

추적 대상:

```text
capture
→ recording
→ analysis
→ canonical frames
→ summary
→ RF experiment
→ result
```

주요 identifier:

```text
recording_id
analysis_run_id
dataset_role
protocol_version
code/Git provenance
model provenance
selection/inclusion history
```

모르는 과거 정보는 `unknown`으로 남긴다.

현재 환경 정보를 과거 촬영 provenance로 소급 채우지 않는다.

---

# 14. Foundation Roadmap — 현재 운영 기준

> 중요: `RESEARCH_DATA_SCHEMA.md` §K에는 과거 설계 시점의 내부 구현 순서/번호가 남아 있다.
>
> **프로젝트 운영상의 Patch 번호는 본 절을 기준으로 한다.**
>
> schema §K의 번호를 현재 Patch 번호로 재해석하거나,
> 과거 Foundation Record를 다시 번호 매기지 않는다.

## Foundation Prelude — DONE

범위:

```text
RNG fairness
rank-weight consistency
relative evaluation
metrics/drop logging
root provenance
8~12cm protocol
face-only gate
provenance setup bridge
```

---

## Patch 1 — DONE

```text
Capture Recording Provenance
```

---

## Patch 2 — DONE

```text
Forward Gate Evidence
```

---

## Patch 3 — DONE

```text
Analysis Provenance
```

---

## Patch 4 — DONE

```text
Canonical Fixed Frames Schema + Hip Raw Observations
```

`DATA-003`의 Design Freeze를 완료했으며 exact contract는 `RESEARCH_DATA_SCHEMA.md` §F가 SSOT다.

```text
frame schema        = frames-schema/1.0.0
canonical header    = legacy 31 + metadata/state 17 + hip 12 = 60 fields
legacy compatibility= 기존 31개 이름·순서·단위·계산 의미 보존
hip                 = bilateral 12-field raw observation
arm                 = exclude-and-version-later
missing             = CSV empty / JSON null + explicit validity state
boolean             = lowercase true/false, unknown=empty
```

구현 결과:

```text
동적 row key 제거
canonical fixed 60-field writer/reader
frame identity/provenance 연결
shoulder in-frame/depth validity 상태 추가
hip geometric in-frame validity + raw depth observation 구현
source enum / missing / boolean contract 구현
legacy 31 값·의미 regression 보존
```

```text
implementation commit = 110cce6
test progression       = 146 baseline → 163 initial implementation → 171 post-hardening
software audit         = initial READ-ONLY PASS + targeted re-audit PASS
hardware validation    = pending / Patch 8
```

**Design Freeze / Python 구현 / hardening / software audit 완료** 상태다.

Patch 4에서 F1/F2 derived geometry·feature formula를 구현하지 않고,
`capture_d455.py`에 새 shoulder/hip/arm coverage acceptance gate를 추가하지 않는다.
formal framing/coverage와 D455 hardware stability는 `OPEN-005` / `OPEN-006`의 후속 범위다.

---

## Early Hardware Preflight — DONE / NON-FORMAL

2026-10-02 실제 Intel RealSense D455로 제한된 engineering preflight를 수행했다.

확인된 범위:

```text
D455 인식                                      PASS
RGB + Depth streaming                         PASS
약 70초 DB3 recording                         PASS
color/depth frames                            1056 / 1056
평균 frame rate                               약 14.9 FPS
check_recording.py                            PASS
Patch 4 analyze_d455.py                       PASS
canonical frame CSV                           649 rows
frame schema                                  frames-schema/1.0.0 / 60 fields
recording_id / analysis_run_id / frame_index  확인
source color/depth frame number               확인
MediaPipe timestamp                           확인
bilateral hip x/y/depth/visibility            실제 값 확인
```

단, 이 recording은 처음 capture할 때 현재 Git clone이 아닌 예전 ZIP 작업 폴더를 사용했으므로 capture-side Git provenance가 완전하지 않다.
원본 DB3와 sidecar/analysis는 Windows PC 로컬에 보존하고 Git에는 포함하지 않는다.

따라서 이 결과의 역할은 다음으로 제한한다.

```text
Early Hardware Preflight evidence
= engineering smoke / extraction-path sanity evidence

Patch 8 formal hardware validation evidence
= 아님

formal research data
= 아님

threshold / protocol decision 도출 근거
= 아님
```

이 preflight는 Patch 4.5~8의 canonical 순서를 재배치하거나 `OPEN-006`을 해소하지 않는다.

---

## Patch 4.5 — DONE / SOFTWARE-VERIFIED / INDEPENDENTLY AUDITED / DOCUMENTATION-CLOSED / MAIN-MERGED

```text
MediaPipe Model Artifact Lock
```

Patch 3은 실제 사용 model artifact의 hash를 **기록**한다.
Patch 4.5는 허용되는 exact model artifact identity를 별도로 **강제**한다.

Design Freeze authority:

```text
docs/research/RESEARCH_DECISION_LOG.md
→ PROV-004 — Patch 4.5 MediaPipe Model Artifact Lock Design Freeze
```

관련 commit:

```text
Design Freeze
6b69255
docs: freeze Patch 4.5 model artifact lock design

implementation
aef7f34
feat: implement Patch 4.5 model artifact lock

documentation closure
26daf50
docs: close Patch 4.5 model artifact lock milestone

closure status sync
9e657ac
docs: sync Patch 4.5 closure status

main merge
15128ff
merge: complete Patch 4.5 model artifact lock foundation
```

canonical tracked manifest:

```text
repository root / mediapipe_model_lock.json
lock schema = mediapipe-model-lock/1.0.0
```

Frozen artifact set:

```text
face
= blaze_face_short_range.tflite
= versioned /1/ source
= exact SHA-256 lock

mesh
= face_landmarker.task
= versioned /1/ source
= exact SHA-256 lock

pose
= pose_landmarker_full.task
= GCS generation 1682642787774579 qualified source
= exact SHA-256 lock
```

implemented policy:

```text
existing artifact hash match
→ verified cached artifact 사용
→ network access 없음

existing artifact hash mismatch
→ HARD FAIL
→ automatic overwrite / redownload / delete / rename / fallback 금지

artifact missing
→ exact locked source에서 temporary download
→ complete SHA-256 verification
→ PASS 후 verified final install

raw inference provenance
→ actual filesystem SHA-256
 = lock SHA-256
 = recorded provenance SHA-256

--from-csv historical reprocessing
→ current lock/model provisioning 및 verification 불필요
→ historical parent model provenance 유지
```

MediaPipe Python package version은 environment provenance에 기록하되
Patch 4.5 model artifact lock에는 포함하지 않는다.

verification:

```text
pre-change baseline        171 tests PASS
new Patch 4.5 tests         33 tests PASS
final full suite           204 tests PASS

independent audit
→ PASS WITH MINOR FINDINGS
→ ACCEPT WITH MINOR NOTES

BLOCKER
→ 0

IMPORTANT
→ 0
```

독립 audit의 4개 MINOR finding은 Foundation Record에 기록했으며,
현재 exact artifact integrity를 우회하거나 PROV-004를 위반하는 defect로 판정되지 않았다.

Foundation Record:

```text
docs/foundation/PATCH_04_5_mediapipe_model_artifact_lock.md
```

현재 상태:

```text
Design Freeze       DONE — PROV-004 / 6b69255
Implementation      DONE — aef7f34
Tests               DONE — 204 PASS
Independent audit   DONE — PASS WITH MINOR FINDINGS
Foundation Record   CREATED
Documentation close DONE — 26daf50
Closure status sync DONE — 9e657ac
Main merge           DONE — 15128ff
Patch 4.5 status     COMPLETE
```

새 D455 raw run은 Patch 4.5 closure criterion이 아니다.
formal D455 hardware validation은 계속 Patch 8 범위다.

---

## Patch 5 — COMPLETE / MAIN-INTEGRATED

```text
End-to-End Lineage Hardening
```

Design Freeze:

```text
PROV-005
d4dc23f
```

Implementation:

```text
dd0464e
summary-schema/1.0.0
rf-sample-lineage/1.0.0
rf-experiment-provenance/1.0.0
```

Verification:

```text
pre-implementation baseline   204 PASS
new Patch 5 targeted           48 PASS
final full suite              252 PASS

independent READ-ONLY audit
PASS WITH MINOR FINDINGS
BLOCKER 0 / IMPORTANT 0 / MINOR 6
```

Main integration:

```text
documentation closure   0ed2954
main merge              ae86d58
post-merge full suite   252 PASS
origin/main             ae86d5875c8fe3200b3b2c1dd26c48256e01105f
```

완료된 핵심:

```text
same raw bytes의 independent recording identity fork 차단
recording/source-run 단위 summary/reference isolation
immutable RF input resolution
persistent per-sample lineage
immutable RF experiment/result provenance
```

Patch 6의 selection ledger / retake scientific selection은 구현하지 않았다.

---

## Patch 6

```text
Selection Manifest / Recapture Inclusion
```

목표:

```text
어떤 recording을 왜 포함/제외했는가
retake 중 어느 것을 선택했는가
결정 이력을 append-only로 보존
```

---

## Patch 7

```text
Integrity Checker / Hardening
```

예:

```text
missing artifact
hash mismatch
orphan artifact
broken parent
partial flat publish
```

등을 자동 감사한다.

---

## Patch 8

```text
Actual D455 End-to-End Smoke / Validation
```

software unit test와 구분한다.

필수 확인 범주:

```text
A. literature / ergonomics / D455 characteristics로 candidate operating range 설정
B. candidate range에서 landmark / depth / 3D geometry stability 검증 후 formal range freeze
C. D455 measurement-quality validation
   - actual-use distance에서 landmark acquisition stability
   - head/shoulder/hip depth valid rate
   - depth repeatability / jitter
   - 3D geometry repeatability
   - RGB landmark + aligned-depth coupling stability
   - distance-dependent feature stability
D. real forward gate: below / pass / above
E. face missing + body-only가 절대 PASS하지 않음
F. 1명 full posture end-to-end recording
G. raw→provenance→analysis→frames→summary 연결
```

특정 거리(예: 70~90cm), 반복 수, exact metric, tolerance는 아직 확정하지 않는다.
checkerboard/cross/known geometric target은 교수 피드백에서 도출된 requirement가 아니며 Patch 8의 필수 요소로 두지 않는다.
measurement-quality validation은 D455-derived body geometry를 실제 자세 연구의 측정값으로 안정적으로 사용할 수 있는지를 확인하는 단계다.

Patch 8 PASS 전:

```text
대규모 formal collection 시작 금지
```

를 기본 원칙으로 한다.

---

# 15. Research Stage 체계

Foundation Patch는 연구 인프라/재현성 기반 작업이다.

F1/F2 핵심 연구는 Patch 번호로 계속 이어가지 않는다.

```text
Foundation
Patch 1 ~ Patch 8

그 이후
Research Stage
```

---

## Research Stage 1 — F1 Design

예정 Gate:

```text
Gate 1.1
사용할 canonical raw observations 확정

Gate 1.2
좌표계 / 단위 / body-relative 기준 확정

Gate 1.3
missing-data policy 확정

Gate 1.4
normalization 확정

Gate 1.5
F1 exact formulas / feature count 확정

Gate 1.6
F1 Design Freeze
```

Gate 통과 전 exact formula를 구현자가 발명하지 않는다.

### Shared pre-experiment gate — `p > 6` rank-weight policy

F1 또는 F2에서 최초로 `p > 6`인 feature set으로 `M0/M1/M2` 비교를 실행하려는 경우,
그 실행 **전에** `OPEN-004`의 exact `rank_weights` policy를 Design Freeze한다.
현재 policy는 M1과 M2 weighting 경로 모두에 영향을 주며, F2 단계까지 자동 유예하지 않는다.
`p <= 6`이면 이 gate 때문에 별도 정책을 미리 발명할 필요는 없다.

---

## Research Stage 2 — F1 Experiment

Design Freeze된 F1을 기준으로:

```text
M0/M1/M2 × F1
```

비교를 수행한다.

실험 protocol은 사전 동결한다.

---

## Research Stage 3 — F2 Design

F1을 기반으로:

```text
RGB-D / metric 3D upper-body geometry
sagittal-plane geometry candidate family
```

를 추가한다.

F2 exact feature는 별도 연구 결정이다.
`>6` rank-weight policy는 F2 전용 결정이 아니라 위 shared pre-experiment gate와 `OPEN-004`를 따른다.

---

## Research Stage 4 — F2 Experiment / Method Freeze

사전 정의된 조건에서 비교 후
최종 method를 freeze한다.

---

## Research Stage 5 — Final External Validation

동결된 method를 final external/different-condition data에 적용한다.

결과를 본 뒤 method를 다시 변경하지 않는다.

---

## 15.1 현재 범위에 자동 추가하지 않는 항목

이번 교수 피드백 반영은 다음을 자동 요구사항으로 승격하지 않는다.

```text
arm-up/down 등의 신규 posture class
전체 workstation ergonomic assessment
desk/elbow relation의 primary classifier 통합
pseudo-side-view visualization을 학술 기여로 주장
실제 side camera를 최종 classifier 입력으로 추가
runtime/FPS를 새 핵심 연구축으로 승격
목적 없는 공개 dataset 추가
```

필요성이 생기면 별도 Decision Log entry로 범위를 다시 결정한다.

---

# 16. 현재 확정 사항

다음은 구현자가 임의로 뒤집지 않는다.

```text
1. F1/F2는 개인별 사전 upright calibration을 요구하지 않는다.

2. F_cal은 legacy/reference-based 비교군이다.

3. M0/M1/M2 정의는 유지한다.

4. M2는 비교 대상이며 성능 우위를 사전 가정하지 않는다.

5. body_forward는 현재 정식 5-class의 6번째 class가 아니다.

6. face/head + 양 shoulder + 양 hip raw observation을
   F1/F2 연구에 필요한 핵심 body structure로 본다.

7. raw / derived geometry / model feature를 분리한다.

8. pilot / formal / external role을 혼합하지 않는다.

9. 기존 pilot을 결과가 좋다는 이유로 formal로 승격하지 않는다.

10. final external data는 method freeze 전 tuning에 사용하지 않는다.

11. forward hard gate는 8~12cm face-only다.

12. body-only 또는 mixed-source movement는 forward gate를 통과시키지 않는다.

13. model provenance 기록과 model lock은 서로 다른 개념이다.

14. historical unknown을 추정으로 채우지 않는다.

15. code/test/source에 없는 실험 결과를 생성하지 않는다.

16. F1/F2는 upper-body skeletal/body-relative representation을 candidate 방향으로 평가하되 raw observation → derived geometry → selected model feature 계층을 분리한다.

17. F2는 RGB-D·metric 3D upper-body geometry와 sagittal-plane geometry를 candidate family로 평가한다.

18. head-forward relative to trunk, whole-trunk-forward/trunk inclination, whole-body translation은 구별 가능성을 평가해야 하는 confounder이며, body_forward를 새 primary class로 자동 추가하지 않는다.

19. 정면 D455 기반 trunk geometry를 actual spine angle 직접 측정으로 주장하지 않는다.

20. Patch 8의 formal operating distance는 literature/ergonomics/D455 evidence로 candidate range를 정한 뒤 실제 sensor validation 후 freeze한다.

21. Patch 8에는 D455-derived body geometry의 measurement-quality validation을 포함한다.

22. face bbox와 contour/oval 표현 차이를 **secondary exploratory analysis candidate로 분류한다는 guardrail은 확정**하되, 실제 분석 채택·metric·F1/F2 포함·최종 논문 사용 여부는 `FEAT-008 (DEFERRED)`로 남긴다.

23. `DATA-003`에 따라 Patch 4 exact canonical raw frame contract는 `frames-schema/1.0.0`으로 freeze되었다. 총 60 fields이며 legacy 31 ordered prefix + metadata/state 17 + bilateral hip 12 구조다. 해당 contract의 Python 구현은 commit `110cce6`에서 완료됐지만 F1/F2 feature 확정을 의미하지 않는다.

24. `PROV-004`에 따라 Patch 4.5 MediaPipe model artifact contract는 `mediapipe-model-lock/1.0.0`으로 freeze되었고 commit `aef7f34`에서 구현 완료됐다. raw inference는 locked artifact verification을 통과해야 하며, `--from-csv` historical reprocessing에는 current model lock/provisioning을 강제하지 않는다.
```

---

# 17. 현재 미확정 — USER / RESEARCH DECISION REQUIRED

다음은 구현자가 정해서는 안 된다.

```text
F1 exact formula
F1 feature count
F1 exact upper-body skeletal landmark set / graph / edge structure
F1 normalization / feature selection
F1 missing-data policy

F2 exact formula
F2 feature count
F2 exact sagittal coordinate/projection convention
F2 exact trunk-axis / representative points / head-to-trunk geometry
F2 exact upper-body skeletal landmark set / graph / edge structure
F2 exact angle / ratio / normalization / feature selection
F2 depth-derived geometry
F2 missing-depth policy

>6 feature에서 rank_weights exact policy (M1/M2 shared weighting 경로)


formal participant 수
formal round 수
formal inclusion/exclusion
ok_with_warnings 처리
exact seed list
exact λ search grid
formal metric set

D455 candidate range의 exact literature/ergonomics/D455 evidence basis
D455 validation exact distance grid
repetition count
landmark acquisition / depth-valid / jitter / 3D-repeatability / RGB-depth coupling / distance-stability의 exact metric
acceptance criterion

bbox-vs-contour/oval exact area-error formula
bbox-vs-contour/oval exact evaluation metric
bbox-vs-contour/oval의 F1/F2 feature 포함 여부 및 최종 논문 채택 여부
```

실험 전에 필요한 시점에 하나씩 Design Freeze한다.

---

# 18. Formal Collection 시작 Gate

다음이 완료되기 전 대규모 formal 수집을 시작하지 않는다.

```text
Patch 4   canonical schema + hip        DONE
Patch 4.5 model lock                    DONE
Patch 5   lineage                       DONE — implementation/audit/closure/main integration
Patch 6   selection policy              PENDING
Patch 7   integrity                     PENDING
Patch 8   actual D455 E2E validation    PENDING
EXPERIMENT_PROTOCOL freeze              PENDING
```

pilot/smoke/validation 촬영은 별개다.

---

# 19. 팀 역할 원칙

연구 판단이 필요한 일:

```text
F1/F2 feature 선택
threshold/ROI 변경
missing policy
실험 포함/제외
outlier/ambiguous label 결정
method freeze
결과 해석
```

은 연구 책임자가 결정한다.

규칙 기반 반복 작업:

```text
실험 운영
checklist
파일/ID 정리
명시된 규칙에 따른 1차 분류
missing checklist
retake 후보 목록
```

은 팀원에게 분담할 수 있다.

팀원이 독립적으로 연구 기준을 바꾸지 않는다.

---

# 20. 문서 운영 규칙

## 20.1 Master

이 파일은 현재 상태만 보여준다.

과거 문구를 계속 누적하지 않는다.

연구 정의가 바뀌었을 때:

```text
v1.0 → v1.1
```

처럼 갱신한다.

코드의 사소한 Patch마다 버전을 올리지 않는다.

---

## 20.2 Decision Log

결정을 덮어쓰지 않는다.

기존 결정을 바꾸려면:

```text
새 Decision Entry 추가
+
새 entry에 `Supersedes:` / `Resolves:` 연결
+
과거 entry에 `Superseded by:` back-pointer를 사후 추가하지 않음
```

을 남긴다.

---

## 20.3 Foundation Record

Patch 종료 후 작성한다.

내용:

```text
목적
설계 결정
구현
검증
독립 review
deferred
commit
```

중간 Codex/Claude 보고 전체를 영구 보존할 필요는 없다.

결정에 영향을 준 finding/verdict를 압축해 남긴다.

---

## 20.4 Patch Worklog

복잡한 Patch에서만 임시로 사용한다.

```text
PATCH_04_WORKLOG.md
```

등.

완료 후 핵심은 Foundation Record에 흡수한다.

Worklog를 연구의 최종 권위 문서로 사용하지 않는다.

---

# 21. 다음 작업

현재 우선순위:

```text
1. Research Master / Decision Log / RESEARCH_DATA_SCHEMA canonicalization        DONE

2. AGENTS.md / CLAUDE.md agent authority alignment                              DONE

3. Patch 4 Design Freeze                                                         DONE
   → DATA-003이 OPEN-001 해소
   → frames-schema/1.0.0 exact 60-field contract freeze

4. Patch 4 구현·hardening·software audit                                          DONE
   → canonical fixed writer/reader
   → shoulder validity + bilateral hip raw observations
   → exact missing/boolean/source enum contract
   → legacy 31 regression 보존
   → 171 tests PASS
   → initial independent READ-ONLY audit PASS
   → targeted post-hardening READ-ONLY re-audit PASS
   → implementation commit 110cce6

5. Patch 4 Foundation Record 작성                                                 DONE
   → docs/foundation/PATCH_04_canonical_frame_schema.md

6. Patch 4 documentation closure initial READ-ONLY audit                         DONE — FAIL
   → F-1 authority/status contradiction
   → F-2 Master provenance/current-state inconsistency

7. F-1/F-2 authority/provenance alignment                                        DONE

8. Targeted Patch 4 documentation READ-ONLY re-audit                             DONE — PASS

9. Patch 4 documentation closure commit / push                                   DONE
   → commit 144a264
   → docs: close Patch 4 implementation milestone

10. Early Hardware Preflight                                                      DONE — NON-FORMAL
   → 2026-10-02 actual D455 engineering preflight 수행
   → Patch 8 / formal research evidence / formal collection 대체 아님

11. Patch 4.5 MediaPipe Model Artifact Lock Design Freeze                        DONE
   → PROV-004
   → Design Freeze commit 6b69255
   → exact artifact / source-version / SHA-256 contract frozen

12. Patch 4.5 MediaPipe Model Artifact Lock implementation                       DONE
   → implementation commit aef7f34
   → mediapipe-model-lock/1.0.0
   → fail-closed existing-artifact verification
   → verified temporary download / install
   → Patch 3 provenance linkage
   → --from-csv historical isolation
   → 171 existing + 33 new = 204 tests PASS

13. Patch 4.5 independent READ-ONLY audit                                        DONE — ACCEPT
   → Claude Opus
   → PASS WITH MINOR FINDINGS
   → ACCEPT WITH MINOR NOTES
   → BLOCKER 0 / IMPORTANT 0
   → 204 tests reproduced PASS

14. Patch 4.5 Foundation Record                                                  DONE
   → docs/foundation/PATCH_04_5_mediapipe_model_artifact_lock.md
   → 4 accepted MINOR notes documented

15. Patch 4.5 documentation closure commit                                       DONE
   → commit 26daf50
   → docs: close Patch 4.5 model artifact lock milestone
   → Foundation Record + AIoT_RESEARCH_MASTER v1.4 closure alignment

16. Patch 4.5 status-sync / push / branch final review                           DONE
   → closure status-sync commit 9e657ac
   → origin/patch4.5/model-artifact-lock push 완료
   → branch final review PASS
   → 204 tests PASS

17. Patch 4.5 main merge                                                         DONE
   → merge commit 15128ff
   → merge: complete Patch 4.5 model artifact lock foundation
   → post-merge 204 tests PASS
   → origin/main push 완료

18. Patch 5 End-to-End Lineage Hardening Design Freeze                           DONE
   → PROV-005
   → Design Freeze commit d4dc23f

19. Patch 5 implementation                                                       DONE
   → implementation commit dd0464e
   → summary-schema/1.0.0
   → rf-sample-lineage/1.0.0
   → rf-experiment-provenance/1.0.0
   → 204 existing + 48 new = 252 tests PASS

20. Patch 5 independent READ-ONLY audit                                          DONE — ACCEPT
   → Claude Opus
   → PASS WITH MINOR FINDINGS
   → BLOCKER 0 / IMPORTANT 0 / MINOR 6
   → implementation commit recommendation YES

21. Patch 5 Foundation Record / documentation closure                            DONE
   → docs/foundation/PATCH_05_end_to_end_lineage_hardening.md
   → 6 accepted MINOR dispositions documented
   → closure commit 0ed2954

22. Patch 5 main integration                                                      DONE
   → merge commit ae86d58
   → merge: complete Patch 5 end-to-end lineage hardening foundation
   → post-merge 252 tests PASS
   → origin/main synchronized at ae86d5875c8fe3200b3b2c1dd26c48256e01105f

23. Patch 6 Selection Manifest / Recapture Inclusion                             NEXT REQUIRED FOUNDATION
   → READ-ONLY 조사 → exact contract → Design Freeze부터 시작
```

---

# 22. Source Basis

본 v1.5는 다음을 통합한 **현재 기준 문서**다.

```text
- 실제 현재 repository / Git history
- AGENTS.md
- CLAUDE.md
- RESEARCH_DATA_SCHEMA.md
- BASELINE_00 / RETROSPECTIVE_01
- FOUNDATION_PRELUDE_00
- canonical `PATCH_01_capture_provenance.md` ~ `PATCH_03_analysis_provenance.md`
- `docs/foundation/PATCH_04_canonical_frame_schema.md`
- `docs/research/RESEARCH_DECISION_LOG.md`의 `PROV-004` Patch 4.5 Design Freeze
- Patch 4.5 Design Freeze commit `6b69255`
- Patch 4.5 implementation commit `aef7f34`
- Patch 4.5 documentation closure commit `26daf50`
- Patch 4.5 closure status-sync commit `9e657ac`
- Patch 4.5 main merge commit `15128ff`
- repository root `mediapipe_model_lock.json`
- Patch 4.5 software verification: 204 tests PASS
- independent Claude Opus READ-ONLY audit: PASS WITH MINOR FINDINGS / ACCEPT WITH MINOR NOTES
- `docs/foundation/PATCH_04_5_mediapipe_model_artifact_lock.md`
- Patch 5 Design Freeze `PROV-005` / commit `d4dc23f`
- Patch 5 implementation commit `dd0464e`
- Patch 5 software verification: baseline 204 / targeted 48 / final 252 tests PASS
- Patch 5 independent Claude Opus READ-ONLY audit: PASS WITH MINOR FINDINGS / BLOCKER 0 / IMPORTANT 0 / MINOR 6
- `docs/foundation/PATCH_05_end_to_end_lineage_hardening.md`
- 2026-10-02 actual D455 Early Hardware Preflight의 local engineering evidence (formal research data 아님)
- 바른자세 알고리즘개량 연구마스터 v6.1
- 현재까지 진행상황 인계요약
- 이후 교수 피드백 반영 및 대화에서 확정된
  calibration-free F1/F2 방향과 Foundation 운영 규칙
```

중요:

`바른자세_알고리즘개량_연구마스터_v6.1.md`는
**2026-09-29 당시의 역사적 연구 상태**다.

이제부터 현재 연구 정의는 본 `AIoT_RESEARCH_MASTER.md`를 우선한다.

---

# 23. Version Log

| Version | Date | Summary |
|---|---|---|
| `v1.0` | 2026-10-01 | 역사/Foundation 정리 이후 현재 연구 방향을 재기준화. M0/M1/M2 역할, F0/F_cal/F1/F2, calibration-free 원칙, data role, operational Patch 1~8, Research Stage 전환, unresolved research decisions를 통합 |
| `v1.1` | 2026-10-01 | `DATA-003` Patch 4 Design Freeze 반영. `OPEN-001` 해소, `frames-schema/1.0.0` exact 60-field contract를 frozen-but-unimplemented로 전환, elbow/wrist `exclude-and-version-later`, 다음 단계는 Patch 4 implementation으로 갱신 |
| `v1.2` | 2026-10-02 | commit `110cce6`의 Patch 4 구현·hardening·171-test 검증·독립 software audit와 commit `144a264`의 documentation/authority closure 완료를 반영. 실제 D455 validation과 OPEN-002~OPEN-006은 계속 pending이다. Early Hardware Preflight는 optional/non-formal이며, 다음 required Foundation milestone은 Patch 4.5 MediaPipe Model Artifact Lock이다. |
| `v1.3` | 2026-10-04 | Patch 4 main merge `d923b23` 및 현재 Patch 4.5 branch baseline을 동기화. 2026-10-02 실제 D455 Early Hardware Preflight 수행 결과를 non-formal engineering evidence로 기록하고, `PROV-004`에 따른 Patch 4.5 MediaPipe Model Artifact Lock Design Freeze 완료를 반영. 다음 required Foundation 작업은 Patch 4.5 implementation이다. |
| `v1.4` | 2026-10-04 | Patch 4.5 implementation commit `aef7f34`, `mediapipe-model-lock/1.0.0`, 기존 171 + 신규 33 = 204 tests PASS, 독립 Claude Opus READ-ONLY audit `PASS WITH MINOR FINDINGS / ACCEPT WITH MINOR NOTES` 및 BLOCKER/IMPORTANT 0건을 반영. `docs/foundation/PATCH_04_5_mediapipe_model_artifact_lock.md` Foundation Record와 documentation closure commit `26daf50`을 current state에 연결하고 model-lock exact values를 미확정 목록에서 제거했다. Patch 4.5 closure status-sync commit `9e657ac`과 main merge commit `15128ff`까지 current state에 반영했다. Patch 4.5는 main integration까지 완료됐으며, 현재 다음 required Foundation milestone은 Patch 5 End-to-End Lineage Hardening이다. |
| `v1.5` | 2026-10-04 | Patch 5 `PROV-005` / Design Freeze commit `d4dc23f`, implementation commit `dd0464e`, `summary-schema/1.0.0`, `rf-sample-lineage/1.0.0`, `rf-experiment-provenance/1.0.0` 구현을 반영. pre-implementation 204 + 신규 48 = 최종 252 tests PASS, 독립 Claude Opus READ-ONLY audit `PASS WITH MINOR FINDINGS`, BLOCKER 0 / IMPORTANT 0 / MINOR 6 및 implementation commit recommendation YES를 기록했다. `docs/foundation/PATCH_05_end_to_end_lineage_hardening.md`에 6개 MINOR closure disposition을 기록하고 Patch 5를 implementation/audit/documentation-closure 완료 상태로 전환했다. Patch 5 main integration은 pending이며, 그 이후 다음 Foundation scope는 Patch 6 Selection Manifest / Recapture Inclusion이다. |
| `v1.6` | 2026-10-04 | Patch 5 documentation closure commit `0ed2954` 이후 main merge commit `ae86d58` (`ae86d5875c8fe3200b3b2c1dd26c48256e01105f`)에서 Foundation을 `main`에 통합했다. merge 직후 전체 `252 tests PASS`를 재확인하고 `origin/main` 동기화를 완료했다. Patch 5는 COMPLETE / MAIN-INTEGRATED 상태이며, 현재 다음 required Foundation milestone은 Patch 6 Selection Manifest / Recapture Inclusion이다. |
