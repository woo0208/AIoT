# PATCH_08 — Windows Compatibility Fixes and Post-CAP-007 Technical Audit

- 문서 성격: **History / audit-trace record** — 설계 계약이 아니며 실행 승인 문서가 아니다
- 작성일: 2026-10-15
- 기록 기준 branch: `fix/patch8-opencv-distribution`
- 기록 기준 HEAD: `3873f0d4f2de5e9c4ced72e76a44c429fdb948e4` (2026-10-15 independent READ-ONLY technical audit 시점 working tree clean — 감사 시점 상태이며, 이후 documentation 편집 중의 working tree 상태를 뜻하지 않음)
- Decision Log: `CAP-007` (원문 통합), `CAP-008` (본 문서의 status record)
- 설계 authority (변경 없음): `CAP-005` + `CAP-006` + `docs/foundation/PATCH_08_actual_d455_end_to_end_validation.md`

> 본 문서는 Patch 8 Design Freeze 이후 Windows 호환성 결함 두 건의 수정과 그 독립 READ-ONLY 기술 감사를 재현 가능한 수준으로 기록한다.
> CAP-005 grid / anchors / thresholds / windows / predicates / retry rules / protocol identity를 정의하거나 변경하지 않는다.
> 본 문서의 어떤 내용도 Patch 8 execution authorization, execution registration, formal D455 measurement, 또는 measurement-quality PASS를 의미하지 않는다.

---

## 0. Evidence 구분

본 문서의 모든 사실은 다음 중 하나로 분류한다.

| 표기 | 의미 |
|---|---|
| `[GIT]` | 본 documentation sync에서 read-only Git 명령과 파일 읽기로 확인 |
| `[USER]` | 사용자가 제공한 실행 로그·관측. 본 documentation sync에서 재실행·재측정하지 않음 |
| `[AUDIT]` | 2026-10-15 독립 READ-ONLY 기술 감사 보고서 (Claude Code session; repository artifact 아님). 감사 자체도 test를 재실행하지 않음 |

Agreement between AI agents는 experimental evidence가 아니다.
Synthetic / mock test PASS는 actual D455 hardware 동작의 증거가 아니다.

---

## 1. Commit lineage `[GIT]`

```text
b2e090f  docs: finalize Patch 7 post-merge status                (Patch 7 main baseline; CAP-005 Design Freeze baseline)
d47a9ed  docs: freeze Patch 8 D455 validation design             (CAP-005 Design Freeze)
576f945  docs: clarify Patch 8 forward slot sequences            (CAP-006)
b71a5ac  feat: implement Patch 8 D455 validation tooling
f5d3cf5  fix: close Patch 8 pre-execution fail-open paths
dc2c5c8  fix: enforce Patch 8 environment identity               (CAP-007 audited implementation HEAD)
60026cf  fix(patch8): normalize provenance paths on Windows      (Windows fix 1)
3873f0d  fix(patch8): support OpenCV distribution identity       (Windows fix 2; current HEAD)
```

- 위 chain은 선형이며 merge commit이 없다.
- 이 로컬 저장소에는 `main` ref가 없다. 따라서 Patch 8 commit의 `main` 통합 여부는 로컬에서 확인할 수 없다 (**UNVERIFIED — local main ref unavailable**).
- `CAP-007` 원 commit `0d281d6`은 `dc2c5c8`의 자식이며 branch `feat/rf-loso-prediction-audit`에만 있다 (§9 참조).

---

## 2. Patch 8 상태 구분 (2026-10-15)

| 상태 | 판정 | 근거 |
|---|---|---|
| Design Frozen | YES | `CAP-005` (`d47a9ed`), `CAP-006` (`576f945`) |
| Implemented | YES | `b71a5ac` → `f5d3cf5` → `dc2c5c8` |
| Code Audited | YES | `dc2c5c8`: BLOCKER 0 / IMPORTANT 0 (`CAP-007`) |
| Windows compatibility fixes | YES | `60026cf`, `3873f0d` |
| Windows-fix technical audit | PASS | `dc2c5c8..3873f0d`: BLOCKER 0 / IMPORTANT 0 / MINOR 7 / DOC_DRIFT 5 (`CAP-008`) |
| Windows Compatibility Verified | YES (제한적) | software test와 한 대의 Windows PC에서의 environment identity (`[USER]`). headless OpenCV 변형 부재는 미확인 (F-2) |
| Execution Authorized | **NO** | `CAP-007` execution deferral 유지. Registry / `execution_id` 없음 |
| Hardware Measurement Completed | **NO** | formal Patch 8 D455 execution 미실시 |
| Measurement Quality Passed | **NOT DETERMINED** | — |

`Code Audited`는 `Execution Authorized`를 의미하지 않는다.
`3873f0d`는 execution code **candidate**일 뿐이며 Foundation §15 / §20의 `audited_implementation_commit`으로 pin되지 않았다.

---

## 3. 관측된 Windows 환경 `[USER]`

```text
OS                      Windows 11
Python                  3.12.10
Camera                  Intel RealSense D455 (USB 3.2로 인식)
pyrealsense2            2.59.1.11053
mediapipe               1.0.1
numpy                   2.5.4
opencv-contrib-python   5.0.0.93
opencv-python           미설치
```

별도의 **비정식 점검**에서 RGB·Depth frame 수신과 MediaPipe landmark viewer 실행이 확인됐다.

이 점검의 역할은 다음으로 제한한다.

```text
Windows 환경 / 장치 인식 sanity check            = YES
Patch 8 formal measurement (static / forward / E2E) = 아님
Patch 8 measurement-quality evidence              = 아님
threshold / protocol 결정 근거                      = 아님
formal research data                              = 아님
```

이 점검이 formal slot / round / ledger / `execution_id`를 사용하지 않았다는 점은 사용자 보고(정식 실측 미실시)에 근거하며 본 sync에서 독립 검증하지 않았다.
본 worktree에는 `validation/` 디렉터리(ignored 포함)와 `docs/research/PATCH_08_EXECUTION_REGISTRY.md`가 없음을 `[GIT]` 확인했다.

---

## 4. 결함 1 — Windows provenance 경로 (`60026cf`)

### 4.1 증상

Windows에서 analysis를 실행하면 closure integrity check가 `SCHEMA_INVALID`를 보고했다 `[USER]`.

### 4.2 원인 `[GIT]` `[AUDIT]`

- `analyze_d455.py`는 compatibility sidecar(`<compatibility_path>.provenance.json`)의 `analysis_manifest` 값을 `os.path.relpath(manifest_path, compatibility_dir)`로 만든다.
- Windows에서 `os.path.relpath()`는 backslash(`\`) 경로를 반환한다.
- Provenance를 다시 읽는 쪽(`selection_manifest.py` artifact path 해석)은 POSIX 형태의 repository-relative path를 요구하며 `\`를 거부한다.

### 4.3 수정 `[GIT]`

`analyze_d455.py:1474` 한 줄:

```text
os.path.relpath(manifest_path, compatibility_dir)
→ os.path.relpath(manifest_path, compatibility_dir).replace(os.sep, "/")
```

- POSIX에서는 `os.sep == "/"`이므로 동작이 바뀌지 않는다.
- Hash 계산, manifest / ledger / integrity 규칙, 절대경로 field는 변경되지 않았다 `[AUDIT]` (A1–A7 PASS).

### 4.4 검증 `[USER]`

```text
기존 Patch 8 regression tests   151 PASS
integrity check                  PASS
```

정적 test 정의 수 `[GIT]`: `test_patch8_ledger.py` 38 + `test_patch8_metrics.py` 44 + `test_patch8_orchestration.py` 44 + `test_patch8_prelock.py` 25 = 151 (실행이 아닌 정의 수 일치 확인).

### 4.5 남은 한계

- 이 branch에는 Windows 경로 수정을 **직접** 검증하는 test가 없다 (F-6).
- 같은 줄을 다른 branch가 다른 방식으로 수정했다 (F-7, §9).

---

## 5. 결함 2 — OpenCV distribution identity (`3873f0d`)

### 5.1 증상

Actual Windows capture environment identity가 실패했다 `[USER]`.

### 5.2 원인

- 사용자 보고에 따르면 MediaPipe는 `opencv-contrib-python`을 의존성으로 요구한다 `[USER]`.
- 관측 환경에는 `opencv-contrib-python`만 설치되어 있었다 `[USER]`.
- `dc2c5c8`의 environment identity는 `REQUIRED_PACKAGE_KEYS`에 `opencv-python`을 포함해 그 version만 필수로 확인했다 `[GIT]`.

### 5.3 수정 `[GIT]`

| 위치 | 변경 |
|---|---|
| `patch8_prelock.py:43-44` | `OPENCV_DISTRIBUTIONS = ("opencv-python", "opencv-contrib-python")`; `ENVIRONMENT_PACKAGES`에 두 배포판 포함 |
| `patch8_prelock.py:171-189` | `package_versions()`: 미설치(`PackageNotFoundError`) → `null`, 그 밖의 metadata 조회 예외 → `"error"` sentinel. 선택적 `on_error` callback |
| `patch8_ledger.py:72-74` | `REQUIRED_PACKAGE_KEYS = (mediapipe, pyrealsense2, numpy)`; `OPENCV_DISTRIBUTION_KEYS`; `PACKAGE_IDENTITY_KEYS` |
| `patch8_ledger.py:322-328` | `_normalized_packages()`: 필수 3개 유효 + OpenCV 두 key 중 non-null이 정확히 1개이고 그 값이 유효한 identity text일 때만 성립 |
| `analyze_d455.py:60` | `import patch8_prelock` |
| `analyze_d455.py:173-190` | analysis environment도 `patch8_prelock.package_versions()` 사용. 기대된 OpenCV 대체 배포판 부재는 `provenance_unknown_reasons`에 기록하지 않음 |
| `test_patch8_opencv_contract.py` (신규) | synthetic test 10개 |

Identity 규칙 요약:

```text
opencv-python만 유효                    → PASS (contrib = null로 정규화)
opencv-contrib-python만 유효            → PASS (opencv-python = null로 정규화)
둘 다 없음                             → FAIL (fail-closed)
둘 다 있음                             → FAIL (fail-closed)
"error" 또는 무효 text                  → FAIL (fail-closed)
mediapipe / pyrealsense2 / numpy 누락   → FAIL
같은 PC에서 capture ↔ analysis 배포판 또는 version 차이 → FAIL ("same-host analysis environment differs")
```

### 5.4 검증 `[USER]`

```text
신규 OpenCV contract tests              10 PASS
기존 Patch 8 regression tests          151 PASS
analysis provenance tests               52 PASS
integrity check                         PASS
actual Windows capture identity         PASS
actual Windows analysis identity        PASS
actual same-PC environment match        PASS
```

정적 test 정의 수 `[GIT]`: `test_patch8_opencv_contract.py` 10, `test_analysis_provenance.py` 52, Patch 8 regression 151 — 사용자 보고 수치와 일치 (실행 여부는 재현하지 않음).

### 5.5 CAP-005 §9와의 관계 `[AUDIT]`

- Foundation §9는 기록 대상을 **"OpenCV version"**으로만 명시하며 특정 PyPI 배포판 이름을 지정하지 않는다 (`docs/foundation/PATCH_08_actual_d455_end_to_end_validation.md` §9).
- 다른 host 간 동일해야 하는 것은 pyrealsense2 / RealSense SDK version이며, canonical provenance와 차이가 있으면 execution을 계속하지 않는다 (§9).
- `opencv-python` 필수 요구는 `dc2c5c8` 구현 단계의 선택이었고 frozen 값이 아니었다.
- 감사 판단: 이번 수정은 §9를 충족하는 fail-closed compatibility fix이며 `Supersedes: CAP-005`가 필요하지 않다.
- 이 판단은 audit evidence이며 연구 책임자의 clarification 결정이 아니다. 별도 `Clarifies` entry 기록 여부는 미결정이다 (§8).

---

## 6. 독립 READ-ONLY 기술 감사 `[AUDIT]`

| 항목 | 내용 |
|---|---|
| 감사 대상 | `dc2c5c8..3873f0d` (`60026cf`, `3873f0d`) |
| 변경 파일 | `analyze_d455.py`, `patch8_ledger.py`, `patch8_prelock.py`, `test_patch8_opencv_contract.py` (신규) — 예상 범위와 일치 |
| 감사 방법 | `git show / diff / log / grep`과 파일 읽기만 사용. test, Python import, camera, package 설치 실행 없음 |
| 결과 | **기술 감사 PASS — BLOCKER 0 / IMPORTANT 0 / MINOR 7 / DOC_DRIFT 5** |
| 감사 범위 | Windows 호환성 수정 code, CAP-005 §9 준수, capture·analysis 환경 동일성, provenance·integrity 영향, test 범위, 문서 불일치 |
| 변경 없음 확인 | D455 capture 설정·RGB/Depth 정렬, MediaPipe model / hash / `mediapipe_model_lock.json`, F0/F1/F2 feature·분류 code·`rf_experiment.py`, `patch8_protocol.py`·`patch8_metrics.py`의 거리·반복·threshold, ledger hash chain·serialization, `integrity_check.py`, `patch8_validation.py` |

감사의 제한:

- 감사에서 test를 재실행하지 않았다. Test PASS는 사용자 보고 evidence다.
- `dc2c5c8` 이전부터 있던 Patch 8 전체(validation, metrics, report, static capture)를 처음부터 재감사하지 않았다. 그 부분은 `CAP-007`이 기록한 `dc2c5c8` audit 결과에 의존한다.
- 공식 연구 실행 승인과는 별개다 (감사 결론: Execution Authorization **NOT APPROVED**).
- 실제 Windows 패키지 상태와 D455 measurement quality는 감사에서 관찰·검증하지 않았다.

감사가 기록한 실행 거버넌스 조건:

- `CAP-007`이 고정한 audited implementation commit은 `dc2c5c8`이고 현재 code는 `3873f0d`다.
- Foundation §12 (lifecycle 5–6단계), §15 (pre-registration의 audited implementation commit), §20 (execution code pinning)에 따라, 새 commit을 실행 대상으로 쓰려면 execution authorization / registration에서 audited commit을 명시적으로 pin해야 한다.
- 이것은 code 결함이 아니라 execution governance 사항이다.

---

## 7. MINOR 7건 추적

MINOR는 실행 차단 사유가 아니지만 **해결된 것이 아니다**. 아래 항목은 모두 OPEN 상태로 추적한다.

| ID | 위치 `[GIT]` 확인 | 내용 `[AUDIT]` | 실행 차단 | 추적 상태 / 필요 조치 |
|---|---|---|---|---|
| F-1 | `analyze_d455.py:179-189` | 두 OpenCV 배포판이 동시에 설치되어 있으면 `errors`가 비어 analysis manifest `provenance_unknown_reasons`에 아무 사유도 기록되지 않는다. 두 version은 기록되지만 실제로 load된 `cv2`가 어느 쪽인지 알 수 없다. `test_analysis_provenance.py:61-62` fixture가 모든 package에 version을 반환하므로 이 상태가 test에서 항상 재현되지만 test는 통과한다 | 아니오 — formal 경로는 `patch8_validation.py:635-640`이 child launch(`:646`) 전에 `patch8_ledger` identity 검사로 거부 | OPEN — 동시 설치 진단 기록의 한계. 수정 여부 미결정 |
| F-2 | `patch8_prelock.py:43,171-189`; `patch8_ledger.py:73,325-326` | OpenCV 식별이 두 배포판의 metadata에만 의존한다. `opencv-python-headless`, `opencv-contrib-python-headless`를 확인하지 않고 `cv2.__version__`도 기록하지 않는다. 예: contrib + headless 동시 설치 시 contrib 하나만 보여 통과하며, 기록된 OpenCV version이 실제 load된 `cv2`와 다를 수 있다. Version field가 빠진 dist-info는 미설치와 구분되지 않을 수 있다 (stdlib 동작 기반 추론; 실행 확인 안 함) | 아니오 | OPEN — headless 감지 범위. formal execution 전 각 PC에서 OpenCV 계열 배포판이 정확히 하나인지 read-only 확인 필요 (§10) |
| F-3 | `analyze_d455.py:175` → `patch8_prelock.py:185-186` | `PackageNotFoundError`가 아닌 일반 metadata 조회 실패가 `null`이 아니라 `"error"` 문자열로 저장된다. mediapipe, numpy 등 analysis provenance의 모든 package에 적용된다. Patch 3 §27은 "lookup 실패 시 `null` + unknown reason"으로 기록한다. 사유는 계속 기록되며 fail-open은 아니다. 이 경로를 검증하는 test가 없다 | 아니오 | OPEN — 표현 방식 결정 필요 (문서화 vs analysis 측 `null` 복귀). §8 참조 |
| F-4 | `analyze_d455.py:60` | Patch 3 analysis core가 Patch 8 module(`patch8_prelock` → `patch8_ledger` → `patch8_protocol`)에 의존하게 됐다. `integrity_check.py`, `rf_experiment.py`도 이를 간접 import한다. 순환 import / import 시 부작용은 없다. `analyze_script_sha256`은 환경 수집 logic 전체를 포함하지 않는다 (`git_commit` / `git_dirty`로는 추적) | 아니오 | OPEN — module 결합도. 분리 여부 미결정 |
| F-5 | `test_patch8_opencv_contract.py` | 오류 상태 test 부족: `"error"` sentinel, analysis 측 오류 사유 기록, ledger 재생(`_apply_session` / `_apply_analysis`) 경로의 contrib 단독 환경, 다른 PC에서 OpenCV가 다른 경우가 test되지 않았다. 기존 orchestration / ledger fixture는 `opencv-python` 경로만 사용한다 | 아니오 | OPEN — T1–T9 후보 (§7.1) |
| F-6 | `analyze_d455.py:1474` | 이 branch에는 Windows 경로 수정을 직접 검증하는 test가 없다. `test_patch8_orchestration.py:997-998`의 integrity 검사로 간접 검출만 가능하며, 이는 Windows에서 실행할 때만 의미가 있다 | 아니오 | OPEN — T8 후보 |
| F-7 | `analyze_d455.py:1474` | 같은 줄을 `feat/rf-loso-prediction-audit`의 `e8630b6`이 `Path(...).relative_to(...).as_posix()`로 다르게 수정하고 test assertion도 추가했다. 두 branch 병합 시 충돌이 예상된다. `CAP-007` 원 commit `0d281d6`도 그 branch에만 있다 | 아니오 | OPEN — 병합 전 처리 방식 결정 필요 (§9) |

### 7.1 Synthetic test 보강 후보 T1–T9 `[AUDIT]`

권장 사항이며 아직 추가되지 않았다. 추가하면 code(test)가 바뀌므로 별도 patch와 재감사가 필요하다.

| ID | 사례 | 예상 결과 |
|---|---|---|
| T1 | `package_versions`에서 `opencv-python` 조회 시 `OSError` | 값 `"error"`, `on_error` 호출 |
| T2 | packages가 `opencv_python="error"`만 있는 경우 / `"error"` + contrib 유효 | capture / analysis identity 모두 `None` |
| T3 | OpenCV 값이 `""` 또는 정수 `5` | `None` |
| T4 | `analysis_environment`: 둘 다 미설치 / 하나 유효 + 다른 하나 일반 예외 | 두 key 사유 모두 기록 / 오류 key만 사유 + `"error"` |
| T5 | `analysis_environment`: 둘 다 설치 | 현재 동작(사유 없음)을 고정하거나 수정 근거로 사용 |
| T6 | `LedgerHarness`로 contrib 단독 `session_start` 후 같은 PC analysis invocation | 허용. 다음 session이 `opencv-python` 단독이면 `environment_matches=False` → "environment differs" |
| T7 | 다른 PC analysis가 다른 OpenCV 배포판으로 시작한 뒤 다시 바뀜 | 첫 실행은 허용(analysis baseline 고정), 다음은 "differs from execution analysis baseline" |
| T8 | `link["analysis_manifest"] == <rid>/<ar>/analysis_manifest.json`이고 `"\\"` 미포함 | PASS (`e8630b6`의 assertion과 같은 내용) |
| T9 | orchestration World의 probe 환경을 contrib 단독으로 바꿔 전체 synthetic 실행 | 실행 PASS, integrity ERROR 0 |

---

## 8. DOC_DRIFT 5건과 본 sync의 처리

| ID | 위치 (감사 시점) | 불일치 `[AUDIT]` | 본 sync 처리 |
|---|---|---|---|
| D-1 | `docs/research/AIoT_RESEARCH_MASTER.md` (§0, §1.1, §1.2, Patch 8 절) | Patch 8 implementation / audit가 PENDING으로 표시됨 | **해소** — Master `v1.13`에서 Patch 8 상태·교차 참조 갱신 |
| D-2 | `AGENTS.md:15`, `CLAUDE.md:48, 353-356, 545` | 같은 오래된 상태 표시 | **해소** — 해당 Patch 8 상태 문장만 최소 수정 |
| D-3 | `docs/research/RESEARCH_DECISION_LOG.md` | 이 branch에 `CAP-007`이 없음. CAP-007 version row 누락. `60026cf` / `3873f0d`와 감사 기록 없음 | **해소** — `CAP-007`을 `0d281d6`과 동일 text로 통합, `CAP-008` append, Version Log `v1.13` |
| D-4 | `docs/foundation/PATCH_03_analysis_provenance.md` §27 | §27은 `opencv-python` 하나와 "실패 시 `null`"만 기록. 현재 code는 두 배포판 key와 `"error"` 값을 기록 (F-3) | **기록만** — §27은 역사 기록이므로 본문을 수정하지 않는다. 차이는 본 문서 §8.1과 `CAP-008`에서 연결 |
| D-5 | `analyze_d455.py:18`, `capture_d455.py:4` | 설치 안내가 `pip install ... opencv-python ...`. MediaPipe가 contrib을 함께 설치하는 환경에서 이 안내를 따르면 두 배포판이 동시 설치되어 ledger identity가 거부한다 (fail-closed) | **OPEN** — 본 작업은 Markdown 전용이므로 Python docstring을 수정하지 않았다. 별도 후속 작업. 설치 주의사항은 §10 |

### 8.1 Patch 3 §27과 현재 구현의 역사적 구분

```text
Patch 3 §27 (역사 기록, [GIT-VERIFIED] 당시)
  기록 대상     Python, OS, architecture, mediapipe, pyrealsense2, opencv-python, numpy, matplotlib
  조회 실패     null + unknown reason

현재 구현 (3873f0d, analyze_d455.analysis_environment)
  기록 대상     mediapipe, pyrealsense2, opencv-python, opencv-contrib-python, numpy, matplotlib (+ Python / OS 등)
  미설치        null; 기대된 OpenCV 대체 배포판 부재는 unknown reason에 기록하지 않음
  기타 조회 실패 "error" + unknown reason
```

`RESEARCH_DATA_SCHEMA.md` §E.2 `environment`는 "OpenCV" 버전으로만 표기하고 null 규칙을 명시하지 않으므로 schema 문구와 직접 충돌하지 않는다 `[AUDIT]`.
현재 저장 형태(두 distribution key, `"error"` sentinel)는 구현 사실이며 schema contract로 확정되지 않았다. 이를 계약화할지, analysis 측을 `null`로 되돌릴지는 미결정이다 (F-3).

### 8.2 본 sync에서 추가로 발견해 처리한 drift

| 위치 | 내용 | 처리 |
|---|---|---|
| `RESEARCH_DATA_SCHEMA.md` 상단 status 문장(현재형) 및 §0 authority overlay §L~N 해석 | Patch 8 "implementation / hardware execution pending" 현재형 표현 | 2026-10-15 status-sync amendment bullet 추가 및 현재형 문장 2곳 최소 갱신. Schema field / version 변경 없음 |
| `RESEARCH_DATA_SCHEMA.md` 본문 내 2026-10-07 dated note | "구현 pending" 표현 | 날짜가 명시된 역사적 status note이므로 수정하지 않음 |
| `docs/foundation/PATCH_08_actual_d455_end_to_end_validation.md` 문서 header status lines | "IMPLEMENTATION PENDING" 등 Design Freeze 시점 상태 | Design Freeze 계약 문서이므로 수정하지 않음. 현재 상태는 `CAP-007` / `CAP-008` / Master가 authority |

---

## 9. Branch 관계와 병합 주의사항 `[GIT]`

```text
                         ┌─ 60026cf ─ 3873f0d                       fix/patch8-opencv-distribution (본 branch)
                         │  (60026cf = fix/patch8-windows-provenance)
dc2c5c8 (merge-base) ────┤
                         └─ 0d281d6 (CAP-007) ─ … ─ e8630b6 ─ … ─ d8b67d9 (FEAT-009) ─ … ─ 6fd01b2
                                                                  feat/rf-loso-prediction-audit
```

- `feat/rf-loso-prediction-audit`과 본 branch의 merge-base는 `dc2c5c8`이다.
- 그 branch에는 `CAP-007` 원 commit `0d281d6`, Windows 경로를 다른 방식으로 수정한 `e8630b6`, F1 `FEAT-009` (Decision Log / Master `v1.12`, commit `d8b67d9`)와 이후 F0/F1·viewer 연구 산출물이 있다. 본 branch에는 포함되지 않는다.
- 본 sync는 그 branch의 연구 상태를 반영·평가·삭제하지 않았고, `e8630b6` 구현을 현재 code로 대체하거나 반대로 덮어쓰지 않았다. 자동 병합하지 않았다.

예상 충돌 (legacy `git merge-tree dc2c5c8 3873f0d feat/rf-loso-prediction-audit`, object 쓰기 없는 read-only 예측):

| 파일 | 예상 | 비고 |
|---|---|---|
| `analyze_d455.py:1474` | **텍스트 충돌** | `60026cf`: `os.path.relpath(...).replace(os.sep, "/")` vs `e8630b6`: `Path(manifest_path).relative_to(compatibility_dir).as_posix()` (+ `from pathlib import Path`). 두 식의 동작 동등성은 본 sync에서 검증하지 않았다. `relative_to`는 하위 경로가 아니면 `ValueError`, `relpath`는 `..` 경로를 만든다 |
| `docs/research/RESEARCH_DECISION_LOG.md` | 본 sync 이후 충돌 예상 | header 문서 버전, Version Log의 `v1.12`/`v1.13` row 위치, 파일 끝 append(`CAP-007` 다음의 `FEAT-009` vs `CAP-008`). `CAP-007` 자체는 양쪽 text가 동일하다 |
| `docs/research/AIoT_RESEARCH_MASTER.md` | 본 sync 이후 충돌 예상 | header 문서 버전, Version Log `v1.12`/`v1.13` row |

Version 번호 처리: `v1.12`는 이미 `feat/rf-loso-prediction-audit`의 `FEAT-009` 동기화가 Decision Log와 Master 모두에서 사용한다. 번호 충돌을 피하기 위해 본 branch는 `v1.12`를 재사용하지 않고 `v1.13`을 사용했다. 향후 통합 시 두 row를 모두 보존하면 `v1.12` (2026-10-11) → `v1.13` (2026-10-15) 순서가 날짜와 일치한다.

통합은 별도 작업이며 다음을 사전에 결정해야 한다:

1. `analyze_d455.py:1474` 경로 정규화 방식 (`60026cf` vs `e8630b6`)과 test(T8) 포함 여부
2. Decision Log / Master의 append 순서와 header 버전 정리
3. 통합 후 code가 바뀌면 그 commit에 대한 재검증·재감사 필요 여부 (Foundation §20 execution code pinning과 연결)

---

## 10. OpenCV 설치 주의사항

관측된 환경에서는 MediaPipe 설치가 `opencv-contrib-python`을 함께 설치했다 `[USER]`.
`analyze_d455.py:18` / `capture_d455.py:4`의 설치 안내(`pip install ... opencv-python ...`)를 그대로 따르면 OpenCV 배포판이 두 개 설치될 수 있고, 그 경우 Patch 8 environment identity는 fail-closed로 거부한다 (D-5).

```text
OpenCV 계열 배포판(opencv-python, opencv-contrib-python,
opencv-python-headless, opencv-contrib-python-headless)은
한 환경에 정확히 하나만 설치한다.
MediaPipe가 이미 opencv-contrib-python을 설치한 환경에 opencv-python을 추가 설치하지 않는다.
```

Formal execution authorization 전, 각 capture / analysis PC에서 다음과 같이 **읽기 전용**으로 확인한다 (F-2; headless 변형은 code가 감지하지 않으므로 사람이 확인).

```text
Windows PowerShell:  python -m pip list | Select-String -Pattern opencv
POSIX shell:         python -m pip list | grep -i opencv
```

결과가 정확히 한 줄이어야 한다. 이 확인 결과는 formal execution registration 시 environment evidence와 함께 기록한다.
본 문서 작업에서는 package 설치·제거·업데이트를 수행하지 않았다.

---

## 11. 후속 작업 후보 (수행하지 않음)

| 항목 | 성격 | 필요 조건 |
|---|---|---|
| `analyze_d455.py:18`, `capture_d455.py:4` 설치 안내 수정 (D-5) | code(docstring) 변경 | 별도 patch |
| T1–T9 synthetic test 보강 (F-5, F-6) | test 변경 | 별도 patch + 재감사 |
| F-1 / F-2 / F-3 / F-4 처리 방향 | 구현·provenance 표현 결정 | 연구 책임자 결정 후 별도 patch |
| CAP-005 §9 implementation identity 형태의 `Clarifies` 기록 여부 | 연구 거버넌스 결정 | 연구 책임자 결정 |
| `feat/rf-loso-prediction-audit` 및 `main` 통합 (F-7) | branch 통합 | 별도 작업, §9 사전 결정 |
| Execution authorization / registration, audited commit pin | 실행 거버넌스 | `CAP-007` deferral 해제 결정 + 새 append-only entry + registry |
| Formal Patch 8 D455 execution | hardware 실측 | 위 authorization 이후에만 |

---

## 12. 본 문서 작업에서 하지 않은 것

- Python / test / model / data / manifest / ledger 변경 없음
- Execution registry, `execution_id`, `validation/` runtime artifact 생성 없음
- Actual D455 실행, 데이터 수집, package 설치·제거·업데이트 없음
- Git merge / cherry-pick / rebase / reset / checkout / switch / commit / push 없음
- `CAP-005`, `CAP-006`, `CAP-007` 본문, Foundation Design Freeze 문서, Patch 3 Foundation 문서 수정 없음
- Test 재실행 없음 — 모든 test PASS는 사용자 제공 evidence
