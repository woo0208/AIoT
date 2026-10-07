# Research Decision Log

- 문서 버전: `v1.11`
- 기준일: `2026-10-07`
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
| `v1.4` | 2026-10-04 | `PROV-006` Design Freeze 후보를 append하여 Patch 6 Selection Manifest / Recapture Inclusion의 planned measurement-slot semantics, explicit recapture relation, append-only selection ledger, immutable dataset manifest, exact analysis/run/frames pinning, dataset-role guard, RF `--dataset-manifest` interface를 동결 제안 |
| `v1.5` | 2026-10-05 | Patch 6 independent READ-ONLY implementation audit의 I-1/OA-1을 반영하여 `PROV-007`을 append. 동일 logical slot의 selection decision을 single-terminal linear supersession chain으로 제한하고, `round` canonical form을 `^[1-9][0-9]*$`로 확정 |
| `v1.6` | 2026-10-05 | `PROV-008`을 append하여 Patch 7 Integrity Checker / Hardening의 repository-wide read-only integrity audit 역할, severity/success semantics, existing-authority reuse, missing/orphan/torn/external 처리 및 implementation boundary를 Design Freeze |
| `v1.7` | 2026-10-05 | Patch 7 independent READ-ONLY implementation audit의 I-2를 반영하여 `PROV-009`를 append. historical CSV-mode input이 참조한 mutable flat compatibility publication의 교체를 corruption으로 보지 않고 immutable `source_frames` + parent analysis lineage로 historical integrity를 검증하도록 authority boundary를 명확화 |
| `v1.8` | 2026-10-05 | Patch 7 Round 2 independent READ-ONLY re-audit의 N-1/N-2를 반영하여 `PROV-010`을 append. mutable compatibility publication을 explicit parent `compatibility_path` relation으로 식별하여 legacy-pilot naming까지 동일 semantics로 포함하고, exclude evidence와 include-selected canonical source의 completed-owner requirement를 역할별로 구분하도록 명확화 |
| `v1.9` | 2026-10-06 | Patch 7 Round 3 independent READ-ONLY re-audit의 remaining IMPORTANT finding을 반영하여 `PROV-011`을 append. selection event의 `include`/`exclude`/`recapture` action 자체가 아니라 각 artifact reference의 실제 role(`historical evidence` vs `selected/consumed canonical source`)에 따라 completed-owner requirement를 적용하도록 명확화 |
| `v1.10` | 2026-10-07 | `CAP-005`를 append하여 Foundation Patch 8 D455 Measurement-Quality and End-to-End Validation을 Design Freeze하고 `OPEN-006`을 해소. candidate-range derivation, 0.60–1.00 m static grid와 mandatory 0.70/0.80 anchors, physical setup, execution governance, single-shot/retry/result firewall, static/production protocol identity, closed pre-lock classification, static/3D/distance-stability metrics, exact five-series depth temporal-SD rule, forward availability population, body-only-negative semantics, exact slot-131 predicate, reconciliation, integrity closure를 `docs/foundation/PATCH_08_actual_d455_end_to_end_validation.md`에 고정했다. Patch 8은 DESIGN-FROZEN이며 implementation / implementation audit / execution registration / hardware execution은 pending이다. `OPEN-002`~`OPEN-005`는 계속 DEFERRED이고 Patch 4/4.5/5/6/7 authority는 변경하지 않는다 |
| `v1.11` | 2026-10-07 | Patch 8 implementation 중 확인된 pre-execution design-authority gap `P8-I1`을 반영하여 `CAP-006`을 append (Clarifies `CAP-005`, Supersedes None). CAP-005가 capture sequence를 명시하지 않았던 forward validation rounds 101–103 / 111–113이 `SEQ_CORE`를 사용함을 명확화하고, 121 = `SEQ_CORE` (§80) / 131 = `SEQ_FULL` (§81)은 그대로 유지한다. formal Patch 8 execution, `execution_id` 발급, Patch 8 결과 관찰은 없었다. production forward gate, `capture-forward-face-v2.0.0`, SEQ_CORE/SEQ_FULL 정의, §75/§76/§79/§80/§81, schema, threshold, `OPEN-002`~`OPEN-005`는 변경하지 않는다 |

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

---

## PROV-006 — Patch 6 Selection Manifest / Recapture Inclusion Design Freeze

**Status:** CONFIRMED
**Logged:** 2026-10-04
**Decision timing:** Patch 6 READ-ONLY repository investigation 및 Q1~Q10 결정 후, implementation 이전 Design Freeze

### Decision

Patch 6의 selection authority와 recapture inclusion contract를 다음과 같이 freeze한다.

#### 1. Responsibility boundary

Patch 5와 Patch 6의 책임을 분리한다.

```text
Patch 5
= What exact bytes were actually used?

Patch 6
= Which recording / analysis run should be selected, and why?
```

Patch 6는 Patch 5의 lineage contract를 대체하지 않는다.

```text
selection decision
→ immutable dataset selection
→ exact canonical frames resolution
→ Patch 5 experiment_manifest.inputs.ours
→ sample_lineage
→ result
```

---

#### 2. Selection unit / round semantics

logical measurement slot:

```text
(dataset_role, subject, round)
```

`round`는 capture-attempt counter가 아니라 participant별 사전에 계획된 measurement slot이다.

`round`의 serialized type은 capture contract와 동일한:

```text
positive-integer decimal string
```

이다.

예:

```json
"round": "1"
```

동일 planned measurement의 재촬영은:

```text
same subject
same round
same dataset_role
new recording_id
```

를 사용한다.

예:

```text
P01 / round 1 / recording A
P01 / round 1 / recording B
P01 / round 1 / recording C
```

는 동일 planned measurement slot에 속할 수 있다.

각 실제 촬영 시도는 unique `recording_id`로 구분한다.

Patch 6는 별도 `attempt_number` 또는 `take_number`를 mandatory identity로 도입하지 않는다.

한 dataset manifest 안에서는 동일 logical slot에 최대 하나의 included recording만 허용한다.

현재 Patch 6는 한 round 안에서 둘 이상의 독립 formal measurement를 동시에 포함하는 protocol을 정의하지 않는다.
향후 필요하면 별도 research decision으로 measurement unit을 확장한다.

---

#### 3. Artifact authority

Patch 6의 canonical selection artifacts는 2계층이다.

```text
manifests/selection_events.jsonl
manifests/datasets/<dataset_manifest_id>.json
```

역할:

```text
selection_events.jsonl
= append-only decision / recapture history

datasets/<dataset_manifest_id>.json
= immutable approved selection snapshot
```

Patch 6는 별도 global:

```text
manifests/recordings.jsonl
```

을 만들지 않는다.

recording identity/provenance authority는 기존 capture/analysis artifacts를 그대로 사용한다.
새 registry를 추가해 이중 authority를 만들지 않는다.

이 결정은 `RESEARCH_DATA_SCHEMA.md`의 기존 3-artifact future proposal보다 우선한다.

---

#### 4. Recapture relationship

recapture 관계는 명시적 directional link로만 기록한다.

```text
child recording
→ recapture_of
→ parent recording
```

다음으로 관계를 추론하지 않는다.

```text
timestamp
filename
path/glob order
latest recording
quality score
same subject/round alone
RF performance
```

recapture relationship과 selection decision은 별개다.

```text
recapture_of
!= automatic replacement

recapture_of
!= automatic exclusion

latest recording
!= authoritative recording
```

한 child recording은 최대 하나의 direct parent recording만 가진다.
self-link와 recapture cycle은 금지한다.

recapture event는 child와 parent 각각의 capture provenance artifact를 exact path/hash로 pin한다.

---

#### 5. Technical evidence vs scientific inclusion

다음을 분리한다.

```text
technical/provenance evidence
!=
scientific inclusion/exclusion decision
```

현재 capture quality의:

```text
ok
ok_with_warnings
retake
```

및 protocol/gate/provenance/hash 상태는 selection evidence다.

Patch 6는 이 값만으로 scientific include/exclude를 자동 결정하지 않는다.

특히 다음 policy는 본 entry에서 결정하지 않는다.

```text
ok_with_warnings formal 허용 여부
재촬영 최대 횟수
예외 승인 조건
formal participant 수
formal round 수
scientific outlier/exclusion 기준
```

formal `selection_decision`과 formal dataset manifest는
향후 사전에 확정된 non-empty `selection_policy_version`을 요구한다.

formal policy가 정의되지 않은 상태에서는
Patch 6 infrastructure를 이유로 임의의 formal selection을 생성하지 않는다.

---

#### 6. Included source binding

included selection은 최소 다음까지 exact하게 pin한다.

```text
recording_id
analysis_run_id
frames_schema_version
canonical frames path
canonical frames SHA-256
analysis_manifest path
analysis_manifest SHA-256
```

canonical frames는 Patch 5의 immutable input contract를 그대로 만족해야 한다.

owner `analysis_manifest.json`은:

```text
status == completed
recording_id exact match
analysis_run_id exact match
frames output exact path/hash match
```

를 만족해야 한다.

`dataset_role`과 `protocol_version`은 frozen 60-field canonical frames row에 존재하지 않는다.

따라서 Patch 6는 다음을 검증한다.

```text
capture provenance.dataset_role
== analysis_manifest.dataset_role
== dataset manifest.dataset_role

capture provenance.protocol_version
== analysis_manifest.protocol_version
```

canonical frames에서는 기존 Patch 4/5 contract의:

```text
recording_id
analysis_run_id
subject
round
frame_schema_version
exact 60-field header
```

를 검증한다.

Patch 6 때문에 `frames-schema/1.0.0`에 field를 추가하지 않는다.

---

#### 7. Evidence pinning

Patch 6는 기존 evidence 값을 불필요하게 복제하지 않는다.

evidence reference는 최소:

```text
recording_id
kind
path
sha256
```

를 가진다.

selection artifact 내부 artifact path는 repository root 기준 normalized relative path를 사용한다.

금지:

```text
absolute path
.. traversal
repository root 밖으로 resolve되는 path
```

consumer는 relative path를 repository root에서 resolve한 뒤
Patch 5 canonical input validation으로 넘긴다.

Patch 5 RF experiment provenance가 resolved absolute paths를 기록하는 기존 contract는 유지한다.

모든 `selection_decision`은 자신의 `recording_id`에 대한
capture provenance evidence를 정확히 하나 요구한다.

include decision은 추가로 exact completed analysis/run/frames를 요구한다.

formal include의 최소 evidence chain:

```text
capture_provenance
quality
analysis_manifest
canonical_frames
```

이다.

pilot include도 최소:

```text
capture_provenance
analysis_manifest
canonical_frames
```

를 요구한다.

exclude는 capture provenance만으로 허용한다.
analysis run이 이미 존재하면 관련 artifact를 evidence로 추가할 수 있지만 필수는 아니다.

`recapture_relation`은 child와 parent 각각의 capture provenance evidence를 요구한다.

---

#### 8. Append-only history / immutable snapshots / supersession

`selection_events.jsonl`은 append-only다.

기존 event를 수정·삭제하지 않는다.

결정 변경은 새 `selection_decision` event를 append하고:

```text
supersedes_selection_event_id
```

로 이전 decision을 연결한다.

dataset manifest는 생성 후 immutable하다.

선택 변경은:

```text
old manifest 유지
new selection event append
new dataset_manifest_id 발급
new manifest 생성
```

으로 처리한다.

supersession 검증은 두 시점을 구분한다.

```text
NEW MANIFEST BUILD TIME
→ selected decision event가 현재 ledger에서 superseded 상태면 새 manifest에 사용할 수 없음

EXISTING MANIFEST REVALIDATION
→ manifest가 pin한 selection_event_id + event SHA를 검증
→ 이후 ledger에 superseding event가 append되었다는 이유로 기존 manifest를 invalid 처리하지 않음
```

따라서 과거 RF experiment가 참조한 immutable manifest의 의미는
후속 selection 변경으로 바뀌지 않는다.

---

#### 9. Dataset-role / protocol integrity

self-recorded dataset manifest의 allowed role:

```text
pilot
formal
```

한 manifest에는 하나의 `dataset_role`만 존재한다.

source capture provenance와 selected analysis manifest의 `dataset_role`은
manifest role과 exact match해야 한다.

따라서:

```text
pilot recording
→ formal manifest
```

silent promotion은 hard error다.

`protocol_version`은:

```text
capture provenance
== selected analysis manifest
```

이어야 한다.

Patch 6는 특정 protocol version을 scientific eligibility criterion으로 새로 고정하지 않는다.

Early Hardware Preflight 또는 legacy pilot을
결과가 좋아 보인다는 이유로 formal manifest에 넣지 않는다.

`external` source는 기존 Patch 5 external-table lineage 경로를 사용하며
Patch 6 self-recorded selection manifest에 섞지 않는다.

---

#### 10. RF interface

manifest-driven RF mode의 canonical CLI:

```text
--dataset-manifest PATH
```

다음 세 selection mode는 mutually exclusive다.

```text
--ours
--ours-frames
--dataset-manifest
```

의미:

```text
--ours
= compatibility / pilot subject discovery

--ours-frames
= exact manual immutable frames selection

--dataset-manifest
= manifest-authoritative selection
```

manifest mode에서는 manual source를 조용히 merge하지 않는다.

RF는 dataset manifest를 검증하고 selected canonical frames를 resolve한 뒤
기존 Patch 5 canonical input validation을 그대로 수행한다.

그 후에도:

```text
experiment_manifest.inputs.ours
```

에는 실제 resolved exact frames/run/hash를 다시 기록한다.

Patch 5 reserved slot:

```text
dataset_manifest.dataset_manifest_id
dataset_manifest.path
dataset_manifest.sha256
```

를 실제 manifest reference로 채운다.

result CSV의:

```text
dataset_manifest_sha256
```

에도 exact manifest bytes SHA-256을 기록한다.

---

### Frozen schemas

#### A. Selection event ledger

Canonical path:

```text
manifests/selection_events.jsonl
```

schema:

```text
selection-event/1.0.0
```

event types:

```text
recapture_relation
selection_decision
```

event ID:

```text
se_<UTC YYYYMMDDTHHMMSSffffffZ>_<uuid4_hex32>
```

모든 event의 exact top-level keys:

```text
schema_version
selection_event_id
event_type
created_at
dataset_role
subject
round
recording_id
selection_policy_version
decided_by
supersedes_selection_event_id
recapture
decision
evidence
```

`round`는 positive-integer decimal string이다.

`recapture_relation`은 explicit child→parent 관계만 기록한다.

`selection_decision`은 one recording에 대한:

```text
include
exclude
```

결정을 기록한다.

selection reason code enum의 scientific 의미는
`selection_policy_version` authority에 맡기며 Patch 6가 임의로 freeze하지 않는다.

formal decision에서는 `selection_policy_version`이 non-empty여야 한다.

evidence item exact fields:

```text
recording_id
kind
path
sha256
```

allowed `kind`:

```text
capture_provenance
quality
analysis_manifest
canonical_frames
other
```

JSONL canonical serialization:

```text
UTF-8
no BOM
LF
json.dumps(
  object,
  ensure_ascii=False,
  sort_keys=True,
  separators=(",", ":")
)
one terminating LF per event
```

event-line SHA-256은 terminating LF를 포함한 exact bytes로 계산한다.

---

#### B. Dataset selection manifest

Canonical path:

```text
manifests/datasets/<dataset_manifest_id>.json
```

schema:

```text
dataset-selection-manifest/1.0.0
```

ID:

```text
dm_<UTC YYYYMMDDTHHMMSSffffffZ>_<uuid4_hex32>
```

manifest는 immutable included snapshot이다.

각 included entry는 exact source를 pin한다.

```text
dataset_role
subject
round
recording_id
selection_event_id
selection_event_sha256
analysis_run_id
frames_schema_version
frames_path
frames_sha256
analysis_manifest_path
analysis_manifest_sha256
```

`round`는 positive-integer decimal string이다.

한 manifest 안에서:

```text
(dataset_role, subject, round)
```

는 unique하다.

entry ordering:

```text
subject lexical ascending
then int(round) numeric ascending
```

manifest는 자신의 SHA-256을 내부에 기록하지 않는다.
consumer가 exact manifest file bytes를 SHA-256하여 pin한다.

---

### Invariants

```text
1. round is a planned measurement slot, not a capture-attempt counter.
2. each capture attempt has its own recording_id.
3. recapture is explicit and never inferred from time/path/order/performance.
4. recapture does not itself replace/include/exclude a recording.
5. technical evidence and scientific selection decision remain separate.
6. one manifest contains at most one included recording per logical slot.
7. included source is pinned through exact recording + analysis run + frames hash.
8. frames-schema/1.0.0 remains exact 60 fields; Patch 6 adds no frame columns.
9. excluded attempts may exist without analysis.
10. selection history is append-only; dataset snapshots are immutable.
11. later supersession does not invalidate an already-created immutable manifest.
12. dataset_role cannot be silently promoted or mixed.
13. manifest RF mode and manual RF modes cannot be mixed.
14. Patch 6 selection authority does not replace Patch 5 actual-byte lineage.
```

---

### Compatibility

유지:

```text
capture-provenance/1.0.0
analysis-provenance/1.0.0
frames-schema/1.0.0 exact 60 fields
summary-schema/1.0.0
mediapipe-model-lock/1.0.0
rf-sample-lineage/1.0.0
rf-experiment-provenance/1.0.0

existing --ours
existing --ours-frames
existing subject-level LOSO grouping
existing RF numeric semantics
existing first-upright RF reference behavior
Patch 5 resolved-absolute-path experiment provenance
```

---

### Rejected behaviors

```text
latest recording auto-select
latest analysis run auto-select
glob-order auto-select
best quality/performance auto-select
recapture => parent automatic exclusion
quality verdict alone => scientific include/exclude
pilot => formal silent promotion
dataset manifest overwrite
selection event rewrite/delete
manual RF source + manifest source merge
same logical slot multiple include
recordings.jsonl duplicate identity authority
Patch 6 frame-schema expansion
later supersession => old immutable manifest invalidation
```

---

### Non-goals

본 결정은 다음을 정하지 않는다.

```text
F1/F2 exact formula / feature count / normalization / missing policy
p > 6 rank_weights exact policy

formal participant count
formal round count
formal scientific eligibility/inclusion/exclusion criteria
ok_with_warnings formal handling
retake maximum count
technical/scientific exception approval policy
outlier policy

exact seed list
exact λ selection rule
formal metric set

Patch 7 general integrity scanner
Patch 8 D455 formal validation grid/repeat/acceptance criteria
```

---

### Evidence / Source

- current `capture_d455.py`
  - `round` = positive-integer decimal string
  - capture attempt마다 unique `recording_id`
  - `dataset_role`, `protocol_version`
  - `_camera.json`, `_quality.json`
- current `analyze_d455.py`
  - immutable `analysis/<recording_id>/<analysis_run_id>/`
  - `analysis-provenance/1.0.0`
  - `dataset_role`, `protocol_version` in analysis manifest
  - canonical frames `frames-schema/1.0.0` exact 60 fields
  - canonical frames에는 `dataset_role`, `protocol_version` column이 없음
- current `rf_experiment.py`
  - exact `--ours-frames`
  - same-slot ambiguity rejection
  - multiple completed run rejection
  - Patch 5 `dataset_manifest` null slot
- `PROV-005`
- `docs/foundation/PATCH_05_end_to_end_lineage_hardening.md`
- `RESEARCH_DATA_SCHEMA.md`
- `AIoT_RESEARCH_MASTER.md`
- Patch 5 main-integrated baseline: `252 tests PASS`
- Patch 6 READ-ONLY investigation, no source implementation

---

### Impact

- Patch 6 implementation은 본 contract와
  `docs/foundation/PATCH_06_selection_manifest_recapture_inclusion.md`
  Design Freeze 이후에만 시작한다.
- `RESEARCH_DATA_SCHEMA.md` §H/§I는 본 결정에 맞춰 같은 docs-only freeze change에서 sync한다.
- 기존 `recordings.jsonl` future proposal 및 automatic first-eligible 정책 문구는 본 결정으로 대체한다.
- formal scientific selection policy가 아직 freeze되지 않았으므로
  Patch 6 implementation 완료 자체가 formal collection 시작 허가를 의미하지 않는다.
- Patch 4/4.5/5 schema 및 numeric semantics는 변경하지 않는다.
- Patch 6 implementation 시 generated manifest JSON/JSONL의 LF canonical bytes를 보장하고
  Windows Git line-ending conversion이 hash identity를 바꾸지 않도록 `.gitattributes` 등 repository-level protection을 추가한다.
- Patch 7/8을 선행 구현하지 않는다.

상세 exact schema/serialization/validation/test contract는:

```text
docs/foundation/PATCH_06_selection_manifest_recapture_inclusion.md
```

를 따른다.

본 `PROV-006` entry 자체는 implementation/test/audit/closure/main integration 완료를 의미하지 않는다.

Supersedes:
Resolves:

---

## PROV-007 — Patch 6 Supersession / Canonical Round Clarification

**Status:** CONFIRMED
**Logged:** 2026-10-05
**Decision timing:** Patch 6 implementation 후 independent READ-ONLY audit에서 I-1 및 OA-1 확인, implementation commit 이전 clarification

### Context

Patch 6 Design Freeze (`PROV-006`)는 다음을 이미 확정했다.

```text
logical slot
= (dataset_role, subject, round)

selection history
= append-only

selection 변경
= supersedes_selection_event_id 사용

new manifest
= current terminal decision 사용

old immutable manifest
= later supersession 이후에도 historical snapshot으로 유효
```

그러나 independent READ-ONLY implementation audit에서 다음 ambiguity가 확인되었다.

```text
I-1
same logical slot에 서로 연결되지 않은 복수 selection_decision이 동시에 current로 남을 수 있음

I-1
하나의 decision을 둘 이상의 후속 decision이 동시에 supersede하는 branch가 가능함

OA-1
round="1"과 round="01"이 서로 다른 lexical slot으로 취급될 수 있음
```

이 ambiguity는 실제 ledger event가 생성되기 전에 해소한다.

---

### Decision A — One current terminal selection decision per logical slot

logical slot은 기존과 동일하다.

```text
(dataset_role, subject, round)
```

각 logical slot에는 **현재 terminal `selection_decision`이 최대 하나만** 존재할 수 있다.

#### A.1 First decision

해당 slot에 prior selection decision이 없으면:

```text
supersedes_selection_event_id = null
```

이어야 한다.

#### A.2 Subsequent decision

해당 slot에 current terminal decision이 하나 존재하면,
새 `selection_decision`은 반드시 그 terminal decision을 직접 supersede해야 한다.

```text
A
↓
B supersedes A
↓
C supersedes B
```

만 허용한다.

#### A.3 Unlinked second decision forbidden

같은 logical slot에 current terminal decision이 이미 존재하는데
새 decision이:

```text
supersedes_selection_event_id = null
```

이면 hard error다.

즉 다음은 금지한다.

```text
A = include R1

B = exclude R1
supersedes = null
```

recording_id가 같거나 달라도 동일 slot이면 같은 규칙을 적용한다.

#### A.4 Branching supersession forbidden

이미 superseded된 decision은 다시 supersede할 수 없다.

따라서 다음은 금지한다.

```text
A
├─ B supersedes A
└─ C supersedes A
```

selection history는 logical slot별 **single linear chain**이어야 한다.

#### A.5 Supersession is slot-level, not recording-level

supersession chain은 recording_id가 바뀌어도 유지된다.

예:

```text
P01 / round 1

A: exclude recording R1
↓
B: include recording R2
   supersedes A
↓
C: include recording R3
   supersedes B
```

이 구조가 허용된다.

Patch 6 selection authority의 현재성(currentness)은 recording 단위가 아니라
logical measurement slot 단위로 판단한다.

---

### Decision B — New manifest uses only the current terminal include decision

새 dataset manifest를 생성할 때는 각 selected logical slot에 대해
**현재 terminal selection decision**만 사용할 수 있다.

그 terminal decision은:

```text
event_type == selection_decision
decision.disposition == include
```

이어야 한다.

이미 superseded된 decision이나,
같은 slot에서 terminal chain에 연결되지 않은 decision을 새 manifest source로 사용할 수 없다.

---

### Decision C — Existing immutable manifests remain historically valid

`PROV-006`의 immutable snapshot semantics는 유지한다.

예:

```text
A = include R1
M1 created from A

later:
B supersedes A
B = include R2
M2 created from B
```

이면:

```text
M1 = historical immutable snapshot으로 계속 유효
M2 = 새로운 selection snapshot
```

이다.

기존 manifest revalidation은 자신이 pin한:

```text
selection_event_id
selection_event_sha256
source artifact hashes
```

를 검증한다.

ledger에 나중 superseding event가 append되었다는 사실만으로
old manifest를 invalid 처리하지 않는다.

---

### Decision D — Canonical `round` representation

Patch 6 identity에서 `round`는 **canonical positive decimal string**이어야 한다.

exact regex:

```regex
^[1-9][0-9]*$
```

허용 예:

```text
"1"
"2"
"9"
"10"
"100"
```

금지 예:

```text
"0"
"00"
"01"
"001"
"+1"
"-1"
"1.0"
" 1"
"1 "
```

따라서 logical round 1의 canonical serialization은 오직:

```json
"round": "1"
```

이다.

`"1"`과 `"01"`을 서로 다른 logical slot으로 허용하지 않는다.

---

### Decision E — New capture identity must use canonical round

앞으로 새 capture identity를 생성할 때도 동일 canonical round rule을 적용한다.

```regex
^[1-9][0-9]*$
```

즉 new capture invocation은 leading-zero round를 허용하지 않는다.

이 clarification은:

```text
frames-schema/1.0.0
RF numeric semantics
scientific selection policy
```

를 변경하지 않는다.

기존 historical/pilot artifact의 non-canonical round를 자동 rename/rewrite하지 않는다.

non-canonical historical round는 새로운 Patch 6 authoritative dataset manifest에
그대로 포함할 수 없다.

---

### Required implementation behavior

Patch 6 implementation은 최소 다음을 보장해야 한다.

```text
1. same slot + no prior decision
   → supersedes must be null

2. same slot + one terminal decision
   → next decision must supersede exactly that terminal decision

3. already-superseded event
   → cannot be superseded again

4. branch
   → reject

5. unlinked second decision in same slot
   → reject

6. linear chain A→B→C
   → allow

7. new manifest
   → current terminal include decision only

8. old immutable manifest
   → later supersession alone does not invalidate it

9. round
   → must match ^[1-9][0-9]*$

10. new capture round input
    → same canonical rule
```

---

### Required tests before implementation commit

최소 다음 regression/negative tests를 요구한다.

```text
T1 same slot second unlinked decision → reject

T2 A superseded by B, then C also supersedes A → reject

T3 valid linear chain A→B→C → PASS

T4 recording_id가 바뀌어도 same-slot chain 유지 → PASS

T5 new manifest from non-terminal/superseded event → reject

T6 old manifest remains valid after later supersession → PASS

T7 round "1" → PASS

T8 round "01" → reject

T9 round "0", "001", "+1", "-1", "1.0" → reject

T10 new capture invocation with non-canonical round → reject
```

---

### Scope boundary

본 clarification은 다음을 새로 결정하지 않는다.

```text
formal participant count
formal round count
ok_with_warnings scientific policy
retake maximum count
outlier/exclusion scientific criteria
F1/F2 definition
Patch 7
Patch 8
```

이는 selection identity / currentness / canonical serialization clarification이다.

---

### Evidence / Source

- Patch 6 independent READ-ONLY implementation audit
  - `I-1`: contradictory/unlinked current decisions and branching supersession
  - `OA-1`: leading-zero round ambiguity
- `PROV-006`
- `docs/foundation/PATCH_06_selection_manifest_recapture_inclusion.md`

---

### Impact

- `PROV-006`의 Patch 6 Design Freeze 전체를 폐기하지 않는다.
- 본 entry가 supersession currentness와 canonical round ambiguity에 대해 더 구체적인 authority다.
- Patch 6 implementation commit 전에 I-1/OA-1을 반영하고 targeted/full regression을 재실행한다.
- independent READ-ONLY re-audit에서 BLOCKER=0 / IMPORTANT=0을 확인하기 전 implementation commit하지 않는다.

Supersedes:
- `PROV-006` 중 supersession currentness가 단일 terminal chain인지 명시되지 않았던 ambiguity
- `PROV-006` 중 `positive-integer decimal string`이 leading zero를 허용하는지 명시되지 않았던 ambiguity

Resolves:
- Patch 6 audit `I-1`
- Patch 6 audit `OA-1`

---

## PROV-008 — Patch 7 Integrity Checker / Hardening Design Freeze

**Status:** CONFIRMED
**Logged:** 2026-10-05
**Decision timing:** Patch 7 READ-ONLY investigation / gap analysis / exact contract 확정 후, implementation 이전

### Decision

Patch 7은 **Patch 1~6에서 이미 고정된 research artifact authority를 repository-wide하게 독립 검증하는 read-only integrity checker / hardening layer**로 고정한다.

Patch 1~6은 artifact 생성·소비 시점의 local/fail-closed validation을 제공하지만, repository 전체를 한 번에 순회하여 다음을 검증하는 general integrity layer는 없다.

```text
inventory
ownership / identity
stored SHA-256 ↔ actual bytes
missing / mixed / structural orphan
malformed / torn authority
cross-layer lineage consistency
```

Patch 7은 이 gap을 해결한다.

상세 normative contract는 다음 문서를 단일 상세 authority로 사용한다.

```text
docs/foundation/PATCH_07_integrity_checker_hardening.md
```

본 entry는 그 문서의 DF 항목·Acceptance Criteria·Test Matrix를 반복하지 않고, 변경 불가한 핵심 결정과 경계만 기록한다.

---

### Core decisions

#### A. Read-only / non-destructive

checker가 허용되는 동작:

```text
discover / inventory / parse / validate / hash / cross-reference / classify / report
```

금지되는 동작:

```text
artifact 수정/삭제/이동
JSON/JSONL rewrite 또는 truncate
selection history rewrite
automatic repair / selection / exclusion / retake
legacy provenance inference/backfill
model download / camera access / experiment rerun
```

즉 Patch 7은 **detect / classify / report** 계층이며 repair/migration 계층이 아니다.

#### B. Severity / success

finding severity:

```text
ERROR
WARNING
INFO
```

`ERROR`는 frozen authority와 actual repository 사이의 **증명된 contradiction**에만 사용한다.

대표 예:

```text
stored SHA != actual SHA
recorded required artifact missing
recording_id / analysis_run_id mismatch
owner mismatch
canonical schema/serialization violation
selection graph violation
malformed/torn canonical authority
completed RF output hash mismatch
```

`WARNING`은 corruption이라고 단정할 수 없는 incomplete/unverifiable state에 사용한다.

repository integrity success condition:

```text
ERROR == 0
```

#### C. Incomplete state != corruption

다음 상태 자체는 ERROR가 아니다.

```text
failed/running capture-analysis-RF state
selection되지 않은 capture
selection되지 않은 completed analysis
historical immutable dataset manifest
```

핵심 구분:

```text
partial / incomplete / unused state != corruption
already-declared authority fact와 actual bytes/identity의 contradiction = corruption
```

별도 timeout authority가 없으므로 오래된 `running`을 자동 `failed`로 재분류하지 않는다.

#### D. Missing / orphan

`missing`:

> frozen authority가 존재한다고 요구하거나 path/hash fact로 이미 기록한 artifact가 현재 없는 상태

`structural orphan`:

> managed canonical namespace에 존재하지만 자신의 frozen ownership relation을 만족하는 authority를 찾을 수 없는 artifact

따라서 단순히 아직 selection/RF에 사용되지 않았다는 이유만으로 orphan으로 판정하지 않는다.

#### E. Existing authority reuse

Patch 7은 다음 existing authority를 재사용하며 재정의하지 않는다.

```text
capture-provenance/1.0.0
analysis-provenance/1.0.0
frames-schema/1.0.0
summary-schema/1.0.0
mediapipe-model-lock/1.0.0
rf-sample-lineage/1.0.0
rf-experiment-provenance/1.0.0
selection-event/1.0.0
dataset-selection-manifest/1.0.0
```

특히 다음은 그대로 유지한다.

```text
frames-schema/1.0.0 exact 60 fields
Patch 5 actual-byte lineage semantics
Patch 6 append-only selection history
Patch 6 immutable dataset snapshot semantics
PROV-007 canonical round / linear supersession semantics
```

#### F. Repository-wide validation families

managed scope:

```text
data/**
analysis/**
manifests/selection_events.jsonl
manifests/datasets/*.json
results/**
mediapipe_model_lock.json
locally present locked model artifact
```

최소 validation family:

```text
Capture
- recording identity
- declared raw/sidecar relation
- existing sidecar identity consistency

Analysis
- directory ↔ manifest identity
- recorded input/output path/hash
- canonical frames owner/schema/hash
- raw identity collision
- batch/run relation

Selection
- whole-ledger parse/serialization
- event identity/hash
- supersession/recapture graph
- evidence path/hash/identity

Dataset manifest
- immutable manifest identity/serialization
- pinned event existence/hash
- selected source path/hash/ownership

RF
- experiment directory ↔ manifest identity
- input/dataset-manifest binding
- sample lineage identity/hash
- completed output existence/hash
```

정확한 field-level rule은 Foundation Patch 7 문서를 따른다.

#### G. Evidence-kind hardening

Patch 6 audit에서 남은 evidence-kind semantic hardening을 포함한다.

단, frozen exact schema가 없는 artifact에 새로운 scientific schema를 발명하지 않는다.

`quality` evidence의 minimum integrity requirement:

```text
valid JSON object
recording_id 존재/일치
pinned exact bytes SHA-256 일치
```

다음은 Patch 7이 판단하지 않는다.

```text
quality verdict의 scientific acceptability
ok_with_warnings formal inclusion policy
retake/exclude scientific policy
```

`kind == other` 역시 path/hash/path-safety 범위를 넘어 의미를 추론하지 않는다.

#### H. Torn/crash detection, no repair

최소 탐지 대상:

```text
selection ledger torn final line
partial/malformed canonical dataset manifest
malformed canonical JSON/JSONL authority
recognized temporary publication residue
```

canonical final authority 자체가 malformed/partial이면 ERROR다.

checker는 tail truncate, line removal, manifest/hash rewrite, file delete/rename 같은 recovery를 자동 수행하지 않는다.

#### I. External input

repository 밖의 resolved absolute path는:

```text
accessible → exact bytes SHA 재검증; mismatch = ERROR
inaccessible → EXTERNAL_UNVERIFIABLE / WARNING
```

유사한 local artifact로 자동 substitute하지 않는다.

#### J. No new self-hash authority in Patch 7 v1

Patch 7 v1에서는 다음을 도입하지 않는다.

```text
global manifest hash registry
integrity catalog
Merkle/root hash
cryptographic signing authority
```

Patch 7 v1은 existing authority 내부의 identity / ownership / stored-hash / serialization / cross-reference consistency에 집중한다.

외부 cryptographic anchor가 없는 authority graph 전체의 일관된 adversarial rewrite를 완전히 증명하지 못할 수 있다는 limitation은 acceptance한다.

#### K. Scientific/hardware semantics unchanged

Patch 7은 다음을 변경하거나 새로 결정하지 않는다.

```text
F1/F2 / RF numeric semantics
Tree / Forest / weighting / λ / seed
LOSO / first-upright / missing-value semantics
label/class definitions
formal participant/round count
scientific inclusion/exclusion / retake policy
Patch 8 D455 hardware validation
raw recording semantic quality
```

Patch 7 전후 invariant:

```text
same research bytes
same numerical outputs
same sample inclusion
same evaluation behavior
same selection history
same frozen schemas
```

---

### Implementation boundary

Patch 7 implementation은 본 `PROV-008`과:

```text
docs/foundation/PATCH_07_integrity_checker_hardening.md
```

가 동일 Design Freeze commit으로 고정된 뒤에만 시작한다.

Design Freeze commit은 authority documentation만 포함하며 Python source/test를 수정하지 않는다.

implementation은 existing validator를 가능한 한 재사용한다. Pure validation logic을 노출하기 위한 refactor는 허용하지만 producer behavior와 기존 regression을 변경해서는 안 된다.

closure 전 요구사항:

```text
targeted Patch 7 tests PASS
full regression PASS
independent READ-ONLY implementation audit
BLOCKER 0
IMPORTANT 0
```

`AGENTS.md`, `CLAUDE.md`, `RESEARCH_DATA_SCHEMA.md`, `AIoT_RESEARCH_MASTER.md`의 완료 status sync는 implementation/test/audit/closure 이후 수행한다.

---

### Evidence / Source

- Patch 7 pre-implementation READ-ONLY repository investigation
- current `capture_d455.py`, `analyze_d455.py`, `rf_experiment.py`, `selection_manifest.py`
- current Patch 1~6 committed tests
- `PROV-004` ~ `PROV-007`
- `docs/foundation/PATCH_05_end_to_end_lineage_hardening.md`
- `docs/foundation/PATCH_06_selection_manifest_recapture_inclusion.md`
- `RESEARCH_DATA_SCHEMA.md`
- `AIoT_RESEARCH_MASTER.md`
- Patch 6 main-integrated baseline:
  - branch `main`
  - HEAD / origin/main `6e6f577`
  - full regression `330 PASS`
  - independent re-audit `BLOCKER 0 / IMPORTANT 0`
  - working tree clean

---

### Impact

- Patch 7의 역할을 repository-wide **read-only integrity audit**로 고정한다.
- Patch 1~6 local validator와 scientific semantics는 유지한다.
- exact MUST/MUST NOT, artifact rule, acceptance criteria, test matrix, Definition of Done은 `docs/foundation/PATCH_07_integrity_checker_hardening.md`가 상세 authority다.
- 본 `PROV-008`은 implementation/test/audit/closure/main integration 완료를 의미하지 않는다.
- Patch 8 real D455 formal hardware validation을 선행 구현하지 않는다.

Supersedes:

Resolves:
- Patch 3 general repository integrity checker handoff
- Patch 5 all-companion inventory / missing / orphan / repository-wide hash audit handoff
- Patch 6 audit M-2 evidence-kind deep semantic validation gap
- Patch 6 audit M-3 torn/crash artifact integrity-diagnostics gap

---

## PROV-009 — Patch 7 Mutable Compatibility Input Integrity Clarification

**Status:** CONFIRMED
**Logged:** 2026-10-05
**Decision timing:** Patch 7 initial implementation 후 independent READ-ONLY audit에서 historical CSV-mode analysis와 mutable flat compatibility copy 사이의 authority ambiguity가 재현된 후

### Context

Patch 7 independent READ-ONLY audit에서 다음 정상 workflow가 repository integrity ERROR를 발생시키는 문제가 확인되었다.

```text
1. recording R에 대해 raw analysis A 수행
2. canonical archived frames 생성
3. flat compatibility copies publication

   analysis/<R>_frames.csv
   analysis/<R>_frames.csv.provenance.json

4. 위 flat compatibility copy를 입력으로 CSV-mode analysis B 수행
5. 이후 동일 recording R에 대해 legitimate raw re-analysis C 수행
6. producer가 current compatibility publication을 C의 결과로 교체
7. historical CSV-mode run B의 input record에 저장된 SHA와
   현재 flat compatibility copy SHA가 달라짐
8. Patch 7 checker가 historical run B를 HASH_MISMATCH ERROR로 판정
```

이 상태는 independent audit에서 실제 producer path를 사용하여 재현되었다.

문제의 원인은 기존 authority의 다음 두 원칙을 문자 그대로 동시에 적용할 경우 발생한다.

```text
A. Recorded complete SHA-256 facts should be verified against actual bytes.

B. Flat compatibility artifacts are non-canonical publication copies
   and may legitimately be replaced by a later analysis of the same recording.
```

따라서 mutable compatibility publication과 immutable historical lineage의 authority boundary를 명확히 한다.

---

### Decision

다음 원칙을 freeze한다.

> **Mutable flat compatibility artifacts referenced by a historical CSV-mode analysis are not persistent authoritative byte anchors. A later legitimate replacement of those flat compatibility copies shall not, by itself, invalidate the historical analysis run. Historical CSV-mode source integrity shall instead be established through the immutable archived `source_frames` artifact and its corresponding parent analysis-manifest lineage.**

즉 다음 파일:

```text
analysis/<recording_id>_frames.csv
analysis/<recording_id>_frames.csv.provenance.json
```

은 current/latest compatibility publication이다.

이 경로의 bytes는 동일 recording의 이후 legitimate raw analysis에 의해 교체될 수 있다.

따라서 historical CSV-mode analysis manifest가 이 flat compatibility path와 당시 SHA-256을 input metadata로 보존하고 있더라도,

```text
historical stored SHA
!=
current flat compatibility bytes SHA
```

라는 사실만으로 historical run을 repository corruption으로 판정해서는 안 된다.

---

### 1. Authority distinction

Patch 7은 다음 두 종류를 구분한다.

#### A. Immutable authoritative lineage artifact

예:

```text
analysis/<recording_id>/<analysis_run_id>/...
```

아래에 보존되는 run-scoped archived artifact와 해당 owner manifest.

이 artifact에 대해 authority가 stored path/hash를 기록했다면:

```text
stored SHA-256
==
actual bytes SHA-256
```

가 계속 성립해야 한다.

불일치 또는 missing은 기존 Patch 7 원칙에 따라 ERROR다.

#### B. Mutable flat compatibility publication

예:

```text
analysis/<recording_id>_frames.csv
analysis/<recording_id>_frames.csv.provenance.json
```

이 파일은 convenience / compatibility publication이며 immutable historical authority가 아니다.

동일 recording의 이후 successful raw analysis가 이 publication을 정상적으로 교체할 수 있다.

따라서 historical run이 과거 시점의 flat compatibility SHA를 기록하고 있다는 이유만으로 현재 publication과 exact-byte equality를 영구 요구하지 않는다.

---

### 2. Historical CSV-mode integrity

historical CSV-mode analysis의 source integrity는 flat compatibility copy의 현재 bytes가 아니라 다음 authoritative chain으로 검증한다.

```text
historical CSV-mode analysis run
        ↓
archived source_frames
        ↓
parent analysis identity
        ↓
parent analysis_manifest
        ↓
parent canonical frames/output hash
```

구체적으로 Patch 7은 historical CSV-mode run에 대해 기존 frozen authority가 제공하는 범위에서 다음을 검증한다.

```text
CSV run identity
recording_id
analysis_run_id

archived source_frames existence
archived source_frames SHA-256
archived source_frames identity/schema

parent analysis reference
parent recording_id / analysis_run_id

parent analysis_manifest existence
parent analysis_manifest identity

parent manifest ↔ parent canonical frames ownership
parent stored hash ↔ authoritative archived bytes
```

이 immutable chain이 온전하면, 현재 flat compatibility publication이 이후 정상적으로 교체되었다는 이유만으로 historical CSV-mode run은 invalid가 아니다.

---

### 3. Flat compatibility input record semantics

CSV-mode analysis manifest에 기록된 flat compatibility input:

```text
inputs.frames
inputs.frames_provenance
```

의 historical path/hash는:

```text
"이 run이 실행될 당시 사용한 compatibility publication"
```

을 나타내는 provenance fact로 해석한다.

이는:

```text
"이 path가 영구적으로 해당 bytes를 유지해야 한다"
```

는 persistent byte-anchor contract가 아니다.

따라서 이후 legitimate replacement가 확인되는 정상 compatibility publication에 대해:

```text
current SHA != historical input SHA
```

만으로:

```text
HASH_MISMATCH ERROR
```

를 발생시키지 않는다.

---

### 4. What remains an ERROR

본 clarification은 compatibility path 전체의 검증을 포기하는 결정이 아니다.

다음은 계속 ERROR 대상이다.

```text
archived source_frames missing

archived source_frames stored SHA mismatch

archived source_frames identity/schema mismatch

parent analysis manifest missing

parent recording_id mismatch

parent analysis_run_id mismatch

parent canonical output ownership mismatch

parent authoritative output SHA mismatch

historical CSV run이 존재하지 않는 parent/run을 claim

flat compatibility provenance가 current canonical owner를
명시적으로 claim하면서 그 claim이 현재 authority와 모순됨
```

즉:

```text
mutable publication replacement
```

만 허용되는 것이며,

```text
immutable lineage corruption
```

은 허용되지 않는다.

---

### 5. What is NOT an ERROR

다음 상태는 그 자체로 ERROR가 아니다.

```text
Raw run A
→ CSV-mode run B
→ same recording raw re-analysis C
→ flat compatibility copy replaced by C
```

그리고 그 결과:

```text
B.inputs.frames.sha256
!=
current analysis/<R>_frames.csv SHA-256
```

가 되어도,

B의 immutable archived source와 parent lineage가 온전하면 historical B는 valid historical analysis state다.

---

### 6. Scope limitation

본 clarification은 다음 mutable flat compatibility artifacts와 그 historical CSV-mode input interpretation에 한정한다.

```text
analysis/<recording_id>_frames.csv
analysis/<recording_id>_frames.csv.provenance.json
```

본 결정은 일반적인 stored-hash verification 규칙을 약화하지 않는다.

다음 artifact의 기존 hash integrity는 그대로 유지한다.

```text
run-scoped archived analysis artifacts
canonical analysis outputs
selection evidence
selection event bytes
dataset manifest sources
RF inputs
sample lineage
RF outputs
other immutable authority artifacts
```

즉 일반 원칙은 여전히:

```text
immutable authoritative artifact
+
stored complete SHA
→ actual bytes must match
```

이다.

---

### 7. No latest/newest authority inference

flat compatibility copy가 현재 어떤 analysis run의 publication인지 판단할 때:

```text
mtime
ctime
directory order
lexical latest
newest run ID
```

같은 heuristic을 authority로 사용하지 않는다.

필요한 current compatibility ownership 판단은 existing provenance sidecar와 frozen explicit identity/hash 관계만 사용한다.

---

### 8. Patch 7 checker behavior

Patch 7 implementation은 historical CSV-mode run의 flat compatibility input record를 검사할 때:

```text
historical flat SHA
vs
current mutable flat bytes
```

의 equality를 persistent ERROR condition으로 사용하지 않는다.

대신 immutable archived source / parent lineage를 검증한다.

이 clarification 때문에:

```text
historical run manifest rewrite
stored historical SHA rewrite
flat file restoration
old compatibility copy regeneration
```

을 수행하지 않는다.

Checker는 계속 READ-ONLY다.

---

### 9. Regression requirement

Patch 7 tests에 최소 다음 regression scenario를 추가한다.

```text
1. raw analysis A
2. CSV-mode analysis B using A compatibility publication
3. B audit PASS
4. same recording raw re-analysis C
5. current flat compatibility publication replaced by C
6. historical B archived source / parent lineage remains intact
7. repository audit must NOT produce ERROR solely because:
      B historical flat-input SHA
      !=
      current flat-copy SHA
```

추가 negative test도 포함한다.

```text
같은 상태에서 B의 archived source_frames bytes를 변조
→ ERROR

같은 상태에서 B의 parent authoritative source를 삭제
→ ERROR
```

즉 false-positive 제거가 false-negative 증가로 이어져서는 안 된다.

---

### 10. Relationship to PROV-008

본 결정은:

```text
PROV-008 — Patch 7 Integrity Checker / Hardening Design Freeze
```

를 폐기하거나 전체 supersede하지 않는다.

`PROV-008`은 계속 Patch 7의 주 authority다.

본 `PROV-009`는 구현 중 independent audit에서 발견된 다음 ambiguity만 명시적으로 해소한다.

```text
stored-hash audit
vs
mutable compatibility publication lifecycle
```

충돌 시 이 특정 항목에 대해서는 `PROV-009` interpretation이 우선한다.

---

### Invariants

```text
1. Flat compatibility copies remain non-canonical.

2. Flat compatibility copies may be legitimately replaced.

3. Historical analysis validity must not depend on a mutable publication
   retaining historical bytes forever.

4. Historical CSV-mode source integrity is anchored by immutable archived
   source_frames + parent analysis lineage.

5. Immutable archived artifacts remain subject to exact stored-hash audit.

6. No historical manifest is rewritten.

7. No flat compatibility artifact is restored or regenerated by Patch 7.

8. No latest/newest heuristic becomes provenance authority.

9. Patch 7 remains READ-ONLY.

10. Scientific/numerical behavior is unchanged.

11. Existing Patch 1–6 schema versions are unchanged.

12. This clarification must remove the reproduced false-positive without
    weakening detection of actual archived-source corruption.
```

---

### Evidence / Source

- Patch 7 initial implementation based on Design Freeze `fd6d90c`
- independent READ-ONLY audit:
  - `BLOCKER 0`
  - `IMPORTANT 2`
  - `MINOR 5`
- reproduced normal workflow:
  - raw analysis
  - CSV-mode analysis
  - later raw re-analysis of the same recording
  - legitimate flat compatibility replacement
  - false `HASH_MISMATCH` on historical CSV-mode inputs
- current producer behavior in `analyze_d455.py`
  - flat compatibility copies are republished/overwritten on later raw analysis
- current Patch 7 Design Freeze:
  - immutable stored-hash audit requirement
  - flat compatibility artifacts are non-authoritative
  - historical legal state must not be classified as corruption

---

### Impact

Patch 7 implementation must be corrected so that:

```text
legitimate later compatibility publication replacement
```

does not invalidate a historical CSV-mode run.

Patch 7 must instead rely on:

```text
archived source_frames
+
parent analysis-manifest lineage
```

for persistent historical integrity.

The implementation correction must add regression tests for:

```text
normal replacement → no ERROR

archived source corruption → ERROR

authoritative parent loss/corruption → ERROR
```

This clarification does not authorize any other weakening of repository-wide hash verification.

Patch 7 implementation remains uncommitted until the independent audit findings are corrected and re-audited.

Supersedes:
- None.

Clarifies:
- `PROV-008` stored-hash semantics for historical CSV-mode inputs that reference mutable flat compatibility publications.

Resolves:
- Patch 7 independent audit finding I-2:
  historical CSV-mode analysis falsely becoming permanent repository ERROR after legitimate re-analysis of the same recording.

---

## PROV-010 — Patch 7 Compatibility Identity and Selection-Evidence Completion Clarification

**Status:** CONFIRMED
**Logged:** 2026-10-05
**Decision timing:** Patch 7 Round 2 independent READ-ONLY re-audit에서 PROV-009의 filename-pattern scope와 Patch 6 exclude-evidence completion semantics에 대한 추가 ambiguity가 재현된 후

### Context

Patch 7 Round 2 independent READ-ONLY re-audit에서 두 개의 추가 false-positive path가 확인되었다.

```text
N-1
PROV-009의 mutable compatibility exception이
analysis/<recording_id>_frames.csv
형식만 인식하여 legacy-pilot compatibility publication을 놓침.

N-2
selection evidence로 참조된 analysis_manifest의 frames output에
completed-owner requirement를 무조건 적용하여,
Patch 6에서 허용된 failed analysis evidence를 ERROR로 판정함.
```

두 finding 모두 corrupted repository가 아니라
기존 frozen authority의 합법적 historical state를 Patch 7 checker가 과도하게 제한하면서 발생한다.

---

### Decision

Patch 7은 다음 두 authority boundary를 추가로 명확히 한다.

```text
1. Mutable compatibility publication identity
   → filename pattern 자체가 아니라
      explicit frozen provenance relation으로 판단한다.

2. Selection evidence completion requirement
   → evidence reference와 consumable selected source를 구분한다.
```

---

# 1. Mutable compatibility publication identity

PROV-009의 다음 예시 경로:

```text
analysis/<recording_id>_frames.csv
analysis/<recording_id>_frames.csv.provenance.json
```

는 mutable compatibility publication의 대표적인 modern naming example이다.

이 literal filename pattern 자체가 compatibility artifact의 canonical identity rule은 아니다.

Patch 7 checker는 mutable compatibility publication 여부를
가능한 경우 parent authoritative frames output에 기록된 explicit provenance relation으로 판정한다.

대표적으로:

```text
parent analysis_manifest
        ↓
frames output
        ↓
compatibility_path
```

관계를 사용한다.

즉:

```text
compatibility_path
```

가 해당 parent output이 publish한 flat compatibility artifact를 명시적으로 가리킨다면,
그 path는 filename spelling과 무관하게 PROV-009의 mutable compatibility semantics를 따른다.

---

## 1.1 Modern and legacy naming

다음 두 형태는 naming rule은 다르지만
동일한 semantic role의 mutable compatibility publication이 될 수 있다.

```text
modern:
analysis/<recording_id>_frames.csv

legacy-pilot:
analysis/<raw-stem>_frames.csv
```

legacy-pilot recording에서 producer가 raw stem 기반 compatibility path를 사용하고,
해당 path가 parent frames output의 frozen explicit `compatibility_path` relation으로 식별된다면,
그 artifact 역시 PROV-009의 mutable compatibility publication으로 취급한다.

따라서 정상 workflow:

```text
legacy raw analysis A
→ legacy flat compatibility publication A
→ CSV-mode analysis B consumes A
→ B archives immutable source_frames / parent lineage
→ later legacy raw re-analysis C
→ same compatibility publication path replaced by C
```

에서:

```text
B historical flat-input SHA
!=
current legacy flat compatibility SHA
```

라는 사실만으로 B를 repository corruption으로 판정해서는 안 된다.

---

## 1.2 No filename-only or heuristic inference

Patch 7은 compatibility identity를 판단하기 위해 다음을 authority로 사용하지 않는다.

```text
basename pattern guess
mtime
ctime
directory order
lexical latest
newest analysis_run_id
largest run ID
```

특히:

```text
*_frames.csv
```

라는 이름만으로 임의의 artifact를 mutable compatibility publication으로 승격하지 않는다.

필요한 relation은 frozen authority가 제공하는 explicit provenance field와
parent/output identity를 통해 확인한다.

---

## 1.3 Historical integrity remains immutable-lineage based

modern 또는 legacy naming 여부와 무관하게,
historical CSV-mode integrity는 계속 다음 chain으로 검증한다.

```text
historical CSV-mode analysis run
        ↓
archived source_frames
        ↓
explicit parent analysis identity
        ↓
parent analysis_manifest
        ↓
parent canonical frames/output
        ↓
stored authoritative SHA
```

따라서 다음은 계속 ERROR다.

```text
archived source_frames missing
archived source_frames SHA mismatch
archived source identity/schema mismatch
parent manifest missing
parent recording_id mismatch
parent analysis_run_id mismatch
parent canonical output missing
parent output ownership mismatch
parent authoritative SHA mismatch
false compatibility ownership claim
```

본 clarification은 immutable lineage validation을 약화하지 않는다.

---

# 2. Selection evidence and completion semantics

Patch 7은 selection event가 참조하는 analysis artifact를 다음 두 역할로 구분한다.

```text
A. evidence
B. selected consumable source
```

두 역할은 동일하지 않다.

---

## 2.1 Exclude decision evidence

Patch 6에서 exclude decision은
실패하거나 불완전한 analysis state를 decision evidence로 참조할 수 있다.

예:

```text
analysis status = failed
+
valid recorded frames/output exists
+
selection decision = exclude
+
event cites analysis manifest as evidence
```

이 상태에서 해당 analysis artifact는:

```text
왜 exclude했는지를 증명하는 historical evidence
```

이지,

```text
향후 RF/dataset에서 소비할 canonical completed source
```

가 아니다.

따라서 Patch 7 checker는 exclude evidence에 대해
단지:

```text
analysis status != completed
```

라는 이유만으로 ERROR를 발생시키지 않는다.

---

## 2.2 Historical evidence validation

exclude evidence가 non-completed analysis를 참조하더라도
Patch 7은 가능한 integrity facts를 계속 검증한다.

예:

```text
manifest 존재
manifest parseability
recording_id
analysis_run_id
recorded output path
output existence
stored SHA
actual SHA
frames header/schema
row identity
owner/output relation
selection-event reference consistency
```

즉:

```text
non-completed
```

라는 상태만 허용되는 것이며,

```text
corrupted evidence
```

까지 허용되는 것은 아니다.

---

## 2.3 Include / selected canonical source

selection decision이 실제 canonical source를 include/select하여
후속 dataset/RF 소비 대상으로 지정하는 경우,
기존 Patch 6 completed-owner requirement를 유지한다.

즉 applicable include path에서는:

```text
selected analysis
→ completed authority required
```

이다.

Patch 7은 이를 약화하지 않는다.

대표적으로 기존 frozen validator / selection source resolution이 요구하는:

```text
completed analysis owner
exact recording_id
exact analysis_run_id
exact frames artifact
exact hash
dataset-role consistency
```

를 그대로 적용한다.

---

## 2.4 Evidence-kind analysis_manifest

`analysis_manifest`가 selection evidence로 등장한다는 이유만으로
그 manifest의 모든 frames output에 consumable canonical-input semantics를 강제하지 않는다.

검증 mode는 해당 reference의 frozen role에 따라 구분한다.

```text
exclude evidence
→ historical-output / evidence integrity validation
→ completion not required by status alone

include selected source
→ canonical consumer validation
→ completion required
```

---

# 3. Relationship to DF-17 / Patch 6 authority

Patch 7 Design Freeze DF-17의 evidence validation은
Patch 6에서 이미 freeze된 selection semantics를 재정의하지 않는다.

따라서 DF-17의 `analysis_manifest` / `canonical_frames` evidence validation 문구를
모든 evidence에 completed-owner requirement를 새로 부과하는 규칙으로 해석하지 않는다.

Patch 6에서 status requirement가 역할별로 다르게 freeze되어 있다면
Patch 7은 그 차이를 보존해야 한다.

이 특정 conflict에서는 본 PROV-010 interpretation이 우선한다.

---

# 4. What remains an ERROR

본 clarification 이후에도 다음은 ERROR다.

```text
exclude evidence manifest missing

exclude evidence path/hash mismatch

exclude evidence frames schema/identity mismatch

exclude event가 존재하지 않는 analysis_run_id를 claim

include decision이 non-completed analysis를 selected canonical source로 사용

dataset manifest가 non-completed selected analysis를 canonical source로 claim

RF input이 non-completed owner를 canonical input으로 사용

legacy/modern compatibility path를 explicit provenance relation 없이
단순 filename guess로 mutable publication이라고 간주

archived CSV source or parent immutable lineage corruption

false current compatibility ownership claim
```

---

# 5. What is NOT an ERROR

다음 상태는 그 자체로 repository corruption이 아니다.

```text
Case A — legacy mutable compatibility lifecycle

legacy raw A
→ CSV B
→ legacy raw C
→ parent compatibility_path로 식별된 flat publication replaced
→ B immutable archived lineage intact
```

결과:

```text
historical flat SHA != current flat SHA
```

여도 ERROR가 아니다.

---

```text
Case B — exclude evidence from failed analysis

analysis run fails after recording valid diagnostic output
→ append-only selection event records exclude decision
→ failed analysis manifest/output cited as evidence
```

이 경우:

```text
status == failed
```

라는 이유만으로 evidence를 ERROR로 판정하지 않는다.

---

# 6. Scope limitation

본 clarification은 다음 두 항목에만 적용한다.

```text
1. PROV-009 mutable compatibility publication identity
2. Patch 6 selection evidence completion semantics
```

다음을 변경하지 않는다.

```text
frames-schema/1.0.0
summary-schema
selection ledger serialization
dataset manifest schema
RF experiment schema
sample lineage schema
Patch 6 include semantics
RF completed-owner requirement
scientific inclusion/exclusion policy
retake policy
F1/F2 definition
Patch 8 hardware validation
```

---

# 7. Required regression tests

Patch 7 implementation commit 전에 최소 다음 test를 추가한다.

## N-1 regression

```text
legacy raw analysis A
→ CSV-mode B consuming legacy flat compatibility publication
→ later legacy raw analysis C replaces flat publication
→ B archived immutable lineage intact

Expected:
NO ERROR solely from historical-flat SHA != current-flat SHA
```

Negative controls:

```text
same lifecycle + archived source corruption
→ ERROR

same lifecycle + parent canonical source loss/corruption
→ ERROR

unrelated/non-compatibility *_frames.csv hash mismatch
→ ERROR
```

---

## N-2 regression

```text
failed analysis
+
valid recorded frames/output
+
Patch 6-valid exclude event
+
analysis_manifest used as exclude evidence

Expected:
NO ERROR solely because analysis status == failed
```

Negative controls:

```text
same exclude evidence + output hash corruption
→ ERROR

same exclude evidence + identity/schema corruption
→ ERROR

include decision selecting non-completed analysis
→ ERROR
```

---

# 8. Invariants

```text
1. Patch 7 remains READ-ONLY.

2. PROV-009 remains in force.

3. Mutable compatibility identity is established through explicit
   provenance relation, not filename guess or latest/newest heuristic.

4. Modern and legacy naming may represent the same mutable semantic role.

5. Historical CSV-mode integrity remains anchored by immutable archived
   source + parent lineage.

6. Exclude evidence does not become a consumable canonical source merely
   because it references an analysis manifest.

7. Failed/running/incomplete status alone is not corruption.

8. Corrupted historical evidence remains ERROR.

9. Include/selected canonical sources retain completed-owner enforcement.

10. RF/dataset consumer completion rules remain unchanged.

11. Scientific/numerical behavior is unchanged.

12. Patch 1–6 schemas and selection semantics are not rewritten.
```

---

### Evidence / Source

- Patch 7 Round 2 independent READ-ONLY re-audit
  - `BLOCKER 0`
  - `IMPORTANT 2`
  - `MINOR 5`

- re-audit finding `N-1`
  - modern `recording_id`-named compatibility lifecycle passes
  - legacy-pilot raw-stem-named compatibility lifecycle reproduces historical `HASH_MISMATCH`
  - producer already records explicit compatibility relation through parent frames output

- re-audit finding `N-2`
  - Patch 6-valid exclude event can cite a failed analysis as evidence
  - Patch 7 evidence path incorrectly reapplies completed-owner requirement

- `PROV-008`
- `PROV-009`
- `docs/foundation/PATCH_07_integrity_checker_hardening.md`
- Patch 3 legacy-pilot provenance contract
- Patch 6 Selection Manifest / Recapture Inclusion frozen contract

---

### Impact

Patch 7 implementation must be corrected so that:

```text
N-1:
explicitly identified legacy mutable compatibility publication
receives the same historical semantics as the modern equivalent.

N-2:
exclude evidence uses historical/evidence integrity validation,
while include-selected canonical sources retain completion enforcement.
```

The repair must not:

```text
broaden compatibility exceptions by filename wildcard

remove completed-owner checks from consumers

rewrite selection history

rewrite historical manifests

introduce newest/latest heuristics

change scientific or numerical behavior
```

Patch 7 implementation remains uncommitted until
the Round 3 repair passes targeted/full regression and
a subsequent independent READ-ONLY re-audit confirms:

```text
BLOCKER == 0
IMPORTANT == 0
```

Supersedes:
- None.

Clarifies:
- `PROV-009` compatibility-publication identity semantics beyond the modern `<recording_id>_frames.csv` naming example.
- `PROV-008` / Patch 7 DF-17 evidence validation where Patch 6 distinguishes exclude evidence from include-selected canonical sources.

Resolves:
- Patch 7 Round 2 re-audit `N-1`
- Patch 7 Round 2 re-audit `N-2`

---

## PROV-011 — Patch 7 Selection Evidence Role Semantics Clarification

**Status:** CONFIRMED
**Logged:** 2026-10-06
**Decision timing:** Patch 7 Round 3 independent READ-ONLY re-audit에서 PROV-010의 exclude-specific implementation이 `recapture` 및 `include` event의 historical evidence role까지 충분히 일반화하지 못해 정상 append-only selection history가 permanent false ERROR가 되는 경로가 재현된 후

### Context

Patch 7 Round 3 independent READ-ONLY re-audit에서 다음 상태가 확인되었다.

기존 Round 3 구현은:

```text
exclude event
→ historical evidence
→ non-completed analysis evidence 허용
```

경로에서는 PROV-010을 올바르게 적용했다.

그러나 동일한 historical evidence role이:

```text
recapture event
include event
```

안에 존재하는 경우에는 event action 때문에 다시 canonical-consumer completion semantics가 적용될 수 있었다.

그 결과 repository authority와 bytes가 정상임에도:

```text
status != completed
```

라는 이유만으로 historical evidence가 permanent `OWNER_MISMATCH` / integrity ERROR가 될 수 있었다.

이는 append-only selection history에서 정상 과거 event를 사후 rewrite하지 않고는 제거할 수 없는 false positive다.

---

### Decision

Patch 7 selection-evidence validation에서 completed-owner requirement는:

```text
event action
(include / exclude / recapture)
```

자체로 결정하지 않는다.

반드시 각 artifact reference가 수행하는 frozen role에 따라 결정한다.

핵심 구분:

```text
A. historical decision evidence
B. selected / consumed canonical source
```

이다.

---

# 1. Event action and artifact role are independent dimensions

Selection event의 action:

```text
include
exclude
recapture
```

은 그 event 내부 모든 artifact reference의 completion semantics를 일괄 결정하지 않는다.

하나의 event에는 서로 다른 역할의 reference가 동시에 존재할 수 있다.

대표적으로:

```text
include event
├─ analysis_selection
│  → downstream에서 실제 선택·소비되는 canonical source
│
└─ evidence[]
   → 해당 결정을 뒷받침하는 historical decision evidence
```

따라서:

```text
include event
```

라는 이유만으로 `evidence[]`의 모든 analysis artifact에 completed-owner requirement를 적용해서는 안 된다.

동일하게:

```text
recapture event
```

의 evidence는 재촬영 판단의 historical evidence일 수 있으며,
failed/running/incomplete status 자체가 corruption을 의미하지 않는다.

---

# 2. Historical evidence role

다음 selection action 모두에서:

```text
include
exclude
recapture
```

artifact가 오직:

```text
evidence[]
```

또는 동등한 frozen historical-evidence reference로 사용되는 경우,
그 artifact는 historical decision evidence role로 검증한다.

Historical evidence validation은:

```text
status == completed
```

를 status 자체만으로 요구하지 않는다.

즉 다음 상태는 그 자체로 ERROR가 아니다.

```text
failed analysis used only as evidence
running analysis used only as evidence
incomplete analysis used only as evidence
```

단, Patch 6 frozen contract가 해당 evidence reference 자체를 허용하는 경우에 한한다.

PROV-011은 Patch 6에서 허용하지 않은 새로운 evidence kind나 reference 형태를 만들지 않는다.

---

# 3. Historical evidence integrity remains strict

Non-completed historical evidence라도 applicable integrity facts는 계속 검증한다.

최소 기존 frozen authority가 요구하는 범위에서:

```text
evidence artifact existence
manifest parseability
evidence kind / reference validity
recording_id
analysis_run_id
artifact path
stored SHA
actual-byte SHA
frames header / exact schema
row recording_id
row analysis_run_id
owner/output relationship
selection-event evidence reference
other frozen identity / lineage fields
```

를 검증한다.

따라서 다음은 계속 ERROR다.

```text
evidence missing

evidence stored SHA mismatch

evidence actual bytes corrupted

evidence schema invalid

evidence recording_id mismatch

evidence analysis_run_id mismatch

evidence owner/output relation invalid

selection event references nonexistent or contradictory evidence

malformed evidence authority that contradicts frozen schema
```

PROV-011은 evidence integrity validation을 약화하지 않는다.

완화되는 것은 오직:

```text
historical evidence role에 대해
status != completed 라는 사실만으로 ERROR를 만드는 것
```

이다.

---

# 4. Selected / consumed canonical source role

실제로 downstream에서 선택·소비되는 canonical source에는 기존 completed-owner requirement를 그대로 적용한다.

대표적 역할:

```text
analysis_selection

dataset-selection manifest의 selected/canonical analysis source

RF canonical input

기타 Patch 5/6 frozen consumer가 completed owner를 요구하는 source
```

이 역할에서는:

```text
status == completed
```

가 계속 필수다.

따라서:

```text
include event
+
analysis_selection points to non-completed analysis
```

는 계속 ERROR다.

PROV-011은 include-selected source의 completion requirement를 완화하지 않는다.

---

# 5. Same artifact in multiple roles

동일한 analysis artifact가 하나의 selection state에서 동시에:

```text
historical evidence
+
selected / consumed canonical source
```

두 역할을 수행한다면,
각 reference edge는 자신의 frozen role에 따라 검증한다.

해당 artifact는 전체 repository state가 valid하려면
모든 applicable role requirement를 충족해야 한다.

따라서 동일 artifact가 selected canonical source 역할도 가진다면:

```text
completed-owner requirement
```

를 만족해야 한다.

Historical evidence role이 존재한다는 이유로
selected-source requirement를 우회할 수 없다.

즉:

```text
same non-completed analysis
├─ evidence role
└─ analysis_selection role
```

이면 evidence reference 자체는 status-only corruption이 아니지만,
selected-source role이 completion requirement를 위반하므로 repository result는 ERROR다.

---

# 6. Action-specific examples

## 6.1 Exclude

```text
exclude event
└─ failed analysis_manifest in evidence[]
```

해당 evidence의 bytes/hash/schema/identity가 정상이라면:

```text
status == failed
```

라는 이유만으로 ERROR를 만들지 않는다.

---

## 6.2 Recapture

```text
recapture event
└─ failed analysis_manifest / canonical_frames in evidence[]
```

재촬영 판단의 historical evidence로서 frozen reference가 유효하고
bytes/hash/schema/identity가 정상이라면:

```text
status != completed
```

라는 이유만으로 ERROR를 만들지 않는다.

---

## 6.3 Include with separate auxiliary evidence

```text
include event
├─ analysis_selection
│  → completed analysis A
│
└─ evidence[]
   → failed analysis B
```

이 경우:

```text
analysis A
→ selected canonical source
→ completed REQUIRED

analysis B
→ historical evidence only
→ completed NOT required solely by status
```

둘의 각 role-specific integrity requirement가 모두 충족되면
전체 event는 status semantics 때문에 실패해서는 안 된다.

---

## 6.4 Include selecting a non-completed source

```text
include event
├─ analysis_selection
│  → failed analysis A
│
└─ evidence[]
   → any valid evidence
```

결과:

```text
ERROR
```

이다.

이유는 event action이 include이기 때문이 아니라:

```text
analysis A가 selected / consumed canonical source role에서
completed-owner requirement를 위반했기 때문
```

이다.

---

# 7. Relationship to PROV-010

본 `PROV-011`은 `PROV-010`을 폐기하거나 전체 supersede하지 않는다.

`PROV-010`의 핵심 원칙:

```text
historical evidence role
!=
selected consumable canonical source role
```

은 그대로 유지한다.

다만 `PROV-010`의 설명과 initial implementation이:

```text
exclude evidence
vs
include selected source
```

구도로 좁게 해석될 수 있었던 ambiguity를 다음과 같이 명확화한다.

정확한 authority boundary는:

```text
event action 기준이 아니라
artifact reference role 기준
```

이다.

이 특정 selection-evidence completion ambiguity에서는
본 `PROV-011` interpretation이 우선한다.

---

# 8. No new selection/scientific semantics

본 clarification은 다음을 새로 결정하거나 변경하지 않는다.

```text
which recordings should scientifically be included

which recordings should be excluded

when a recapture should scientifically occur

participant count

round count

retake maximum

quality threshold

outlier policy

F1/F2 definition

RF numerical behavior

Patch 8 hardware criteria
```

또한 selection event의 frozen schema, action vocabulary, append-only history를 변경하지 않는다.

Patch 7은 계속 기존 selection authority를:

```text
read
validate
cross-reference
report
```

할 뿐이다.

---

# 9. Required regression tests

Patch 7 implementation commit 전에 최소 다음 regression을 요구한다.

## R-1 — exclude historical evidence

```text
failed analysis
+
valid exclude event
+
analysis used only as evidence
```

Expected:

```text
NO ERROR solely because status != completed
```

기존 regression을 유지한다.

---

## R-2 — recapture historical evidence

```text
failed or running analysis
+
Patch 6-valid recapture event
+
analysis_manifest and/or canonical_frames used only as evidence
```

Expected:

```text
NO ERROR solely because status != completed
```

---

## R-3 — include event with separate failed evidence

```text
include event
+
completed selected analysis A
+
separate failed analysis B used only as evidence
```

Expected:

```text
NO ERROR solely because evidence B is non-completed
```

Selected source A는 기존 completion requirement를 충족해야 한다.

---

## R-4 — selected non-completed analysis remains invalid

```text
include event
+
analysis_selection → failed/running analysis
```

Expected:

```text
ERROR
```

Historical evidence rules로 이 failure를 우회할 수 없다.

---

## R-5 — recapture evidence corruption

```text
valid recapture evidence role
+
evidence hash/schema/identity corruption
```

Expected:

```text
ERROR
```

---

## R-6 — include auxiliary evidence corruption

```text
completed selected source
+
separate historical evidence
+
evidence hash/schema/identity corruption
```

Expected:

```text
ERROR
```

---

## R-7 — same artifact occupies both roles

```text
include event
+
same non-completed analysis referenced as evidence
+
same analysis selected through analysis_selection
```

Expected:

```text
ERROR
```

because selected-source completion semantics remain applicable.

---

# 10. Implementation constraint

Patch 7 checker는 다음과 같은 action-wide bypass를 구현해서는 안 된다.

```text
if action == exclude:
    completion_not_required_for_everything

if action == recapture:
    completion_not_required_for_everything

if action == include:
    completion_required_for_everything
```

대신 reference의 role을 명시적으로 구분해야 한다.

Conceptually:

```text
historical evidence reference
→ evidence integrity validation
→ completion not required by status alone

selected / consumed source reference
→ canonical consumer validation
→ completion required where frozen authority says so
```

기존 Patch 3/5/6 validator를 가능한 한 재사용하며,
새 scientific inference를 추가하지 않는다.

---

# 11. Invariants

```text
1. Event action alone does not determine evidence completion semantics.

2. Historical evidence role may occur in include, exclude, or recapture events.

3. Non-completed status alone is not corruption for a legal historical evidence role.

4. Historical evidence hash/schema/identity/ownership corruption remains ERROR.

5. Selected / consumed canonical sources retain completed-owner enforcement.

6. An artifact occupying multiple roles must satisfy every applicable role requirement.

7. Evidence-role semantics cannot be used to bypass selected-source completion requirements.

8. Patch 6 selection schema and append-only history remain unchanged.

9. Patch 7 does not rewrite selection events or historical authority.

10. Patch 7 remains READ-ONLY.

11. Scientific/numerical behavior remains unchanged.

12. PROV-009 and PROV-010 remain in force except for the specific ambiguity clarified here.
```

---

### Evidence / Source

- Patch 7 Round 3 independent READ-ONLY re-audit
  - `BLOCKER 0`
  - `IMPORTANT 1`
  - previous `I-1`, `I-2`, `N-1` confirmed resolved
  - `N-2` confirmed resolved for exclude evidence but incomplete for equivalent historical evidence roles under recapture/include actions
- reproduced legal append-only selection-history states where valid historical evidence could receive permanent false completed-owner ERROR
- `PROV-008`
- `PROV-009`
- `PROV-010`
- Patch 6 Selection Manifest / Recapture Inclusion frozen authority
- `docs/foundation/PATCH_07_integrity_checker_hardening.md`

---

### Impact

Patch 7 implementation must be corrected so that:

```text
completion requirement
```

is determined by:

```text
artifact reference role
```

rather than:

```text
event action
```

Specifically:

```text
include / exclude / recapture historical evidence
→ no completed-owner requirement solely from evidence status

selected / consumed canonical source
→ existing completed-owner requirement preserved
```

The correction must remove the reproduced false positive without weakening
hash/schema/identity/ownership validation or canonical-consumer completion enforcement.

Patch 7 implementation remains uncommitted until:

```text
focused implementation repair
→ targeted regression
→ full regression
→ independent READ-ONLY re-audit
```

confirms:

```text
BLOCKER == 0
IMPORTANT == 0
```

Supersedes:
- None.

Clarifies:
- `PROV-010` selection-evidence completion semantics: the controlling boundary is artifact reference role, not selection event action.
- `PROV-008` / Patch 7 evidence validation where historical evidence can appear under `include`, `exclude`, or `recapture` events.

Resolves:
- Patch 7 Round 3 independent READ-ONLY re-audit remaining IMPORTANT finding: legal `recapture` and `include` historical evidence can otherwise receive a permanent false completed-owner ERROR.

---

## CAP-005 — Foundation Patch 8 D455 Measurement-Quality and End-to-End Validation Design Freeze

**Status:** CONFIRMED
**Logged:** 2026-10-07
**Decision timing:** Pre-implementation / pre-formal-hardware-execution Design Freeze — V5.1.1 independent READ-ONLY audit `BLOCKER 0 / IMPORTANT 0` 이후, Patch 8 implementation 및 formal D455 hardware execution 이전

### Decision

Foundation Patch 8의 actual Intel RealSense D455 measurement-quality / end-to-end validation protocol을 Design Freeze한다.

상세 normative contract는 다음 문서를 단일 상세 authority로 사용한다.

```text
docs/foundation/PATCH_08_actual_d455_end_to_end_validation.md
```

본 entry는 그 문서의 section 전체를 반복하지 않고, 변경 불가한 핵심 결정과 경계만 기록한다. 본 entry와 Foundation document 사이에 표현 차이가 보이면 Foundation document의 exact rule을 따르며, 임의 해석 대신 충돌로 보고한다.

---

### Core decisions

#### A. Candidate-range derivation / static grid / anchors

```text
lower bound
= max(D455 ideal lower bound 0.60 m, ergonomic lower region 0.50 m)
= 0.60 m

upper bound
= ergonomic upper region 1.00 m

static candidate region = 0.60–1.00 m
spacing                 = 0.10 m
frozen static grid      = 0.60 / 0.70 / 0.80 / 0.90 / 1.00 m
mandatory anchors       = 0.70 / 0.80 m (existing repository seating target)
```

특정 논문 한 편의 거리를 그대로 채택하지 않는다 (`CAP-003`).

Range concepts는 분리한다.

```text
formal initial seating range (Patch 8 전체 PASS 후) = 0.70–0.80 m
validated static measurement envelope              = 별도 산출
```

Envelope가 더 넓더라도 initial seating range를 자동 확대하지 않는다.

#### B. Pre-data declaration

Patch 8 결과를 보기 전에 다음을 고정한다.

```text
static grid                    0.60 / 0.70 / 0.80 / 0.90 / 1.00 m
static repetitions             3
static hold                    10.0 s
frame coverage                 >= 0.85
landmark / conditional depth   >= 0.95
complete RGB-D geometry        >= 0.90
depth SD                       <= 10 mm
within-take geometry CV        <= 3%
between-take geometry spread   <= 3%
distance stability             <= 5%
minimum valid n                30
production-guide timeout       15 s
```

2026-10-02 Early Hardware Preflight는 위 값의 선택 근거가 아니다 (local engineering evidence only).

결과 관찰 후 protocol 변경은 CAP-005를 소급 수정하지 않고 `Supersedes: CAP-005` + `POST-HOC PROTOCOL CHANGE` 표기를 가진 새 append-only entry로만 한다.

#### C. Physical setup

```text
one adult reserved validation subject, dataset_role = pilot
rigid camera mount; camera pose fixed after first canonical static take
camera disturbance after first canonical static take → execution FAIL
pose re-check: height > 5 mm, pitch/yaw/roll > 1 degree, or witness-mark displacement → FAIL
face / both shoulders / both hips observable and unobstructed across the static grid
pre-attempt setup check before attempt_start
color 1280×720 / depth 848×480 / 15 FPS / depth aligned to color
warm-up 60 s; settling 10 s after reposition and after objective retry
independent physical distance reference: static nominal ±0.02 m; production placement 0.75 ±0.02 m
```

Patch 8 setup은 validation setup only이며 `OPEN-005` formal workstation framing을 해결하지 않는다.

#### D. Execution governance

```text
Design Freeze commit
→ implementation commit
→ regression tests
→ independent implementation audit (BLOCKER 0 / IMPORTANT 0)
→ execution authorization / registration commit
→ formal hardware execution
```

```text
execution pre-registration before first formal D455 use
execution starts at first formal slot attempt_start
one execution_id per formal execution; session_id per physical session
no hidden rehearsal reclassification
single-shot first execution
audited implementation commit pinned; mid-execution code/environment change → FAIL / terminated
re-execution only via new append-only authorization entry
clean execution workspace
runtime governance outputs under validation/patch8/<execution_id>/
```

#### E. Protocol identities / ledger

```text
static slots 1–15                 protocol_version = patch8-d455-static-validation-v1.0.0
production slots 101–113/121/131  protocol_version = capture-forward-face-v2.0.0
validation ledger format          patch8-validation-control/1.0.0
```

Static path는 existing `capture-provenance/1.0.0` 구조를 재사용하며 `target_range_m` / `start_distance` 등 existing production field를 새 의미로 repurpose하지 않는다. `nominal_distance`, `repetition_index`, `attempt_index`, `execution_id`는 ledger authority이며 existing scientific field에 재사용하지 않는다.

`patch8-validation-control/1.0.0`은 operational governance ledger다. `frames-schema/1.0.0`, `summary-schema/1.0.0`, `selection-event/1.0.0`, `dataset-selection-manifest/1.0.0`의 새 version이나 대체물이 아니다. Patch 8 retry bookkeeping은 Patch 6 scientific selection이 아니다.

Ledger는 canonical JSON serialization과 `previous_event_sha256` / `event_sha256` hash chain을 사용하며 기존 line 수정/삭제를 금지한다.

#### F. Retry / result firewall / closed pre-lock classification

```text
attempt_start → acquisition → capture_finished → recording-stage classification
→ pre-result structural probes → validity_locked → attempt_end
→ only after lock: unseal results / analysis / Patch 8 metrics
```

```text
acquisition validity is immutable before result inspection
static operator-visible feedback firewall from settling start until validity_locked
production child-process stdout/stderr and result-bearing files sealed before lock
closed pre-lock classification table overrides generic retry rules
guide q / 15 s guide timeout / s skip → GUIDE_NOT_SATISFIED, canonical FAIL evidence, NO RETRY
operator q / SIGINT / SIGTERM / kill / manual closure → MANUAL_ABORT, NO RETRY
POWER_FAILURE requires independent power-loss evidence
partial frame loss is not machine-invalid
unclassifiable termination → UNCLASSIFIED_TERMINATION, acquisition-valid, NO RETRY (fail-closed)
static slot max 3 attempts; production one attempt_start = one child launch
first completed analysis run is canonical; a non-conforming first completed run is canonical FAIL
```

#### G. Static metrics

```text
static analysis window   1.0 <= t < 9.5
frame coverage           N_static / 127.5 >= 0.85 (N_static >= 109)
landmark acquisition     face detection / face mesh / pose / bilateral shoulder in-frame / bilateral hip in-frame >= 0.95
head depth-valid         valid = face_detected && face_depth_valid && face_depth_source == "bbox_roi"; valid / face_detected >= 0.95
shoulder / hip           count(point_valid && point_depth_valid) / count(point_valid) >= 0.95
complete RGB-D geometry  complete / N_static >= 0.90
minimum n                30
```

Depth temporal repeatability는 정확히 다섯 series에 각각 적용한다.

```text
z_face_m           face_detected && face_depth_valid && face_depth_source == "bbox_roi" && finite && > 0
z_lsh_m            lsh_valid && lsh_depth_valid && finite && > 0
z_rsh_m            rsh_valid && rsh_depth_valid && finite && > 0
left_hip_depth_m   left_hip_valid && left_hip_depth_valid && finite && > 0
right_hip_depth_m  right_hip_valid && right_hip_depth_valid && finite && > 0
```

```text
sample population = canonical rows of that take within the frozen static window (§55)
                    INTERSECTED WITH that series' validity mask
                    (no additional filtering of any kind)
per canonical take, per series: n >= 30
temporal_depth_sd_mm = sample_sd(depth_m, ddof = 1) × 1000 <= 10 mm
all five series PASS → canonical take PASS
all three canonical takes PASS → static distance point PASS (for this criterion)
```

3D / IPD / stability:

```text
P = SDK deproject(color intrinsics, pixel, aligned_depth)
shoulder_width_3d, hip_width_3d, trunk_length_3d (validation-only)
IPD valid frame rule; valid_ipd_n >= 30; take metric median(ipd_cm)

within-take CV <= 0.03         exactly: shoulder_width_3d / hip_width_3d / trunk_length_3d
between-take spread <= 0.03    exactly: shoulder_width_3d / hip_width_3d / trunk_length_3d
distance stability <= 0.05     exactly: ipd_cm / shoulder_width_3d / hip_width_3d / trunk_length_3d
                               anchor = 6 take medians at 0.70 m and 0.80 m
```

Static point PASS는 Foundation document §71의 모든 조건을 요구한다. 0.70 m 또는 0.80 m anchor FAIL이면 range validation FAIL이며 envelope = NONE이다. Anchors PASS이면 envelope는 both anchors를 포함하는 maximal contiguous PASS grid interval이다.

#### H. Forward / body-only / E2E

```text
forward availability population (no pooling, per designated phase):
101–103  forward_head
111–113  body_forward
121      excluded (body-only negative protocol only)
131      forward_head AND body_forward, each independently

forward phase window 1.0 < t < phase_duration - 0.5; N_forward >= 109; blocking rates per Foundation §75.3

production forward gate unchanged: 0.08–0.12 m inclusive, face_only
validation bands: below 0.05–0.07 / pass 0.09–0.11 / above 0.13–0.15 m (closer_m)
forward slots max 3 attempts; TARGET_MISS bounded retry only for non-null, internally consistent, out-of-band closer_m
```

Body-only negative slot 121 (`SEQ_CORE`, designated phase `body_forward`)은 reference face sufficient, current face insufficient, valid body-mode samples, `closer_m == null`, `forward_gate_result != pass`, `forward_gate_reasons == ["insufficient_current_face_samples"]`를 요구하며 target condition achieved but gate PASS이면 immediate FAIL이다.

Slot 131 (`SEQ_FULL`, `dataset_role = pilot`) PASS predicate:

```text
canonical acquisition-valid recording exists
AND capture verdict == ok
AND forward_head §75 PASS AND body_forward §75 PASS
AND forward_head production gate PASS AND body_forward production gate PASS
AND canonical analysis predicate PASS
AND artifact/lineage predicate PASS
AND recording reconciliation PASS AND analysis reconciliation PASS
```

`capture verdict == ok` requirement는 Patch 8 validation closure 전용이며 formal experiment의 `ok_with_warnings` eligibility (`OPEN-005`)를 결정하지 않는다. Result-based retry는 금지한다.

#### I. Reconciliation / integrity

```text
every execution-created raw recording ↔ exactly one attempt_start + exactly one capture_finished binding
every canonical recording ↔ exactly one canonical_analysis_run_id; unlogged completed run → FAIL
pre-hardware integrity_check.py: exit 0 / PASS / ERROR 0
closure integrity_check.py:      exit 0 / PASS / ERROR 0; WARNING recorded, not auto-FAIL
preserved evidence is never deleted to clear ERROR
```

#### J. Patch 8 PASS / failure semantics

Patch 8 COMPLETE는 Foundation document §92의 A–Y 조건을 모두 요구한다. FAIL은 evidence이며 grid, anchors, thresholds, camera settings, resolution, FPS, ROI, schema, models, production forward gate, body fallback semantics, scientific features를 자동 변경하지 않는다. 재실행은 Foundation document §21 governance를 따른다.

#### K. Explicit non-decisions

```text
F1 / F2 exact formula; formal scientific feature set
formal participant count / rounds / inclusion / exclusion
formal selection_policy_version
RF λ grid / model-selection rule
final EXPERIMENT_PROTOCOL
participant-specific calibration
new shoulder / hip posture hard gate
new body fallback capable of forward PASS
new scientific depth ROI
frames-schema/1.0.0 field / summary-schema/1.0.0 field
OPEN-005 formal workstation framing
```

Head bbox depth, `ipd_cm`, `shoulder_width_3d`, `hip_width_3d`, shoulder/hip midpoint, `trunk_length_3d`는 validation-only quantity이며 `OPEN-002` / `OPEN-003` resolution 또는 F1/F2 definition이 아니다.

---

### Rationale

`CAP-003`은 literature / ergonomics / D455 characteristics로 candidate range를 정한 뒤 actual D455 validation을 거쳐 formal range를 freeze하도록 요구했고, `CAP-004`는 Patch 8에 D455 measurement-quality validation을 포함하도록 했다. 그 exact 절차·grid·반복·metric·acceptance criterion은 `OPEN-006`으로 남아 있었다.

Patch 8 결과를 보기 전에 모든 protocol 값, PASS/FAIL predicate, retry/canonical-selection rule을 고정해야 hardware 결과에 맞춘 threshold tuning, retake cherry-picking, post-hoc canonical selection을 구조적으로 배제할 수 있다. Production forward gate와 Patch 4~7 frozen contract를 그대로 사용해야 validation 대상이 실제 연구 pipeline과 동일하게 유지된다.

### Alternatives / Rejected / Deferred

```text
특정 논문 한 편의 거리값 채택                              REJECTED (CAP-003)
<40 cm fallback / 새 거리 보정 선제 도입                     REJECTED (CAP-003)
Early Hardware Preflight 값을 threshold 근거로 사용         REJECTED
envelope 결과로 initial seating range 자동 확대               REJECTED
결과 관찰 후 retry / 더 좋은 run으로 canonical 교체         REJECTED
checkerboard / cross / known geometric target 필수화         NOT REQUIRED (CAP-004)
formal framing / ok_with_warnings formal eligibility        DEFERRED (OPEN-005)
F1 / F2 exact definition                                    DEFERRED (OPEN-002 / OPEN-003)
rank_weights p > 6 policy                                   DEFERRED (OPEN-004)
```

### Evidence / Source

Repository evidence:

- existing production seating / start target `0.70–0.80 m` (`capture_d455.py` `target_range_m`; `RESEARCH_DATA_SCHEMA.md` §C.2 / §M.1)
- `CAP-003` — candidate evidence → actual D455 validation → formal distance/range freeze
- `CAP-004` — Patch 8 D455 measurement-quality validation scope
- `CAP-001`, `CAP-002`, `DATA-003`, `PROV-004` ~ `PROV-011` (unchanged frozen authority)
- Patch 7 main baseline: branch `main`, HEAD / origin/main `b2e090f` (`b2e090ffbbbaf378f4f8243d424bd374e57e1e44`), working tree clean

External evidence:

- RealSense D455 official product specification / product page
  - URL: https://www.realsenseai.com/products/real-sense-depth-camera-d455f/
  - relevant fact: Ideal Range 0.6 m to 6 m
  - access date: 2026-10-07
- U.S. Occupational Safety and Health Administration (OSHA), eTools: Computer Workstations — Workstation Components — Monitors
  - URL: https://www.osha.gov/etools/computer-workstations/components/monitors/
  - relevant fact: preferred viewing distance 20–40 inches (approximately 50–100 cm)
  - access date: 2026-10-07
  - OSHA range는 workstation ergonomic evidence일 뿐 D455 sensor-accuracy specification이 아니다

Design Freeze review evidence:

- V5.1.1 Design Freeze draft (`PATCH_08_DESIGN_FREEZE_V5.1.1_AUDIT_DRAFT.md`, SHA-256 `4747c181eee5280151cd332e43ef7ed28b953cb3be004f201c56c2818af5b199`)
- final independent READ-ONLY Design Freeze audit: `BLOCKER 0 / IMPORTANT 0 / MINOR 1`, READY FOR DESIGN-FREEZE COMMIT; 단일 MINOR(E2-R1 depth temporal-SD sample-population wording)는 Foundation document §62에 clarification-only로 반영

Agreement between AI review passes는 experimental evidence가 아니다. 본 entry는 D455 hardware 결과를 포함하지 않는다.

### Impact

- Foundation Patch 8 Design Freeze를 완료한다. Patch 8 state는 **DESIGN-FROZEN**이다.
- Patch 8 implementation, implementation audit, execution authorization / registration, formal D455 hardware execution은 모두 **PENDING**이다. 본 entry는 Patch 8 COMPLETE 또는 actual D455 validation PASS를 의미하지 않는다.
- Patch 8 implementation은 `docs/foundation/PATCH_08_actual_d455_end_to_end_validation.md`의 §90 implementation scope와 §91 MUST NOT을 따른다.
- 본 entry가 `OPEN-006`을 해소한다. append-only 규칙에 따라 과거 `OPEN-006` entry의 본문과 `Status: DEFERRED`는 수정하지 않는다. 현재 상태는 `OPEN-006` RESOLVED BY CAP-005다.
- `OPEN-002`, `OPEN-003`, `OPEN-004`, `OPEN-005`는 계속 DEFERRED다.
- Patch 4 / 4.5 / 5 / 6 / 7 authority (`DATA-003`, `PROV-004` ~ `PROV-011`)와 `CAP-001` ~ `CAP-004`는 변경하지 않는다.
- `frames-schema/1.0.0`, `summary-schema/1.0.0`, `selection-event/1.0.0`, `dataset-selection-manifest/1.0.0`, `capture-forward-face-v2.0.0` production semantics는 변경하지 않는다.
- Execution registry (`docs/research/PATCH_08_EXECUTION_REGISTRY.md` 예시)와 `execution_id`는 Design Freeze에서 만들지 않으며 audited implementation 이후 formal hardware execution 전에 등록한다.
- 대규모 formal participant collection은 Patch 8 PASS 및 기타 formal collection gate 전 시작하지 않는다.

Supersedes:
- None

Resolves:
- `OPEN-006`

---

## CAP-006 — Patch 8 Forward Validation Slot Sequence Clarification

**Status:** CONFIRMED
**Logged:** 2026-10-07
**Decision timing:** Pre-execution clarification — Patch 8 implementation(uncommitted working tree) 중 implementation gap `P8-I1`이 확인된 직후, implementation commit / independent implementation audit / execution authorization·registration / formal Patch 8 D455 hardware execution **이전**

### Context

`CAP-005`와 그 상세 authority `docs/foundation/PATCH_08_actual_d455_end_to_end_validation.md`는 production validation slot에 대해 다음을 이미 freeze했다.

```text
§33  101–103  forward_head  below / pass / above
     111–113  body_forward  below / pass / above
     121      body-only negative, designated phase = body_forward
     131      full-posture E2E
§41  101–113 / 121 / 131 → capture_d455.py child process
§75  forward availability population (101–103 forward_head only,
     111–113 body_forward only, 121 excluded, 131 both phases separately)
§76  validation bands
§78  forward slots
§79  forward-slot attempt / retry semantics
§80  round 121: sequence = SEQ_CORE
§81  round 131: sequence = SEQ_FULL
```

그러나 rounds 101–113의 capture sequence identity (`SEQ_CORE` vs `SEQ_FULL`)는 CAP-005 어디에도 명시되지 않았다.
`sequence =` 지정은 §80 (121)과 §81 (131)에만 존재한다.

Patch 8 implementation 중 이 누락이 implementation gap `P8-I1`로 확인됐다.
구현은 값을 임의로 선택하지 않고 101–113의 production capture launch를 fail-closed로 차단한 상태에서 본 clarification을 요청했다.
101–113의 evaluation logic (§75 / §76 / §79)은 sequence 선택과 무관하게 designated phase만 평가한다.

Chronology:

```text
CAP-005 Design Freeze (commit d47a9ed)
→ Patch 8 implementation (uncommitted working tree) discovers P8-I1
→ 본 pre-execution clarification: rounds 101–113 = SEQ_CORE
→ (next) implementation applies the clarified mapping
→ regression tests → independent implementation audit
→ execution authorization / registration → formal hardware execution
```

본 clarification 시점의 상태:

```text
formal Patch 8 hardware execution performed     NO
formal execution_id created                     NO
execution registry created                      NO
Patch 8 result (formal or partial) observed     NO
Patch 8 implementation committed / audited      NO
```

따라서 본 entry는 결과 관찰 후의 protocol 변경 (CAP-005 Foundation §3.1 `POST-HOC PROTOCOL CHANGE`)이 아니며 `Supersedes: CAP-005`를 사용하지 않는다.
CAP-005 본문과 Foundation 문서가 101–113의 sequence를 원래 지정했던 것처럼 소급 기술하지 않는다.

### Decision

Patch 8 production validation slot의 capture sequence identity를 다음으로 명확화한다.

```text
round  designated phase              purpose                        capture sequence
101    forward_head                  below                          SEQ_CORE
102    forward_head                  pass                           SEQ_CORE
103    forward_head                  above                          SEQ_CORE
111    body_forward                  below                          SEQ_CORE
112    body_forward                  pass                           SEQ_CORE
113    body_forward                  above                          SEQ_CORE
121    body_forward                  body-only negative             SEQ_CORE  (unchanged, §80)
131    forward_head + body_forward   full-posture E2E               SEQ_FULL  (unchanged, §81)
```

`SEQ_CORE` / `SEQ_FULL`은 existing production `capture_d455.py` 정의 그대로이며, 본 entry는 그 자세 순서·유지 시간·prep 시간을 변경하지 않는다.
101–113은 production protocol `capture-forward-face-v2.0.0`의 existing `core` capture mode로 수행한다.

본 entry는 rounds 101–113의 capture sequence identity만 고정한다.
Designated phase, band, population, retry, body-only-negative, E2E semantics를 포함한 다른 slot semantics는 변경하지 않는다.

### Rationale

- CAP-005는 designated phase, §75 forward availability population, §76 validation bands, §79 retry semantics, §80 body-only-negative slot, §81 E2E slot을 freeze했으나 rounds 101–113의 capture sequence identity를 누락했다. 본 entry는 그 implementation ambiguity만 닫는다.
- 101–113은 production forward gate의 below / pass / above 판정을 검증하는 targeted forward-phase validation slot이며 full-posture E2E validation slot이 아니다. Full-posture E2E validation은 `SEQ_FULL`을 사용하는 dedicated slot 131이 담당한다.
- Repository fact: `capture_d455.py`에서 `SEQ_FULL = SEQ_CORE + [lean_back, lean_left, lean_right, upright]`이다. 따라서 `SEQ_CORE`는 두 designated forward phase와 각 phase의 production-gate reference인 직전 upright hold를 `SEQ_FULL`과 동일한 순서·유지 시간으로 포함하며, forward-gate validation 대상이 아닌 lean phase만 제외한다.
- §75의 "101–103의 non-designated `body_forward` / 111–113의 non-designated `forward_head`는 population이 아니다" 문구는 `SEQ_CORE`에도 두 forward phase가 모두 존재하므로 그대로 성립한다.

### Alternatives / Rejected / Deferred

```text
101–113 = SEQ_FULL                                   REJECTED  101–113은 full-posture E2E가 아님; E2E는 slot 131 전용
slot별 / attempt별 operator의 sequence 선택           REJECTED  사전 고정되지 않은 protocol 선택 경로를 만들지 않음
production CLI 기본값(SEQ_FULL)을 구현이 암묵 채택    REJECTED  미명시 authority를 구현에서 임의 결정하지 않음
CAP-005 본문 / Foundation §33·§78 소급 수정           REJECTED  append-only 원칙
Supersedes: CAP-005 / POST-HOC PROTOCOL CHANGE        NOT APPLICABLE  formal execution 및 결과 관찰 이전의 clarification
```

### Evidence / Source

- `CAP-005` entry 및 `docs/foundation/PATCH_08_actual_d455_end_to_end_validation.md` §33, §41, §75, §76, §78, §79, §80 (`sequence = SEQ_CORE`), §81 (`sequence = SEQ_FULL`): rounds 101–113의 sequence 명시 없음
- `capture_d455.py` `SEQ_CORE` / `SEQ_FULL` 정의 및 existing `core` capture mode (변경 없음)
- Patch 8 implementation working-tree report on baseline `d47a9ed` (repository artifact 아님): implementation gap `P8-I1`, rounds 101–113 production launch fail-closed
- 연구 책임자의 명시적 pre-execution 결정 (2026-10-07)

Agreement between AI agents는 experimental evidence가 아니다. 본 entry는 D455 hardware 결과를 포함하지 않는다.

### Impact

- Rounds 101–113의 capture sequence identity = `SEQ_CORE`가 authority로 확정된다. 본 entry는 `CAP-005`와 함께 읽으며, 이 항목에 대해서만 CAP-005보다 더 구체적인 authority다. CAP-005와 Foundation 문서의 다른 모든 rule은 그대로 유효하다.
- Foundation 문서 본문은 수정하지 않는다 (Design Freeze 기록 보존). §33 / §41 / §78을 적용할 때 본 entry를 함께 적용한다.
- 다음은 변경하지 않는다: production protocol `capture-forward-face-v2.0.0`, production forward gate `0.08–0.12 m inclusive` / `face_only` / body-only·mixed source cannot PASS, §75 availability population, §76 validation bands, §79 forward-slot retry semantics, §80 slot-121 body-only-negative semantics, §81 slot-131 E2E predicate, `SEQ_CORE` / `SEQ_FULL` semantics, `frames-schema/1.0.0`, `summary-schema/1.0.0`, Patch 5 lineage, Patch 6 selection, Patch 7 integrity, 모든 threshold 및 scientific metric.
- `OPEN-006`은 RESOLVED BY CAP-005 그대로이며 `OPEN-002`, `OPEN-003`, `OPEN-004`, `OPEN-005`는 계속 DEFERRED다.
- Patch 8 implementation은 아직 uncommitted / unaudited다. 다음 단계에서 본 authority에 맞춰 101–113 mapping을 적용하고 targeted / full regression 후 independent READ-ONLY implementation audit를 받는다.
- 본 entry는 Patch 8 implementation 완료, implementation audit 통과, execution authorization, formal hardware execution, 또는 Patch 8 PASS를 의미하지 않는다. Patch 8은 DESIGN-FROZEN이며 implementation / implementation audit / execution registration / hardware execution은 PENDING이다.

Supersedes:
- None

Clarifies:
- `CAP-005` / Foundation §33, §41, §78: production rounds 101–103 및 111–113의 capture sequence identity (`SEQ_CORE`). §80 (121 = `SEQ_CORE`)와 §81 (131 = `SEQ_FULL`)은 변경 없이 재확인한다.

Resolves:
- Patch 8 implementation gap `P8-I1`: pre-execution design-authority gap — `SEQ_CORE` vs `SEQ_FULL` unspecified for rounds 101–113

---
