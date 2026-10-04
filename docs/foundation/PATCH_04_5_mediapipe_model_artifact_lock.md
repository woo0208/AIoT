# PATCH_04_5 — MediaPipe Model Artifact Lock

> 상태: **IMPLEMENTED / SOFTWARE-VERIFIED / INDEPENDENTLY AUDITED / HARDWARE RUN NOT REQUIRED FOR CLOSURE**
>
> 운영상 Patch 번호: **Foundation Patch 4.5**
>
> lock schema:
>
> ```text
> mediapipe-model-lock/1.0.0
> ```
>
> Design Freeze authority:
>
> ```text
> docs/research/RESEARCH_DECISION_LOG.md
> → PROV-004 — Patch 4.5 MediaPipe Model Artifact Lock Design Freeze
> ```
>
> parent / Design Freeze commit:
>
> ```text
> 6b69255
> docs: freeze Patch 4.5 model artifact lock design
> ```
>
> 구현 commit:
>
> ```text
> aef7f34
> feat: implement Patch 4.5 model artifact lock
> ```
>
> main baseline:
>
> ```text
> d923b23
> merge: complete Patch 4 frame schema foundation
> ```
>
> documentation closure milestone:
>
> ```text
> 2026-10-04
> ```
>
> 작성 목적: `PROV-004`에서 Design Freeze한 MediaPipe model artifact의
> exact identity/source/version/SHA-256 contract를 repository의 tracked lock manifest,
> fail-closed verification, verified provisioning, Patch 3 analysis provenance linkage 및
> regression tests로 구현한 Foundation Patch 4.5의 범위, 검증 결과, 독립 audit,
> 남은 한계와 후속 작업을 기록한다.

---

# 1. 이 Patch의 위치

Foundation 흐름:

```text
FOUNDATION_PRELUDE_00
algorithm / evaluation / capture hardening
        ↓
PATCH 1
capture recording provenance
        ↓
PATCH 2
forward gate evidence
        ↓
PATCH 3
analysis provenance
        ↓
PATCH 4
canonical frame schema + hip raw observations
        ↓
PATCH 4.5  ← 이 문서
MediaPipe model artifact lock
        ↓
PATCH 5+
lineage / selection / integrity hardening
        ↓
PATCH 8
actual D455 formal hardware validation
```

Patch 3이 실제 분석 실행에서 사용한 model artifact의 provenance를 기록하고,
Patch 4가 canonical frame output을 고정했다면,
Patch 4.5는 raw MediaPipe inference에 **어떤 exact model bytes만 허용되는지**를 강제한다.

Patch 4.5의 핵심은 다음 구분이다.

```text
analysis provenance
→ 실제 실행에서 무엇을 사용했는가를 기록

model artifact lock
→ 어떤 artifact만 사용하도록 허용하는가를 강제
```

Patch 4.5는 다음이 아니다.

```text
F1/F2 feature-engineering Patch
posture classification 변경 Patch
Random Forest algorithm 변경 Patch
landmark set 확장 Patch
capture protocol 변경 Patch
D455 formal hardware-validation Patch
Python dependency/environment 전체 lock Patch
```

---

# 2. 증거 수준

### `[DESIGN-FROZEN]`

`RESEARCH_DECISION_LOG.md`의 `PROV-004`에서 확인한 Patch 4.5 frozen contract.

### `[GIT-VERIFIED]`

commit `aef7f34`의 source / manifest / tests와 Git diff에서 확인한 구현 사실.

### `[TEST-VERIFIED]`

Windows 환경에서 다음 전체 test suite 결과로 확인한 software verification.

```text
pre-change baseline    171 PASS
new Patch 4.5 tests     33 PASS
--------------------------------
final suite            204 PASS
```

실행 기준:

```powershell
$env:PYTHONUTF8="1"
python -B -m unittest -q
```

### `[AUDIT-VERIFIED]`

Claude Opus 독립 READ-ONLY audit에서 확인한 결과.

```text
Audit verdict
PASS WITH MINOR FINDINGS

Recommendation
ACCEPT WITH MINOR NOTES

BLOCKER
0

IMPORTANT
0
```

독립 audit에서도 Windows / Python 3.12.10 환경에서 전체 `204 tests`가 다시 PASS했다.

### `[HARDWARE-DEFERRED]`

Patch 4.5 closure를 위해 새로운 D455 hardware run은 요구하지 않는다.

2026-10-02 Early Hardware Preflight는 별도의 non-formal engineering evidence이며,
formal D455 hardware validation은 계속 Foundation Patch 8의 대상이다.

---

# 3. 목적과 경계

`[DESIGN-FROZEN + GIT-VERIFIED]`

Patch 4.5의 목적은 MediaPipe inference model artifact가 동일 filename 또는 mutable source 때문에
조용히 다른 bytes로 바뀌는 silent model drift를 차단하는 것이다.

canonical control flow:

```text
tracked model lock manifest
        ↓
manifest validation
        ↓
existing artifact SHA-256 verification
        │
        ├─ match
        │    → use verified artifact
        │
        └─ missing
             → exact locked source download
             → temporary artifact
             → complete SHA-256 verification
             → verified final install
        ↓
raw MediaPipe inference
        ↓
Patch 3 analysis provenance
```

기존 artifact가 존재하면서 SHA-256이 다르면:

```text
HARD FAIL
```

한다.

이 경우 자동 overwrite, automatic redownload, delete, rename, quarantine 또는 fallback으로
실행을 계속하지 않는다.

---

# 4. Canonical Lock Manifest

`[DESIGN-FROZEN + GIT-VERIFIED]`

repository root의 tracked source of truth:

```text
mediapipe_model_lock.json
```

schema:

```text
mediapipe-model-lock/1.0.0
```

canonical artifact role은 정확히:

```text
face
mesh
pose
```

세 개다.

각 artifact entry의 필수 field:

```text
role
filename
source_url
version_identifier
sha256
```

SHA-256 textual representation은 lowercase 64-hex를 canonical representation으로 사용한다.

---

# 5. Frozen Artifact Set

`[DESIGN-FROZEN + GIT-VERIFIED + AUDIT-VERIFIED]`

## 5.1 face

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

## 5.2 mesh

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

## 5.3 pose

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

Pose는 numbered `/1/` artifact를 사용하지 않는다.

Design Freeze 당시 확인된 `/1/` SHA-256:

```text
5134a3aad27a58b93da0088d431f366da362b44e3ccfbe3462b3827a839011b1
```

이는 실제 연구에 사용된 Pose artifact와 다른 bytes다.

따라서 Pose의 source identity는 mutable unqualified `/latest/`가 아니라
GCS generation `1682642787774579`을 명시한 generation-qualified locator로 고정한다.

---

# 6. Manifest Validation

`[GIT-VERIFIED + TEST-VERIFIED + AUDIT-VERIFIED]`

`load_model_lock()` / `validate_model_source()` 경로에서 raw inference 전에
tracked manifest를 읽고 검증한다.

다음은 fail-closed 대상이다.

```text
manifest missing
malformed JSON
duplicate JSON key
unsupported lock_schema_version
invalid top-level structure
malformed artifacts collection
required role missing
duplicate role
unknown role
required field missing
invalid field type
invalid filename contract
invalid/noncanonical SHA-256
invalid source URL
invalid version_identifier
unqualified /latest/
invalid generation query
```

canonical filename contract가 role별 exact filename을 요구하므로 다음과 같은 임의 path는 허용되지 않는다.

```text
../x
subdir/x
absolute path
role 간 filename swap
```

generation-qualified Pose source는 허용한다.

---

# 7. Existing Artifact Verification

`[GIT-VERIFIED + TEST-VERIFIED + AUDIT-VERIFIED]`

`models/<filename>`이 이미 존재하면 network access보다 먼저 complete SHA-256을 계산한다.

```text
actual hash == locked hash
→ PASS
→ cached artifact 사용
→ network request 없음

actual hash != locked hash
→ HARD FAIL
```

hash mismatch diagnostic에는 최소 다음을 포함한다.

```text
artifact path
expected SHA-256
actual SHA-256
```

mismatch existing artifact에 대해서는 다음을 수행하지 않는다.

```text
automatic overwrite
automatic redownload
automatic delete
automatic rename
automatic quarantine
fallback source 사용
```

mismatch bytes는 원인 조사 가능성을 위해 보존한다.

complete hashing은 chunked streaming으로 수행하며,
file stat을 hash 전후에 확인하여 hash 도중 artifact 변경도 감지한다.

---

# 8. Missing Artifact Provisioning

`[GIT-VERIFIED + TEST-VERIFIED + AUDIT-VERIFIED]`

final artifact가 존재하지 않는 경우에만 network provisioning을 수행한다.

```text
missing final artifact
→ exact manifest source_url
→ temporary download
→ complete SHA-256 verification
→ expected hash match
→ verified final install
```

허용되지 않는 fallback:

```text
unqualified /latest/
다른 numbered version
다른 GCS generation
다른 mirror
다른 model variant
다른 precision
legacy hard-coded alternate URL
```

현재 구현에는 alternate/fallback URL path가 없다.

---

# 9. Verified Temporary Install

`[GIT-VERIFIED + TEST-VERIFIED + AUDIT-VERIFIED]`

network bytes를 final model path에 직접 다운로드하지 않는다.

현재 구현:

```text
mkstemp(dir=models/)
→ urlretrieve(..., temporary path)
→ verify_model_artifact(temporary)
→ os.link(temporary, final)
→ temporary unlink
```

temporary artifact는 `models/` 내부에 생성되므로 final artifact와 동일 filesystem을 사용한다.

hash mismatch 또는 network/download failure 시:

```text
HARD FAIL
invalid final artifact 설치 금지
```

를 유지한다.

destination이 provisioning 중 새로 생긴 경우 `os.link()`의 destination-existing failure를 이용하여
기존 destination을 무조건 교체하지 않고 다시 검증한다.

독립 audit에서 target Windows 환경의 NTFS + Python 3.12에서 다음을 직접 확인했다.

```text
existing destination에 os.link
→ FileExistsError / WinError 183

temp hard link 생성 후 temp unlink
→ final file 정상 유지

administrator privilege
→ 불필요
```

따라서 현재 target Windows/NTFS 환경에서는 PROV-004의 verified-install contract를 충족한다.

완전한 adversarial filesystem race-proof protocol은 Patch 4.5 scope 밖이다.

---

# 10. `--from-csv` Historical Reprocessing

`[DESIGN-FROZEN + GIT-VERIFIED + TEST-VERIFIED + AUDIT-VERIFIED]`

`--from-csv`는 새로운 MediaPipe inference를 수행하지 않는다.

따라서 다음을 구분한다.

```text
RAW MediaPipe inference
→ current lock manifest 필요
→ current model verification 필요

--from-csv historical reprocessing
→ current lock manifest 불필요
→ current model provisioning 불필요
→ current model verification 불필요
→ MediaPipe inference 없음
```

실제 integration test에서는 current lock과 models를 제거하고
lock/provision/verify/inference 관련 경로가 호출되면 실패하도록 설정한 상태에서도
CSV historical reprocessing이 완료되는 것을 확인했다.

historical parent model provenance는 당시 값 그대로 유지한다.

```text
source_url
version_identifier
sha256
source_url_kind
```

현재 lock 정보를 historical run에 backfill하지 않는다.

이는 `PROV-002`의:

```text
historical unknown remains unknown
```

정책을 유지한다.

---

# 11. Patch 3 Analysis Provenance Linkage

`[DESIGN-FROZEN + GIT-VERIFIED + TEST-VERIFIED + AUDIT-VERIFIED]`

새로운 raw analysis가 성공한 경우 다음 invariant를 만족한다.

```text
actual filesystem model SHA-256
==
lock manifest SHA-256
==
analysis provenance recorded SHA-256
```

`record_model_artifacts()`는 inference 직전에 artifact를 다시 full-hash한다.

따라서 provisioning 이후 inference 이전에 artifact bytes가 바뀌면
HARD FAIL하고 `process_recording`으로 진행하지 않는다.

provenance의:

```text
source_url
version_identifier
```

는 corresponding lock entry의 frozen 값을 기록한다.

기존 analysis provenance schema는 유지한다.

```text
analysis-provenance/1.0.0
```

Patch 4.5를 위해 다음을 추가하지 않았다.

```text
duplicate expected_sha256 field
불필요한 provenance schema bump
불필요한 source_url_kind redesign
```

현재 `source_url_kind="configured_download_url"`은
verified artifact의 configured/locked source라는 기존 의미와 모순되지 않는 것으로 독립 audit에서 판정했다.

---

# 12. Runtime Model Directory / Git Policy

`[DESIGN-FROZEN + GIT-VERIFIED + AUDIT-VERIFIED]`

역할을 다음과 같이 분리한다.

```text
models/
→ runtime/local artifact storage

mediapipe_model_lock.json
→ tracked canonical artifact contract
```

`.gitignore`에:

```text
models/
```

를 추가했다.

기존 tracked model binary를 삭제하거나 untrack하지 않았으며,
독립 audit에서 Git tracked model binary가 없음을 확인했다.

model binary 자체는 Patch 4.5의 canonical lock mechanism으로 Git에 commit하지 않는다.

---

# 13. Automated Test Contract

`[TEST-VERIFIED]`

Patch 4.5에서 신규 33개 test가 추가되었다.

주요 coverage:

```text
1. exact frozen manifest contents
2. matching cached artifact / no network
3. cached mismatch HARD FAIL + preservation + diagnostics
4. mismatch checked before any missing-file provisioning
5. complete hashing beyond first chunk
6. exact-source download + verified final install
7. downloaded hash mismatch cleanup
8. interrupted download cleanup
9. final-install failure cleanup
10. concurrent matching destination preservation
11. concurrent mismatching destination preservation
12. unreadable existing artifact rejection
13. raw inference + missing lock rejection
14. malformed JSON rejection
15. duplicate JSON key rejection
16. unsupported schema rejection
17. invalid top-level structure rejection
18. malformed artifact collection rejection
19. missing role rejection
20. duplicate role rejection
21. unknown role rejection
22. missing field / invalid type rejection
23. invalid filename rejection
24. noncanonical SHA-256 rejection
25. invalid / noncanonical source URL rejection
26. invalid version_identifier rejection
27. unqualified /latest/ rejection
28. invalid generation query rejection
29. exact generation-qualified Pose acceptance
30. raw provenance hash/source/version linkage
31. post-provision artifact change detection
32. --from-csv current-lock/model independence + historical provenance preservation
33. Patch 4 frames-schema/1.0.0 exact 60-field regression
```

test network behavior는 mocked/stubbed되어 있으며
live Google network를 테스트 dependency로 사용하지 않는다.

repository `models/`도 test fixture로 사용하지 않고 temporary directory를 사용한다.

---

# 14. Regression Result

`[TEST-VERIFIED + AUDIT-VERIFIED]`

구현 전:

```text
171 tests PASS
```

구현 후 Codex verification:

```text
33 Patch 4.5 tests PASS
204 total tests PASS
```

독립 Claude Opus READ-ONLY audit 재검증:

```text
Ran 204 tests
OK
```

따라서 acceptance criterion:

```text
all previous 171 tests remain PASS
+
all new Patch 4.5 tests PASS
```

를 만족한다.

Patch 4 canonical frame contract:

```text
frame_schema_version = frames-schema/1.0.0
canonical fields      = exactly 60
```

도 regression 없이 유지되었다.

---

# 15. Independent READ-ONLY Audit

`[AUDIT-VERIFIED]`

Claude Opus를 사용한 independent READ-ONLY audit 결과:

```text
Audit verdict
PASS WITH MINOR FINDINGS

Recommendation
ACCEPT WITH MINOR NOTES
```

contract compliance 결과:

```text
frozen manifest                 PASS
manifest validation             PASS
existing artifact verification  PASS
missing artifact provisioning   PASS
verified temporary install      PASS
mismatch HARD FAIL              PASS
no fallback                     PASS
--from-csv isolation            PASS
historical provenance           PASS
Patch 3 provenance linkage      PASS
.gitignore model policy         PASS
Patch 4 schema regression       PASS
scope guard                     PASS
```

BLOCKER 또는 IMPORTANT finding은 없었다.

독립 audit 과정에서 repository file 수정은 없었고,
audit 종료 후 working tree는 audit 시작 상태와 동일했다.

---

# 16. Accepted Minor Audit Notes

독립 audit의 4개 MINOR finding은 Patch 4.5 closure blocker로 판단하지 않는다.

## MINOR-1 — runtime validator는 frozen value 자체가 아니라 source/version 구조를 검증

현재 validator는 manifest entry의 role/source/version 조합이 canonical structural form인지 검증한다.

scratch manifest 자체를 변경하면 self-consistent한 다른 Pose numbered version 또는 generation 구조가
validation을 통과할 수 있다.

그러나:

```text
tracked mediapipe_model_lock.json
+
exact frozen-manifest regression test
+
corresponding SHA-256 enforcement
```

가 현재 frozen values의 repository contract를 구성한다.

따라서 현재 frozen artifact에 대한 integrity bypass는 아니다.

향후 model lock 변경은 `PROV-004` §3에 따라 별도 explicit decision과 lock update가 필요하다.

처리:

```text
ACCEPTED MINOR
code change 없음
```

## MINOR-2 — temporary unlink cleanup failure가 원래 exception을 가릴 수 있음

`provision_model_artifact()`의 `finally`에서 temporary `os.unlink()`가 unguarded다.

Windows에서 antivirus/indexer handle 때문에 unlink가 `PermissionError`를 일으키는 경우:

```text
success path
→ provisioning run이 fail-closed할 수 있음

failure path
→ cleanup PermissionError가 original exception의 표면 error가 될 수 있음

possible residue
→ ignored models/ 아래 temporary file
```

invalid final artifact가 설치되거나 integrity check를 우회하지는 않는다.

따라서 PROV-004 위반은 아니며 현재 closure를 막지 않는다.

처리:

```text
ACCEPTED MINOR
향후 필요 시 cleanup failure를 non-fatal warning으로 hardening 가능
현재 Patch 4.5에서 추가 수정하지 않음
```

## MINOR-3 — verified final install이 hard-link 지원에 의존

현재 verified publication은 `os.link()`를 사용한다.

FAT32, exFAT 또는 일부 SMB 환경에서는 hard-link가 지원되지 않아
automatic provisioning이 fail-closed할 수 있다.

현재 target Windows repository/model 환경은 NTFS이며
독립 audit에서 실제 hard-link 동작을 검증했다.

manual provisioning 후 동일 SHA-256 verification 경로도 유지된다.

PROV-004는 atomic semantics를 `가능한 범위에서` 요구하므로 contract 위반이 아니다.

처리:

```text
ACCEPTED MINOR
현재 NTFS target 환경에서는 문제 없음
generic cross-filesystem portability hardening은 후속 필요 시 검토
```

## MINOR-4 — raw run_analysis mismatch direct integration test 부재

현재 test suite는:

```text
ensure_models mismatch unit test
+
record_model_artifacts re-check
+
raw provenance run_analysis integration
```

을 통해 mismatch/inference-before-use contract를 검증한다.

다만:

```text
run_analysis
+ pre-existing mismatched artifact
+ process_recording never called
```

을 하나의 direct integration test로 검증하는 test는 없다.

이는 test-strength gap이며 실제 safety defect로 판정되지 않았다.

처리:

```text
ACCEPTED MINOR
closure blocker 아님
향후 test hardening candidate
```

---

# 17. Scope Audit

`[GIT-VERIFIED + AUDIT-VERIFIED]`

Patch 4.5 구현에서 다음은 변경하지 않았다.

```text
F0 / F_cal
F1 / F2 formulas
posture classification
Random Forest algorithms
M0 / M1 / M2 behavior
rank_weights policy
landmark set
elbow / wrist inclusion
confidence thresholds
capture protocol
camera distance
forward gate
D455 formal validation
UI
performance architecture
multi-person tracking
sagittal processing
Patch 4 canonical 60-field schema
```

변경된 implementation surface는 다음으로 제한된다.

```text
.gitignore
analyze_d455.py
mediapipe_model_lock.json
test_model_artifact_lock.py
test_analysis_provenance.py
test_frame_schema.py
```

authority documents는 implementation commit에서 수정하지 않았다.

---

# 18. Hardware / Research Evidence Boundary

Patch 4.5의 software/reproducibility contract는 완료되었지만,
이 결과를 실제 D455 measurement-quality validation으로 확대 해석하지 않는다.

2026-10-02 수행한 Early Hardware Preflight는:

```text
engineering smoke / extraction-path sanity evidence
```

이며 다음이 아니다.

```text
Patch 8 formal hardware validation evidence
formal research data
formal participant collection
threshold / protocol decision 근거
```

새로운 D455 raw MediaPipe run은 Patch 4.5 closure criterion이 아니다.

formal D455 validation은 계속 Patch 8에서 수행한다.

---

# 19. Deferred / Out-of-Scope

Patch 4.5 완료는 다음을 해소하지 않는다.

```text
OPEN-002  F1 exact definition
OPEN-003  F2 exact definition
OPEN-004  rank_weights policy for >6 features
OPEN-005  formal experiment exact protocol
OPEN-006  D455 validation exact grid / metric / acceptance criterion
```

또한 다음은 별도 scope다.

```text
full Python dependency/environment lock
general repository-wide artifact integrity framework
remote source long-term archival guarantee
complete adversarial concurrent-filesystem threat model
generic hard-link portability abstraction
Patch 5+ lineage / selection / integrity work
Patch 8 actual D455 formal validation
```

MediaPipe Python package `1.0.1`은 Early Hardware Preflight에서 관찰된 environment provenance이며
Patch 4.5의 hard model artifact lock 자체가 아니다.

---

# 20. Patch 4.5 완료 판단

현재 repository evidence 기준:

```text
[완료]

PROV-004 Design Freeze
mediapipe-model-lock/1.0.0 tracked manifest
exact face artifact lock
exact mesh artifact lock
generation-qualified Pose artifact lock
manifest fail-closed validation
complete SHA-256 verification
existing mismatch HARD FAIL / preservation
no automatic overwrite/redownload/fallback
verified temporary provisioning
destination race re-verification
Patch 3 provenance hash/source/version linkage
--from-csv current-lock/model isolation
historical provenance preservation
models/ runtime Git-ignore policy
Patch 4 frames-schema/1.0.0 regression preservation
33 new Patch 4.5 tests
171 previous tests preserved
204 total tests PASS
independent Claude Opus READ-ONLY audit
PASS WITH MINOR FINDINGS
ACCEPT WITH MINOR NOTES
BLOCKER 0
IMPORTANT 0
```

남은 항목:

```text
[후속 / 별도 scope]

Patch 4.5 Foundation documentation closure commit
Patch 5+ Foundation work
Patch 8 actual D455 formal validation
OPEN-002 ~ OPEN-006 research decisions
formal participant collection
```

따라서 운영상:

```text
Patch 4.5 Design Freeze             = DONE
Patch 4.5 implementation            = DONE
Patch 4.5 software verification     = DONE
Patch 4.5 independent audit         = DONE
Patch 4.5 blocking findings         = NONE
Patch 4.5 Foundation Record         = CREATED
Patch 4.5 documentation closure     = NEXT
Patch 8 hardware validation         = PENDING
formal research collection          = NOT STARTED
```

---

# 21. 관련 Commit

```text
main baseline
d923b23
merge: complete Patch 4 frame schema foundation

Patch 4.5 Design Freeze
6b69255
docs: freeze Patch 4.5 model artifact lock design

Patch 4.5 implementation
aef7f34
feat: implement Patch 4.5 model artifact lock
```

documentation closure commit은 본 Foundation Record와 Research Master closure alignment를
repository에 반영한 뒤 생성한다.

본 문서는 자기 자신이 포함될 미래 Git commit hash를 사전에 확정할 수 없으므로
존재하지 않는 hash를 추정하거나 placeholder를 canonical provenance로 기록하지 않는다.

정확한 documentation closure commit hash는 commit 생성 후
`AIoT_RESEARCH_MASTER.md`의 현재-state / version history에 기록한다.

---

# 22. 현재 문서 상태

```text
contract freeze                 COMPLETE — PROV-004 / 6b69255
implementation                 COMPLETE — aef7f34
software tests                 COMPLETE — 204 PASS
independent audit              COMPLETE — PASS WITH MINOR FINDINGS
BLOCKER / IMPORTANT            NONE
accepted MINOR notes           4
Foundation Record              CREATED
documentation closure          PENDING — NEXT
new D455 run for Patch 4.5     NOT REQUIRED
formal D455 validation         DEFERRED — Patch 8
formal collection              NOT STARTED
```

---

# 23. Source Priority

본 기록은 다음 우선순위를 적용한다.

```text
1. PROV-004 Design Freeze contract
2. commit aef7f34 source / lock manifest / tests
3. reproduced 204-test software verification
4. independent Claude Opus READ-ONLY audit
5. AIoT_RESEARCH_MASTER current-state routing
6. 추정
```

원칙:

```text
PROV-004가 Patch 4.5 frozen design contract의 권위다.

mediapipe_model_lock.json이 현재 허용된 exact model artifact contract의
executable tracked source of truth다.

Git/source/test가 현재 implementation fact의 권위다.

analysis provenance는 실제 실행에서 사용한 artifact를 기록하고,
model lock은 어떤 artifact를 허용하는지 강제한다.

Foundation Record는 구현·검증·audit 이력을 기록하지만
PROV-004 또는 lock manifest를 재정의하지 않는다.

software PASS를 Patch 8 hardware validation 또는 formal research evidence로 확대 해석하지 않는다.

accepted MINOR finding은 BLOCKER/IMPORTANT가 아니며,
별도 decision 없이 Patch 4.5 contract를 재설계하는 근거로 사용하지 않는다.
```

---

# 24. Closure Recommendation

현재 증거 기준 최종 판단:

```text
Patch 4.5 implementation
ACCEPT

software regression
PASS — 204/204

independent audit
PASS WITH MINOR FINDINGS

blocking findings
NONE

recommended next action
Foundation documentation closure
→ Research Master status alignment
→ docs-only closure commit
→ push
→ final branch review
→ main merge
```

Patch 4.5는 software/reproducibility Foundation 관점에서 closure 가능한 상태다.
