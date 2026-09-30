# PATCH_01 — Capture Recording Provenance

> 상태: **소급 복원(Retrospective Reconstruction), 최종 후보 v2 (Final Candidate v2)**
>
> v2 반영: **2026-10-01 Claude READ-ONLY 1차 검토 Finding 1~7 반영. Targeted 재검토 전 상태.**
>
> 운영상 Patch 번호: **Foundation Patch 1**
>
> 관련 commit:
>
> ```text
> 1d25c8c66fe8da5127e8ee4054ff225db8960b64
> feat: add capture recording provenance
> ```
>
> parent:
>
> ```text
> 1851261
> docs: align schema with calibration-free body geometry
> ```
>
> 작성 목적: 촬영 artifact에 고유한 identity와 최소한의 실행 provenance를 부여한
> Foundation Patch 1의 목적, 설계 결정, 구현, 검증, 한계를 복원한다.

---

# 1. 이 Patch의 위치

Foundation 흐름:

```text
BASELINE / RETROSPECTIVE
        ↓
FOUNDATION_PRELUDE_00
알고리즘·평가·촬영 hardening
        ↓
PATCH 1  ← 이 문서
촬영 artifact provenance
        ↓
PATCH 2
forward gate evidence
        ↓
PATCH 3
analysis provenance
        ↓
PATCH 4
canonical fixed frame schema + hip
```

Patch 1은 새로운 분류 알고리즘을 만드는 단계가 아니다.

핵심 목적은:

> **“이 raw 촬영본이 정확히 어떤 촬영 시도에서 만들어졌는가?”**

를 나중에도 식별할 수 있게 만드는 것이다.

---

# 2. 복원에 사용한 증거 수준

본 문서는 다음 표기를 사용한다.

### `[GIT-VERIFIED]`

commit `1d25c8c`의 실제 source tree / diff에서 확인.

### `[TEST-VERIFIED]`

해당 commit을 별도 worktree로 checkout하여 실제 테스트를 실행해 확인.

### `[SCHEMA-VERIFIED]`

Patch 전 작성된 `RESEARCH_DATA_SCHEMA.md`에서 확인.

### `[CHAT-RECONSTRUCTED]`

당시 대화와 그 대화를 바탕으로 작성된 후속 정리 문서에서 복원.

### `[UNKNOWN]`

현재 증거만으로 확정할 수 없는 사항.

---

# 3. 문제 정의

## 3.1 Patch 전 상태

`[GIT-VERIFIED]`

기존 촬영 파일 stem은 대략:

```text
<subject>_r<round>_<YYYYMMDD_HHMMSS>
```

형태였다.

이 방식만으로는 다음 문제가 남는다.

```text
같은 subject / round에서 재촬영
같은 초 안의 중복 시도
실패한 촬영 후 즉시 재시도
시계 충돌 또는 복사본 혼입
```

등이 발생했을 때,
촬영 시도 자체를 불변 ID로 식별하기 어렵다.

또한 raw와:

```text
_camera.json
_markers.csv
_samples.csv
_quality.json
```

사이에 공통 identity가 명시적으로 전파되지 않았다.

---

## 3.2 연구상 문제

`[SCHEMA-VERIFIED]`

후속 연구에서 다음 질문에 답할 수 있어야 했다.

```text
이 frames/result의 원본 촬영은 무엇인가?
이 촬영은 pilot인가 formal인가?
어떤 protocol로 찍혔는가?
어떤 Git checkout에서 실행됐는가?
dirty working tree였는가?
실제 capture_d455.py byte는 무엇이었는가?
재촬영은 이전 실패 촬영과 다른 시도인가?
```

파일명만으로는 이 질문에 충분히 답할 수 없다.

---

# 4. Patch 1의 핵심 목표

`[CHAT-RECONSTRUCTED]`

Patch 1의 운영상 목표는 다음으로 정리된다.

```text
1. 촬영 시도마다 고유 recording_id 발급
2. dataset_role을 명시적으로 지정
3. protocol version을 기록
4. Git HEAD / dirty 여부 / capture script hash 기록
5. recording_id를 capture sidecar들에 전파
6. 충돌이나 재촬영으로 기존 artifact를 덮어쓰지 않음
7. 촬영 시작 실패도 “존재했던 시도”로 보존
8. 기존 촬영/분석 의미를 불필요하게 변경하지 않음
```

---

# 5. Recording ID 설계

## 5.1 형식

`[GIT-VERIFIED]`

신규 촬영 시도 ID:

```text
<subject>_r<round>_<YYYYMMDD>_<HHMMSS>_<ffffff>_<uuid4_hex32>
```

예시 형식:

```text
P03_r1_20261001_143025_123456_<32hex>
```

실제 UUID 값은 매 시도마다 새로 생성된다.

---

## 5.2 subject 규칙

허용:

```text
영문
숫자
하이픈(-)
```

정규식:

```text
[A-Za-z0-9-]+
```

금지 예:

```text
../P03
P03_test
P03/4
빈 문자열
```

`_`는 ID 구성요소 구분에 사용되므로
신규 subject ID에서 허용하지 않는다.

---

## 5.3 round 규칙

`[GIT-VERIFIED]`

round는:

```text
양의 정수 의미를 가진 문자열
```

이어야 한다.

예:

```text
"1"
"2"
```

금지:

```text
"0"
"-1"
"1/2"
```

---

# 6. dataset_role

`[GIT-VERIFIED]`

CLI에서 필수로 지정한다.

허용 값:

```text
pilot
formal
external
```

사용 예:

```bash
python capture_d455.py P03 1 --dataset-role pilot
python capture_d455.py P03 1 core --dataset-role formal
```

`--dataset-role`이 없거나
정의되지 않은 값이면 실행을 거부한다.

## 의미

```text
pilot
= protocol 개발/점검용

formal
= 정식 수집 대상으로 등록된 촬영 시도

external
= 별도 수집 조건의 평가용 자료
```

role은 촬영본의 역할을 기록하기 위한 metadata다.

Patch 1 자체가:

```text
formal = 자동 품질 PASS
```

를 의미하게 만들지는 않는다.

---

# 7. Protocol Version

`[GIT-VERIFIED]`

Patch 1에서 현재 촬영 protocol identifier를:

```text
capture-forward-face-v2.0.0
```

으로 저장한다.

코드 상수:

```python
PROTOCOL_VERSION = "capture-forward-face-v2.0.0"
FWD_VALIDATION_SOURCE = "face_only"
```

또한 provenance에 현재 forward target:

```text
0.08 m
0.12 m
```

을 기록한다.

중요:

Patch 1은 8~12cm / face-only gate를 새로 설계한 Patch가 아니다.

그 동작은 Prelude의:

```text
c6525a3
90e6caa
```

에서 이미 확립되었다.

Patch 1은 **그 현재 설정을 provenance에 기록**한다.

---

# 8. Capture Start Time

`[GIT-VERIFIED]`

촬영 identity 생성 시:

```text
Asia/Seoul
UTC+09:00
```

기준 offset-aware datetime을 생성한다.

저장:

```text
capture_start_time
capture_start_time_iso
capture_timezone
start_time
```

예상 관계:

```text
capture_start_time == capture_start_time_iso
capture_timezone == "Asia/Seoul"
```

`start_time`은 기존 파일명 호환용 timestamp 의미를 유지한다.

---

# 9. Git / Code Provenance

## 9.1 Git commit

`[GIT-VERIFIED]`

실행 중인 `capture_d455.py`가 위치한 repository에서:

```bash
git rev-parse HEAD
```

를 실행하여 commit hash를 기록한다.

허용 형식:

```text
40 hex
또는
64 hex
```

---

## 9.2 Dirty state

실행 시:

```bash
git status --porcelain --untracked-files=normal
```

결과를 이용해:

```text
git_dirty = true / false
```

를 기록한다.

## 왜 둘 다 필요한가

commit hash만 저장하면:

```text
HEAD = A
하지만 capture_d455.py는 local edit 상태
```

를 구분할 수 없다.

그래서:

```text
git_commit
+
git_dirty
+
capture_script_sha256
```

를 함께 기록한다.

---

## 9.3 Capture script SHA-256

`[GIT-VERIFIED]`

실제로 실행 중인:

```text
capture_d455.py
```

원본 byte를 SHA-256으로 계산한다.

즉 줄바꿈 등을 재구성한 텍스트가 아니라
실제 파일 byte를 기준으로 한다.

---

## 9.4 Git/hash 조회 실패 정책

`[GIT-VERIFIED]`

Git 실행이나 script hash 계산이 실패해도
촬영 전체를 중단시키지 않는다.

대신:

```text
해당 field = null
provenance_unknown_reasons[field] = 실패 이유
stderr에 경고 출력
```

으로 처리한다.

원칙:

> **모르는 provenance를 추정해서 채우지 않는다.**

---

# 10. recording_id 예약 / Collision 방지

## 10.1 촬영 시작 전 ID 예약

`[GIT-VERIFIED]`

`reserve_capture()`는 실제 camera recording 시작 전에
촬영 ID를 예약한다.

검사 대상 suffix:

```text
.db3
.bag
_camera.json
_markers.csv
_samples.csv
_quality.json
```

동일 stem의 artifact가 이미 있으면
기존 파일을 덮어쓰지 않는다.

---

## 10.2 Exclusive reservation

예약용:

```text
<recording_id>_camera.json
```

을:

```python
open(..., "x")
```

모드로 배타 생성한다.

동시에 같은 candidate를 잡은 경우에도
`FileExistsError`를 통해 충돌을 감지한다.

---

## 10.3 Collision 시 처리

충돌하면:

```text
기존 artifact 보존
→ 새로운 UUID 생성
→ 다시 예약
```

한다.

timestamp/subject/round 의미를 유지하면서
마지막 UUID 부분만 새로 생성한다.

---

# 11. Failed Attempt Preservation

`[GIT-VERIFIED]`

중요한 설계 결정이다.

촬영 ID를 먼저 예약하므로,
카메라 stream 자체가 시작되지 못해도:

```text
_camera.json
```

reservation은 남는다.

초기 상태:

```text
record_file = null
```

이 될 수 있다.

즉:

> “촬영이 실패했으니 존재하지 않았던 시도로 취급”

하지 않는다.

연구 관점에서는:

```text
시도했다
→ 실패했다
→ 새 ID로 재촬영했다
```

라는 이력을 보존한다.

---

# 12. `.db3` → `.bag` Fallback과 ID

`[GIT-VERIFIED]`

RealSense recording format fallback:

```text
.db3 시도
→ 실패
→ .bag 시도
```

가 발생해도 같은 촬영 시도이므로
**같은 recording_id를 유지**한다.

새로운 UUID를 발급하지 않는다.

반대로:

```text
새로운 촬영 / 재촬영
```

은 새 recording_id를 가져야 한다.

---

# 13. Sidecar Propagation

`[GIT-VERIFIED]`

동일 `recording_id`를 다음 artifact에 전파한다.

## `_camera.json`

최상위:

```text
recording_id
```

및 provenance metadata 저장.

## `_markers.csv`

각 row 마지막 column:

```text
recording_id
```

## `_samples.csv`

각 row 마지막 column:

```text
recording_id
```

## `_quality.json`

최상위:

```text
recording_id
```

---

# 14. Camera Metadata와 기존 의미 보존

`[GIT-VERIFIED]`

기존 `_camera.json`에서 사용하던 정보:

```text
subject
round
start_time
record_file
start_distance
target_range_m
fps
sequence
prep_sec
device
serial
firmware
usb
depth_scale_m
color_intrinsics
depth_intrinsics
depth_to_color_extrinsics
stereo_baseline_mm
```

의 의미를 유지하면서 provenance field를 추가한다.

Patch 1은 기존 field를 다른 의미로 재사용하지 않는다.

---

# 15. sidecar_files

`[GIT-VERIFIED]`

reservation metadata에는:

```text
camera
markers
samples
quality
```

각 sidecar의 basename mapping도 저장한다.

목적:

```text
recording_id
→ 관련 artifact 이름
```

을 명시적으로 연결하기 위함이다.

---

# 16. Retake 정책

`[GIT-VERIFIED]`

quality verdict가 retake일 때
기존에는 실패 파일을 지우거나 이름을 바꾸는 방향의 안내가 있었다.

Patch 1 이후에는:

```text
실패한 촬영본도 보존
재촬영에는 새 recording_id 부여
```

하도록 안내한다.

재촬영 명령에도:

```text
--dataset-role <기존 role>
```

을 유지해서 출력한다.

이 결정은 selection을 나중에 결과 보고 임의로 바꾸는 것이 아니라
**모든 촬영 시도를 보존한 뒤 별도 선택 정책으로 관리**하기 위한 기반이다.

---

# 17. 기존 Analysis Reader 호환성

`[TEST-VERIFIED]`

Patch 1은 기존 markers CSV에:

```text
recording_id
```

열을 하나 추가하지만,
기존 분석 helper:

```text
parse_name()
load_markers()
```

가 계속 동작하는지 테스트했다.

즉 provenance 추가 때문에
기존 analyzer의 marker parsing을 깨뜨리지 않는 것을 확인했다.

---

# 18. 변경 파일

`[GIT-VERIFIED]`

commit `1d25c8c`:

```text
capture_d455.py
test_capture_protocol.py
```

두 파일만 변경됐다.

Git stat:

```text
2 files changed
394 insertions(+)
21 deletions(-)
```

핵심 연구 모델:

```text
rf_experiment.py
analyze_d455.py
```

등은 이 commit에서 변경하지 않았다.

---

# 19. 검증

## 19.1 당시 commit 전체 테스트 재실행

`[TEST-VERIFIED]`

commit `1d25c8c`를 별도 detached worktree로 checkout한 뒤:

```bash
python3 -m unittest discover -v
```

를 현재 복원 과정에서 다시 실행했다.

결과:

```text
Ran 77 tests
OK
```

즉:

```text
77 / 77 PASS
```

를 재현했다.

---

## 19.2 Patch 1에 추가된 주요 테스트

`[GIT-VERIFIED]`

### Identity

- 동일 timestamp에서도 20개 recording_id가 모두 unique
- ID 형식 검사
- Asia/Seoul offset 확인

### dataset_role

- pilot/formal/external 허용
- role 누락 거부
- 정의되지 않은 role 거부

### subject / round

- unsafe subject 거부
- invalid round 거부

### protocol metadata

- protocol version 확인
- face_only source 확인
- forward target이 현재 상수와 연동됨을 확인

### Git/code provenance

- Git HEAD 확인
- dirty state 확인
- Git unavailable 시 unknown reason 기록
- capture script SHA-256 실제 파일 hash와 일치
- script hash 실패 시 unknown reason 기록

### Collision

- 기존 raw artifact를 덮어쓰지 않음
- 기존 reservation을 덮어쓰지 않음
- concurrent exclusive collision 재시도

### Failed attempt

- camera start 실패 후에도 reservation metadata 보존

### End-to-end writer 구조

fake camera/profile을 이용해:

```text
camera.json
markers.csv
samples.csv
quality.json
```

에 동일 recording_id가 들어가는지 확인.

또 `.db3` 실패 후 `.bag` fallback에서도
같은 ID가 유지되는지 확인.

### Backward compatibility

기존 analysis reader가
추가된 CSV column이 있어도 기존 의미대로 동작하는지 확인.

---

## 19.3 Diff hygiene

`[TEST-VERIFIED]`

현재 복원 과정에서:

```bash
git diff --check 1851261 1d25c8c
```

를 재실행했다.

결과:

```text
PASS
```

whitespace error가 확인되지 않았다.

---

# 20. 독립 Review 기록

## 역사적 review verdict

`[UNKNOWN]`

현재 확보된 대화/파일에서는
Patch 1에 대한 Claude/Codex 독립 review의
정확한 최종 verdict 문구를 신뢰성 있게 복원하지 못했다.

따라서:

```text
COMMIT OK
NO ISSUE
```

같은 문구를 임의로 소급 작성하지 않는다.

확정 가능한 사실은:

```text
Patch 1은 프로젝트 추적상 완료 상태였고,
commit 1d25c8c로 저장됐다.
```

는 점이다.

## 현재 복원 검증

현재 기록 복원 과정에서는:

```text
실제 Git diff 확인
77/77 tests 재실행 PASS
git diff --check PASS
```

까지 확인했다.

이는 과거 독립 review verdict를 대체하거나
과거에 존재했다고 주장하는 기록은 아니다.

---

# 21. Hardware Validation 상태

Patch 1의 핵심 기능은 provenance/identity이므로
fake camera 기반 writer test로 구조를 검증했다.

그러나 실제:

```text
D455
RealSense recording
실제 filesystem artifact
GUI/live
```

를 포함한 end-to-end hardware smoke는
Foundation Patch 8 대상으로 남겼다.

따라서:

```text
software structure verified
≠
actual D455 end-to-end verified
```

로 구분한다.

---

# 22. 의도적으로 변경하지 않은 것

Patch 1에서는 다음을 바꾸지 않는다.

```text
M0 / M1 / M2 모델 정의
RF feature 정의
8~12cm threshold 자체
face-only forward gate 자체
posture sequence 의미
depth 계산식
기존 camera intrinsic/extrinsic 의미
quality PASS/FAIL 계산 로직
```

Patch 1은 **identity/provenance 추가**가 중심이다.

---

# 23. Patch 1의 범위 밖

다음은 후속 Patch로 분리한다.

## Patch 2

```text
PASS/FAIL을 만든 실제 forward gate evidence
reference/current median
valid count
valid ratio
closer_m
failure reason
```

## Patch 3

```text
analysis_run_id
analysis input hash
MediaPipe artifact provenance
analysis manifest
raw/from-csv lineage
```

## Patch 4

```text
canonical fixed frame schema
hip raw observation
frame-level identity columns
```

## 이후

```text
raw → frames → summary → RF 전체 lineage
selection manifest
integrity checker
actual D455 smoke
```

---

# 24. Schema 문서와 실제 Patch 1 구현의 차이

`[SCHEMA-VERIFIED + GIT-VERIFIED]`

당시 `RESEARCH_DATA_SCHEMA.md`에는
향후 capture provenance 후보로 더 넓은 field가 정의되어 있었다.

예:

```text
recording_started_at / recording_ended_at
runtime_versions
capture_face_detector artifact hash
actual/requested stream snapshot
capture_state
forward_gate_settings 상세 snapshot
```

그러나 commit `1d25c8c`에서
이 모든 field가 실제 구현된 것은 아니다.

Patch 1에서 실제 확인되는 핵심 구현은:

```text
recording_id
dataset_role
protocol_version
capture start timestamp/timezone
git_commit
git_dirty
capture_script_sha256
forward target/source
unknown reason
sidecar propagation
collision-safe reservation
failed-attempt preservation
```

이다.

따라서 Foundation Record에서는:

> schema에 존재했다 = Patch 1에서 구현 완료

로 소급해서 기록하지 않는다.

추가 schema field들의 정확한 운영상 귀속은
후속 foundation 설계/검증에서 별도로 판단한다.

---

# 25. Patch 1 완료 판단

현재 복원 가능한 근거 기준:

```text
[완료]
고유 recording identity
role 명시
현재 capture protocol 식별
Git/code provenance
충돌 방지
failed attempt 보존
capture sidecar ID 전파
기존 reader 호환성
unit/integration-style test

[후속]
forward 판정 evidence      → Patch 2
analysis provenance         → Patch 3
canonical frame schema      → Patch 4
actual D455 E2E smoke       → Patch 8
```

따라서 운영상:

```text
Patch 1 = DONE
```

으로 유지한다.

단,
위 완료 판정은 **Patch 1의 실제 구현 범위**에 대한 것이며
`RESEARCH_DATA_SCHEMA.md`에 적힌 모든 미래 capture metadata field가
완료됐다는 의미는 아니다.

---

# 26. 연구상 의미

Patch 1 이후 촬영본은 단순히:

```text
P03 1회차 파일
```

가 아니라:

```text
고유한 recording_id를 가진 하나의 촬영 시도
```

로 다룰 수 있게 됐다.

그리고 최소한 다음을 함께 추적할 수 있다.

```text
누구 / 몇 회차
어떤 dataset role
언제 발급된 시도
어떤 capture protocol
어떤 Git HEAD
dirty 여부
실제 capture script hash
어떤 sidecar들이 같은 시도에 속하는지
```

이는 후속:

```text
gate evidence
analysis provenance
frame schema
full lineage
selection manifest
```

를 구축하기 위한 첫 identity layer다.

---

# 27. 관련 Commit

```text
Parent
1851261
docs: align schema with calibration-free body geometry

Patch 1
1d25c8c66fe8da5127e8ee4054ff225db8960b64
feat: add capture recording provenance

Next
a262c6d
feat: record forward gate evidence
```

---

# 28. 현재 문서 상태

```text
기술적 복원              COMPLETE
commit/diff 확인          COMPLETE
77-test 재현              COMPLETE
diff check                COMPLETE
과거 독립 review 문구     UNKNOWN
actual D455 smoke         DEFERRED TO PATCH 8
```

최종 후보 전 내부 검토에서 다음을 확인했다.

1. `BASELINE_00`과 충돌 없음
2. `RETROSPECTIVE_01`과 `64f8897` 경계 역할 분리
3. `FOUNDATION_PRELUDE_00`과 목적 분리
4. Patch 2/3와 구현 범위 분리

남은 절차:

```text
Claude 1차 READ-ONLY review finding 반영본(v2) targeted 재검토
→ blocker 없으면 canonical Foundation Record로 확정
```

---

# 29. Source Priority

본 복원에서는 다음 우선순위를 적용했다.

```text
1. commit 1d25c8c 실제 source / Git diff
2. commit 1d25c8c 실제 test code와 재실행 결과
3. Patch 전 RESEARCH_DATA_SCHEMA.md
4. 당시 연구 정리 문서 / 대화 기록
5. 추정
```

확인되지 않은 과거 review 결과나
구현되지 않은 schema field를 임의로 채우지 않았다.
