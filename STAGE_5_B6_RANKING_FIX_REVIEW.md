# Stage 5 B6 — 순위 안정성 수정안 검토

작성: 2026-11-05. **SYNTHETIC STRUCTURAL ONLY / PROPOSED / PENDING_USER_APPROVAL**.
실제 연구 결과의 오류나 특정 모델의 우수성을 주장하지 않는다. B6는 아직 최종 RESOLVED가 아니다.

## 1. 시작 Git 상태

HEAD `ce3bfba`, branch `feat/aiot-stage5e-d455-readiness`로 요청과 일치했다. 최근 이력은 `ce3bfba`, `800faa3`, `ed22f0f`다.

```text
 M STAGE_5E_C6_FRAME_REUSE_REVIEW.md
?? STAGE_5E_BUNDLE_D.md
?? STAGE_6_EXECUTION_HANDOFF.md
?? artifacts/
```

`git status --short`, `git log -3 --oneline`, `git diff`, `git ls-files`의 원문·stderr·returncode 및 시작 파일별 SHA-256은 [start_state.json](analysis/STAGE_5_B6_REVIEW_20261105_573d17a8/start_state.json)에 저장했다. 시작 diff는 기존 C6 보고서 §15 추가뿐이다. Git의 global ignore/cache 읽기 permission 경고도 기록했으며 이를 이유로 설정/파일을 수정하지 않았다.

C6의 실제 추적 경로는 `STAGE_5E_C6_FRAME_REUSE_REVIEW.md`이고 정상적으로 읽혔다. 이동/경로 수정 없음. 기존 세 문서의 시작 SHA-256:

| 파일 | SHA-256 |
|---|---|
| C6 보고서 | `60553acb6ecbe73876a797539111effc58552092e1e50932459e5e9385ce1954` |
| 묶음 D | `1afc1be7b5c06382735cfd5736c8341d4c98d555d4955e84ea981776b89dc29e` |
| Stage 6 인계 | `a95eb9dccb0a83c9842a890ffc2cc81de743665e824ca3db827ff2b7939e73fb` |

기존 변경·미추적 문서는 그대로 보존했다. `artifacts/`의 내용은 접근·수정·삭제·스테이징하지 않았다. reset/clean/commit/push 없음.

## 2. 기존 구현·호출·오류 계약

- 구현: `formal6_evaluation.py:248`의 `rank_candidates(scores)`.
- 운영 호출: 같은 파일 `_evaluate_candidates`, line 343. 후보별 `c["pooled"]`를 전달한다. `evaluate_development`가 이 경로를 호출한다. 기준선 비교 복사본은 `rank=False`여서 선정하지 않는다.
- 직접 기존 테스트: `test_formal6_evaluation.py:215/218/220/222`. `test_formal6_synthetic.py:68`은 외부 재선정 금지 mock이다.
- 기존 별도 검토 호출: `analysis/READ_ONLY_STAGE_5E_BUNDLE_D_20261105/review.py:193`. 이 파일도 변경하지 않았다.
- `formal6_synthetic.py`는 evaluator를 통해 간접 호출한다. 실제·합성 개발 평가 후 recommendation 소비자는 기존 경로를 유지한다.

전체 소스 검색은 `artifacts/`, `.git`, venv/cache를 제외하고 ignored analysis의 Python/Markdown까지 포함했다. 신규 제안 함수는 기존 production 파일 어디에서도 import/call하지 않는다.

입력은 후보 ID→요약 점수 mapping이다. 정확히 다섯 ID, `status="COMPLETE"`, 길이6의 list/tuple `mean_recall`, finite인 `mean_macro_f1`, `mean_accuracy`, Recall P0/P1/P5를 요구한다. 성공은 `status="DEVELOPMENT_RECOMMENDATION_ONLY"`, `ranking=tuple[5 IDs]`, `recommendation=ranking[0]`, `reasons=()`다. 최종 모델 artifact를 만들지 않는다.

예상 차단은 `BLOCKED / ranking=() / recommendation=None`와 다음 사유다: `all_five_approved_candidates_required`, `six_class_recall_required:<ID>`, `incomplete_candidate_scores:<ID>`. 원본은 비mapping/문자열 점수/비mapping 후보 값에 incidental TypeError/AttributeError를 낼 수 있다. 이 사실을 원본 변경 사유로 확장하지 않았다. 제안 API만 malformed 입력을 BLOCKED로 방어한다. 승인용 activation diff는 **원본의 선행 검증을 그대로 두므로 기존 오류 계약도 보존**한다.

dict는 중복 key를 보존하지 못한다. 제안 API는 중복 pair sequence를 dict로 변환하지 않고 거부한다. 호출자가 이미 dict로 소실시킨 중복을 검출했다고 주장하지 않는다. 기존처럼 Recall2/3/4의 별도 finite 검증은 추가하지 않았으며, 완전6-class 여부는 upstream COMPLETE/클래스 차단 계약을 유지한다.

## 3. 승인된 EXP-006/007 규칙과 코드 대조

확인 문서: `AGENTS.md`, Master §12/26/27/28, Decision Log EXP-005/006/007, `docs/research/STAGE_5D8_FORMAL_EVALUATION_FREEZE.md` §7/9 및 후속 절, `RESEARCH_DATA_SCHEMA.md`의 authority/frozen 계약, 묶음 D와 Stage 6 인계. 과거 본문의 미확정 서술은 후속 확정을 따라 읽고 소급 수정하지 않았다.

| 고정 순서/별칭 | 공식 후보 ID | 특징 수 |
|---|---|---:|
| 1 / A | RF_M0_H9 | 9 |
| 2 / B | RF_M1_H9 | 9 |
| 3 / C | RF_M2_H9 | 9 |
| 4 / D | RF_M0_H9-F9 | 8 |
| 5 / E | LR_B0_H9-F9 | 8 |

모델 선정 우선순위는 Macro-F1→P0 Recall→P1 Recall→P5 Recall→Accuracy→적은 특징 수→위 고정 순서다. 표시 반올림 전 원점수의 절댓값 차이 **<=1e-12**를 동점으로 한다. 반올림/quantization/새 지표를 사용하지 않는다. F0+RF M0, F_cal+RF M0, H5+RF M0는 EXP-007 비교 기준선으로만 유지한다.

실제 support0 Recall=N/A, INCOMPLETE, 공식6 Macro-F1 미산출, 별도 fixed6 zero_division0 진단점수다. 개발2인 LOSO의 필수 클래스가 부족하면 fit 전에 선정 BLOCKED; 참가자/fold/클래스 사후 삭제나 외부4인 보충 없음.

RF는 seed0/1/2 각각의 두 heldout fold 예측을 원래 sample 위치의 OOF 배열로 합쳐 pooled scope 지표를 구하고 `_summary`에서 seed별 지표의 산술평균을 쓴다. fold F1 평균이나 seed-majority prediction 지표로 바꾸지 않는다. LR B0는 각 LOSO fold의 train-only StandardScaler와 고정 deterministic 모델로 OOF를 구성하고 **seed0 결과 한 개**로 요약한다. 두 fold fit을 독립 seed3회라고 세지 않는다. C1/L2(l1_ratio0)/lbfgs/tol1e-4/max_iter10000/interceptTrue/class_weightNone 및 B0 상대가중1을 유지한다.

문서와 구현의 핵심 차이는 **전역 연쇄 동점 집합의 정의가 EXP-006에 명시되지 않았는데 코드가 pairwise comparator를 선택했다는 점**이다. scalar 허용오차와 지표 순서는 일치하지만 comparator의 추이성은 보장되지 않는다. 최고값 기준 집합은 아직 승인된 해석이 아니다. RF/LR 요약 방식은 위 문서 의미와 일치하며 변경하지 않았다.

## 4. 독립 합성 재현 결과

입력 A/B/C Macro-F1은 각각 `0.5`, `0.5+0.75e-12`, `0.5+1.50e-12`; P0 Recall은 `0.9/0.8/0.7`이다. P1/P5도 각각 같은 Recall값, Accuracy는 모두0.1로 두었다. D/E는 모든 점수0.1이다. 이는 API 반례용 임의 점수이며 실현 가능한58구간 CM이라고 주장하지 않는다.

원본 `cmp_to_key`를 잠시 감싸 **실제 comparator closure를 포착**했다. 비교 산식을 재작성한 복제품으로 원본을 대신하지 않았다.

| 비교 | 실제 Macro-F1 절대 차 | 원본 비교값 | 우선 후보 |
|---|---:|---:|---|
| A,B | 7.499556531342932e-13 | -1 | A (Recall) |
| B,C | 7.500666754367558e-13 | -1 | B (Recall) |
| A,C | 1.500022328571049e-12 | +1 | C (Macro-F1) |

실제 원본 반환은 `(A,B,C,D,E)`, recommendation A다. 제안 반환은 `(B,C,A,D,E)`, recommendation B다. 상세 float hex, 양방향6비교, 120개 입력/결과를 [최종 reproduction.json](analysis/STAGE_5_B6_REVIEW_20261105_573d17a8/final_no_inference/reproduction.json)에 보관했다.

실제 API에 동일 점수를 dict 입력 순서120개로 전달하면 **원본도 A 120/120**이다. 원본이 dict 순서와 무관한 고정 `ids`를 sort하기 때문이다. 같은 입력100회 반복도 원본/제안 각각 동일하다. 원본 API의 입력 순서 의존성을 관측했다고 쓰지 않는다.

별도 진단에서 포착한 comparator로 **정렬할 ID 배열 자체**의120개 순열을 sort하면 A/B/C가 각각40회 우승한다. 이는 comparator 결함의 증거이며, 원본 API가 그 배열을 인자로 받는다는 뜻은 아니다.

## 5. 추이성 문제

epsilon 근접관계에서 A~B, B~C지만 A~C는 거짓이다. Recall 우선순위를 적용하면 엄격 선호 A>B, B>C, C>A가 되어 strict weak ordering의 추이성을 위반한다. 고정 sort 입력은 반복 실행을 결정적으로 만들 뿐 이 순환을 해결하지 않는다. 실제 출력의 A보다 epsilon을 초과해 Macro-F1이 높은 C가 뒤에 남는다.

이는 **SYNTHETIC STRUCTURAL ONLY**다. 실제58구간의 선정 오류·발생 빈도·실제 연구 성적은 NOT_MEASURED다.

## 6. 제안 방식의 정확한 명세

`formal6_ranking_proposed.py:rank_candidates_proposed`는 별도 review-only API다. 성공 status는 `PROPOSED_REVIEW_ONLY`로 운영 결과와 구별한다.

1. 다섯 후보 전체 점수/상태를 검증한다. 불완전 후보를 몰래 제외하지 않는다.
2. 생존집합 S에서 현재 지표의 `best=max(score[c] for c in S)`를 계산한다.
3. `abs(best-score[c]) <= 1e-12`인 후보만 다음 S로 남긴다. 단계마다 **현재 S**의 최고값을 다시 구한다.
4. 한 후보가 남으면 선택한다. 여러 후보면 Macro-F1/P0/P1/P5/Accuracy 순서로 반복한다.
5. 계속 동점이면 적은 특징 수, 그다음 동결된 ID 순서로 선택한다.

A-B-C에서는 Macro 단계 최고 C로부터 B/C만 남고 P0 단계에서 B가 이긴다. 탈락한 A를 후속 지표로 복귀시키지 않는다. pairwise sort·반올림·quantization·epsilon 변경 없음.

기존 API의 전체 ranking도 검토할 수 있게 **선택한 후보를 제거하고 나머지에서 Macro-F1부터 다시 시작**해5개 순위를 구성했다. 첫 추천은 반드시 전체5개에서 산출한다. 이 나머지 순위 확장 역시 제안의 일부이며 승인 대상이다. 뒤 순위를 구할 때 처음 탈락자를 영구 삭제하지 않는다. 이 set-based selection은 새 pairwise comparator나 전역 동치관계를 정의한다는 주장이 아니다.

집합의 max와 필터는 입력 배열 순서에 무관하고, 마지막 잔여 동점은 고정 ID 순서로 끝난다. 각 선택에서 후보가 반드시 하나 제거되어 종료한다. subset별 선택이므로 후보 구성 변경에 대한 독립성까지 보장하는 것은 아니며 공식 집합은 계속5개다.

## 7. 변경 파일과 승인용 diff

**기존 파일 수정0, 신규 파일4개와 새 검증 폴더**:

- `formal6_ranking_proposed.py`: 제안 알고리즘과 review-only fail-closed 입력 방어.
- `test_formal6_ranking_proposed.py`: T01~T20 및 실제 원본 comparator 재현3개.
- 이 문서: B6 검토/검증/보존 기록.
- [STAGE_5_B6_DECISION_PROPOSAL.md](STAGE_5_B6_DECISION_PROPOSAL.md): 승인 대기 후속 결정 초안.
- `analysis/STAGE_5_B6_REVIEW_20261105_573d17a8/`: 새 start snapshot, 검증 스크립트·로그·JSON, 미적용 activation patch, 최종 hash 목록. 기존 evidence 덮어쓰기 없음.

[미적용 activation patch](analysis/STAGE_5_B6_REVIEW_20261105_573d17a8/activation_PENDING_USER_APPROVAL.patch)는 원본의 `compare`/`sorted` 블록을 local import와 `ranking = rank_candidates_proposed(scores)["ranking"]` 두 줄로 대체한다. 새 런타임 의존성을 동결 hash에서 빠뜨리지 않도록 `code_hashes`의 기존 source pin 목록에 제안 모듈 경로 한 개도 추가한다. 선행 검증·원래 success/blocked 반환·호출자·기존 pin은 그대로다. 상수/학습/지표 산식을 바꾸지 않는다. 운영 status는 기존대로 유지하고 review-only status를 운영 결과에 노출하지 않는다.

`git apply --check` PASS. 실제 적용 없음. patch의 함수를 별도 namespace에만 compile하여 정상108사례의 전체 반환 동등성, 연쇄반례120순열의 B 선택, 정상 차단/TypeError/AttributeError 포함8개 오류 계약 및 새 의존성 pin을 검증했다. [activation_checks_with_source_pin.json](analysis/STAGE_5_B6_REVIEW_20261105_573d17a8/activation_checks_with_source_pin.json). 원본 함수/소스는 그대로 A를 반환한다. 초기 ranking-only patch/검증도 별도 이름으로 보존했으며 승인 대상은 `activation_PENDING_USER_APPROVAL.patch` 최신본이다.

## 8. 새 알고리즘 순열·경계 검증

| 테스트 | 검증 | 결과 |
|---|---|---|
| T01~T04 | 명확1위, 정확동점, epsilon 미만/초과 | PASS |
| T05 | nextafter 바로 위/아래 및 exact EPS, 5지표 경계 | PASS |
| T06 | A-B-C에서 A 제외 후 B, 전체 B/C/A/D/E | PASS |
| T07 | 공식5개 전체120순열의 추천/전체순위 직접 비교 | PASS, B 120/120 |
| T08 | 5지표별 우승 및 전부동점 각각120순열 (720회) | PASS |
| T09~T12 | P0→P1→P5→Accuracy 순차 해소·탈락자 미복귀 | PASS |
| T13~T14 | 8열 우선 및 같은 차원 최종 고정순서 | PASS |
| T15 | None/N/A/NaN/±Inf, malformed recall/status/score | PASS |
| T16 | 누락/불명/추가ID·중복 pair sequence 거부 | PASS |
| T17 | 기존 `_summary`/`_prediction_report`/frozen seed 계약 | PASS |
| T18 | 정상108사례(8명시+100분리점수) 전체순위 원본 동등 | PASS |
| T19~T20 | 입력 값/객체 불변, 동일입력100회 | PASS |
| 원본 재현3개 | 실제 comparator 순환/API순열/반복결정성 | PASS |

T17의 이미 구성된 합성 정답·예측 배열은 모델 출력이 아니다. RF3개 seed 지표 평균, LR seed0 한 결과,6 Recall 평균, 불완전 차단을 확인했다. 크기 다른 합성 fold에서 pooled OOF F1이 fold F1 평균과 다른 것도 확인했다. 모델별 seed dispatch는 기존 source와 보고서/설정 계약을 함께 확인했으며 fit 루프 자체는 실행하지 않았다.

binary float 경계 예: `0.5+1e-12`의 실제 차이는 `9.999778782798785e-13`이라 동점이다. 그 값의 `nextafter(+inf)`와0.5 차이는 `1.000088900582341e-12`라 비동점이다. 바로 아래는 `9.99866855977416e-13`이다. 기대값은 십진 표기만으로 정하지 않았다. 별도로 `1e-12 - 0.0 == TIE_TOLERANCE`의 inclusive 경계도 검사했다.

## 9. 기존 회귀와 실제 실행 건수

최종 실행 명령:

```powershell
python -X utf8 -B analysis/STAGE_5_B6_REVIEW_20261105_573d17a8/final_no_inference/verify_b6.py
python -X utf8 -B analysis/STAGE_5_B6_REVIEW_20261105_573d17a8/check_activation.py
git apply --check analysis/STAGE_5_B6_REVIEW_20261105_573d17a8/activation_PENDING_USER_APPROVAL.patch
```

Python3.12.10 / NumPy2.5.3 / sklearn1.9.1의 정확 환경은 최종 JSON에 기록했다. 실행 결과의 실제 Python patch version은 JSON을 우선한다.

| 최종 unittest 그룹 | PASS | FAIL/ERROR | SKIP |
|---|---:|---:|---:|
| 신규 B6 | 23 | 0 | 0 |
| 기존 formal6 | 8 | 0 | 8 |
| 기존 readiness/C6/provenance | 30 | 0 | 2 |
| 합계 | **61** | **0** | **10** |

SKIP은 runner가 명시적으로 보고하는 제외 항목이다. 기존 formal6의 fit 동반4개 및 synthetic pipeline class setup에서 fit/추론하는4개, C6의 hand-built RF leaf 추론2개다. 기존 테스트 원문은 변경하지 않았다. 자동 discovery 전체를 실행했다고 주장하지 않는다. 실제 test ID/사유는 [test_results.json](analysis/STAGE_5_B6_REVIEW_20261105_573d17a8/final_no_inference/test_results.json), 원문은 [tests.log](analysis/STAGE_5_B6_REVIEW_20261105_573d17a8/final_no_inference/tests.log)다.

기존 formal6 실행8개는 차원/공통키/참조, 결측/identity, bridge, 클래스부족 fit전 차단, 외부자료 선접근 차단, N/A/기존동점, hash/lazy freeze gate, 원본8열 합성 입력 validation이다. 실제 개발 평가 fit/최종freeze/외부추론 통합은 NOT_RUN이므로 **FORMAL_REGRESSION=PARTIAL**이다. 허용된 fit 없는 합성 경로는 PASS다.

첫 시도는61 PASS /2 FAIL /8 SKIP이었다. 두 FAIL은 추가한 `RF.predict` 금지 guard가 C6의 hand-built leaf 호출을 차단한 것으로 실제 predictor 본문은 실행되지 않았다. 로그/스크립트/JSON을 상위 폴더에 보존했다. 해당2개를 최종 runner에서 명시 SKIP 후 재검증했다. 첫 시도의 guard 시도2회와 최종 호출0을 혼동하지 않는다. 최초 전체그룹 FAIL 표시는 제안 알고리즘 실패를 뜻하지 않으며 신규23개는 두 시도 모두 PASS다.

최종 guard 호출은 Forest.fit/predict, RF.fit_models, LR.fit/predict, StandardScaler.fit **모두0**이다. activation 별도 검증도 fit/predict0이다. unittest71개에는 skip10개가 포함되며 실제 실행 성공61개다. activation의108/120/8개 assertion은 unittest 수에 합산하지 않았다.

## 10. 공식 평가·탐색 자료 분리

점수는 이 작업의 수기 합성 fixture뿐이다. 실제58구간/파일럿/외부4인의 raw·feature·예측·저장 평가 결과를 읽거나 모델 fit/추론하지 않았다. 기존 연구 문서와 필요한 ignored LR **소스**, 기존 합성 validator 소스만 확인했다. 촬영/장치 실행/정식 선정/새 execution registry/ID/모델 artifact 없음. 합성 metric을 실제 연구 성적으로 보고하지 않는다.

## 11. 원본·동결 코드 보존 근거

시작에 존재하던 모든 tracked 파일과 기존 두 untracked 문서의 byte SHA-256을 종료 시 재대조해 변경0을 확인했다. `formal6_evaluation.py`는 `97662e7fd513a1a9825e6fb59edcd462cefdb4bb397fc16dbc5ed10558c4de8a`로 동일하다. C6 provenance 및 계측 source도 byte 동일하다. 상세는 최종 [verification.json](analysis/STAGE_5_B6_REVIEW_20261105_573d17a8/final_no_inference/verification.json)과 [end_state.json](analysis/STAGE_5_B6_REVIEW_20261105_573d17a8/end_state.json).

공식8조합/후보5/RF seeds0,1,2/M0,M1,M2/LR B0/개발2인 LOSO/공통support·coverage/P0참조제외/모든 특징식과F0,F_cal,H5,H9,H9-F9/10초창/결측·N/A·INCOMPLETE/외부4인 접근차단/IRB HOLD·DEFERRED/CAP-007/009 release/Headless 정식기본값/실측evidence를 변경하지 않았다. B1/B2/B4와 C6 수정 없음. Master/Decision Log/Schema/동결문서도 변경하지 않았다.

## 12. 승인 전 운영 경로

**변경하지 않았다.** 제안은 별도 import 가능한 review 모듈과 미적용 patch뿐이다. 운영 `rank_candidates`는 원본이며 원래 반례의 A 추천을 유지한다. B6 해결을 이유로 현 코드의 정식 자동선정을 허가하지 않는다. 묶음 D/인계의 B6 BLOCKED 조건은 계속 유효하다.

## 13. 남은 승인·우려 및 판정

후속 결정 초안에 최고값 기준 집합과 전체 ranking의 반복선택 정의를 명시적으로 승인해야 한다. 결과 열람 전에 interpretation/version/source hash를 확정해야 하며, 승인 후 최소 patch 적용·회귀/독립 검토를 별도 완료해야 한다. 이번 정상108사례의 동등성은 모든 가능한 점수 집합의 동등성을 뜻하지 않는다. 연쇄 근접점수에서는 선택 결과가 달라질 수 있고 반례에서는 실제로 달라진다.

현재 인터페이스의 dict 중복소실 한계와 원본 incidental 오류는 기록만 했다. model fit/추론이 필요한 통합 회귀는 이번 범위상 미검증이다. 실제 연구 결과를 열어 해석을 고르는 조건으로 삼지 않는다.

| 최종 항목 | 판정 |
|---|---|
| ORIGINAL_REPRO | PASS |
| PROPOSED_ALGORITHM | PASS |
| PERMUTATION_INVARIANCE | PASS |
| FORMAL_REGRESSION | PARTIAL |
| FROZEN_RULES_PRESERVED | PASS |
| APPROVAL_STATE | PENDING_USER_APPROVAL |
| B6_READY_FOR_APPROVAL | YES |

## 14. C-7/5단계 종료 영향

C-7/5단계 종료 검토에 제출할 B6 반례·수정안·합성 회귀·승인용 diff는 준비됐다. **B6 승인 및 운영 반영 완료로 기록한 것은 아니다.** 승인/적용/후속 검토 전에는 Stage5 종료나 Stage6 준비완료를 선언하지 않는다. 다른 blocker, C6 품질·Headless 상태, IRB 및 별도 실행release 조건은 그대로다. C-7의 다른 종료 기준을 새로 정의하거나 B1/B2/B4를 해소하지 않는다.
