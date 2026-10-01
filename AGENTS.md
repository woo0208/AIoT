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
- Use `RESEARCH_DATA_SCHEMA.md` for data/schema contracts. Patch 4 exact frame contract is frozen by `DATA-003` as `frames-schema/1.0.0` in Schema §F but remains unimplemented until Patch 4 code lands; do not reopen or alter that contract implicitly during implementation.
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
