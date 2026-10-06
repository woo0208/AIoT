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
- Patch 7 repository-wide READ-ONLY Integrity Checker / Hardening implementation is COMPLETE at commit `cc39b7d`, committed and pushed on `patch7/integrity-checker-hardening`. The final independent READ-ONLY implementation audit is PASS WITH MINOR FINDINGS: BLOCKER 0 / IMPORTANT 0 / MINOR 6. Authority is `PROV-008` with `PROV-009` / `PROV-010` / `PROV-011`; completion requirements follow artifact reference role, not selection event action. Closure documentation is synchronized; main integration and post-merge regression remain pending. After branch closure / main integration, the next required Foundation scope is Patch 8.
- For other unimplemented/future schema designs, including Patch 8 scientific or validation details, confirm their status in `RESEARCH_DECISION_LOG.md` before treating them as implemented or frozen contracts.
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
