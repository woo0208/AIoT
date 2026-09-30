# FOUNDATION_PRELUDE_00 — Algorithm and Capture Hardening

> 상태: **소급 정리(Retrospective), 최종 후보 v2 (Final Candidate v2)**
>
> v2 반영: **2026-10-01 Claude READ-ONLY 1차 검토 Finding 1~7 반영. Targeted 재검토 전 상태.**
>
> 범위: **Core hardening `64f8897` ~ `90e6caa` + provenance setup bridge `753bbac` ~ `1851261`**
>
> 목적: 정식 provenance Patch 1~3에 들어가기 전에 수행된
> **알고리즘 비교 공정성, 평가 신뢰성, 실험 재현성, 촬영 프로토콜 통제 강화 작업**을
> 하나의 Foundation Prelude로 정리한다.
>
> 이 문서는 새로운 핵심 연구 방법(F1/F2)을 정의하는 문서가 아니다.
> 기존 prototype을 연구용 pipeline으로 사용하기 전에 필요한 hardening 작업을 기록한다.

---

# 1. 왜 이 문서가 필요한가

현재 운영상 Foundation Patch는 다음과 같이 관리한다.

```text
Patch 1  capture provenance
Patch 2  forward gate evidence
Patch 3  analysis provenance
Patch 4  canonical fixed schema + hip
...
```

하지만 Git history에는 Patch 1 이전에 이미 중요한 연구 기반 수정이 존재한다.

```text
64f8897  RNG isolation
c9a60a3  rank-weight policy
8d4b4b7  relative evaluation
c5358c0  external metrics / drop logging
c585665  CSV resource handling
fd7176f  root split provenance
c6525a3  forward 8~12 cm protocol
90e6caa  face-only forward hard gate
```

이 변경들을 기록하지 않고 Patch 1부터 시작하면:

> “Patch 1 이전의 알고리즘/평가/촬영 기반 정비는 어디에 기록되어 있는가?”

라는 공백이 생긴다.

따라서 이 구간은 개별 Patch로 다시 번호를 붙이지 않고:

```text
FOUNDATION_PRELUDE_00
```

으로 묶어 관리한다.

### 1.1 `RESEARCH_DATA_SCHEMA.md` §K와 운영상 Foundation Patch 번호의 관계

`RESEARCH_DATA_SCHEMA.md` §K는 provenance 구현 전에 작성된 **설계상 최소 patch 순서**이고,
현재 History/Foundation 문서의 **운영상 Patch 번호와 1:1로 동일하지 않다.**

현재 대응 관계는 다음처럼 해석한다.

| Schema §K 설계 순서 | 실제/현재 Foundation 운영 |
|---|---|
| K1 ID·artifact 계약 + K2 capture metadata | Foundation Patch 1 — Capture Recording Provenance에서 통합 구현. 별도 `data_provenance.py`는 만들지 않음 |
| K3 gate evidence | Foundation Patch 2 — Forward Gate Evidence |
| K4 모델 lock·analysis run | analysis-run provenance는 Foundation Patch 3에서 구현; **model artifact lock은 아직 미구현이며 Foundation Patch 4.5로 분리** |
| K5a canonical frames + K5b body raw observations | 현재 운영상 Foundation Patch 4 — canonical fixed schema + hip raw observations의 설계/구현 대상 |

따라서 같은 "Patch 4"라는 표현이 나오더라도:

```text
Schema §K의 Patch 4
= 과거 설계 순서의 "모델 lock·analysis run"

현재 운영상 Foundation Patch 4
= canonical fixed frames schema + hip raw observations
```

로 구분한다. 과거 문서를 현재 번호에 맞춰 소급 재번호화하지 않는다.

---

# 2. 이 문서의 위치

연구 이력은 다음과 같이 구분한다.

```text
docs/history/
├── BASELINE_00_HANDOFF_SNAPSHOT.md
└── RETROSPECTIVE_01_PRE_GIT_CHANGES.md

docs/foundation/
├── FOUNDATION_PRELUDE_00_algorithm_and_capture_hardening.md
├── PATCH_01_capture_provenance.md
├── PATCH_02_forward_gate_evidence.md
├── PATCH_03_analysis_provenance.md
└── ...
```

역할 차이:

```text
BASELINE_00
= 팀원에게 전달받은 코드 상태

RETROSPECTIVE_01
= handoff → 현재 research-main 계보의 root commit `64f8897` 사이 복원

FOUNDATION_PRELUDE_00
= 현재 research-main 계보의 root commit `64f8897` 이후, provenance Patch 이전의 hardening 및 setup bridge

PATCH_01~
= 명시적으로 설계·검증한 Foundation Patch
```

---

# 3. Prelude의 전체 목적

이 구간의 목적은 정확도를 억지로 높이는 것이 아니었다.

핵심 목적은 다음 네 가지다.

1. **M0 / M1 / M2 비교 공정성 확보**
2. **평가 방식에서 생기는 구조적 유리함 제거**
3. **실험 결과의 재현성과 추적성 보강**
4. **촬영 프로토콜과 실제 코드 동작의 불일치 제거**

즉:

> 결과를 좋게 만들기 위한 튜닝이 아니라,
> 비교 조건과 실험 조건을 명확하게 만드는 hardening 작업

으로 정의한다.

---

# 4. Commit Timeline

| Commit | 역할 |
|---|---|
| `64f8897` | RNG isolation |
| `c9a60a3` | reduced feature rank-weight policy 통일 |
| `8d4b4b7` | relative non-reference evaluation 추가 |
| `c5358c0` | 외부 평가 metric 및 drop logging 강화 |
| `c585665` | CSV file handle 안정화 |
| `fd7176f` | root split provenance logging |
| `c6525a3` | forward posture 8~12 cm protocol 통일 |
| `90e6caa` | forward hard gate를 face-depth-only로 제한 |
| `753bbac` | research data provenance schema 최초 정의 |
| `0e938d9` | generated research data Git 제외 정책 추가 |
| `1851261` | calibration-free body geometry 방향에 맞게 schema 보정; Patch 1의 직접 parent |

### 4.1 Provenance Foundation Setup Bridge

Core hardening `90e6caa` 이후 Patch 1 `1d25c8c`까지에는
provenance 체계를 준비하는 별도 setup 구간이 존재한다.

```text
753bbac
docs: define research data provenance schema
→ recording / analysis / data lineage를 어떤 field와 규칙으로 추적할지
  문서 차원의 계약을 먼저 정의

0e938d9
chore: ignore generated research data
→ raw/analysis/result 같은 generated artifact를
  Git source history와 분리하기 위한 repository hygiene

1851261
docs: align schema with calibration-free body geometry
→ 개인 calibration을 최종 제안 방법의 필수 전제로 두지 않는 방향과
  raw → derived geometry → model feature 계층을 schema에 반영
→ formal 수집 전 별도 D455 operating-range / hardware validation 설계(§M)도 추가
→ 이후 Patch 1 `1d25c8c`의 직접 parent
```

이 bridge는 **코드 provenance Patch 자체가 아니라,
Patch 1~3을 구현하기 위한 규칙/저장 정책의 준비 구간**이다.

research-main ancestry 안에서 연구 방법 변경으로 분류하지 않는 commit:

```text
29d8a57  chore: add Codex project instructions
```

이는 tooling 성격이며,
알고리즘·촬영·provenance 방법의 의미를 바꾸는 Foundation step으로 사용하지 않는다.

한편 다음 commit은 **research-main ancestry가 아니다.**

```text
bc224bc  별도 legacy lineage의 root
30006de  Delete BOM_LIST.md
39dfc2f  Delete introduce.md
branch:  origin/legacy-main-20260930
```

이들은 repository에 보존된 별도 legacy lineage에 속하며,
현재 research-main의 commit chronology나 Prelude 방법론 timeline에 포함하지 않는다.

---

# 5. Step 1 — RF RNG Isolation

## Commit

```text
64f8897
baseline: step 1 RNG isolation completed
```

## 기존 문제

기존 `Forest.fit()`에서는 하나의 RNG가:

```text
bootstrap sample 생성
+
Tree 내부 feature permutation
```

에 같이 사용됐다.

개념적으로:

```python
rng = np.random.default_rng(seed)

for each tree:
    bootstrap = rng.integers(...)
    tree = Tree(..., rng)
```

구조였다.

M0와 M2는 split 규칙이 다를 수 있으므로
Tree 내부 random draw 횟수도 달라질 수 있다.

그러면:

```text
첫 번째 tree에서 RNG 소비량 차이
        ↓
RNG state divergence
        ↓
두 번째 tree 이후 bootstrap sample도 달라짐
```

이 가능하다.

즉 성능 차이에:

```text
M2 split-weighting 효과
+
다른 bootstrap sample 효과
```

가 동시에 섞일 수 있었다.

## 변경

RNG를 분리했다.

```python
boot_seed, tree_seed = np.random.SeedSequence(self.seed).spawn(2)
boot_rng = np.random.default_rng(boot_seed)
tree_seeds = tree_seed.spawn(self.T)
```

각 tree마다:

```python
b = boot_rng.integers(...)
rng = np.random.default_rng(seed)
```

를 사용한다.

즉:

```text
bootstrap 전용 RNG
tree 내부 전용 RNG
tree별 독립 seed
```

구조로 변경했다.

## 검증

다음 조건을 테스트했다.

- M0 == M2(λ=0)
- M0 == M1
- 동일 seed에서 M0/M1/M2 bootstrap 동일
- 다른 seed에서 bootstrap/RNG state 달라짐
- 동일 seed 재실행 deterministic
- 첫 tree에서 추가 random draw가 발생해도 이후 bootstrap에 영향 없음

## 연구상 의미

M0/M1/M2 비교에서:

> “알고리즘 차이가 아니라 bootstrap sample이 달라서 결과가 달라진 것 아닌가?”

라는 혼입 가능성을 줄였다.

---

# 6. Step 2 — M2 Rank-Weight Policy 통일

## Commit

```text
c9a60a3
fix: unify rank-based weights for reduced feature sets
```

## 기존 문제

6개 feature일 때:

```text
0.30, 0.20, 0.15, 0.15, 0.15, 0.05
```

의 paper-style rank weight를 사용했다.

하지만 feature 수가 6이 아니면:

```python
mdi / mdi.sum()
```

으로 바뀌었다.

즉:

```text
all / relative
→ rank-based weight

invariant
→ normalized raw MDI
```

로 동일한 M2 이름 아래 서로 다른 weight policy가 적용됐다.

## 변경

feature 수 `p <= 6`이면 동일한 rank-based 정책을 사용한다.

예: 4 feature

```text
원본 상위 4개
0.30, 0.20, 0.15, 0.15

재정규화
0.375, 0.250, 0.1875, 0.1875
```

`p > 6`이면:

```text
ValueError
```

를 발생시킨다.

## 왜 p > 6을 막았는가

미래 F2에서 feature 수가 늘어날 가능성이 있지만,
그때 사용할 weight policy는 별도 연구 결정이다.

따라서 구현 코드가 자동으로 새로운 policy를 발명하지 못하도록 막았다.

## 검증

- 6-feature 기존 정책 보존
- 4-feature weight 검증
- p=1~5 positive / normalized
- p>6 명시적 오류
- M0=M1
- M0=M2(λ=0)
- RNG isolation regression 유지

## 연구상 의미

feature set마다 M2의 내부 weight 정의가 달라지는 문제를 제거했다.

또한 수정 전 invariant M2 결과는
최종 결과로 그대로 사용하지 않고 재실행 대상으로 분류했다.

---

# 7. Step 3 — Relative Non-Reference Evaluation

## Commit

```text
8d4b4b7
fix: add non-reference evaluation for relative features
```

## 기존 문제

relative feature는 참가자의 기준 upright를 빼서 만든다.

개념적으로:

```text
X_relative = X - reference
```

이므로 reference sample 자신은:

```text
(A, 0, 0, 0, 0, 0)
```

에 가까운 특수한 좌표가 된다.

이 sample은 모델 입장에서 매우 쉬운 normal sample이 될 수 있다.

## 변경

기존 전체 평가는 유지한다.

추가로 relative에 대해:

```text
calibration upright excluded
```

인 non-reference evaluation을 별도로 출력한다.

## 데이터셋별 처리

### 논문 데이터

참가자당 upright가 1개라면
그 upright가 reference이므로 제외 후 upright class가 남지 않는다.

따라서 결과를:

```text
5-class Macro F1
```

로 부르지 않고
reference 제외 4-posture 평가로 구분한다.

### 자체 데이터

한 round에 upright가 여러 번 존재할 수 있으므로:

```text
첫 upright
= calibration reference

이후 upright
= 평가에 유지
```

한다.

## 연구상 의미

relative 방식이 reference sample 구조 때문에
평가상 유리해질 가능성을 별도로 관찰할 수 있게 했다.

모델 정의나 학습 데이터 자체는 바꾸지 않았다.

---

# 8. Step 4 — External Evaluation Metrics 강화

## Commit

```text
c5358c0
feat: extend external evaluation and drop logging
```

## 기존 문제

자체 데이터 외부 적용 결과가 Accuracy 중심이었다.

하지만 normal sample이 여러 번 등장하므로
class distribution이 균등하지 않을 수 있다.

Accuracy만 보면:

```text
normal을 많이 맞혀서 높은 것인지
모든 자세를 고르게 맞힌 것인지
```

구분하기 어렵다.

## 추가

- Macro F1
- 5×5 confusion matrix
- participant별 sample count
- participant별 Accuracy
- participant별 Macro F1
- posture별 recall

## body_forward 처리

`body_forward`는 원 논문 5개 class에 포함되지 않으므로:

```text
y = -1
```

을 유지한다.

정식 5-class metric에는 포함하지 않는다.

단:

```text
M0가 body_forward를 어떤 기존 class로 예측하는가
```

는 보조 분석으로 유지한다.

## 연구상 의미

Accuracy 하나로만 결과를 해석하는 위험을 줄였다.

---

# 9. Step 4 — Drop Logging 강화

## Commit

동일:

```text
c5358c0
```

## 기존 문제

결측 sample은:

```python
continue
```

로 조용히 제외될 수 있었다.

따라서:

```text
누가
어느 round에서
어느 posture가
어떤 feature 때문에
```

빠졌는지 확인하기 어려웠다.

## 변경

drop 시 최소 다음을 기록한다.

- subject
- round
- step
- label
- drop reason
- missing feature

또한:

```text
loaded count
dropped count
reason별 count
```

를 출력한다.

## 중요한 점

drop 기준 자체는 바꾸지 않았다.

즉:

```text
기존 포함 sample → 그대로 포함
기존 제외 sample → 그대로 제외
```

하며,
**관찰 가능성만 높였다.**

---

# 10. Step 4.5 — CSV File Handle 안정화

## Commit

```text
c585665
fix: close CSV files with context managers
```

## 기존 문제

다음과 같은 형태가 존재했다.

```python
csv.DictReader(open(...))
```

파일 핸들이 명시적으로 닫히지 않아
ResourceWarning이 발생할 수 있었다.

## 변경

```python
with open(...) as f:
    ...
```

형태로 변경했다.

## 연구상 영향

수치 계산이나 알고리즘 의미는 바꾸지 않는다.

목적은 반복 실행 안정성과 resource handling 개선이다.

---

# 11. Step 5 — Root Split Provenance

## Commit

```text
fd7176f
feat: add root split provenance logging
```

## 기존 문제

과거 기록에는:

```text
M0 A-root 비율
M2 A-root 비율
```

같은 수치가 있었지만,
현재 코드로 그 수치를 다시 어떻게 만들었는지
명확한 재현 경로가 없었다.

## 변경

각 trained tree의 root feature를 기록한다.

예:

```python
tree.feat[0]
```

기록 항목:

- 전체 tree 수
- root split 존재 tree 수
- leaf-only tree 수
- feature별 root count
- feature별 root percentage
- tree별 root feature index

또한 결과 provenance에:

- dataset / track
- feature set
- model
- seed
- tree count
- max_features
- λ
- LOSO held-out participant

등을 기록한다.

## 중요한 점

이 기능은 **관찰용 logging**이다.

Tree split decision 자체를 바꾸거나
추가 RNG draw를 발생시키지 않는다.

## 연구상 의미

M2가 단순히 Accuracy만 바꾸는 것이 아니라
실제 tree의 feature 선택에 어떤 영향을 미쳤는지
추적할 수 있게 했다.

과거 root ratio 수치는 목표값으로 맞추지 않고,
수정된 RNG/weight 정책 기준으로 다시 산출해야 한다.

---

# 12. Step 6 — Forward Posture 8~12 cm Protocol 통일

## Commit

```text
c6525a3
fix: align forward posture capture protocol to 8-12 cm
```

## 기존 문제

Handoff baseline에서는 다음이 동시에 존재했다.

```text
문서/화면 목표
8~12 cm

live guidance 기준
약 4 cm

final fail 회피 기준
약 1.5 cm
```

즉 문서와 실제 코드의 acceptance logic이 일치하지 않았다.

## 왜 중요한가

연구 목적은:

```text
forward_head
vs
body_forward
```

에서 얼굴 전진량 자체는 비슷하게 통제하고,
어깨/몸통의 움직임 차이를 관찰하는 것이다.

얼굴 이동량부터 다르면:

```text
자세 차이
+
전진 거리 차이
```

가 섞인다.

## 변경

공통 상수:

```python
FWD_TARGET_MIN_M = 0.08
FWD_TARGET_MAX_M = 0.12
```

를 사용해:

- 화면 안내
- live 판정
- final quality 판정

을 통일했다.

## 자세 안내도 정리

### forward_head

의도:

```text
등·어깨 고정
정면 시선
고개 각도 유지
머리 전체를 수평으로 앞으로
```

### body_forward

의도:

```text
머리만이 아니라
등·어깨를 포함한 상체 전체를 앞으로 이동
```

## 어깨 hard gate를 두지 않은 이유

예:

```text
shoulder movement < 2 cm
```

같은 조건을 촬영 acceptance에 넣지 않았다.

어깨 이동 자체가 이후 연구할 후보 신호이므로
그 feature로 데이터를 미리 선별하면 순환 논리가 생길 수 있기 때문이다.

따라서:

```text
얼굴 전진량
= hard gate

어깨 움직임
= 기록 후 분석
```

으로 분리했다.

---

# 13. Step 6.1 — Forward Hard Gate를 Face Depth 전용으로 제한

## Commit

```text
90e6caa
fix: require face depth for forward posture validation
```

## Step 6 이후 남은 문제

거리 측정 helper는 일반적으로:

```text
face depth 성공
→ face 사용

face 실패
→ body fallback
```

구조였다.

이건 일반 거리 측정에는 합리적이다.

하지만 forward hard gate에서 그대로 사용하면:

```text
얼굴 검출 없음
몸이 10 cm 앞으로 이동
→ 8~12 cm PASS
```

가 가능하다.

## 왜 문제인가

연구에서 통제하는 값은:

```text
body 전체 거리
```

가 아니라:

```text
얼굴 전방 이동량
```

이다.

따라서 body fallback으로 PASS시키면
실험 조건 자체가 바뀐다.

## 변경

`forward_head`, `body_forward`의:

- live 판정
- final quality 판정
- reference upright

에서 **face depth sample만 사용**한다.

다음 혼합은 허용하지 않는다.

```text
upright face
vs
forward body
```

또는:

```text
upright body
vs
forward face
```

## face sample 부족

### live

```text
얼굴 거리 측정 필요
```

상태.

### final

```text
재촬영 필요
```

처리.

## body fallback 자체는 유지

body fallback 기능 전체를 제거한 것은 아니다.

계속:

- 일반 거리 표시
- 사람 검출 보조
- 일반 기록

에는 사용할 수 있다.

단:

```text
forward 8~12 cm hard gate
```

에서만 금지한다.

## 검증

최신 당시 보고 기준:

- face 10 cm → PASS
- body-only 10 cm → FAIL
- face/body mixed → FAIL
- face 7 cm → FAIL
- face 13 cm → FAIL
- 일반 body fallback → 유지
- 전체 unittest → 63 PASS

실제 D455 GUI/live 하드웨어 검증은 별도 smoke test 대상으로 남았다.

---

# 14. Prelude 동안 의도적으로 바꾸지 않은 것

이 hardening 구간은
핵심 모델을 새로 정의하는 단계가 아니었다.

다음은 유지했다.

## 모델 정의

### M0

일반 Random Forest.

### M1

입력 feature에 양수 weight를 곱한 뒤 RF.

### M2

```text
Score
=
[(1-λ) + λ·w_j/mean(w)] × ΔGini
```

형태의 split weighting.

## 기존 feature 의미

```text
A
x_c
y_c
θL
θR
θ1
```

정의 자체를 바꾸지 않았다.

## 자체 D455 좌표 환산

```text
1280×720
→ 중앙 960×720 crop
→ ×2/3
→ 640×480
```

기존 환산 로직은 유지했다.

## body_forward

6번째 정식 classification class로 승격하지 않았다.

## shoulder movement

촬영 hard gate로 사용하지 않았다.

---

# 15. 과거 결과 재사용 주의

이 Prelude의 일부 변경은
실험 조건 자체를 바꿨다.

따라서 수정 전 수치는
그대로 최종값으로 사용할 수 없다.

## 재실행이 필요한 대표 항목

### M2

- RNG isolation
- reduced-feature weight policy

변경 때문에 재계산 필요.

### Relative

기존 전체 결과와 함께
non-reference 평가를 같이 봐야 한다.

### External evaluation

Accuracy뿐 아니라:

- Macro F1
- confusion matrix
- participant metric
- posture recall

을 같이 확인해야 한다.

### Root split

과거 root 비율을 목표값으로 맞추면 안 된다.

수정된 코드에서 새로 산출해야 한다.

---

# 16. 당시 검증 상태

Step 6.1 완료 시점의 정리 문서 기준:

```text
63 tests PASS
```

단:

```text
실제 D455 GUI/live hardware smoke test
```

는 별도로 남아 있었다.

따라서 이 Prelude에서:

```text
unit-test verified
```

와:

```text
hardware verified
```

를 동일하게 취급하지 않는다.

---

# 17. Prelude의 연구상 의미

이 구간의 핵심은 성능 개선 자체가 아니다.

수정 전에는 다음 문제가 있었다.

```text
M2 tree 구조가 bootstrap RNG에 간접 영향 가능
feature 수에 따라 M2 weight policy 변경
relative reference sample이 평가상 쉬운 sample이 될 가능성
external 평가가 Accuracy 중심
drop sample 원인 추적 부족
root split 결과 재현 경로 부족
촬영 문서와 코드 threshold 불일치
face 미검출 시 body 거리로 forward PASS 가능
```

Prelude 완료 후에는:

```text
M0/M1/M2 비교 공정성 향상
평가 해석성 향상
결측/drop 추적성 향상
root split 재현성 향상
forward posture 조건 통일
face-only hard gate 확립
```

상태가 됐다.

---

# 18. 이 Prelude와 Patch 1~3의 차이

## Prelude

주로:

```text
알고리즘 비교 공정성
평가 방식
촬영 조건
기초 logging
```

을 hardening한다.

## Patch 1~3

그 이후:

```text
Patch 1
촬영 artifact의 신분증 / provenance

Patch 2
forward gate PASS/FAIL의 증거 저장

Patch 3
분석 실행 artifact의 provenance / lineage
```

를 구축한다.

즉:

```text
Prelude
= 실험과 비교를 믿을 수 있게 만드는 기초 정비

Patch 1~3
= 그 실험과 분석을 추적 가능하게 만드는 provenance 체계
```

로 구분한다.

---

# 19. Commit Mapping

```text
64f8897
RNG isolation

c9a60a3
rank-weight policy

8d4b4b7
relative non-reference evaluation

c5358c0
external metrics + drop logging

c585665
CSV context manager

fd7176f
root split provenance

c6525a3
forward 8~12 cm protocol

90e6caa
face-only forward hard gate
```

---

# 20. 이 문서의 증거 수준

## 높은 신뢰도

- commit hash / commit message
- 각 단계의 최종 코드 목적
- 후속 정리 문서에 기록된 변경 이유
- Step 6.1까지의 당시 검증 결과

## 부분 소급

- 각 commit 내부의 모든 세부 시행착오
- 정확한 의사결정 시간
- 각 수정 직전 수행된 예비 실험의 정확한 code revision

이 항목은 확정적으로 복원하지 않는다.

---

# 21. 다음 이력 문서

다음 순서로 이어진다.

```text
PATCH_01_capture_provenance.md
PATCH_02_forward_gate_evidence.md
PATCH_03_analysis_provenance.md
```

이 세 문서는 Prelude와 달리
각 Patch의:

```text
목적
설계 결정
구현
검증
독립 review
미해결 사항
관련 commit
```

을 별도로 기록한다.

---

# 22. 현재 상태

```text
FOUNDATION_PRELUDE_00 작성 상태
= FINAL CANDIDATE

기술적 주요 흐름 복원
= COMPLETE

모든 역사적 세부 복원
= PARTIAL / 불확실한 부분은 미기재
```

내부 문서 세트 검토에서 다음을 확인했다.

1. BASELINE_00과 역할/경계 일치
2. RETROSPECTIVE_01과 `64f8897` 경계 일치
3. Patch 1~3과 방법론 범위 분리
4. provenance setup bridge `753bbac`~`1851261` 보강
5. non-methodology commit의 의도적 제외 명시

남은 절차:

```text
Claude 1차 READ-ONLY review finding 반영본(v2) targeted 재검토
→ blocker 없으면 canonical record로 확정
```

---

# 23. Source Notes

본 최종 후보본은 다음 자료를 기준으로 정리했다.

- Handoff snapshot 기반 `BASELINE_00`
- `RETROSPECTIVE_01`
- Git commit history
- `바른자세_코드수정_근거_및_변경내역_팀원설명용_v1.md`
- 당시 테스트/수정 요약
- 현재 대화에서 확정된 Foundation/Patch 용어 체계

원칙:

```text
실제 Git / source
>
당시 테스트
>
정리 문서
>
대화 기반 복원
>
추정
```

추정은 확정 사실로 서술하지 않는다.
