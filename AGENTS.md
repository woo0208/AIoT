# Project Instructions

## Scope
- Modify only the issue explicitly requested in the current task.
- Do not refactor or edit unrelated code.
- If another issue is discovered, report it without fixing it unless requested.

## Canonical research authority
- Before research-sensitive work, read `docs/research/AIoT_RESEARCH_MASTER.md`, `docs/research/RESEARCH_DECISION_LOG.md`, and `RESEARCH_DATA_SCHEMA.md`.
- Use Git/source/tests for current implementation facts; use canonical History/Foundation records when historical implementation context is needed.
- Use `AIoT_RESEARCH_MASTER.md` for current research direction, scope, terminology, and roadmap.
- Use `RESEARCH_DECISION_LOG.md` for decision status, rationale, and whether an item is OPEN or DEFERRED.
- Use `RESEARCH_DATA_SCHEMA.md` for data/schema contracts. Patch 4 exact frame contract is frozen by `DATA-003` as `frames-schema/1.0.0` in Schema §F and implemented at commit `110cce6`; Patch 4.5 model artifact lock is implemented as `mediapipe-model-lock/1.0.0`; Patch 5 end-to-end lineage is frozen by `PROV-005`, implemented at commit `dd0464e`, and main-integrated at merge commit `ae86d58` with `summary-schema/1.0.0`, `rf-sample-lineage/1.0.0`, and `rf-experiment-provenance/1.0.0`. Patch 6 selection authority is frozen by `PROV-006`, clarified by `PROV-007`, and implemented at commit `9c5fff9` as `selection-event/1.0.0` + `dataset-selection-manifest/1.0.0` with RF `--dataset-manifest` binding and canonical round identity. Patch 6 committed-state verification is 330 tests PASS; independent re-audit has BLOCKER 0 / IMPORTANT 0. Patch 6 documentation closure is commit `950d2ce`; it is main-integrated at merge commit `2058db1`, and the immediate post-merge full regression is 330 tests PASS. Patch 6 is COMPLETE / MAIN-INTEGRATED. Real D455 formal hardware validation remains Patch 8 scope. Do not reopen or alter frozen Patch 4/4.5/5/6 contracts implicitly in later work.
- Patch 7 repository-wide READ-ONLY Integrity Checker / Hardening is COMPLETE / MAIN-INTEGRATED: implementation `cc39b7d`, documentation closure `98a8917`, main merge `1e99e06`. The final independent READ-ONLY implementation audit is PASS WITH MINOR FINDINGS: BLOCKER 0 / IMPORTANT 0 / MINOR 6. Authority is `PROV-008` with `PROV-009` / `PROV-010` / `PROV-011`; completion requirements follow artifact reference role, not selection event action. Documentation closure audit passed; main integration, origin/main synchronization at `1e99e06`, and immediate post-merge regression are complete: pytest 454 passed / 1571 subtests, unittest 454 tests / OK. The next required Foundation scope is Patch 8.
- Patch 8 Actual D455 Measurement-Quality / End-to-End Validation is DESIGN-FROZEN by `CAP-005` (CONFIRMED; Resolves `OPEN-006`, so `OPEN-006` is RESOLVED BY CAP-005; Supersedes none). The frozen Patch 8 design authority is `docs/foundation/PATCH_08_actual_d455_end_to_end_validation.md`. Patch 8 implementation, implementation audit, execution authorization/registration, and formal D455 hardware execution are PENDING; formal Patch 8 hardware execution has NOT been performed, and Patch 8 is not COMPLETE. `OPEN-002` through `OPEN-005` remain DEFERRED.
- Patch 8 implementation guardrails: implement only what that Foundation document specifies (its §90 scope) and obey its §91 MUST NOT list. Do not change its grid, anchors, thresholds, windows, depth series/validity masks, quantity lists, predicates, retry/firewall rules, or protocol/ledger identities, and do not tune them toward observed results; a post-hoc protocol change requires a new Decision Log entry with `Supersedes: CAP-005`. Do not change production forward-gate semantics, `SEQ_CORE`/`SEQ_FULL`, `frames-schema/1.0.0`, `summary-schema/1.0.0`, or frozen Patch 4/4.5/5/6/7 contracts. `patch8-validation-control/1.0.0` is an operational governance ledger, not a scientific schema. Do not create an execution registry, `execution_id`, or formal validation runtime artifacts before the audited implementation and an explicit execution authorization.
- For other unimplemented/future schema designs, confirm their status in `RESEARCH_DECISION_LOG.md` before treating them as implemented or frozen contracts.
- Do not implicitly resolve an OPEN or DEFERRED research decision because implementation requires a value. Stop and report an apparent authority conflict instead of choosing one silently.
- After canonicalization, do not rewrite historical Decision Log entries. Record changed decisions in new entries using `Supersedes:` and resolved OPEN items using `Resolves:` where applicable.

## Research integrity
- Preserve the definitions of M0, M1, and M2 unless the task explicitly targets them.
- Do not change seeds, folds, feature definitions, labels, preprocessing, or evaluation rules unless explicitly requested.
- Do not tune code to reproduce or improve a desired accuracy.
- Experimental results are evidence, not targets.

## Data and results
- Never fabricate or infer experiment results when the required datasets are unavailable.
- Synthetic data may be used only for structural/unit tests.
- Clearly distinguish structural tests from actual research-data results.

## Editing
- Prefer the smallest patch that solves the requested problem.
- Do not automatically commit or push.
- Report every modified file and the exact behavior changed.

## Verification
- Run relevant tests after changes.
- Preserve existing tests unless the requested change intentionally alters their assumptions.
- Report which tests were actually run and whether they passed.
