# F1 Feature Core Calculation Contract

- **문서 상태:** `CORE CALCULATION CONFIRMED / F1 FULL DESIGN FREEZE PENDING`
- **Decision authority:** `RESEARCH_DECISION_LOG.md` `FEAT-009` (Status: CONFIRMED — core calculation only)
- **연구자 승인일:** 2026-10-11 (Research Stage 1 Gate 1.6 부분 승인)
- **기록 기준:** branch `feat/posture-integrated-v0`, HEAD `9d05815`
- **관련 OPEN:** `OPEN-002` — **부분 승인 / DEFERRED 유지 (RESOLVED 아님)**. `OPEN-004`, `OPEN-005`는 변경하지 않는다.
- **데이터 계약:** `RESEARCH_DATA_SCHEMA.md` §F `frames-schema/1.0.0` (`DATA-003`). 이 문서는 Schema를 변경하지 않는다.

이 문서는 연구자가 승인한 **F1 frame-level 핵심 계산 계약**만 기록한다.
F1 전체 Design Freeze, 구현 승인, 실측 결과, 분류 성능 주장이 아니다.

---

## 1. 승인 사항 (APPROVED CORE)

| ID | 승인 항목 | 내용 |
|---|---|---|
| AC-1 | F1-5 기본 계산 표현 | §3의 5개 feature 이름·출력 순서·수식을 F1 기본 계산 표현으로 채택 |
| AC-2 | 공통 정규화 | FS/SH 선형 성분은 공통 shoulder-width `D_sh`로 정규화 |
| AC-3 | 어깨선 각도 표현 | `so_beta`는 radian, period-π, 범위 `[-π/2, π/2)` |
| AC-4 | 동일 frame 계산 | Geometry는 **동일 frame의 관측값으로 먼저** 계산한다 (서로 다른 frame의 좌표를 먼저 병합하지 않는다) |
| AC-5 | F1-6 비교 후보 | `sin(2β)`, `cos(2β)`를 사용하는 F1-6을 **별도 비교 후보**로 유지. 기본 표현은 F1-5 |

---

## 2. 입력 (canonical raw observations)

모든 좌표는 `frames-schema/1.0.0`의 **원래 color 이미지 비반전 pixel 좌표**다
(Schema §F.2: capture의 거울 UI 좌표나 RF의 640×480 환산 좌표가 아님).
`x`는 영상 오른쪽, `y`는 영상 아래쪽이 양의 방향이다.
`left/right`는 **사람(subject) 기준**이며 화면 좌우와 구분한다.

| 기호 | 의미 | Canonical field (Schema §F) |
|---|---|---|
| `F` | Face bbox center | `face_x`, `face_y` (detector bbox 중심; 코·해부학적 머리 중심이 아님) |
| `L` | subject-left shoulder | `lsh_x`, `lsh_y` (MediaPipe landmark 11) |
| `R` | subject-right shoulder | `rsh_x`, `rsh_y` (MediaPipe landmark 12) |
| `Lh` | subject-left hip | `left_hip_x_px`, `left_hip_y_px` |
| `Rh` | subject-right hip | `right_hip_x_px`, `right_hip_y_px` |

Depth, MediaPipe 상대 z, 개인별 upright reference, label은 F1-5 계산 입력이 아니다 (`FEAT-002` calibration-free 원칙과 일치).

---

## 3. 승인된 수식과 출력 순서

중간 기하:

```text
S    = (L + R) / 2          # shoulder midpoint
H    = (Lh + Rh) / 2        # hip midpoint
W    = R - L                # shoulder vector (subject-left → subject-right)
D_sh = norm(W) = sqrt(W_x^2 + W_y^2)
```

출력 (이 순서 고정):

| 순서 | Feature | 계산식 | 단위 | Family |
|---:|---|---|---|---|
| 1 | `fs_x` | `(F_x - S_x) / D_sh` | 무차원 | FS (face–shoulder) |
| 2 | `fs_y` | `(F_y - S_y) / D_sh` | 무차원 | FS |
| 3 | `sh_x` | `(S_x - H_x) / D_sh` | 무차원 | SH (shoulder–hip) |
| 4 | `sh_y` | `(S_y - H_y) / D_sh` | 무차원 | SH |
| 5 | `so_beta` | `wrap_pi(atan2(W_y, W_x))` | rad | SO (shoulder orientation) |

`wrap_pi`는 period-π 각도를 `[-π/2, π/2)`로 사상한다. 이 범위와 동치인 수학적 정의:

```text
wrap_pi(θ) = θ - π * floor((θ + π/2) / π)
```

따라서 `W`와 `-W`는 같은 `so_beta`를 준다 (어깨선의 방향이 아니라 축(axis)을 표현).
`so_beta = 0`은 이미지 좌표에서 어깨선이 수평임을 뜻한다.

### F1-6 비교 후보 (기본 표현 아님)

```text
[fs_x, fs_y, sh_x, sh_y, sin(2*so_beta), cos(2*so_beta)]
```

`(sin 2β, cos 2β)`는 하나의 period-π 각도의 연속 인코딩이며, 독립적인 신체 관측값 두 개를 추가하는 것이 아니다.
F1-6의 실제 채택 여부는 별도 비교·승인 대상이다.

### 해석 한계

- 모든 값은 **투영 2D 기하**다. 실제 3D 해부학적 각도, 척추각, 시상면 각도, 개인의 실제 신체 치수를 주장하지 않는다.
- `D_sh` 정규화는 동일 frame 내 2D 평행이동·균일 확대에 대한 불변성을 제공하지만, 물리적 yaw/pitch/roll 및 원근 변화에 대한 불변성을 보장하지 않는다.

---

## 4. 수학적 정의 조건

- 모든 입력 좌표는 유한(finite) 실수여야 한다.
- `D_sh > 0`이어야 한다. `D_sh = 0`이면 5개 feature 모두 **미정의**이며, `atan2(0, 0)`의 반환값을 유효한 β로 사용하지 않는다.
- `D_sh > 0`은 **수학적 정의 조건일 뿐**이며 센서 품질용 최소 길이 임계값이 아니다. `D_sh` 품질 임계값은 승인되지 않았다 (§6).
- 수식상 의존 관계 (수학적 사실이며 sample 채택 정책이 아님):
  - `fs_x`, `fs_y` — `F`, `L`, `R` 필요
  - `sh_x`, `sh_y` — `L`, `R`, `Lh`, `Rh` 필요
  - `so_beta` — `L`, `R` 필요

---

## 5. 기존 Schema validity 경계

이 계약은 `frames-schema/1.0.0`의 validity 의미를 그대로 따르며 새 validity·품질 기준을 만들지 않는다.

| 관측 | Schema가 정의한 상태 (변경 없음) | 계산 입력 시 경계 |
|---|---|---|
| Face | `face_detected` (bool). 별도 `face_valid` field는 없음 | `face_detected`가 `true`이고 `face_x/face_y`가 유한값일 때만 `F`로 사용. **추가 in-frame 검사 여부는 미승인** |
| Shoulder | `lsh_valid` / `rsh_valid` = finite 및 normalized `0 <= x,y < 1` (§F.3 #44/#45). legacy numeric prefix는 invalid여도 값이 남을 수 있음 (§F.3 D02 note) | 해당 `*_valid`가 명시적 `true`일 때만 사용. 숫자 존재만으로 유효로 보지 않음 |
| Hip | `left_hip_valid` / `right_hip_valid` = geometric in-frame validity; invalid이면 x/y는 empty (§F.4) | 해당 `*_hip_valid`가 명시적 `true`일 때만 사용 |

- `false`, empty/`None`(unknown), NaN, ±Infinity를 유효값·0·보간값으로 조용히 대체하지 않는다 (Schema §F.1 serialization 원칙, `PROV-002`).
- `*_visibility`, `face_score`는 acceptance threshold로 사용하지 않는다 (Schema §F.4). visibility cutoff는 승인되지 않았다.
- 위 경계는 frame 단위 계산 가능 여부의 전제일 뿐이며, 모델 학습용 sample eligibility·결측 처리 정책이 아니다.

---

## 6. 승인되지 않은 사항 (NOT APPROVED)

다음은 이 문서와 `FEAT-009`로 **확정되지 않는다.** 구현자는 임의로 선택하지 않는다.

| 항목 | 상태 |
|---|---|
| 5점(F, L, R, Lh, Rh) joint-frame support의 최종 sample 채택 정책 | 미승인 |
| Frame → sample(step/round) median 집계 | 미승인 |
| `so_beta`의 angular aggregation 방식 | 미승인 |
| `N_min`, `R_min` | 미승인 |
| `D_sh` 품질 임계값 | 미승인 |
| Face 추가 in-frame 정책 | 미승인 |
| 모델 수준 결측 처리 (complete-case / imputation / indicator 등) | 미승인 |
| F1용 M1/M2 가중치 정책 | 미승인 |
| 자체 데이터 LOSO 프로토콜 | 미승인 (`OPEN-005` 연계, 변경 없음) |
| F1 전체 Design Freeze | 미승인 — `OPEN-002` 부분 승인 상태 유지 |
| 실제 측정 결과 및 분류 성능 | 없음 / 주장하지 않음 |

참고 사실 (정책 결정 아님): F1-5는 5개, F1-6은 6개 feature이므로 현재 `rf_experiment.py`의 `rank_weights()`가 거부하는 `p > 6` 조건에는 해당하지 않는다. 그러나 이것이 F1에 대한 M1/M2 가중치 정책의 승인을 뜻하지 않으며, `OPEN-004`는 변경하지 않는다.

---

## 7. 실측·근거가 필요한 항목

다음은 실제 데이터 또는 측정으로만 결정할 수 있으며, 현재 근거가 없다 (`NOT VERIFIED`).

- Face / 양 Shoulder / 양 Hip의 frame별·family별 coverage 및 5점 동시 유효율
- 반복 frame에서 `fs_*`, `sh_*`, `so_beta`의 변동·이상치 분포 (집계 방식 선택 근거)
- `so_beta` 분포 및 axial resultant length 분포 (`R_min` 근거)
- `D_sh` 분포와 저품질 사례 (`D_sh` 임계값 근거)
- Face bbox center의 in-frame 실패 사례 (recording별 image size/provenance 포함)
- step/round당 사용 가능한 frame 수 (`N_min` 근거)
- 실제 D455 측정 품질 (`CAP-005` / Patch 8 범위; formal 실행 없음, `CAP-007` 기준 execution deferred)
- Hip을 포함한 실제 canonical 데이터의 존재 및 lineage (기존 paper dataset에는 양쪽 Hip canonical 원재료가 없음)

---

## 8. 변경하지 않는 것

- `frames-schema/1.0.0` 및 기타 frozen schema/contract
- F0 / F_cal 정의, M0/M1/M2 정의, class/label, 평가 split
- `OPEN-002`(부분 승인, DEFERRED 유지), `OPEN-003`, `OPEN-004`, `OPEN-005`의 상태
- 소스코드·테스트 (이 문서는 구현을 시작하거나 승인하지 않는다)
