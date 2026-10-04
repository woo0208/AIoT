# Research Decision Log

- 문서 버전: `v1.3`
- 기준일: `2026-10-04`
- 상태: **ACTIVE / Append-Only**
- 권장 위치: `docs/research/RESEARCH_DECISION_LOG.md`
- 역할: 현재 Research Master에 반영된 중요한 연구·데이터·실험·거버넌스 결정을 **왜 그렇게 결정했는지** 기록

---

# 0. 사용 규칙

이 문서는 현재 상태를 요약하는 Master가 아니다.

질문:

> **“왜 지금의 연구 규칙이 이렇게 되었는가?”**

에 답한다.

## 0.1 Append-Only 원칙

본 문서가 canonicalize된 이후에는 기존 entry의 본문·Status·Evidence를 덮어쓰지 않는다.
결정이 바뀌거나 OPEN/DEFERRED가 해소되면 **새 entry를 추가**해 관계를 기록한다.

예:

```text
DEC-027
Status: CONFIRMED
Supersedes: DEC-012
Resolves: OPEN-004
```

따라서 과거 entry의 `Status: DEFERRED`는 "그 entry가 기록될 당시 미정이었다"는 역사적 상태로 남는다.
현재 유효성은 후속 entry의 `Supersedes` / `Resolves` 관계로 판단한다.
canonicalization 전인 v1.0 정리 단계에서는 내부 모순 제거를 위해 기존 초안 entry를 정리할 수 있다.

canonicalization 이후 과거 entry에 `Superseded by:` 같은 back-pointer를 사후 추가하지 않는다.
대체·해소 관계는 항상 **새 entry의 `Supersedes:` / `Resolves:`**에만 기록한다.

---

## 0.2 Status

```text
CONFIRMED
현재 적용 중인 결정

DEFERRED
결정이 필요하지만 아직 고정하지 않음

SUPERSEDED
초기 소급 기록 시 이미 후속 결정으로 대체된 historical entry에만 사용.
canonicalization 이후 기존 entry의 Status를 SUPERSEDED로 사후 변경하지 않음

REJECTED
검토했으나 채택하지 않음
```

---

## 0.3 날짜 정책

이 문서의 초기 entry는
2026-10-01에 과거 결정을 **소급 통합 기록**한 것이다.

정확한 최초 결정 날짜를 증명할 수 없는 경우:

```text
Logged: 2026-10-01
Decision timing: Retrospective consolidation; exact original timestamp not asserted
```

로 기록한다.

앞으로의 결정은 결정 당시 날짜로 즉시 기록한다.

본 v1.0의 **초기 통합 entry**에서 `Logged` 또는 `Decision timing`을 개별 반복하지 않은 경우에는
다음 값을 상속한다.

```text
Logged: 2026-10-01
Decision timing: Retrospective consolidation; exact original timestamp not asserted
```

단, entry에 `Current governance decision`, `Current consistency decision` 등 더 구체적인 timing이 적혀 있으면 그 값을 우선한다.

---

## 0.4 Entry Template

```text
## DEC-XXX — 제목

Status:
Logged:
Decision timing:

Decision:

Rationale:

Alternatives / Rejected / Deferred:

Evidence / Source:

Impact:

Supersedes:
Resolves:
```

### 초기 v1.0 Evidence / Source 규칙

초기 통합 entry의 근거는 다음 범주로 구분한다.

```text
현재 구현 사실
→ Git / source / test

과거 구현·변경 사실
→ canonical docs/history/* 및 docs/foundation/*

데이터 계약
→ RESEARCH_DATA_SCHEMA.md
   단, 아직 구현되지 않은 future design은 구현 완료 사실을 의미하지 않으며,
   Patch 4 exact canonical contract는 GOV-005 / OPEN-001에 따라 Design Freeze 전 proposal

과거 실험 수치·관찰 중 현재 repository에 result artifact가 없는 항목
→ historical preliminary evidence
   독립 재현된 현재 결과로 간주하지 않음

현재 연구 방향·미확정 유지 결정
→ AIoT_RESEARCH_MASTER.md + 본 Decision Log
```

개별 entry에서 더 구체적인 evidence가 필요한 경우 해당 entry에 `Evidence / Source`를 추가한다.

---

# 1. Governance Decisions

## GOV-001 — 현재 연구 정의의 Single Source of Truth

**Status:** CONFIRMED
**Logged:** 2026-10-01
**Decision timing:** Current governance decision

### Decision

현재 연구의 목적·역할·로드맵은:

```text
docs/research/AIoT_RESEARCH_MASTER.md
```

를 Single Source of Truth로 사용한다.

### Rationale

과거 v6.1 master, handoff summary, schema, Patch 기록이 서로 다른 시점의 상태를 담고 있어
앞으로 구현자가 과거 규칙과 현재 규칙을 혼동할 위험이 있다.

### Impact

- 과거 master는 역사 자료로 유지
- 현재 연구 방향은 새로운 Master 우선
- 구현 사실은 Git/source/test 우선
- 데이터 계약은 `RESEARCH_DATA_SCHEMA.md` 우선
- 단, 아직 구현되지 않은 future schema의 **확정 여부**는 해당 Decision Log entry를 함께 확인한다.
- Patch 4 exact canonical contract는 GOV-005 / OPEN-001이 우선하며, 기존 Step 1.5 세부안을 자동 확정하지 않는다.

---

## GOV-002 — Patch와 Research Stage를 분리

**Status:** CONFIRMED
**Logged:** 2026-10-01
**Decision timing:** Retrospective consolidation

### Decision

```text
Patch
= Foundation / infrastructure / reproducibility 작업

Research Stage
= F1/F2 가설·특징·실험·해석
```

으로 분리한다.

### Rationale

Foundation 번호를 연구 방법 설계까지 계속 늘리면
인프라 수정과 과학적 결정의 성격이 섞인다.

### Impact

- Foundation은 Patch 1~8 체계
- 이후 F1/F2는 Research Stage / Gate로 운영
- 과거 Patch 번호를 다시 매기지 않음

---

## GOV-003 — `RESEARCH_DATA_SCHEMA.md` §K의 번호는 운영 Patch 번호가 아님

**Status:** CONFIRMED
**Logged:** 2026-10-01
**Decision timing:** Current consistency decision

### Decision

`RESEARCH_DATA_SCHEMA.md` §K의 과거 내부 구현 순서 번호를
현재 operational Patch 번호로 사용하지 않는다.

현재 운영 순서는 `AIoT_RESEARCH_MASTER.md`를 따른다.

### Rationale

schema §K는 Patch 1~3 실제 구현 전에 작성된 설계 순서이며,
현재 프로젝트의 Patch 1~3 의미와 번호가 달라졌다.

### Impact

- history를 schema 번호에 맞춰 소급 재번호화하지 않음
- Patch 4 이후는 Master의 operational roadmap 사용
- schema는 데이터 계약 역할을 유지

---

## GOV-004 — AI 에이전트 보고서는 원문 보관보다 결정 중심으로 압축

**Status:** CONFIRMED
**Logged:** 2026-10-01
**Decision timing:** Retrospective consolidation; exact original timestamp not asserted

### Decision

Patch 진행 중 Codex/Claude 전체 보고서를 매번 영구 문서화하지 않는다.

복잡한 경우 임시 Worklog에:

```text
implementation round
review finding
fix
final verdict
```

만 누적한다.

Patch 완료 후 Foundation Record에 핵심 근거를 압축한다.

### Rationale

전체 AI transcript를 보관하면 연구 기록보다 도구 로그가 더 커지고,
실제 결정 근거를 찾기 어려워진다.

### Impact

- Worklog는 필요 시만 생성
- 덮어써서 과거 finding을 지우지 않음
- 최종 Foundation Record가 영구 기록

---

## GOV-005 — Step 1.5 future schema 세부를 Patch 4 pre-freeze proposal로 재분류

**Status:** CONFIRMED
**Logged:** 2026-10-01
**Decision timing:** Current governance decision before Patch 4 Design Freeze

### Decision

`RESEARCH_DATA_SCHEMA.md`의 Step 1.5 future canonical writer 설계 중
아직 구현되지 않은 exact Patch 4 field contract는 **Design Freeze 전 proposal**로 취급한다.

이 재분류는 최소 다음 위치의 동일 설계 의도를 함께 포함한다.

```text
§F.1 / §F.3 / §F.4의 exact header·field/version 후보
§K의 5a / 5b future implementation plan
§L의 "확정" 표현 중 Patch 4 exact raw contract 부분
§N.2 / §N.3의 신규 hip/arm exact contract 요약
```

현재 구현·검증된 Patch 1~3 provenance/lineage 동작을 되돌리지 않는다.
또한 F1/F2 exact formula나 Patch 4 exact field 값을 이 entry에서 새로 선택하지 않는다.

### Rationale

기존 Step 1.5 문서는 future 설계안과 당시 "확정" 표현이 섞여 있으나,
현재 Research Master는 Patch 4 exact schema를 별도 Design Freeze 대상으로 운영한다.
이 상태 차이를 기록하지 않으면 `OPEN-001`과 Schema의 권위가 충돌한다.

### Evidence / Source

- `RESEARCH_DATA_SCHEMA.md` §F, §K, §L, §N
- Claude READ-ONLY canonicalization audit B1/I2
- `OPEN-001`

### Impact

- 기존 candidate field 이름·순서·값은 검토 재료로 보존한다.
- `OPEN-001`이 닫히기 전에는 candidate를 final canonical contract로 해석하지 않는다.
- future/unimplemented schema section은 현재 구현 사실로 인용하지 않는다.
- Patch 4 Design Freeze 전에 Schema 본문에서도 이 status가 발견 가능해야 한다.

---

# 2. Research Framing Decisions

## RES-001 — M0/M1/M2 세 모델을 유지

**Status:** CONFIRMED
**Logged:** 2026-10-01
**Decision timing:** Retrospective consolidation

### Decision

```text
M0 = 일반 RF
M1 = 원 논문식 input-weighted RF
M2 = split-score weighted RF
```

세 모델을 유지한다.

### Rationale

- M1=M0 현상 자체가 연구 질문의 증거
- M2는 실제 split을 변경하는 비교안
- 한 모델만 남기면 초기 연구 질문과 비교 구조가 사라짐

### Alternatives

```text
M1 삭제
→ REJECTED

M2를 무조건 최종 방법으로 지정
→ REJECTED
```

### Impact

F1/F2가 추가되어도 M0/M1/M2 비교 축은 유지한다.

---

## RES-002 — M2의 현재 해석은 “작동하지만 안정적 gain 미확인”

**Status:** CONFIRMED
**Logged:** 2026-10-01

### Decision

M2에 대해:

```text
split change
= 확인

stable performance improvement
= 현재까지 미확인
```

으로 기록한다.

### Rationale

현재 결과를 성공 또는 실패로 과장하지 않기 위해서다.

### Evidence / Source

- `docs/foundation/FOUNDATION_PRELUDE_00_algorithm_and_capture_hardening.md`의 M0/M1/M2 공정성·rank-weight·root split 검증 기록
- 현재 source/test는 M2가 split behavior를 바꿀 수 있음을 검증하지만, 안정적 성능 향상 자체를 보장하지 않음

### Impact

M2를 원하는 결과가 나올 때까지 tuning하지 않는다.

---

## RES-003 — 특징 표현 문제를 독립 연구축으로 승격

**Status:** CONFIRMED
**Logged:** 2026-10-01

### Decision

새 환경에서의 성능 변화는
분류기 weighting만의 문제가 아니라:

```text
absolute position
coordinate system
camera placement
body geometry representation
```

과 관련된 특징 표현 문제로 별도 연구한다.

### Rationale

파일럿에서 feature 구성 변화의 영향이
M0/M1/M2 간 차이보다 크게 관찰됐다.

### Important wording

다음 표현은 사용하지 않는다.

```text
"병목은 무조건 분류기가 아니라 특징이다"
```

대신:

> 현재 예비 실험에서는 특징 표현의 영향이 분류기 weighting 방식보다 크게 관찰됐다.

### Evidence / Source

- Legacy own-data feature comparison의 historical preliminary observation
- 현재 repository에는 해당 비교 수치를 독립 재현할 원 결과 artifact가 없으므로 현재 frozen result로 간주하지 않음

### Impact

F1/F2 연구가 핵심 후속 단계가 됨.

---

# 3. Feature Decisions

## FEAT-001 — F0 / F_cal / F1 / F2 역할 분리

**Status:** CONFIRMED
**Logged:** 2026-10-01

### Decision

```text
F0
원 논문 baseline

F_cal
legacy upright-reference relative comparison

F1
calibration-free body-relative 2D geometry

F2
F1 + RGB-D / 3D body geometry
```

으로 정의한다.

### Rationale

기존 `all / invariant / relative` CLI 이름과
새 연구적 역할을 그대로 동일시하면
기존 비교법과 제안법이 혼동된다.

### Impact

기존 feature mode를 이름만 바꿔 F1/F2로 간주하지 않는다.

---

## FEAT-002 — F1/F2는 개인별 사전 posture calibration을 요구하지 않음

**Status:** CONFIRMED
**Logged:** 2026-10-01

### Decision

F1/F2 inference에서:

```text
처음 몇 초/몇십 초 정상 자세 측정
개인별 upright baseline
이전 upright reference
```

를 필수 입력으로 요구하지 않는다.

### Rationale

교수 피드백과 현재 연구 방향은
환경·개인 조건에 덜 의존하는 feature representation을 요구한다.

### Clarification

capture sequence의 upright와
F0/F_cal legacy 경로에서 사용하는 upright/reference 동작은 비교·재현 목적으로 유지 가능하다.

그 존재가 F1/F2 calibration requirement를 뜻하지 않는다.
`zero-personal-calibration`은 F1/F2의 requirement이며 legacy F0/F_cal을 calibration-free로 재해석하는 결정이 아니다.

### Impact

F1/F2 formula 설계에서 hidden reference dependency를 검사해야 한다.

---

## FEAT-003 — Face/Shoulder/Hip을 핵심 canonical body observations로 확보

**Status:** CONFIRMED
**Logged:** 2026-10-01

### Decision

향후 canonical raw observation에는 최소:

```text
face/head
left/right shoulder
left/right hip
```

관찰을 확보하는 방향을 유지한다.

### Rationale

head–shoulder–hip 관계가
body-relative trunk/head geometry와 sagittal RGB-D / metric 3D candidate를 설계할 수 있는 최소 구조를 제공한다.
특히 head-relative forward 변화와 whole-trunk-forward 변화를 별도로 분석할 수 있는 원재료가 된다.

### Important

이 결정은:

```text
특정 trunk angle
특정 ratio
특정 feature formula
```

를 F1/F2로 확정한 것이 아니다.

### Impact

Patch 4에서 hip raw observation이 핵심 대상이 된다.

---

## FEAT-004 — Elbow/Wrist는 primary 5-class의 필수/core feature로 확정하지 않음

**Status:** CONFIRMED
**Logged:** 2026-10-01
**Decision timing:** Current research scope decision before Patch 4 Design Freeze

### Decision

elbow/wrist는 현재:

```text
primary 5-class posture classifier의 필수/core feature가 아님
auxiliary upper-body / ergonomic context 후보
```

으로 취급한다.

elbow/wrist raw observation을 저장하는 것과 F1/F2 model feature로 사용하는 것은 별도 결정이다.
`arm-up/down` 등을 새로운 posture class로 자동 추가하지 않는다.

Patch 4 canonical raw schema에서 arm을 `include / reserve / exclude-and-version-later` 중 어떻게 처리할지는
본 entry가 아니라 `OPEN-001`에서 추적한다.

### Rationale

교수 피드백의 정정된 취지는 head/shoulder/hip뿐 아니라 elbow/wrist를 포함할 수 있는
**upper-body skeletal representation**을 검토하라는 방향에 가깝다.
따라서 elbow/wrist raw observation 확보의 연구적 근거는 이전보다 강해졌지만,
현재 연구 질문에서 primary classifier의 필수 입력 또는 새로운 class로 확정할 근거는 아직 부족하다.
raw 보존 가능성과 classifier 사용을 분리하면 연구 범위를 workstation 전체 ergonomics로 과도하게 확장하지 않을 수 있다.

### Impact

- 구현자가 arm field의 exact schema를 임의 결정하지 않는다.
- `OPEN-001`의 include/reserve/exclude 판단에서 skeletal/context 재사용 가치를 함께 검토한다.
- arm context를 사용할 경우에도 primary posture classification과 auxiliary context를 구분한다.
- desk/elbow relation은 현재 core classifier requirement가 아니다.

---

## FEAT-005 — Raw / Derived / Model Feature 계층 분리

**Status:** CONFIRMED
**Logged:** 2026-10-01

### Decision

```text
Canonical Raw Observation
Derived Geometry
Model Feature
```

세 계층을 분리한다.

### Rationale

raw schema에 특정 feature 가설을 직접 박아 넣으면
후속 feature 설계 변경 시 원자료까지 재정의되는 문제가 생긴다.

### Impact

Patch 4는 raw observation 중심.
F1/F2 formula는 Research Stage에서 결정.

---

## FEAT-006 — F2는 sagittal RGB-D / metric 3D geometry를 candidate family로 평가

**Status:** CONFIRMED
**Logged:** 2026-10-01
**Decision timing:** Current research-direction decision

### Decision

F2에서는 upper-body raw observations를 바탕으로
**sagittal-plane body-relative RGB-D / metric 3D geometry**를 candidate family로 평가한다.

주요 분석 목적 중 하나는 다음 confounder를 구별할 수 있는지 검토하는 것이다.

```text
head-forward relative to trunk
vs
whole-trunk-forward / trunk inclination
vs
whole-body translation
```

후보 개념에는 head–shoulder depth relation, shoulder–hip depth relation,
trunk-axis inclination proxy, head-to-trunk relative relation 등이 포함될 수 있다.

### Guardrail

이 entry는 다음을 확정하지 않는다.

```text
exact landmark set / graph structure
exact coordinate plane / projection
exact trunk-axis definition
exact angle/ratio/formula
feature count
normalization
classifier inclusion
```

정면 D455 RGB-D에서 얻는 값은 anatomical/clinical **actual spine angle**로 주장하지 않고,
`trunk-axis` / `trunk-inclination proxy` 또는 body-relative 3D geometry로 기술한다.

### Impact

exact F2 definition은 계속 `OPEN-003`에서 추적한다.

---

## FEAT-007 — Upper-body skeletal representation을 candidate representation 방향으로 유지

**Status:** CONFIRMED
**Logged:** 2026-10-01
**Decision timing:** Professor-feedback clarification before canonicalization

### Decision

얼굴 일부 또는 단일 면적 특징만으로 자세를 표현하는 방향에 한정하지 않고,
주요 upper-body landmark의 상대적 구조를 **skeletal / body-relative representation 후보**로 검토한다.

현재 후보 observation 범주는 다음과 같다.

```text
head / face
left/right shoulder
left/right hip
left/right elbow
left/right wrist
```

이 구조에서 다음과 같은 derived geometry 후보를 만들 수 있다.

```text
head-relative geometry
trunk geometry
left/right symmetry
arm configuration
sagittal RGB-D geometry
```

### Layering Rule

```text
Raw Observation
→ Derived Geometry
→ Selected Model Feature
```

을 분리한다.

raw landmark를 저장하거나 관찰 가능하게 만드는 것과,
그 landmark·angle·ratio를 RF classifier 입력으로 선택하는 것은 별도 결정이다.

### Guardrail

이 entry는 다음을 확정하지 않는다.

```text
exact landmark set
exact graph/edge structure
exact angle / ratio
exact normalization
exact feature count
exact feature selection
Patch 4 elbow/wrist include/reserve/exclude
```

elbow/wrist의 exact raw schema 처리는 계속 `OPEN-001`,
F1/F2 exact feature 정의는 `OPEN-002` / `OPEN-003`에서 추적한다.

---

## FEAT-008 — Face bbox vs contour/oval fidelity는 secondary exploratory analysis candidate

**Status:** DEFERRED

**Status semantics:** `secondary / exploratory`로 제한한다는 **scope guardrail 자체는 CONFIRMED**이며, 실제 분석 채택·exact metric·F1/F2 feature 포함·최종 논문 사용 여부가 DEFERRED다.
**Logged:** 2026-10-01
**Decision timing:** Professor-feedback clarification; final use intentionally deferred

### Decision

현재 분석에 이미 존재하는:

```text
face_area_px
oval_area_px
oval_size_cm2
box_to_oval
```

등을 이용하여 rectangular face bounding box와 facial contour/oval 표현의 차이를
**secondary / exploratory analysis candidate**로 검토할 수 있다.

후보 질문은 다음과 같다.

```text
bbox가 facial contour/oval을 얼마나 거칠게 근사하는가?
resolution / pixel localization / contour representation에 따라 차이가 어떻게 변하는가?
그 차이가 F0 계열 absolute/area feature의 한계를 설명하는 데 의미가 있는가?
```

### Guardrail

이 entry는 core contribution 또는 mandatory experiment를 확정하지 않는다.
또한 다음은 계속 미확정이다.

```text
exact area-error formula
exact evaluation metric
F1/F2 feature inclusion
final paper inclusion
```

새 sensor calibration 또는 known-target requirement로 해석하지 않는다.

---

# 4. Calibration / Posture Decisions

## CAL-001 — Upright의 세 역할을 구분

**Status:** CONFIRMED
**Logged:** 2026-10-01

### Decision

```text
1. capture sequence upright
2. F_cal reference upright
3. F1/F2 calibration-free inference
```

를 별도 개념으로 유지한다.

### Rationale

촬영 품질 reference와
classifier inference dependency를 혼동하지 않기 위해서다.

---

## POST-001 — `body_forward`는 정식 6번째 class가 아님

**Status:** CONFIRMED
**Logged:** 2026-10-01

### Decision

`body_forward`는:

```text
보조 분석 자세
```

로 유지한다.

정식 5-class metric에는 자동 포함하지 않는다.

### Rationale

원 논문 분류 class와의 비교 가능성을 유지하면서
head-forward relative to trunk와 whole-trunk-forward 차이를 분석하기 위한 confounder condition이다.
`body_forward` 자체를 새 primary class로 만드는 것이 목적이 아니다.

---

# 5. Capture / Sensor Decisions

## CAP-001 — Forward gate는 8~12cm face-only

**Status:** CONFIRMED
**Logged:** 2026-10-01

### Decision

```text
target: 0.08 ~ 0.12 m
boundaries: inclusive
source: face-only
```

를 유지한다.

body-only 또는 face/body mixed source는 hard gate를 통과시키지 않는다.

### Rationale

forward_head와 body_forward에서
얼굴 전진량을 공통 조건으로 맞추고
body/shoulder 변화는 관찰 대상으로 남기기 위해서다.

---

## CAP-002 — Shoulder/Hip movement를 촬영 hard gate로 미리 사용하지 않음

**Status:** CONFIRMED
**Logged:** 2026-10-01

### Decision

현재 단계에서는:

```text
shoulder movement threshold
shoulder/face ratio threshold
hip movement threshold
```

를 새로운 capture acceptance criterion으로 추가하지 않는다.

### Rationale

그 값들이 이후 F1/F2에서 검증할 candidate signal이므로
같은 signal로 데이터를 사전 선별하면 순환 논리가 생길 수 있다.

---

## CAP-003 — D455 operating-range는 실제 hardware validation으로 확인

**Status:** CONFIRMED
**Logged:** 2026-10-01

### Decision

추정으로:

```text
40cm fallback
새 거리 보정
새 capture threshold
특정 논문 한 편의 거리값을 formal distance로 자동 채택
```

를 추가하지 않는다.

운영 거리 결정은 다음 순서를 따른다.

```text
literature / ergonomics / D455 characteristics
→ candidate operating range 설정
→ actual D455 validation
→ landmark / depth / 3D geometry stability 확인
→ formal collection distance/range freeze
```

실제 D455 validation에서 최소 다음을 확인한다.

```text
actual-use distance
landmark acquisition stability
head/shoulder/hip depth valid rate
depth repeatability / jitter
3D geometry repeatability
RGB landmark + aligned-depth coupling stability
distance-dependent feature stability
```

### Impact

Foundation Patch 8에서 실제 hardware validation을 수행한다.
exact distance grid와 acceptance criterion은 `OPEN-006`이다.

---

## CAP-004 — Patch 8에 D455 measurement-quality validation을 포함

**Status:** CONFIRMED
**Logged:** 2026-10-01
**Decision timing:** Current validation-scope decision

### Decision

formal posture collection 전에 Patch 8에서
**D455-derived body geometry를 실제 자세 연구의 측정값으로 안정적으로 사용할 수 있는지**
measurement-quality validation을 수행한다.

검토 범주는 다음을 포함한다.

```text
actual-use distance에서 landmark acquisition stability
head / shoulder / hip depth valid rate
depth repeatability / jitter
3D geometry repeatability
RGB landmark와 aligned depth 결합의 안정성
distance 변화에 따른 feature stability
```

### Clarification

이 validation requirement는 교수의 "십자가 / 졸라맨" 또는 "edge / 면적 / pixel / segment" 표현을
cross/checkerboard/known geometric target calibration으로 해석한 결과가 아니다.
해당 교수 피드백의 주된 의미는 upper-body skeletal representation과 face representation fidelity 검토로 정정한다.

measurement-quality validation 자체는 D455 기반 body geometry를 연구 측정값으로 사용할 수 있는지 확인하기 위한
독립적인 연구 인프라 검증으로 유지한다.

### Impact

exact distance grid, repetition count, quality metric, tolerance/acceptance criterion은 `OPEN-006`에서 결정한다.
특정 checkerboard/cross/known target을 요구하지 않는다.

---

# 6. Data Role / Experiment Decisions

## DATA-001 — `pilot | formal | external` 역할 분리

**Status:** CONFIRMED
**Logged:** 2026-10-01

### Decision

dataset role은:

```text
pilot
formal
external
```

로 구분한다.

### Rationale

개발 데이터와 정식 평가 데이터를 결과를 본 뒤 섞는 것을 방지하기 위해서다.

---

## DATA-002 — 기존 P01/P02/legacy 촬영은 pilot 유지

**Status:** CONFIRMED
**Logged:** 2026-10-01

### Decision

기존 P01/P02 및 통제되지 않은 legacy 자체 촬영을
결과가 좋아 보인다는 이유로 formal로 승격하지 않는다.

### Rationale

촬영 시점에 현재 provenance/protocol/freeze 규칙이 적용되지 않았다.

---

## EXP-001 — Final external data는 method freeze 전 tuning에 사용하지 않음

**Status:** CONFIRMED
**Logged:** 2026-10-01

### Decision

different-condition final external set은:

```text
method freeze
→ 열람/평가
```

순서로 사용한다.

### Rationale

final test 결과를 보고 feature/threshold/model을 바꾸면
독립 검증이 아니게 된다.

### Impact

final external 결과를 본 뒤 F1/F2를 수정하지 않는다.

---

## EXP-002 — Formal collection은 Foundation 완료 후 시작

**Status:** CONFIRMED
**Logged:** 2026-10-01

### Decision

대규모 formal collection은 최소 다음이 완료된 뒤 시작한다.

```text
Patch 4
Patch 4.5
Patch 5
Patch 6
Patch 7
Patch 8
EXPERIMENT_PROTOCOL freeze
```

### Rationale

schema/model/lineage/selection/hardware 조건이
중간에 바뀌면 formal data의 해석이 흔들릴 수 있다.

### Clarification

pilot/smoke/hardware validation 촬영은 formal collection과 다르다.

---

# 7. Provenance / Data Integrity Decisions

## PROV-001 — Model provenance와 Model Lock은 별개

**Status:** CONFIRMED
**Logged:** 2026-10-01

### Decision

Patch 3:

```text
실제로 사용한 model artifact SHA-256 기록
```

은 완료됐다.

하지만:

```text
허용된 exact hash만 실행 가능
```

한 lock은 아직 아니다.

### Impact

별도:

```text
Foundation Patch 4.5 — MediaPipe Model Artifact Lock
```

을 수행한다.

---

## PROV-002 — Historical unknown은 추정으로 채우지 않음

**Status:** CONFIRMED
**Logged:** 2026-10-01

### Decision

과거:

```text
commit
model hash
protocol
author rationale
capture environment
```

을 확인할 수 없으면 `unknown`으로 남긴다.

### Rationale

현재 환경의 정보를 과거 provenance로 소급 기록하면
연구 이력이 사실보다 깨끗하게 조작된다.

---

## PROV-003 — Inherited prototype history를 새로 꾸미지 않음

**Status:** CONFIRMED
**Logged:** 2026-10-01

### Decision

연구 역사는:

```text
Phase 0     inherited handoff snapshot
Phase 0.5   retrospectively reconstructed pre-Git change
Phase 1+    Git-tracked / progressively controlled
```

로 기록한다.

과거에 존재하지 않은 commit이나
근거 없는 설계 이유를 만들어내지 않는다.

---

# 8. Result Interpretation Decisions

## RESLT-001 — Legacy own-data 수치는 preliminary historical evidence

**Status:** CONFIRMED
**Logged:** 2026-10-01

### Decision

대표 과거 값:

```text
all       ≈ 0.400
invariant ≈ 0.844
relative  ≈ 0.756
```

등은 현재 코드 기준 final result가 아니다.

### Rationale

이후:

```text
RNG isolation
rank-weight policy
relative non-reference evaluation
metrics/drop logging
```

이 보강됐다.

### Evidence / Source

- pre-canonical 연구 메모/인계 내용에서 이관된 historical preliminary observation
- 현재 repository에는 이 수치들의 exact originating result artifact 또는 독립 재현 파일이 남아 있지 않음
- 따라서 source provenance가 제한적이라는 사실 자체를 함께 보존하며 현재 재현 결과로 승격하지 않음

### Impact

최종 문서에 사용할 수치는 현재 frozen implementation으로 재실행한다.

---

## RESLT-002 — 과거 root split 비율을 목표값으로 재현하지 않음

**Status:** CONFIRMED
**Logged:** 2026-10-01

### Decision

과거 기록의 root ratio를
현재 code가 맞춰야 하는 target으로 사용하지 않는다.

### Rationale

RNG/weight policy가 수정된 뒤
현재 조건의 실제 결과가 새로운 증거다.

### Evidence / Source

- `docs/foundation/FOUNDATION_PRELUDE_00_algorithm_and_capture_hardening.md`의 RNG isolation, rank-weight consistency, root split provenance 기록
- `docs/history/RETROSPECTIVE_01_PRE_GIT_CHANGES.md`의 관련 변경 복원 기록

---

# 9. Current Deferred Research Decisions

아래 항목은 **미정이라는 사실 자체가 현재 결정**이다.

구현자는 임의 선택하지 않는다.

---

## OPEN-001 — Patch 4 exact canonical field contract

**Status:** DEFERRED
**Logged:** 2026-10-01
**Decision timing:** Current consistency decision before Patch 4 Design Freeze

`RESEARCH_DATA_SCHEMA.md`의 Step 1.5 future canonical writer 세부안은
`GOV-005`에 따라 **pre-freeze proposal**이며 이 OPEN item을 닫지 않는다.
이는 §F뿐 아니라 동일 설계를 요약·참조하는 §K/§L/§N의 future Patch 4 문구에도 적용한다.

미확정:

```text
canonical schema/version label의 최종값
canonical exact field list / count / order
F.3 metadata·enum 중 Patch 4에 실제 채택할 exact contract
hip depth field naming
hip depth ROI / extraction contract
raw validity / missing serialization의 exact contract
elbow/wrist include / reserve / exclude-and-version-later
boolean writer/reader final contract 표현
```

기존 구현의 값·의미를 임의 변경한다는 뜻은 아니다.
Patch 4 Design Freeze에서 필요한 exact contract만 명시적으로 결정한다.

---

## OPEN-002 — F1 exact definition

**Status:** DEFERRED
**Logged:** 2026-10-01
**Decision timing:** Current research decision; exact formula intentionally deferred

미확정:

```text
exact upper-body skeletal landmark set / graph or edge structure
exact formulas
feature count
coordinate/body-relative basis
normalization
missing policy
feature selection
```

Research Stage 1에서 Gate 단위로 결정.

---

## OPEN-003 — F2 exact definition

**Status:** DEFERRED
**Logged:** 2026-10-01
**Decision timing:** Current research decision; F1 freeze 이후로 intentionally deferred

미확정:

```text
exact upper-body skeletal landmark set / graph or edge structure
3D formulas
feature count
depth missing policy
exact sagittal coordinate / projection convention
head / shoulder / hip 및 선택적 arm landmark의 exact representative point
exact trunk-axis definition
head–shoulder / shoulder–hip / head-to-trunk 관계의 exact geometry
normalization과 classifier inclusion / feature selection
```

F1 freeze 이후 결정한다.
`FEAT-006`은 candidate family와 confounder 분석 목적만 확정하며 actual spine angle 측정을 주장하지 않는다.

---

## OPEN-004 — `rank_weights` policy for >6 features

**Status:** DEFERRED
**Logged:** 2026-10-01
**Decision timing:** Current research decision; first p > 6 M0/M1/M2 comparison 이전에 결정

현재 구현에서 `rank_weights()`는 `p > 6`을 명시적 policy 없이 자동 확장하지 않으며,
이 값은 M1과 M2 양쪽의 weighting 경로에 사용된다.
따라서 `p > 6`이면 M2만의 문제가 아니라 현재 `fit_models()` 비교 경로 전체가 진행되지 않는다.

F1 또는 F2 중 **최초로 `p > 6`인 feature set으로 M0/M1/M2 비교를 실행하기 전** exact policy를 결정한다.
F2 단계까지 자동 유예하지 않는다.
M1과 M2가 어떤 exact policy를 공유할지/어떻게 정의할지는 계속 미확정이다.

---

## OPEN-005 — Formal experiment exact protocol

**Status:** DEFERRED
**Logged:** 2026-10-01
**Decision timing:** Current research decision; protocol freeze 전까지 deferred

미확정:

```text
participant count
round count
exact inclusion/exclusion
ok_with_warnings eligibility
seed list
λ grid
λ selection rule
formal metric set
```

`EXPERIMENT_PROTOCOL.md` freeze 전에 확정.

---

## OPEN-006 — D455 validation exact grid

**Status:** DEFERRED
**Logged:** 2026-10-01
**Decision timing:** Current research decision; Patch 8 validation plan 전까지 deferred

미확정:

```text
literature / ergonomics / D455 evidence를 candidate range에 반영하는 exact 절차
거리 grid
반복 수
landmark acquisition stability의 exact metric
head/shoulder/hip depth valid-rate의 exact 정의
depth repeatability / jitter metric
3D geometry repeatability metric
RGB landmark + aligned-depth coupling metric
distance-dependent feature stability metric
오차/변동 산출법
acceptance criterion
```

`70~90 cm` 같은 숫자는 이 entry를 닫지 않는다.
checkerboard/cross/known geometric target은 교수 피드백에서 도출된 requirement가 아니며,
현재 OPEN-006의 필수 결정 항목으로 두지 않는다.
Patch 8 계획 확정 전에 필요한 exact validation protocol을 결정한다.

---

# 10. Future Entry Rule

앞으로 중요한 연구 결정을 내릴 때:

```text
1. Decision Log에 새 entry 추가
2. 영향받는 Master 항목 갱신
3. 데이터 계약 변경이면 RESEARCH_DATA_SCHEMA 갱신
4. 구현은 그 다음
```

canonicalization 이후 기존 entry는 수정하지 않는다.
기존 결정을 대체하면 새 entry에 `Supersedes: <ID>`, OPEN을 해소하면 `Resolves: <OPEN-ID>`를 기록한다.
과거 OPEN entry 자체의 Status를 사후 변경하지 않는다.

순서를 권장한다.

특히 다음은 **결정 기록 없이 바로 구현하지 않는다.**

```text
F1/F2 formula
depth ROI
missing policy
calibration semantics
label/class
evaluation split
selection/inclusion
M0/M1/M2 definition
final-test 결과를 본 parameter 변경
```

---

# 11. Version Log

| Version | Date | Summary |
|---|---|---|
| `v1.0` | 2026-10-01 | 현재 Research Master를 만들면서 기존 대화·schema·history·Foundation 기록에서 이미 확정된 연구/데이터/실험/거버넌스 결정을 최초 통합. 미확정 항목은 OPEN entry로 분리 |
| `v1.1` | 2026-10-01 | `DATA-003`을 append하여 Patch 4 `frames-schema/1.0.0` exact canonical frame contract를 freeze하고 `OPEN-001`을 해소 |
| `v1.2` | 2026-10-04 | `PROV-004`를 append하여 Patch 4.5 MediaPipe Model Artifact Lock의 exact artifact set, source/version identity, SHA-256, fail-closed verification, verified provisioning, Patch 3 provenance linkage 및 scope를 Design Freeze |
| `v1.3` | 2026-10-04 | `PROV-005`를 append하여 Patch 5 End-to-End Lineage Hardening의 raw SHA identity collision, `summary-schema/1.0.0`, immutable RF input resolution, `rf-sample-lineage/1.0.0`, `rf-experiment-provenance/1.0.0`, Patch 6 selection boundary를 Design Freeze |

---

# 12. Post-Canonicalization Decision Entries

## DATA-003 — Patch 4 canonical frame contract Design Freeze

**Status:** CONFIRMED
**Logged:** 2026-10-01
**Decision timing:** Patch 4 Design Freeze after research-document canonicalization and agent-authority alignment

### Decision

Patch 4의 최초 fixed canonical frame contract를 다음과 같이 freeze한다.

```text
frame schema label
= frames-schema/1.0.0

legacy pre-Patch-4 dynamic frame CSV
= unversioned legacy format

canonical header
= legacy 31-field ordered prefix
  + Patch 4 metadata/state 17 fields
  + bilateral hip raw-observation 12 fields
= total 60 fields
```

기존 31개 field는 이름·순서·단위·계산 의미를 그대로 보존한다. 신규 field는 뒤에만 append한다.

### Exact ordered Patch 4 extension

기존 31개 뒤의 17개 metadata/state field는 다음 순서로 고정한다.

```text
frame_schema_version
recording_id
analysis_run_id
frame_index
color_frame_number
depth_frame_number
mediapipe_ts_ms
face_depth_source
face_detected
face_mesh_detected
pose_detected
face_depth_valid
lsh_valid
rsh_valid
lsh_depth_valid
rsh_depth_valid
shoulder_depth_source
```

그 뒤 bilateral hip raw-observation 12개를 다음 순서로 고정한다.

```text
left_hip_x_px
left_hip_y_px
left_hip_depth_m
left_hip_visibility
left_hip_valid
left_hip_depth_valid
right_hip_x_px
right_hip_y_px
right_hip_depth_m
right_hip_visibility
right_hip_valid
right_hip_depth_valid
```

### Identity / provenance contract

canonical frame-row key는 다음이다.

```text
(analysis_run_id, recording_id, frame_index)
```

`frame_index`는 trim / `--step` filtering 전에 증가하는 **1-based source playback traversal index**다. 따라서 canonical CSV에서 연속일 필요가 없다.
`color_frame_number`와 `depth_frame_number`는 supporting source-frame provenance이며 canonical key에는 포함하지 않는다.

source enum은 다음을 사용한다.

```text
face_depth_source:
  bbox_roi
  oval_center_roi
  missing

shoulder_depth_source:
  both
  left_only
  right_only
  missing
```

`unknown_legacy`는 legacy reader/canonical view에서만 허용하며 새 `frames-schema/1.0.0` writer가 생성하지 않는다.

### Geometric validity / depth contract

Hip의 `*_valid`는 visibility threshold가 아니라 **geometric in-frame validity**다.

```text
pose result 존재
AND x/y finite
AND 0 <= normalized x < 1
AND 0 <= normalized y < 1
→ hip_valid = true
```

hip가 out-of-frame 또는 otherwise invalid이면 x/y와 depth는 missing, `hip_valid=false`, `hip_depth_valid=false`이며 depth extraction을 시도하지 않는다. MediaPipe visibility는 별도 raw value로 보존하며 Patch 4 acceptance threshold로 사용하지 않는다.

Hip depth는 기존 shoulder `median_depth()` primitive를 재사용한다.

```text
ROI half-width = 6 px
valid raw depth pixel = raw_depth > 0
minimum valid raw depth pixels = 10
reduction = median
unit conversion = recording depth_scale → meters
```

in-frame hip에서 depth를 얻지 못하면 `hip_valid=true`를 유지하고 depth만 missing, `hip_depth_valid=false`로 기록한다. Patch 4는 hip 전용 ROI tuning, visibility threshold, interpolation/reconstruction rule을 추가하지 않는다.

`lsh_valid/rsh_valid`는 기존 shoulder landmark가 실제 color-frame bounds 안에 있는지를 나타내는 신규 canonical state다. D02의 legacy 31-field 보존 때문에 기존 `lsh_x/rsh_x/z_lsh_m/z_rsh_m` 계산값 자체를 소급 변경하지 않는다. canonical `lsh_depth_valid/rsh_depth_valid`와 `shoulder_depth_source`는 새 in-frame validity를 함께 고려하여 해석한다.

### Missing / boolean serialization

```text
Python missing observation → None
CSV missing numeric/string observation → empty cell
JSON equivalent → null
```

numeric sentinel `0`, `-1` 또는 임의 보간값으로 missing을 채우지 않는다. explicit state/source enum의 literal `missing`은 빈 measurement cell과 별개다.

canonical boolean CSV 표현은 lowercase ASCII다.

```text
true  → True
false → False
empty → None / unknown
```

새 writer는 canonical boolean에 `0/1`을 사용하지 않는다. legacy에서 새 state를 복원할 수 없으면 false로 강제하지 않고 unknown으로 남긴다.

### Arm disposition

`frames-schema/1.0.0`에는 elbow/wrist raw-observation column을 **포함하지 않고 예약 빈 열도 두지 않는다**.

```text
elbow/wrist
→ exclude-and-version-later
```

향후 연구상 필요성이 확인되면 명시적 schema-version update로 추가한다. 이 제외는 formal 촬영에서 elbow/wrist coverage가 보장된다는 뜻이 아니다. 이후 raw 재추출 가능성은 촬영 당시 실제 RGB/depth 관측 가능성, raw 보존, 고정 model artifact 등에 조건부다. formal collection 전 framing/coverage 위험은 `OPEN-005` / `OPEN-006`의 protocol·hardware-validation 경로에서 별도로 다룬다. Patch 4에서 새 capture acceptance threshold를 도입하지 않는다.

### Rationale

Patch 4의 목적은 F1/F2 feature를 설계하는 것이 아니라, 현재 dynamic frame writer를 재현 가능한 fixed raw-observation contract로 바꾸고 FEAT-003에서 확정한 hip observation을 안전하게 추가하는 것이다. 기존 31개 값의 의미를 보존하고 raw observation / derived geometry / selected model feature를 분리해야 이후 연구 가설이 데이터 원재료 계약을 소급 변경하지 않는다.

또한 static code audit에서 현재 capture가 hip/elbow/wrist in-frame/depth coverage를 보증하지 않고, 기존 shoulder depth 경로도 landmark image-bound state를 별도 기록하지 않는 점을 확인했다. 따라서 Patch 4는 coverage hard gate를 새로 만들지 않고 in-frame/depth validity를 표현하며, 실제 coverage 검증은 후속 protocol/hardware-validation 결정으로 분리한다.

### Evidence / Source

- `analyze_d455.py`의 현재 dynamic `write_csv()`와 shoulder/depth extraction 경로
- `test_analysis_provenance.py`의 legacy 31-field regression baseline
- `FEAT-003`, `FEAT-004`, `FEAT-007`, `CAP-004`
- `GOV-005`, `OPEN-001`
- `RESEARCH_DATA_SCHEMA.md` §F / §J / §K / §L / §N
- Patch 4 Design Freeze D01~D11 review and final ratification at repository baseline `065c823e17fcc01206b07d93a07256046694d2ed`

### Impact

- 이 entry가 `OPEN-001`을 해소한다. append-only 규칙에 따라 과거 `OPEN-001` entry의 `Status: DEFERRED`는 수정하지 않는다.
- `RESEARCH_DATA_SCHEMA.md`의 Patch 4 pre-freeze proposal을 본 결정에 맞는 frozen-but-unimplemented contract로 갱신한다.
- Patch 4 구현은 이 contract를 따라야 하며, 본 entry 자체는 구현 완료를 의미하지 않는다.
- F1/F2 exact formula·derived geometry는 계속 `OPEN-002` / `OPEN-003`이다.
- `rank_weights`의 p>6 정책은 계속 `OPEN-004`다.
- formal framing/coverage protocol과 D455 exact validation plan은 계속 `OPEN-005` / `OPEN-006`이다.
- hip midpoint, trunk axis/angle, sagittal projection, arm feature/class는 Patch 4 canonical raw field에 추가하지 않는다.

Supersedes:
Resolves: OPEN-001


## PROV-004 — Patch 4.5 MediaPipe Model Artifact Lock Design Freeze

**Status:** CONFIRMED
**Logged:** 2026-10-04
**Decision timing:** Patch 4.5 Design Freeze after local artifact / source-byte cross-verification and before implementation

### Decision

Foundation Patch 4.5에서 MediaPipe inference에 사용되는 model artifact의 exact identity와 provisioning contract를 다음과 같이 freeze한다.

Patch 3은 실제 분석 실행에서 filesystem에 존재하는 model artifact의 SHA-256을 provenance에 기록하지만, 허용된 model bytes 자체를 강제하지는 않는다.

Patch 4.5에서는:

```text
tracked model lock manifest
+
exact artifact filename
+
exact source locator
+
exact version identifier
+
exact SHA-256
```

을 canonical model artifact contract로 사용한다.

raw MediaPipe inference는 이 contract를 통과한 artifact만 사용할 수 있다.

---

### 1. Lock manifest

repository root에 다음 tracked manifest를 둔다.

```text
mediapipe_model_lock.json
```

lock schema version은:

```text
mediapipe-model-lock/1.0.0
```

으로 고정한다.

canonical top-level structure는:

```json
{
  "lock_schema_version": "mediapipe-model-lock/1.0.0",
  "artifacts": [
    ...
  ]
}
```

이다.

각 artifact entry의 필수 field는 정확히 다음과 같다.

```text
role
filename
source_url
version_identifier
sha256
```

canonical artifact role은 정확히:

```text
face
mesh
pose
```

세 개다.

SHA-256 textual representation은 lowercase 64-hex를 canonical representation으로 사용한다.

Patch 4.5는 downloaded runtime model binary와 tracked lock contract를 분리한다.

---

### 2. Frozen artifact set

#### face

```text
role:
face

filename:
blaze_face_short_range.tflite

source_url:
https://storage.googleapis.com/mediapipe-models/face_detector/blaze_face_short_range/float16/1/blaze_face_short_range.tflite

version_identifier:
1

sha256:
b4578f35940bf5a1a655214a1cce5cab13eba73c1297cd78e1a04c2380b0152f
```

Windows에서 실제 사용된 local artifact와 위 versioned `/1/` source에서 다시 다운로드한 artifact의 SHA-256이 동일함을 확인했다.

---

#### mesh

```text
role:
mesh

filename:
face_landmarker.task

source_url:
https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task

version_identifier:
1

sha256:
64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff
```

Windows에서 실제 사용된 local artifact와 위 versioned `/1/` source에서 다시 다운로드한 artifact의 SHA-256이 동일함을 확인했다.

---

#### pose

```text
role:
pose

filename:
pose_landmarker_full.task

source_url:
https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/latest/pose_landmarker_full.task?generation=1682642787774579

version_identifier:
gcs-generation:1682642787774579

sha256:
4eaa5eb7a98365221087693fcc286334cf0858e2eb6e15b506aa4a7ecdcec4ad
```

Pose artifact는 단순 versioned `/1/` source를 사용하지 않는다.

실제 source-byte 검증 결과:

```text
local artifact SHA-256
=
4eaa5eb7a98365221087693fcc286334cf0858e2eb6e15b506aa4a7ecdcec4ad

current unqualified /latest/ SHA-256
=
4eaa5eb7a98365221087693fcc286334cf0858e2eb6e15b506aa4a7ecdcec4ad

/1/ SHA-256
=
5134a3aad27a58b93da0088d431f366da362b44e3ccfbe3462b3827a839011b1
```

로 확인되었다.

`/2/`~`/5/` numbered paths도 확인했으나 해당 object는 존재하지 않았다.

따라서 `/1/` artifact를 현재 연구에서 실제 사용한 Pose artifact라고 간주하지 않는다.

현재 `/latest/` object의 Google Cloud Storage metadata에서:

```text
generation:
1682642787774579

ETag:
"5a9ad88919b2231d02b1fdf4a54090ec"

Last-Modified:
Fri, 28 Apr 2023 00:46:27 GMT

Content-Length:
9398198
```

를 확인했다.

동일 generation을 명시한 source locator에서 artifact를 다시 다운로드한 결과 SHA-256이 local research artifact와 정확히 일치했다.

따라서 Pose의 canonical source는 unqualified `/latest/`가 아니라:

```text
/latest/...task?generation=1682642787774579
```

인 generation-qualified source locator로 freeze한다.

ETag, Last-Modified 및 Content-Length는 cross-verification evidence이며 canonical integrity criterion은 SHA-256이다.

generation-qualified object의 향후 원격 보존 가능성 자체를 보장한다고 가정하지 않는다. 원격 source availability와 별개로 exact SHA-256 verification은 항상 필수다.

---

### 3. Artifact change policy

위 artifact의 다음 항목 중 하나라도 변경하려면 silent replacement로 처리하지 않는다.

```text
filename
model variant
precision
source locator
version identifier
expected SHA-256
```

변경이 필요한 경우 별도의 explicit research/reproducibility decision과 lock update를 수행한다.

동일 filename이라는 이유만으로 다른 bytes를 동일 artifact로 간주하지 않는다.

---

### 4. Existing artifact verification

`models/<filename>`이 이미 존재하면 network provisioning보다 먼저 전체 file SHA-256을 계산한다.

```text
actual SHA-256 == locked SHA-256
→ PASS
→ 기존 artifact 사용

actual SHA-256 != locked SHA-256
→ HARD FAIL
```

existing artifact mismatch 시 다음 동작을 하지 않는다.

```text
자동 overwrite
자동 redownload
자동 삭제
자동 rename
자동 quarantine
```

기존 mismatch artifact는 원인 조사 가능성을 위해 그대로 보존한다.

HARD FAIL diagnostic에는 최소:

```text
artifact path
expected SHA-256
actual SHA-256
```

을 포함한다.

mismatch가 존재하는 상태에서 다른 source에서 자동으로 대체 artifact를 받아 실행을 계속하지 않는다.

---

### 5. Missing artifact provisioning

locked artifact가 존재하지 않는 경우에만 network provisioning을 허용한다.

download source는 해당 manifest entry의 exact `source_url`만 사용한다.

```text
artifact missing
→ exact locked source_url에서 temporary download
→ complete SHA-256 verification
→ expected SHA-256과 일치
→ verified final install
```

다음 자동 fallback은 허용하지 않는다.

```text
unqualified /latest/
다른 numbered version
다른 generation
다른 mirror
다른 model variant
다른 precision
임의 fallback URL
```

단, Pose에 freeze된 generation-qualified `/latest/...?...generation=...` locator는 unqualified `/latest/`와 구분하며 허용한다.

사용자가 model artifact를 수동으로 provision하는 것은 허용한다.

그러나 수동으로 배치한 artifact도 동일한 locked SHA-256 verification을 반드시 통과해야 한다.

---

### 6. Verified temporary download and final install

network bytes를 final model path에 직접 다운로드하지 않는다.

동일 model directory의 temporary artifact 또는 동일 filesystem에서 atomic finalization이 가능한 temporary artifact를 사용한다.

```text
temporary download
→ download completion
→ SHA-256 계산
→ expected SHA-256과 비교
```

hash가 일치할 때만 final model path로 설치한다.

downloaded bytes mismatch 시:

```text
HARD FAIL
temporary artifact 정리
invalid final artifact 설치 금지
```

로 한다.

network error, interrupted download 또는 provisioning failure 시에도:

```text
HARD FAIL
incomplete final artifact를 남기지 않음
```

을 보장한다.

verified install은 가능한 범위에서 atomic final install semantics를 사용한다.

Patch 4.5의 명시적 contract는 기존 final artifact를 자동 overwrite하지 않는 것이다.

download 중 다른 process가 destination을 생성한 경우에도 기존 destination을 무조건 교체하지 않고 해당 destination을 다시 검증한다.

악의적 concurrent filesystem mutation에 대한 완전한 adversarial race-proof protocol은 Patch 4.5 scope에 포함하지 않는다.

---

### 7. Manifest validation

raw MediaPipe inference를 수행하는 경로에서는 model provisioning 또는 model loading보다 먼저 lock manifest를 읽고 검증한다.

다음은 HARD FAIL이다.

```text
manifest missing
malformed JSON
unsupported lock_schema_version
invalid top-level structure
artifacts structure malformed
required role missing
duplicate role
unknown role
required field missing
invalid filename contract
invalid SHA-256 representation
invalid source_url
invalid version_identifier
```

`mediapipe-model-lock/1.0.0`에서 canonical artifact set은 정확히:

```text
face
mesh
pose
```

세 개다.

unqualified `/latest/` source는 canonical lock source로 허용하지 않는다.

단, Pose와 같이 exact Google Cloud Storage generation이 명시된 generation-qualified locator는 해당 exact artifact를 식별하는 locked source로 허용한다.

lock schema contract를 변경할 경우 기존 `1.0.0` 의미를 silently 변경하지 않고 명시적 schema-version update 또는 후속 decision을 사용한다.

---

### 8. Patch 3 analysis provenance linkage

Patch 3의 기존 analysis provenance field set을 유지한다.

Patch 4.5 이후 raw inference의 성공 invariant는:

```text
actual filesystem artifact SHA-256
==
lock manifest expected SHA-256
```

이다.

completed raw analysis provenance의 각 model entry에서:

```text
sha256
```

은 실제 사용한 filesystem artifact의 SHA-256이며 동시에 corresponding lock entry의 SHA-256과 일치해야 한다.

기존 provenance field:

```text
source_url
version_identifier
```

에는 해당 lock entry의 frozen source/version 정보를 기록한다.

현재 `source_url_kind` field와 전체 model provenance field set을 Patch 4.5만을 위해 불필요하게 확장하지 않는다.

Patch 4.5를 위해 별도의 duplicate `expected_sha256` provenance field를 추가하지 않는다.

source of truth의 역할은 다음과 같이 구분한다.

```text
mediapipe_model_lock.json
→ 허용된 model artifact contract

analysis provenance
→ 해당 실행에서 실제로 사용한 artifact 기록
```

raw inference가 완료됐다면 두 SHA-256은 동일해야 한다.

---

### 9. Historical provenance

Patch 4.5 이전 analysis provenance를 현재 lock 정보로 소급 수정하지 않는다.

과거 provenance에:

```text
/latest/ source
version_identifier = unknown / null
historical model information
```

등이 기록되어 있다면 당시 상태 그대로 유지한다.

현재 확인된 generation/version/hash 정보를 과거 실행 당시 이미 알고 있었던 정보처럼 backfill하지 않는다.

이는 `PROV-002`의 historical-unknown policy를 유지한다.

---

### 10. `--from-csv` policy

`--from-csv` reprocessing은 새로운 MediaPipe inference를 수행하지 않는다.

따라서:

```text
raw MediaPipe inference
→ current lock manifest 필수
→ current model verification 필수

--from-csv
→ current local model provisioning 불필요
→ current model verification 불필요
```

로 구분한다.

`--from-csv`는 parent lineage의 historical model provenance를 유지하며, 현재 local model artifact를 새로 사용한 것처럼 기록하지 않는다.

따라서 current lock manifest의 부재 또는 current model artifact의 부재가 historical CSV-only reprocessing 자체를 불필요하게 차단해서는 안 된다.

---

### 11. MediaPipe Python package version

Windows Early Hardware Preflight 환경에서 실제 확인된 MediaPipe package version은:

```text
mediapipe = 1.0.1
```

이다.

이 값은 existing analysis environment provenance의 관찰값으로 유지한다.

그러나 Patch 4.5에서는 Python package dependency 자체를 model artifact lock에 포함하지 않는다.

```text
MediaPipe model bytes
→ HARD LOCK

MediaPipe Python package version
→ environment provenance record
```

로 구분한다.

전체 Python dependency/environment lock은 Patch 4.5 scope가 아니다.

---

### 12. Runtime model directory / Git policy

downloaded runtime model binary는 tracked lock contract와 역할을 분리한다.

```text
models/
→ runtime/local artifact storage

mediapipe_model_lock.json
→ canonical tracked model lock
```

Patch 4.5 implementation에서 accidental model binary commit을 방지하기 위해 `models/`를 repository ignore policy에 포함하는 것은 허용한다.

model binary 자체를 Git에 commit하는 것은 Patch 4.5의 canonical artifact-lock 방식으로 채택하지 않는다.

---

### 13. Test contract

Patch 4.5 implementation은 최소 다음을 자동 검증해야 한다.

```text
1. existing artifact hash == expected lock hash
   → PASS
   → network access 없음

2. existing artifact bytes 변경
   → HARD FAIL
   → automatic download 없음
   → existing bytes 보존

3. artifact missing
   → exact locked source에서 download
   → expected hash 일치 시 verified install + PASS

4. downloaded bytes hash mismatch
   → HARD FAIL
   → invalid final artifact 설치 금지

5. network/download failure
   → HARD FAIL
   → incomplete final artifact 금지

6. raw inference에서 lock manifest missing
   → FAIL

7. malformed / invalid lock manifest
   → FAIL

8. missing / duplicate / unknown artifact role
   → FAIL

9. invalid SHA-256 / source / version contract
   → FAIL

10. unqualified /latest/ source
    → FAIL

11. exact generation-qualified Pose source
    → valid lock source

12. completed raw analysis provenance model SHA-256
    = actual filesystem SHA-256
    = lock SHA-256

13. raw analysis provenance source_url / version_identifier
    = corresponding frozen lock values

14. --from-csv
    → current model provisioning/verification을 수행하지 않음
    → historical parent model provenance 보존

15. Patch 4 canonical frame contract
    → frames-schema/1.0.0
    → exact 60 fields
    → regression 없음

16. 기존 Patch 4 baseline tests
    → 모두 계속 PASS

17. 신규 Patch 4.5 tests
    → 모두 PASS
```

Patch 4 baseline은 Design Freeze 시점 repository에서:

```text
171 tests PASS
```

로 검증되어 있다.

따라서 Patch 4.5 acceptance criterion은 특정 총 test count를 171로 유지하는 것이 아니라:

```text
all previous 171 tests remain PASS
+
all new Patch 4.5 tests PASS
```

이다.

Windows에서는 기존 text encoding 환경 차이를 고려하여 필요 시:

```powershell
$env:PYTHONUTF8="1"
python -B -m unittest -q
```

로 전체 regression suite를 검증한다.

---

### 14. Foundation Record requirement

Patch 4.5 구현·테스트·독립 READ-ONLY audit가 완료된 뒤 별도 Foundation Record를 작성한다.

Foundation Record에는 최소:

```text
Design Freeze authority = PROV-004
implemented lock manifest
implemented verification/provisioning behavior
test evidence
regression result
independent audit result
remaining deferred items
implementation / documentation commit references
```

를 기록한다.

본 `PROV-004` entry 자체는 Patch 4.5 구현 완료 또는 audit 완료를 의미하지 않는다.

---

### Rationale

현재 `analyze_d455.py`는 model artifact가 없으면 configured `/latest/` URL에서 다운로드하고, 이미 artifact가 존재하면 exact allowed SHA-256 verification 없이 사용한다.

Patch 3은 실제 사용 artifact의 SHA-256을 provenance에 기록하지만:

```text
실제로 무엇을 사용했는가
```

를 기록하는 것과:

```text
어떤 artifact만 사용하도록 허용하는가
```

를 강제하는 것은 별개의 문제다.

Patch 4.5 source-byte cross-verification 과정에서 실제로 다음이 확인되었다.

```text
pose_landmarker_full.task

local research artifact
= current /latest/ bytes
= generation 1682642787774579 bytes
= SHA-256 4eaa5e...

하지만:

/1/ bytes
= SHA-256 5134a3...
```

즉 동일 filename과 동일 byte length를 가지더라도 source/version에 따라 다른 model bytes가 존재할 수 있다.

따라서 filename 또는 mutable `/latest/` path만으로 research model identity를 정의하는 것은 충분하지 않다.

Patch 4.5는:

```text
exact source/version identity
+
exact SHA-256
+
fail-closed verification
```

을 통해 silent model drift를 차단한다.

---

### Alternatives / Rejected / Deferred

다음은 채택하지 않는다.

```text
unqualified /latest/ URL을 canonical lock source로 사용
filename만으로 artifact identity 판단
동일 file size를 동일 artifact의 근거로 사용
Pose /1/ artifact를 실제 사용 artifact로 간주
hash mismatch 시 자동 overwrite
hash mismatch 시 자동 redownload
downloaded artifact를 hash verification 없이 설치
다른 version/mirror로 자동 fallback
historical provenance에 현재 lock 정보를 소급 삽입
Patch 3 provenance schema를 불필요하게 확장
--from-csv에 current model availability를 강제
MediaPipe package 전체 dependency lock을 Patch 4.5에 포함
```

다음은 별도 scope로 남긴다.

```text
full Python dependency/environment lock
general repository-wide artifact integrity framework
remote source long-term archival guarantee
malicious concurrent filesystem mutation threat model
Patch 5 end-to-end lineage hardening
Patch 7 general integrity checker
```

---

### Evidence / Source

- current repository `analyze_d455.py`의 MediaPipe model download/loading implementation
- Patch 3 analysis provenance implementation 및 Foundation Record
- `PROV-001` — Model provenance와 Model Lock은 별개
- `PROV-002` — Historical unknown은 추정으로 채우지 않음
- `AIoT_RESEARCH_MASTER.md`의 Patch 4.5 requirement
- Windows actual MediaPipe environment: `mediapipe 1.0.1`
- Windows local artifact `Get-FileHash -Algorithm SHA256` 결과
- versioned `/1/` source-byte download verification
- Pose `/1/`과 actual `/latest/` artifact의 SHA-256 불일치 확인
- Pose `/2/`~`/5/` numbered source availability 확인
- Pose current `/latest/` Google Cloud Storage generation metadata 확인
- Pose generation-qualified source 재다운로드 후 SHA-256 재검증
- Patch 4 baseline regression: 171 tests PASS

본 evidence는 Patch 4.5 Design Freeze의 근거이며 Patch 4.5 implementation 완료 사실을 의미하지 않는다.

---

### Impact

- Patch 4.5 implementation은 본 exact artifact/source/hash contract를 따라야 한다.
- `PROV-001`을 supersede하지 않는다.
- `PROV-001`에서 별도 Foundation 작업으로 남긴 model lock을 본 entry에서 구체적인 executable contract로 freeze한다.
- raw MediaPipe inference는 locked artifact 검증을 통과해야 한다.
- historical analysis provenance는 수정하지 않는다.
- Patch 3 analysis provenance field set은 가능한 범위에서 유지한다.
- Patch 4 `frames-schema/1.0.0` exact 60-field canonical contract를 변경하지 않는다.
- F1/F2 feature formula를 설계하거나 구현하지 않는다.
- posture classification을 변경하지 않는다.
- RF algorithm을 변경하지 않는다.
- landmark set을 변경하지 않는다.
- elbow/wrist를 추가하지 않는다.
- confidence threshold를 변경하지 않는다.
- capture protocol / camera distance / forward gate를 변경하지 않는다.
- UI / performance refactor / multi-person tracking / sagittal-view generation을 추가하지 않는다.
- 본 entry 확정 후 Patch 4.5 implementation을 시작할 수 있다.
- 본 entry 자체는 Patch 4.5 implementation, test, audit 또는 Foundation closure 완료를 의미하지 않는다.

Supersedes:
Resolves:

---

## PROV-005 — Patch 5 End-to-End Lineage Hardening Design Freeze

**Status:** CONFIRMED
**Logged:** 2026-10-04
**Decision timing:** Patch 5 READ-ONLY repository investigation 후, implementation 이전 Design Freeze

### Decision

Patch 5의 executable lineage contract를 다음과 같이 freeze한다.

#### 1. Raw content identity

raw SHA-256 ↔ recording identity conflict 판단의 현재 repository authority는:

```text
analysis/*/ar_*/analysis_manifest.json
```

의 `analysis_mode=extract_raw` manifests다.

유효 raw SHA가 이미 다른 `recording_id`에 연결되어 있으면 새 analysis run directory를 만들기 전에 hard error로 중단한다.

```text
same raw SHA + same recording_id
→ allow

same raw SHA + different recording_id
→ reject
```

Patch 5는 automatic legacy alias merge/crosswalk 또는 global raw catalog를 만들지 않는다.

#### 2. Summary contract

Patch 5 canonical summary schema:

```text
summary-schema/1.0.0
```

exact field count:

```text
52
```

기존 44-field ordered prefix를 유지하고 다음 8 fields를 append한다.

```text
summary_schema_version
recording_id
analysis_run_id
source_frames_analysis_run_id
dataset_role
protocol_version
reference_recording_id
reference_analysis_run_id
```

frame grouping key:

```text
(recording_id, frame.analysis_run_id, step)
```

summary reference는 same recording + same source frame run 안으로 제한한다.

raw extraction에서는:

```text
analysis_run_id == source_frames_analysis_run_id
```

`--from-csv`에서는:

```text
analysis_run_id
= current re-summary run

source_frames_analysis_run_id
= parent canonical frame run
```

이다.

동일 recording의 서로 다른 source frame runs가 한 summary operation에 동시에 존재하면 reject한다.

#### 3. RF input declaration

Patch 5는 Patch 6 selection ledger를 미리 만들지 않는다.

actual RF input declaration은:

```text
results/<experiment_run_id>/experiment_manifest.json
```

의 `inputs` block에 기록한다.

lineage-safe explicit CLI:

```text
--ours-frames PATH [PATH ...]
```

를 도입한다.

`--ours-frames`는 canonical immutable run archive frames만 허용한다.

```text
analysis/<recording_id>/<analysis_run_id>/<recording>_frames.csv
```

frames schema/identity, owner completed analysis manifest, manifest output hash와 actual frames hash를 모두 검증한다.

기존 `--ours SUBJECT...`는 compatibility/pilot mode로 유지하되 flat sidecar를 통해 immutable owner run으로 resolve해야 한다.

다음 ambiguity는 자동 선택하지 않고 reject한다.

```text
same recording_id + multiple completed analysis runs

same subject + same round + different recording_id
```

#### 4. RF sample lineage

canonical artifact:

```text
results/<experiment_run_id>/sample_lineage.jsonl
```

schema:

```text
rf-sample-lineage/1.0.0
```

logical key:

```text
(experiment_run_id, dataset_track, feature_mode, sample_index)
```

`sample_index`는 0-based model-sample order다.

source kind:

```text
canonical_frames
external_table
```

canonical frames sample은 recording/run/frames hash를 보존한다.

external table sample은 fake recording ID를 만들지 않고:

```text
source_dataset_id
source file SHA-256
1-based physical source row number
```

를 보존한다.

우리 canonical frames의 calibration/relative reference는 같은 recording/run 안에 있어야 하며 reference step을 기록한다.

JSONL serialization:

```text
UTF-8
no BOM
LF
json.dumps(... ensure_ascii=False, sort_keys=True, separators=(",", ":"))
one newline per object
```

전체 exact bytes를 SHA-256 한다.

#### 5. RF experiment run

experiment ID:

```text
er_<UTC YYYYMMDDTHHMMSSffffffZ>_<uuid4_hex32>
```

canonical directory:

```text
results/<experiment_run_id>/
```

manifest:

```text
rf-experiment-provenance/1.0.0
```

canonical run artifacts:

```text
experiment_manifest.json
sample_lineage.jsonl
rf_results.csv
rf_results.txt
fig5_rf_compare.png
```

앞의 네 artifact는 completed run에 필수다. `fig5_rf_compare.png`는 기존 optional plot-failure semantics를 유지하며, plot 실패 사실을 manifest에 기록한다.

manifest top-level:

```text
schema_version
experiment_run_id
started_at
ended_at
status
dataset_manifest
inputs
code
environment
options
sample_lineage
outputs
errors
provenance_unknown_reasons
```

completed run은 immutable하다.

기존 flat `analysis/rf_results.*`는 compatibility copy로 유지할 수 있으나 provenance authority가 아니다.

#### 6. Result CSV lineage

기존 result fields를 유지하고 다음을 추가한다.

```text
experiment_run_id
dataset_manifest_sha256
lineage_manifest_path
lineage_manifest_sha256
```

Patch 5 current/pilot에서는 `dataset_manifest_sha256`이 empty다.

`lineage_manifest_path`:

```text
sample_lineage.jsonl
```

`lineage_manifest_sha256`은 exact JSONL bytes hash다.

기존 `root_provenance`는 유지한다.

#### 7. Patch 6 boundary

Patch 5는 다음을 생성하지 않는다.

```text
manifests/recordings.jsonl
manifests/selection_events.jsonl
manifests/datasets/<dataset_manifest_id>.json
```

Patch 5 experiment manifest에는 future interface로:

```text
dataset_manifest_id
path
sha256
```

slot만 두며 현재 Patch 5 실행에서는 null이다.

향후 Patch 6 formal dataset manifest는 selection authority가 되지만, RF experiment manifest는 선택된 source를 실제 resolved frames path/run/hash로 다시 기록한다.

Patch 5는 **what exact bytes were used**를 보장하고,
Patch 6는 **which recording/run should be selected and why**를 결정한다.

### Invariants

```text
1. same raw bytes may not silently fork into independent recording identities

2. summary aggregation/reference may not cross recording or source-analysis-run boundaries

3. ambiguous recording/run selection fails closed

4. RF inputs are pinned by exact artifact hash, not mutable path alone

5. every RF sample retains persistent source lineage

6. every RF result belongs to one immutable experiment run

7. recording_id does not replace subject as LOSO participant grouping
```

### Compatibility

다음은 유지한다.

```text
analysis-provenance/1.0.0
frames-schema/1.0.0 exact 60 fields
frame_index 1-based
mediapipe-model-lock/1.0.0
historical --from-csv parent provenance
existing Tree/Forest/M0/M1/M2 semantics
current first-upright RF reference rule
subject-level LOSO grouping
```

### Non-goals

본 결정은 다음을 정하지 않는다.

```text
F1/F2 formula
F1/F2 normalization/missing policy
p > 6 rank_weights policy
retake scientific selection
formal participant/round policy
formal seed list
λ selection policy
formal metrics
Patch 8 hardware acceptance criteria
```

### Evidence

- current `analyze_d455.py`
- current `rf_experiment.py`
- current Patch 3/4/4.5 Foundation records
- `RESEARCH_DATA_SCHEMA.md` G/H/I의 future lineage/selection separation
- `AIoT_RESEARCH_MASTER.md`의 Patch 5 / Patch 6 boundary
- pre-implementation baseline `204 tests PASS`
- READ-ONLY synthetic probes:
  - same raw bytes modern/legacy double identity reproducible
  - different recordings can merge into one summary aggregate
  - RF subject/round reference can cross recording boundary

### Impact

- Patch 5 implementation은 본 contract 이후에만 시작한다.
- summary writer/loader와 RF input/output 경계에 lineage validation이 추가된다.
- ambiguous legacy behavior가 error로 바뀌는 것은 intentional hardening이다.
- Patch 4 canonical 60-field frames schema는 변경하지 않는다.
- Patch 6 selection policy를 선행 구현하지 않는다.
- Patch 7 general integrity checker를 선행 구현하지 않는다.
- Patch 8 formal D455 validation을 선행하지 않는다.

상세 exact header/schema/field/serialization/test contract는:

```text
docs/foundation/PATCH_05_end_to_end_lineage_hardening.md
```

를 따른다.

본 `PROV-005` entry는 Patch 5 implementation/test/audit/closure 완료를 의미하지 않는다.

Supersedes:
Resolves:
