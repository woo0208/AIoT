# PATCH_02 — Forward Gate Evidence

> 상태: **소급 복원(Retrospective Reconstruction), 최종 후보 v2 (Final Candidate v2)**
>
> v2 반영: **2026-10-01 Claude READ-ONLY 1차 검토 Finding 1~7 반영. Targeted 재검토 전 상태.**
>
> 운영상 Patch 번호: **Foundation Patch 2**
>
> 관련 commit:
>
> ```text
> a262c6d87366ccb4af50cda3f80a4c3ac94d0bda
> feat: record forward gate evidence
> ```
>
> parent:
>
> ```text
> 1d25c8c66fe8da5127e8ee4054ff225db8960b64
> feat: add capture recording provenance
> ```
>
> commit timestamp:
>
> ```text
> 2026-09-30T16:58:52+09:00
> ```
>
> 작성 목적: 이미 확립되어 있던 face-only 8~12cm forward hard gate의
> **실제 판정 근거를 `_quality.json`에 영구 기록**하도록 만든 Foundation Patch 2의
> 목적, 구현, 검증, 한계를 복원한다.

---

# 1. 이 Patch의 위치

Foundation 흐름:

```text
FOUNDATION_PRELUDE_00
알고리즘·평가·촬영 hardening
        ↓
PATCH 1
capture recording provenance
        ↓
PATCH 2  ← 이 문서
forward gate evidence
        ↓
PATCH 3
analysis provenance
        ↓
PATCH 4
canonical fixed frame schema + hip
```

Patch 2는 forward gate 자체를 새로 설계한 단계가 아니다.

이미 Prelude에서:

```text
c6525a3
8~12 cm protocol 통일

90e6caa
face-only hard gate 확립
```

이 완료되어 있었다.

Patch 2의 질문은 다음이다.

> **“이 촬영이 왜 forward gate를 PASS/FAIL 했는가?”**

즉 판정 결과만 남기는 것이 아니라
**그 판정에 실제로 사용된 reference/current face median, sample count,
valid ratio, 이동량, reason code를 같이 기록**하는 것이 목적이다.

---

# 2. 복원에 사용한 증거 수준

본 문서에서는 다음을 구분한다.

### `[GIT-VERIFIED]`

commit `a262c6d`의 실제 source / diff에서 확인.

### `[TEST-VERIFIED]`

commit `a262c6d`를 detached worktree로 checkout하여
현재 복원 과정에서 테스트를 재실행해 확인.

### `[SCHEMA-VERIFIED]`

Patch 2 이전 `RESEARCH_DATA_SCHEMA.md`에 정의된
forward hard-gate evidence 계약에서 확인.

### `[CHAT-RECONSTRUCTED]`

당시 대화와 그 대화를 바탕으로 작성된 후속 정리 문서에서 복원.

### `[UNKNOWN]`

현재 자료로 정확한 역사적 사실을 확정할 수 없는 사항.

---

# 3. Patch 전 상태

## 3.1 Gate 동작 자체는 이미 존재

`[GIT-VERIFIED]`

Patch 2 이전부터 `quality_check()`에는:

```text
reference = 직전 hold upright
current = forward_head 또는 body_forward
source = face_only
target = 0.08 ~ 0.12 m
```

의 final hard gate가 존재했다.

유효 face sample이 부족하면:

```text
재촬영 필요
```

로 fail되며,
거리 차가 범위를 벗어나면:

```text
below target
또는
above target
```

상태가 된다.

---

## 3.2 그러나 결과의 근거가 구조화되어 저장되지 않음

Patch 전 `_quality.json`에는 주로:

```text
verdict
fails
warnings
frames
total_sec
recording_id
steps
```

가 저장됐다.

따라서 나중에 특정 촬영본을 보면서:

```text
reference face median이 정확히 얼마였는가?
current face median은 얼마였는가?
몇 sample 중 몇 개가 유효했는가?
50% 조건을 만족했는가?
closer_m은 얼마였는가?
정확히 어떤 reason code로 fail했는가?
```

를 machine-readable한 형태로 직접 확인하기 어려웠다.

---

# 4. 연구상 문제

기존 사람이 읽는 실패 문구만으로는:

```text
"얼굴 거리 측정 샘플 부족"
"얼굴 전방 이동 7.0cm — 목표 8~12cm"
```

같은 최종 메시지는 알 수 있어도,
판정에 들어간 세부 evidence가 충분히 보존되지 않는다.

이는 후속 연구에서 다음을 어렵게 만든다.

```text
1. PASS/FAIL을 사후 감사
2. 판정 window와 sample 분모 확인
3. reference/current의 유효 face 비율 확인
4. body fallback이 gate에 섞이지 않았는지 확인
5. 재촬영 이유를 구조적으로 분류
6. 동일 protocol로 촬영됐는지 검증
```

따라서:

> **판정을 다시 계산해서 추정하는 것이 아니라,
> 그 판정에 실제 사용된 값을 그 시점에 같이 저장**

하는 것이 필요했다.

---

# 5. Patch 2 핵심 목표

`[SCHEMA-VERIFIED + GIT-VERIFIED]`

Patch 2의 실제 목표는 다음과 같이 정리된다.

```text
1. 기존 final gate 판정 의미는 바꾸지 않는다.
2. forward_head/body_forward hold phase마다 evidence를 만든다.
3. 실제 gate helper가 사용한 reference/current median을 기록한다.
4. 동일 trimmed window의 total/valid counts를 기록한다.
5. valid face fraction을 명시적으로 기록한다.
6. closer_m과 target bounds를 기록한다.
7. PASS/FAIL reason을 고정 code로 기록한다.
8. evidence를 _quality.json에 영구 저장한다.
9. 기존 quality_check() caller와 기존 JSON field를 깨뜨리지 않는다.
```

---

# 6. 변경 파일

`[GIT-VERIFIED]`

commit `a262c6d`에서 변경된 파일:

```text
capture_d455.py
test_capture_protocol.py
```

Git stat:

```text
2 files changed
267 insertions(+)
5 deletions(-)
```

알고리즘 파일:

```text
rf_experiment.py
analyze_d455.py
```

등은 이 commit에서 변경하지 않았다.

---

# 7. `median_face_distance()`의 Evidence Count 추가

## 변경 전 역할

`median_face_distance()`는
forward gate용 face-only median을 반환했다.

유효 sample 규칙:

```text
mode == "face"
and
distance_m is not None
```

그리고 다음 조건을 만족해야 한다.

```text
valid face sample 수 >= min_samples
valid face sample 수 >= 전체 sample의 50%
```

---

## Patch 2 변경

`[GIT-VERIFIED]`

helper에 optional:

```python
sample_counts=None
```

인자를 추가했다.

호출자가 dict를 넘기면:

```text
total_samples
valid_face_samples
valid_face_fraction
```

을 같은 helper 실행에서 채운다.

핵심:

```text
gate용 median을 계산한 window
=
evidence count를 계산한 window
```

가 되게 했다.

---

## 50% 경계

`[GIT-VERIFIED]`

조건은:

```python
len(values) < 0.5 * len(samples)
```

이면 실패다.

따라서:

```text
49% → fail
50% → 통과 가능
```

이다.

Patch 2는 이 threshold를 변경한 것이 아니라
**현재 threshold가 실제로 어떤 분자/분모에서 적용됐는지 기록**한다.

---

# 8. Final Gate Window

`[GIT-VERIFIED]`

`quality_check()`의 final measurement window는:

```python
1.0 < t < phase_duration_s - 0.5
```

이다.

즉:

```text
시작 1.0초 제외
종료 0.5초 제외
```

후 남은 sample이
reference/current evidence의 분모가 된다.

Patch 2는 별도의 진단용 window를 새로 만들지 않는다.

---

# 9. Reference Policy

`[GIT-VERIFIED]`

forward phase보다 앞에 있는:

```text
hold + upright
```

중 **가장 최근 phase**를 reference로 사용한다.

즉:

```text
현재 forward phase
← 직전 hold upright
```

이다.

중요:

직전 upright의 face sample이 부족하더라도
더 오래된 upright로 자동 fallback하지 않는다.

예:

```text
upright A  충분
upright B  불충분
forward
```

이면:

```text
reference = upright B
→ insufficient_reference_face_samples
```

이다.

`upright A`로 대체하지 않는다.

---

# 10. Evidence Record 구조

`[GIT-VERIFIED]`

`forward_head` 또는 `body_forward`의 각 hold phase마다
다음 evidence object를 생성한다.

## 대상 식별

```text
step
phase_idx
label
```

## reference 식별

```text
reference_step
reference_phase_idx
reference_label
```

reference 자체가 없으면:

```text
null
```

로 둔다.

---

## 실제 gate 값

```text
reference_face_median_m
current_face_median_m
closer_m
```

정의:

```text
closer_m
=
reference_face_median_m
-
current_face_median_m
```

둘 중 하나라도 gate에 사용할 수 없으면:

```text
closer_m = null
```

이다.

---

## target / source

```text
forward_target_min_m
forward_target_max_m
forward_validation_source
```

현재 값:

```text
0.08
0.12
face_only
```

---

## 결과

```text
forward_gate_result
forward_gate_reasons
```

결과:

```text
pass
fail
```

reason은 배열이다.

정상이면:

```json
[]
```

이다.

---

## reference/current sample evidence

각 prefix별:

```text
reference_total_samples
reference_valid_face_samples
reference_valid_face_fraction

current_total_samples
current_valid_face_samples
current_valid_face_fraction
```

을 기록한다.

---

# 11. Reason Code

`[GIT-VERIFIED]`

실제 Patch 2에서 사용하는 고정 reason code:

```text
below_target
above_target
missing_reference
insufficient_reference_face_samples
insufficient_current_face_samples
```

정상 PASS:

```text
forward_gate_reasons = []
```

---

# 12. Missing 처리

## reference 자체가 없음

`[GIT-VERIFIED]`

예:

```text
forward phase 이전에 hold upright가 없음
```

이면:

```text
reference_step = null
reference_phase_idx = null
reference_label = null
reference_face_median_m = null
reference_valid_face_fraction = null
reference_total_samples = 0
reference_valid_face_samples = 0
closer_m = null
reason = missing_reference
```

으로 기록한다.

---

## phase는 있지만 face evidence 부족

예:

```text
total = 10
valid face = 4
```

이면:

```text
valid_face_fraction = 0.4
face_median_m = null
```

이다.

관측된 face 값이 일부 있어도
50% gate 조건을 만족하지 못하면:

> **그 일부 값의 median을 “실제로 gate에 사용된 값”처럼 저장하지 않는다.**

---

## total sample 자체가 0

```text
total_samples = 0
valid_face_samples = 0
valid_face_fraction = null
face_median_m = null
```

로 기록한다.

0m 같은 숫자로 측정 실패를 위장하지 않는다.

---

# 13. `face_ratio`와 `valid_face_fraction`의 분리

`[GIT-VERIFIED]`

기존 `steps[].face_ratio`는:

```text
mode == "face"
```

인 sample 비율이다.

반면 Patch 2의:

```text
*_valid_face_fraction
```

은:

```text
mode == "face"
AND
distance_m is not None
```

인 sample 비율이다.

예:

```text
10 sample 모두 mode == face
그중 distance가 있는 것은 4개
```

이면:

```text
face_ratio = 1.0
valid_face_fraction = 0.4
```

가 가능하다.

Patch 2는 기존 `face_ratio`의 의미를 바꾸지 않는다.

---

# 14. 일반 거리 통계와 Face-Only Evidence의 분리

기존:

```text
steps[].median_m
```

에는 일반 distance 측정 경로가 반영되므로
body fallback이 섞일 수 있다.

Patch 2는 이를:

```text
face-only gate median
```

으로 재해석하거나 덮어쓰지 않는다.

대신 별도:

```text
reference_face_median_m
current_face_median_m
```

을 둔다.

따라서:

```text
일반 촬영 통계
≠
forward hard-gate evidence
```

를 명확하게 분리했다.

---

# 15. `quality_check()` Backward Compatibility

## 기존 caller

Patch 전에는:

```python
fails, warns, rows = quality_check(...)
```

3개 결과를 기대한다.

## Patch 2

`[GIT-VERIFIED]`

새 signature:

```python
quality_check(..., include_evidence=False)
```

기본값은:

```text
False
```

이다.

따라서 기존 caller는 계속:

```text
fails
warns
rows
```

3-tuple을 받는다.

evidence가 필요할 때만:

```python
quality_check(..., include_evidence=True)
```

를 사용해:

```text
fails
warns
rows
forward_gate_evidence
```

4개를 받는다.

이 설계로 기존 동작과 호출 계약을 유지했다.

---

# 16. `report()`와 `_quality.json`

`[GIT-VERIFIED]`

`report()`는:

```python
quality_check(..., include_evidence=True)
```

를 호출한다.

그리고 `_quality.json` 최상위에:

```text
forward_gate_evidence
```

를 추가한다.

Patch 2 후 실제 JSON 구성의 핵심:

```text
verdict
fails
warnings
frames
total_sec
recording_id
forward_gate_evidence
steps
```

이다.

---

# 17. 중요한 의미 — Gate Evidence와 Overall Verdict는 다름

`[SCHEMA-VERIFIED + GIT-VERIFIED]`

```text
forward_gate_result = pass
```

라고 해서:

```text
quality verdict = ok
```

라는 뜻은 아니다.

예를 들어:

```text
forward gate 자체는 10cm로 PASS
하지만 녹화가 중단됨
또는 frame 누락이 심함
```

이면 전체 촬영은 여전히 retake일 수 있다.

따라서:

```text
forward_gate_result
= 해당 forward distance gate 결과

quality.verdict
= 촬영 전체 품질 결과
```

로 구분한다.

---

# 18. Live Evidence는 저장하지 않음

`[SCHEMA-VERIFIED]`

Patch 2는 final quality gate evidence를 기록한다.

매 화면의 live UI 상태까지
새로운 영구 log로 저장하는 기능은 추가하지 않는다.

즉:

```text
live guidance의 모든 순간 기록
```

이 아니라:

```text
최종 quality_check에 실제 사용된 evidence
```

를 보존하는 Patch다.

---

# 19. 테스트 추가

`[GIT-VERIFIED]`

`ForwardGateEvidenceTests`에
**17개 테스트**가 추가됐다.

주요 검증 범위는 다음과 같다.

---

## 19.1 정상 PASS

```text
reference = 0.75 m
current = 0.65 m
closer = 0.10 m
```

결과:

```text
pass
reasons = []
```

`forward_head`, `body_forward`
둘 다 검증한다.

---

## 19.2 범위 미달 / 초과

```text
7 cm
→ below_target

13 cm
→ above_target
```

---

## 19.3 경계 포함

```text
8 cm
12 cm
```

둘 다 PASS하는지 검증한다.

즉 target bound는 inclusive다.

---

## 19.4 Body-only 차단

reference/current가 body sample뿐이면:

```text
face median = null
gate = fail
```

인지 확인한다.

Patch 2는 face-only gate를 새로 만든 것은 아니지만,
evidence가 그 사실을 정확하게 반영하는지 검증한다.

---

## 19.5 Mixed source 차단

예:

```text
reference = face
current = body
```

또는 반대인 경우:

```text
fail
closer_m = null
```

인지 확인한다.

---

## 19.6 Valid ratio 부족

```text
10 sample 중 valid face 4개
→ 0.4
→ median = null
→ fail
```

검증.

---

## 19.7 정확히 50%

```text
10 sample 중 valid face 5개
→ 0.5
```

일 때 gate median을 사용할 수 있는지 검증.

---

## 19.8 Reference 없음

직전 hold upright가 존재하지 않을 때:

```text
missing_reference
```

와 null/0 field 조합을 검증.

---

## 19.9 Empty / Aborted window

sample이 비어 있거나 aborted 상태에서도
forward phase에 대한 evidence object가 사라지지 않는지 확인한다.

---

## 19.10 Latest Upright 정책

여러 upright가 있을 때
가장 최근 hold upright를 reference로 쓰는지 확인한다.

가장 최근 upright가 불충분하더라도
더 오래된 upright로 fallback하지 않는지도 검증한다.

---

## 19.11 Window 동일성

trim boundary 바깥 sample을 추가해도:

```text
count
median
```

둘 다 동일 final window만 사용하는지 확인한다.

---

## 19.12 판정 helper와 evidence의 단일성

mock을 이용해:

```text
median helper
evaluate_forward_distance
```

가 실제 evidence 값 생성과 같은 실행 경로를 쓰는지 확인한다.

즉 evidence를 별도의 두 번째 계산으로 만들어
판정값과 어긋나는 구조를 방지한다.

---

## 19.13 Forward phase만 기록

evidence 배열에는:

```text
forward_head
body_forward
```

의 hold phase만 들어가는지 확인한다.

---

## 19.14 기존 결과 계약 보존

기존 fixture에 대해:

```text
quality_check(..., include_evidence=False)
```

의 기존 3개 결과가 그대로 유지되는지 확인한다.

또:

```text
include_evidence=True
```

일 때 앞의 3개 결과가 동일한지 검증한다.

---

## 19.15 JSON serialization

`report()`가 실제로
`quality_check()`에서 받은 동일 evidence를:

```text
_quality.json.forward_gate_evidence
```

에 저장하는지 확인한다.

기존 JSON field도 그대로 유지되는지 확인한다.

---

# 20. 전체 테스트 재실행

`[TEST-VERIFIED]`

현재 복원 과정에서
commit `a262c6d`를 별도 detached worktree로 checkout하고:

```bash
python3 -m unittest discover -v
```

를 실행했다.

결과:

```text
Ran 94 tests
OK
```

즉:

```text
94 / 94 PASS
```

를 재현했다.

Patch 1의 77 tests에서:

```text
+17 ForwardGateEvidenceTests
```

가 추가된 구조와 일치한다.

---

# 21. Diff Hygiene

`[TEST-VERIFIED]`

현재 복원 과정에서:

```bash
git diff --check a262c6d^ a262c6d
```

실행 결과:

```text
PASS
```

whitespace error가 확인되지 않았다.

---

# 22. 독립 Review 기록

## 역사적 review verdict

`[UNKNOWN]`

현재 확보된 원본/대화/파일만으로
Patch 2에 대한 과거 Claude/Codex 독립 review의
정확한 최종 문구를 직접 검증하지 못했다.

따라서:

```text
COMMIT OK
HARDWARE PENDING
```

같은 과거 verdict를
증거 없이 확정 문구로 소급 기재하지 않는다.

확정 가능한 사실:

```text
Patch 2는 commit a262c6d로 저장됐고
프로젝트 운영상 완료된 Foundation Patch로 취급되고 있다.
```

## 현재 복원 검증

이번 복원에서는:

```text
실제 commit diff 확인
94/94 tests PASS
git diff --check PASS
```

까지 재검증했다.

이는 과거 review 기록을 새로 만들어내는 것이 아니라,
현재 확인 가능한 기술적 검증 결과다.

---

# 23. Hardware Validation 상태

Patch 2에서 추가한 evidence 구조는
synthetic test fixture로 충분히 구조 검증할 수 있다.

그러나 다음은 별개다.

```text
실제 D455
실제 얼굴 검출
실제 depth noise
실제 7cm / 10cm / 13cm 이동
GUI live 표시
실제 recording artifact
```

따라서:

```text
evidence software path verified
≠
actual D455 gate hardware verified
```

이다.

실제 D455 smoke / operating-range validation은
후속 Foundation Patch 8의 범위로 남긴다.

---

# 24. 의도적으로 변경하지 않은 것

Patch 2에서는 다음을 바꾸지 않는다.

```text
0.08 / 0.12 m threshold
inclusive boundary
1.0 sec 시작 trim
0.5 sec 종료 trim
valid face 50% rule
face-only gate
직전 hold upright reference policy
median 계산 의미
일반 body fallback
steps[].median_m
기존 overall quality verdict logic
posture sequence
M0 / M1 / M2
RF feature / metric 정의
```

핵심 원칙:

> **판정을 바꾸지 않고, 판정 근거를 기록한다.**

---

# 25. Schema 문서와 실제 Patch 2 구현의 차이

`[SCHEMA-VERIFIED + GIT-VERIFIED]`

Patch 전 schema에는 `_quality.json` 최상위에 미래 목표로:

```text
schema_version
recording_id
dataset_role
protocol_version
forward_gate_evidence
```

를 두는 설계가 적혀 있었다.

하지만 commit `a262c6d`의 실제 `_quality.json` writer에서
확인되는 Patch 2 핵심 추가는:

```text
forward_gate_evidence
```

이다.

이미 Patch 1의:

```text
recording_id
```

는 유지된다.

반면 이 commit에서:

```text
schema_version
dataset_role
protocol_version
reference_recording_id
```

등 schema에 적힌 모든 미래 field가
실제로 추가된 것은 아니다.

따라서:

> schema에 정의됨 = Patch 2 구현 완료

로 소급 기록하지 않는다.

본 Foundation Record는
**실제 commit에 구현된 범위**를 기준으로 한다.

---

# 26. Patch 2 완료 판단

현재 복원 가능한 근거 기준:

```text
[완료]
forward phase별 evidence object 생성
reference/current identity
reference/current face median 기록
total / valid sample count 기록
valid face fraction 기록
closer_m 기록
target/source 기록
pass/fail reason code 기록
quality JSON serialization
기존 quality_check 계약 보존
기존 step 통계 의미 보존
94/94 test 재현

[후속]
actual D455 hardware validation
analysis provenance
canonical frame schema
full raw→analysis lineage
```

따라서 운영상:

```text
Patch 2 = DONE
```

으로 유지한다.

단:

```text
software evidence path 완료
```

와:

```text
실제 센서 환경에서 물리적 정확도 검증 완료
```

는 동일한 의미가 아니다.

---

# 27. 연구상 의미

Patch 2 전에는:

```text
"이 촬영이 retake였다"
```

는 결과를 알 수 있었다.

Patch 2 후에는 forward gate에 대해:

```text
어느 phase가 대상이었는가
어느 upright를 reference로 썼는가
각 window에 sample이 몇 개 있었는가
face-depth가 실제로 몇 개 유효했는가
각 valid fraction이 얼마였는가
reference/current median이 얼마였는가
실제 closer_m이 얼마였는가
목표 범위가 무엇이었는가
face_only였는가
왜 pass/fail했는가
```

를 machine-readable하게 보존할 수 있다.

즉 Patch 2는:

> **forward gate 결과를 단순 결과값에서 감사 가능한 evidence-bearing result로 바꾼 단계**

라고 정리할 수 있다.

---

# 28. 관련 Commit

```text
Parent / Patch 1
1d25c8c66fe8da5127e8ee4054ff225db8960b64
feat: add capture recording provenance

Patch 2
a262c6d87366ccb4af50cda3f80a4c3ac94d0bda
feat: record forward gate evidence

Next
1cdc528
feat: add verified analysis provenance tracking
```

`a262c6d`의 직접 다음 research-method commit은
Patch 3 `1cdc528`이며, 두 commit 사이에 별도 schema/documentation commit은 없다.

---

# 29. 현재 문서 상태

```text
기술적 복원              COMPLETE
commit/diff 확인          COMPLETE
17개 신규 evidence test   CONFIRMED
94-test 재현              COMPLETE
diff check                COMPLETE
과거 독립 review 문구     UNKNOWN
actual D455 smoke         DEFERRED
```

최종 후보 전 내부 검토에서 다음을 확인했다.

1. Patch 1과 capture identity / gate evidence 범위 분리
2. Patch 3와 capture evidence / analysis provenance 범위 분리
3. 현재 schema의 미래 설계와 Patch 2 당시 실제 구현을 별도 표기
4. `a262c6d → 1cdc528` 직접 ancestry 확인
5. 전체 history/foundation timeline과 용어 정합성 확인

남은 절차:

```text
Claude 1차 READ-ONLY review finding 반영본(v2) targeted 재검토
→ blocker 없으면 canonical Foundation Record로 확정
```

---

# 30. Source Priority

본 복원에서 적용한 우선순위:

```text
1. commit a262c6d 실제 source / Git diff
2. commit a262c6d 실제 test code와 재실행 결과
3. Patch 전 RESEARCH_DATA_SCHEMA.md
4. 당시 대화 / 후속 연구 정리 문서
5. 추정
```

확인되지 않은 과거 review 문구나
실제 commit에 없는 future schema field는
임의로 구현 완료로 기재하지 않는다.
