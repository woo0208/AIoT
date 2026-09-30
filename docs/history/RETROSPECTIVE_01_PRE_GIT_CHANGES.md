# RETROSPECTIVE_01 — Pre-Git / Early Git Transition Reconstruction

> 상태: **소급 복원(Retrospective Reconstruction), 최종 후보 v2 (Final Candidate v2)**
>
> v2 반영: **2026-10-01 Claude READ-ONLY 1차 검토 Finding 1~7 반영. Targeted 재검토 전 상태.**
>
> 작성 기준일: 2026-09-30
>
> 목적: 팀원에게 전달받은 handoff snapshot과 현재 research-main 계보의 root commit을 직접 비교하여,
> **Git 이력 관리가 시작되기 직전/시작 시점에 실제로 어떤 코드 변경이 있었는지**를
> 가능한 범위에서 복원한다.
>
> 중요: 이 문서는 과거 개발 과정을 완벽히 재현한다고 주장하지 않는다.
> **파일·Git·대화로 확인 가능한 사실만 확정하고, 확인되지 않는 중간 과정은 UNKNOWN으로 남긴다.**

---

# 1. 이 문서가 다루는 범위

본 문서의 범위는 다음 두 기준점 사이이다.

```text
Phase 0
팀원에게 전달받은 Handoff Snapshot
        ↓
Phase 0.5
현재 research-main 계보의 Git history가 생기기 전 또는
그 root commit을 만들기 직전의 수정
        ↓
Current Research-Main Lineage Root Commit
64f8897
"baseline: step 1 RNG isolation completed"
```

이후의 다음 수정은 이 문서의 범위가 아니다.

```text
c9a60a3  rank-weight policy
8d4b4b7  relative non-reference evaluation
c5358c0  external metrics / drop logging
c585665  CSV context manager
fd7176f  root split provenance
c6525a3  forward 8~12 cm protocol
90e6caa  face-only forward validation
...
```

이후 변경은 Git에서 개별 commit으로 추적 가능하므로,
각 Foundation Record에서 별도로 관리한다.

---

# 2. 사용한 증거

## 2.1 Handoff source artifact

`[USER-CONFIRMED]`

사용자가 팀원에게 전달받은 당시 코드라고 확인한 ZIP:

```text
새 폴더 (2).zip
```

ZIP SHA-256:

```text
ddd5edb7181f6589f450699d1340a4363878f8bc5adf8efd923d67359ea4cda8
```

이 snapshot의 세부 상태는 다음 문서에서 관리한다.

```text
docs/history/BASELINE_00_HANDOFF_SNAPSHOT.md
```

현재는 Final Candidate v2 상태다.

---

## 2.2 현재 research-main 계보의 root commit

`[GIT-VERIFIED]`

현재 research-main 계보의 root commit:

```text
64f8897e0e51df190d3939828dabee9195486744
```

commit message:

```text
baseline: step 1 RNG isolation completed
```

commit timestamp:

```text
2026-09-29 23:45:41 +0900
```

중요:

```text
64f8897은 **현재 research-main 계보에서 parent가 없는 root commit**이다.
```

따라서 Git 자체만으로는:

```text
수정 전 코드
→ RNG isolation 수정
→ 64f8897
```

의 diff를 복원할 수 없다.

이번 복원은 **handoff ZIP을 "수정 전" 기준점으로 사용하고,
64f8897 tree를 "현재 research-main 계보의 첫 Git snapshot"으로 사용해 직접 비교**했다.

또한 repository 전체에는 별도의 legacy lineage가 존재한다.

```text
root: bc224bc
branch: origin/legacy-main-20260930
examples: 30006de, 39dfc2f
```

이 legacy lineage는 **현재 research-main ancestry에 속하지 않는다.**
따라서 `64f8897`을 repository 전체의 유일한 최초 Git root로 표현하지 않고,
**현재 research-main 계보의 root commit**으로만 표현한다.

---

# 3. 핵심 결론

## 3.1 Handoff → 64f8897 사이에서 확인되는 코드 변경

`[SNAPSHOT+GIT-VERIFIED]`

다섯 개 기존 소스 파일을 byte-level 비교한 결과:

| File | Handoff → 64f8897 |
|---|---|
| `analyze_d455.py` | **동일** |
| `capture_d455.py` | **동일** |
| `check_recording.py` | **동일** |
| `compare_paper.py` | **동일** |
| `rf_experiment.py` | **변경됨** |

그리고 최초 Git snapshot에서 새 파일:

```text
test_rf_rng.py
```

가 추가됐다.

즉 현재 확보된 증거를 기준으로 하면,
**Phase 0.5에서 코드상 확정적으로 복원 가능한 변경은 RF RNG isolation 한 건이다.**

---

# 4. 정확한 코드 변화 — RF RNG Isolation

> 범위 주의:
> 이 절은 **handoff와 64f8897 사이에 실제로 무엇이 달라졌는지**를 증거 중심으로 기록한다.
> RNG isolation의 연구적 의미와 후속 hardening 맥락은
> `FOUNDATION_PRELUDE_00_algorithm_and_capture_hardening.md`를 우선한다.

## 4.1 Handoff 상태

`[SNAPSHOT-VERIFIED]`

Handoff의 `Forest.fit()`은 하나의 RNG를 만들고
bootstrap sampling과 Tree 내부 난수에 함께 사용했다.

개념 구조:

```python
rng = np.random.default_rng(self.seed)

for each tree:
    b = rng.integers(...)
    tree = Tree(..., rng)
```

Tree 내부에서는 동일 RNG를 이용해 feature permutation 등이 수행됐다.

따라서:

```text
bootstrap 난수
+
tree 내부 난수
```

가 하나의 stream을 공유했다.

Handoff `rf_experiment.py` SHA-256:

```text
8f753008ff233831bc70513ced723047a91f5425b15f023f55778283383337c9
```

---

## 4.2 문제 인식

`[CHAT-RECONSTRUCTED]`

M0와 M2는 split 선택 규칙이 다르기 때문에
한 tree 안에서 사용하는 permutation/random draw 횟수가 달라질 수 있다.

예를 들어:

```text
M0
→ 특정 tree에서 permutation을 더 많이 소비

M2
→ 다른 split 구조 때문에 RNG 소비 횟수가 달라짐
```

상태에서 같은 RNG stream을 bootstrap에도 사용하면:

```text
첫 tree의 내부 RNG 소비량 차이
        ↓
RNG state가 달라짐
        ↓
다음 tree의 bootstrap sample까지 달라짐
```

이 될 수 있다.

그러면 M0와 M2 차이를 비교할 때:

```text
M2 split weighting 효과
+
서로 다른 bootstrap sample 효과
```

가 섞일 수 있다.

따라서 이 수정의 목적은 **정확도 향상**이 아니라
M0/M1/M2 비교에서 random sampling 조건을 분리하여
공정성을 높이는 것이었다.

---

# 5. 실제 수정 내용

## 5.1 변경 전

```python
rng = np.random.default_rng(self.seed)

for _ in range(self.T):
    b = rng.integers(0, len(X), len(X))
    t = Tree(self.K, self.mf, sw, rng).fit(...)
```

## 5.2 변경 후

`[GIT-VERIFIED]`

64f8897의 `Forest.fit()`:

```python
boot_seed, tree_seed = np.random.SeedSequence(self.seed).spawn(2)
boot_rng = np.random.default_rng(boot_seed)
tree_seeds = tree_seed.spawn(self.T)

for seed in tree_seeds:
    b = boot_rng.integers(0, len(X), len(X))
    rng = np.random.default_rng(seed)
    t = Tree(self.K, self.mf, sw, rng).fit(...)
```

즉:

```text
bootstrap 전용 RNG
+
tree 내부 전용 RNG
+
tree별 독립 seed
```

로 분리했다.

`[SNAPSHOT+GIT-VERIFIED]`

Handoff → root commit의 실제 `rf_experiment.py` diff 규모:

```text
추가 7줄
삭제 3줄
```

64f8897의 `rf_experiment.py` SHA-256:

```text
8dcb3740a0d31b48e2e832da95607d6f7769407a2912cf74f35a973a299f91c6
```

---

# 6. 새 테스트 파일 추가

`[GIT-VERIFIED]`

64f8897에는 새 파일:

```text
test_rf_rng.py
```

가 포함됐다.

SHA-256:

```text
07e61cede3f54a1d69ad2502507feda508c833069799f954575f8882e40b82cf
```

파일 길이:

```text
132 lines
```

확인되는 테스트는 6개다.

### Test 1

```text
M0 == M2(λ=0)
```

예측뿐 아니라 tree probability까지 동일한지 확인.

### Test 2

```text
M0 == M1
```

동일 조건에서 prediction/probability 일치 확인.

### Test 3

```text
M0/M1/M2의 tree별 bootstrap과 initial RNG state pairing
```

확인.

### Test 4

```text
다른 seed
→ bootstrap / tree RNG state가 달라짐
```

확인.

### Test 5

```text
같은 seed 재실행
→ deterministic
```

확인.

### Test 6

첫 번째 tree에서 추가 random draw를 의도적으로 발생시켜도:

```text
이후 tree의 bootstrap
이후 tree의 initial RNG state
```

가 변하지 않는지 확인.

이 테스트가 Phase 0.5 수정의 핵심 목적을 직접 검증한다.

---

# 7. Phase 0.5에서 변경되지 않은 부분

이번 비교에서 매우 중요한 사실이다.

## 7.1 Capture

`[SNAPSHOT+GIT-VERIFIED]`

`capture_d455.py`는 Handoff snapshot과 64f8897에서 byte-identical이다.

따라서 다음 문제는 **Phase 0.5에서 수정되지 않았다.**

```text
UI 목표: 8~12 cm
live 기준: 4 cm
final fail 기준: 1.5 cm

face depth 실패 시 body fallback 가능
```

이 부분은 이후 별도 Git commit에서 처리됐다.

```text
c6525a3
fix: align forward posture capture protocol to 8-12 cm

90e6caa
fix: require face depth for forward posture validation
```

---

## 7.2 Analysis

`[SNAPSHOT+GIT-VERIFIED]`

`analyze_d455.py`도 Handoff와 64f8897이 byte-identical이다.

따라서 Phase 0.5에서:

```text
recording_id
analysis_run_id
analysis manifest
fixed frame schema
hip observation
model artifact provenance
```

등은 추가되지 않았다.

---

## 7.3 Reduced-feature weight policy

64f8897 시점에도 Handoff의 기존 weight policy가 유지됐다.

즉:

```text
6 features → paper rank weights
reduced features → normalized MDI
```

문제는 그대로였다.

이는 이후:

```text
c9a60a3
fix: unify rank-based weights for reduced feature sets
```

에서 수정됐다.

---

## 7.4 Relative evaluation

Calibration reference sample을 별도로 제외해 보는 평가는
Phase 0.5 범위가 아니다.

이후:

```text
8d4b4b7
fix: add non-reference evaluation for relative features
```

에서 추가됐다.

---

## 7.5 Metrics / Drop logging / Root provenance

다음도 모두 Phase 0.5 이후의 별도 Git 변경이다.

```text
c5358c0
external evaluation + drop logging

c585665
CSV context manager

fd7176f
root split provenance logging
```

따라서 이러한 후속 수정을
“Git 이전에 이미 수정했다”고 소급 기록하지 않는다.

---

# 8. Git 이력 시작 경계에 대한 해석

## 8.1 중요한 특수성

64f8897은:

```text
"수정 전 baseline"
```

commit이 아니다.

이미 RNG isolation이 완료된 코드를 통째로 처음 commit한:

```text
"현재 research-main 계보의 첫 Git snapshot + Step 1 완료 상태"
```

이다.

따라서 연구 이력 경계는 다음처럼 이해하는 것이 가장 정확하다.

```text
Phase 0
Handoff Snapshot
원본 artifact로 보존

        ↓

Phase 0.5
RNG isolation 문제 발견
RNG isolation 구현
테스트 작성
정확한 edit-by-edit Git history는 없음

        ↓

2026-09-29 23:45:41 +0900

64f8897
현재 research-main 계보의 root commit
= Step 1 완료 상태를 baseline으로 저장

        ↓

Phase 1
Git-tracked / progressively controlled hardening
= 이후 변경은 commit 단위로 추적 가능하며,
  schema·foundation record·독립 review 체계는 후속 단계에서 점진적으로 추가됨
```

즉:

> **Git-controlled history는 64f8897부터 시작하지만,
> 64f8897에 포함된 RNG isolation 자체의 개발 과정은 Git 이전 구간에 걸쳐 있다.**

라고 기록하는 것이 가장 정직하다.

---

# 9. Git 이전에 "코드 수정"과 "연구 활동"을 구분

Git 이전/첫 commit 직전에는
코드 변경 외에도 다음과 같은 분석·실험 활동이 있었을 가능성이 있다.

예:

```text
원 논문 Dataset 분석
M0/M1/M2 비교
자체 데이터 비교
MultiPosture 검토
feature 구성 검토
```

후속 연구 마스터 문서에는 이러한 작업의 실행 기록이 남아 있다.

그러나 현재 확보된 자료만으로:

```text
정확히 어느 실행이 64f8897 이전이었는지
어떤 코드 revision으로 각각 실행했는지
정확한 실행 순서가 무엇이었는지
```

를 모두 commit 수준으로 연결할 수는 없다.

따라서 본 문서에서는:

```text
코드 변화
→ Handoff vs 64f8897 비교로 확정

연구 실험/분석 chronology
→ 별도 근거가 있을 때만 추가
```

원칙을 적용한다.

실험 결과를 임의로 Phase 0.5에 배정하지 않는다.

---

# 10. 복원 신뢰도

| 항목 | 신뢰도 | 근거 |
|---|---|---|
| Handoff 코드 상태 | 높음 | 원본 ZIP |
| 64f8897 코드 상태 | 높음 | Git tree |
| Handoff→64f 코드 diff | **매우 높음** | 양쪽 파일 직접 비교 |
| RNG isolation 목적 | 높음 | 이후 설명 문서 + 테스트 구조 |
| 테스트 내용 | 매우 높음 | 64f8897 `test_rf_rng.py` |
| 정확한 수정 시작 시각 | 낮음 | Git 이전 edit history 없음 |
| 수정 중간 시행착오 | UNKNOWN | 기록 없음 |
| 어떤 AI/도구가 최초 수정했는지 | UNKNOWN | 현재 증거 부족 |
| 각 예비 실험의 정확한 실행 revision | UNKNOWN | provenance 미구축 |

---

# 11. 확인된 사실 vs 추정 금지 사항

## 확인된 사실

```text
1. Handoff와 64f8897 사이에서 기존 5개 파일 중
   rf_experiment.py만 달라졌다.

2. analyze_d455.py, capture_d455.py,
   check_recording.py, compare_paper.py는 동일하다.

3. 변경 내용은 bootstrap RNG와 tree RNG 분리다.

4. test_rf_rng.py가 새로 추가됐다.

5. 64f8897은 현재 research-main 계보에서 parent 없는 root commit이다.

6. 64f8897부터 이후 수정은 개별 Git commit으로 추적 가능하다.
```

## 추정하면 안 되는 사항

```text
1. RNG 수정의 정확한 시작 날짜/시간
2. 수정 중 몇 번 실패했는지
3. 최초 구현을 누가/어떤 도구가 작성했는지
4. 64f 이전 모든 실험이 어떤 정확한 revision에서 실행됐는지
5. Git 이전에 별도의 미보존 코드 버전이 전혀 없었다고 단정
```

특히 마지막 항목이 중요하다.

현재 두 기준점 사이의 **보존된 최종 차이**는 정확하게 복원 가능하지만,
중간에 만들어졌다가 버려진 임시 버전의 존재 여부까지
증명할 수는 없다.

---

# 12. BASELINE_00과의 연결

`BASELINE_00_HANDOFF_SNAPSHOT.md`는:

```text
"처음 받은 코드는 어떤 상태였는가?"
```

를 담당한다.

본 `RETROSPECTIVE_01`은:

```text
"그 코드에서 최초 Git snapshot으로 넘어가는 동안
확실하게 무엇이 바뀌었는가?"
```

를 담당한다.

그리고 이후 Foundation Record는:

```text
"Git-controlled phase에서 각 Patch를 왜/어떻게 변경했는가?"
```

를 담당한다.

세 문서의 역할은 중복시키지 않는다.

---

# 13. 이 문서 이후의 이력 구조

```text
docs/history/
├── BASELINE_00_HANDOFF_SNAPSHOT.md
└── RETROSPECTIVE_01_PRE_GIT_CHANGES.md

docs/foundation/
├── PATCH_01_capture_provenance.md
├── PATCH_02_forward_gate_evidence.md
├── PATCH_03_analysis_provenance.md
└── ...
```

Git-tracked 초기 연구 hardening은 별도 문서:

```text
FOUNDATION_PRELUDE_00_algorithm_and_capture_hardening.md
```

에서 관리한다.

해당 Prelude는:

```text
Core hardening: 64f8897 ~ 90e6caa
Provenance setup bridge: 753bbac ~ 1851261
```

를 다루며,
본 `RETROSPECTIVE_01`과 역할을 분리한다.

본 문서는 **handoff snapshot → 64f8897 사이의 보존된 변화**에 집중하고,
64f8897 이후 변경의 연구적 의미는 Prelude와 각 Foundation Patch record를 우선한다.

---

# 14. 논문 이력 관점에서의 의미

이 복원 결과는 다음을 명확하게 한다.

프로젝트는:

```text
제로베이스 코드
```

에서 시작한 것이 아니라:

```text
기존 prototype
→ handoff
→ 문제 감사
→ 비교 공정성 문제 발견
→ RNG isolation
→ Git-controlled hardening
→ provenance/foundation 구축
→ 이후 핵심 연구
```

순서로 발전했다.

따라서 향후 논문 이력에서:

> “초기 prototype의 모든 설계 결정을 처음부터 연구자가 통제했다”

고 서술해서는 안 된다.

대신:

> “기존 prototype을 인수한 뒤,
> 연구 결과에 영향을 줄 수 있는 구현·평가 조건을 단계적으로 감사하고
> 통제 가능한 pipeline으로 전환했다”

는 실제 흐름을 유지한다.

---

# 15. 현재 상태 판정

```text
RETROSPECTIVE_01 핵심 코드 복원: COMPLETE
역사적 세부 chronology 복원: PARTIAL / 일부 UNKNOWN 유지
```

이 문서는 Final Candidate v2이며,
Handoff → 64f8897의 **보존된 코드 변화 자체는 높은 신뢰도로 복원됐다.**

---

# 16. 현재 상태와 다음 작업

현재 다음 작업은 완료되었다.

```text
BASELINE_00 작성
RETROSPECTIVE_01 작성
FOUNDATION_PRELUDE_00 작성
Patch 1~3 Foundation Record 복원
6개 문서 상호 모순/중복/용어 검토
```

다음 순서:

```text
1. Claude 1차 READ-ONLY 검토 finding 반영본(v2) targeted 재검토
2. blocker가 없으면 canonical filename으로 확정
3. docs/history + docs/foundation commit/push
4. Patch 4 Design Freeze로 복귀
```

---

# 17. Source Notes

본 최종 후보본 작성에 사용한 근거:

```text
A. Handoff source artifact
   새 폴더 (2).zip

B. Current repository Git history
   특히 64f8897 tree / commit metadata

C. Handoff snapshot과 64f8897의 직접 byte/file diff

D. 바른자세 연구 코드 수정 내역 및 수정 근거
   - Step 1 RNG isolation 목적 및 검증 설명

E. 기존 연구 대화/마스터 문서
   - Git 시작 전후의 연구 맥락 보조
```

상충 시 우선순위:

```text
실제 source artifact / Git tree
>
동시대 테스트 코드
>
후속 정리 문서
>
대화 기반 복원
>
추정
```

추정은 확정 사실로 승격하지 않는다.
