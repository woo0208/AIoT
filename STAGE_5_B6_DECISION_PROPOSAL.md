# Stage 5 B6 — 후속 결정 초안

**Status: PROPOSED**

**Approval: PENDING_USER_APPROVAL**

작성: 2026-11-05. 승인된 Decision Log에 편입하지 않은 별도 검토 초안이다. 결정 ID를 발급하거나 B6를 RESOLVED로 처리하지 않는다.

참조: [EXP-006](docs/research/RESEARCH_DECISION_LOG.md#exp-006--5-d-8-수치-규칙-후속-확정), EXP-005/007, [5-D-8 동결 문서](docs/research/STAGE_5D8_FORMAL_EVALUATION_FREEZE.md), [B6 검토 보고서](STAGE_5_B6_RANKING_FIX_REVIEW.md).

**Proposed relationship (미발효):** EXP-006 Decision2의 전역 후보집합 동점 처리 해석을 후속 명시한다. pairwise 연쇄 동점 해석과 다른 선택을 허용하는 범위의 Supersedes/Clarifies 관계 및 최종 ID는 승인 시 명시해야 한다. 기존 EXP-006의 scalar `1e-12`, 원점수, 지표 우선순위와 EXP-005/007의 나머지 규칙은 보존한다. 과거 Decision Log 본문은 소급 수정하지 않는다. 이 초안 자체에는 유효한 Supersedes/Resolves 효력이 없다.

## 문제 정의와 합성 반례

현재 `formal6_evaluation.rank_candidates`는 `cmp_to_key`의 쌍별 epsilon 동점을 사용한다. 근접관계의 비추이성이 후속 Recall과 결합하면 A>B, B>C, C>A 순환을 만든다.

| 합성 후보 | Macro-F1 | P0 Recall |
|---|---:|---:|
| A = RF_M0_H9 | 0.5 | 0.9 |
| B = RF_M1_H9 | 0.5+0.75e-12 | 0.8 |
| C = RF_M2_H9 | 0.5+1.50e-12 | 0.7 |

나머지 두 후보는 명백히 낮게 둔다. 실제 float에서 A/B와 B/C 차이는 <=1e-12, A/C는 >1e-12다. 원본 추천 A와 달리 아래 제안은 B를 추천한다. 고정 ID 배열을 sort하는 원본 API는 dict120순열에서도 A로 결정적이지만 comparator 자체는 strict weak ordering을 위반한다. 포착한 실제 comparator로 정렬할 배열을 순열화하면 A/B/C 각40회다.

이 반례는 **SYNTHETIC STRUCTURAL ONLY**이며 실제58구간에서 관측된 오류가 아니다. 실제 연구 성적·오류 빈도·모델 우수성은 NOT_MEASURED다.

## 제안하는 동점 집합

공식5개 후보의 완전한 원점수 mapping을 모두 검증한 뒤 S를 전체후보로 둔다. 각 지표 m에서 `b=max(score_m(c): c in S)`를 구하고 `S={c in S: abs(b-score_m(c))<=1e-12}`로 좁힌다. 한 후보면 즉시 선택하고, 여러 후보면 다음 지표로 진행한다.

순서: **Macro-F1 → P0 Recall → P1 Recall → P5 Recall → Accuracy → 적은 특징 수 → 기존 고정 후보 순서**.

각 단계의 기준 최고값은 현재 생존집합에서 계산한다. 탈락자를 나중 지표에서 복귀시키지 않는다. 동일 두 후보의 점수가 근접하더라도 전체집합의 최고값으로부터 멀면 탈락할 수 있다. 따라서 이 해석은 단순한 sort 구현 교체 이상의 승인 대상이다.

원본 전체 ranking 반환을 유지하려면 첫 선택 후 그 후보만 제거하고 나머지에서 Macro-F1부터 다시 같은 절차를 적용한다. 순위마다 생존집합을 새로 만들고 남은 모든 후보를 고려한다. 이 전체 순위 확장도 함께 승인할 항목이다. 첫 추천은 항상 전체5개 입력으로 결정한다.

고정 후보 순서:

1. RF_M0_H9 (9열)
2. RF_M1_H9 (9열)
3. RF_M2_H9 (9열)
4. RF_M0_H9-F9 (8열)
5. LR_B0_H9-F9 (8열)

## 보존 근거와 변화 가능성

숫자 자체의 원점수 비교와 `abs차<=1e-12`는 그대로다. 변경점은 모든 쌍을 독립 비교하던 방법에서 **각 생존집합 최고값을 기준으로 동점집합을 정의**하는 방법으로의 전환이다. 지표/차원/고정순서/후보 추가나 반올림/quantization/epsilon 축소·확대는 없다.

108개 정상 합성사례는 원본과 전체순위가 같았지만 연쇄근접 사례는 추천이 달라질 수 있다. 이 차이를 버그 수정이라는 명목으로 자동 승인하지 않는다. 기존 N/A/INCOMPLETE 및 클래스부족 차단, RF seed0/1/2 pooled OOF 후 seed평균, deterministic LR 단일 seed0 요약, baseline3개 비교전용, 개발/외부 분리는 유지한다.

## 검증과 적용 조건

- 신규23개 PASS: T01~T20과 원본재현3개. 공식5개120순열에서 B 및 전체순위 동일, 모든 지표별 추가720순열과 binary-float 경계 PASS.
- 기존 fit 없는 회귀38개 PASS; fit/추론을 요구하는10개는 SKIP. 합계61 PASS/0 FAIL/10 SKIP. 전체 fit 동반 통합은 NOT_RUN이므로 formal regression은 PARTIAL.
- 공식 원본 소스/모든 시작 tracked 파일·기존 untracked 문서는 byte 동일. 제안 API는 운영에 연결하지 않았다.
- [미적용 activation patch](analysis/STAGE_5_B6_REVIEW_20261105_573d17a8/activation_PENDING_USER_APPROVAL.patch): 기존 validator와 반환계약을 보존하고 comparator/sort 블록을 제안 ranking 호출로 대체하며, 새 모듈을 기존 source hash pin 목록에 추가한다. patch check 및 메모리 내108정상/120반례순열/8오류계약·의존성 pin 검사 PASS.

승인 전에는 정식 자동선정에 사용하지 않는다. **실제 개발/외부 평가 결과 열람 전에** 아래를 확정해야 한다.

1. 최고값 기준 동점집합 및 전체 ranking 반복선택 정의의 명시 승인.
2. EXP-006과의 후속 관계·결정 ID/version·source hash 기록. 원문 수정 없이 새 결정으로 남김.
3. 최소 activation diff 적용 후 관련 회귀 및 독립 검토. 이번 범위에서 제외한 fit/추론 통합 검증의 승인된 실행 범위도 별도 확인.
4. B6 해결 상태를 근거와 함께 후속 갱신. 다른 Stage5/6 gate·IRB·CAP-007/009 실행release는 별도로 유지.

특정 실제 후보가 이기는지 확인한 뒤 이 초안을 채택/철회하는 절차는 허용하지 않는다. 실제 결과가 이미 열람된 상태가 새로 확인되면 그 사실과 사후선택 위험을 별도 승인 검토해야 한다.

**현재 결론: B6_READY_FOR_APPROVAL=YES / APPROVAL_STATE=PENDING_USER_APPROVAL. 최종 RESOLVED 아님.**
