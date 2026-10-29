# Historical evaluator archive

`compare.py` is the original pre-fit frozen script. `compare_fixed.py` is the
successful script used to produce the saved experiment. Their bytes are preserved;
the archive is not executed by publication or verification. `EVALUATOR_FIX.json`
records the final baseline-reader correction. Model, feature, aggregation, split,
seed, scaler, metric and benchmark settings were not changed by that correction.

The scripts contain historical pseudonymous input filenames and byte identities,
not captured data. Private inputs are intentionally absent from Git.

For authorized reproduction in a **new private directory**, recover the original
private evidence bundle containing:

- Original `PLAN.json`, `samples.json`, `input_identities.json` and the archive files.
- `inputs/`: both original pilot CSVs, the original six-class baseline JSON, and
  the prior H9 feature-ablation result JSON referenced by the evaluator.
- `source/`: exact source snapshot listed in the private plan, including the
  original H9 loader/aggregation, RF implementation and their import dependencies.
- The exact package versions in `../requirements.lock.txt`.

The shared `protocol.json` is a safe extraction of settings, not a replacement for
the immutable private plan. The original local integrity check also requires the
private original-workspace identity record and Git state; an arbitrary Git clone
is not equivalent. Do not fabricate missing files, bypass identity checks, replace
the baseline with synthetic data, or treat this archive as currently authorized
to launch a new experiment. Missing private inputs must be reported by filename.

Current verification requires none of those private inputs:

```text
cd research/h9_five_algorithms_20261029
python -B verify_results.py
python -B -m unittest -v test_verify_results.py
```

These commands only verify existing aggregate counts and run structural arithmetic
and tamper-detection tests. They never fit models, collect data or benchmark inference.
