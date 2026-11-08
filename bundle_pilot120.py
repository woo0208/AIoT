"""Export the already evaluated 120-segment exploratory set as a private bundle.

python -X utf8 -B bundle_pilot120.py [--verify]
No training, raw-file concatenation, canonical selection manifest or new selection.
"""
import argparse
from collections import Counter
import csv
from pathlib import Path

from review_lr_features import ROOT, read, digest
from evaluate_new_pilot_lr6 import write
from evaluate_pilot_p5_supplement import OUT as EVALUATION
from f1_sample_aggregator import H9_FEATURE_NAMES

import numpy as np

SOURCE = EVALUATION/"local_private/results.json"
OUT = EVALUATION/"local_private/dataset120"
FEATURES = [f"F{i}" for i in range(1,10)]
FIELDS = ["subject","analysis_run_id","recording_id","segment_id","label_id","label",
          "is_supplement","original_recording_id","original_segment_id",*FEATURES]


def dataset_rows(saved):
    binding = saved["quality"]["binding"]
    new_by_key = {tuple(r["sample_key"]):r for r in saved["quality"]["samples"]}
    for i,(key,person,label,values) in enumerate(zip(saved["sample_keys"],saved["subjects"],saved["labels"],saved["matrix"])):
        analysis_id,recording,segment = key
        supplemented = tuple(key) in new_by_key
        original_recording = binding["original_recording_id"] if supplemented else recording
        original_segment = new_by_key[tuple(key)]["original_segment_id"] if supplemented else int(segment)
        yield dict(subject=person,analysis_run_id=analysis_id,recording_id=recording,segment_id=segment,
            label_id=label,label=saved["results"]["LR9"]["metrics"]["per_class"][label]["label"],
            is_supplement=supplemented,original_recording_id=original_recording,original_segment_id=original_segment,
            **dict(zip(FEATURES,values)))


def validate_source(saved):
    assert len(saved["sample_keys"]) == len(saved["matrix"]) == len(saved["labels"]) == 120
    assert np.array(saved["matrix"]).shape == (120,9) and np.isfinite(saved["matrix"]).all()
    assert Counter(saved["subjects"]) == {"P01":60,"P02":60}
    assert Counter(saved["labels"]) == {i:20 for i in range(6)}
    assert len({tuple(k) for k in saved["sample_keys"]}) == 120
    for person in ("P01","P02"):
        assert Counter(y for p,y in zip(saved["subjects"],saved["labels"]) if p==person) == {i:10 for i in range(6)}
    rows = list(dataset_rows(saved))
    assert sum(r["is_supplement"] for r in rows) == 7
    slots = {(r["subject"],r["original_recording_id"],r["original_segment_id"]) for r in rows}
    assert len(slots) == 120
    assert {r["original_segment_id"] for r in rows if r["is_supplement"]} == set(saved["quality"]["binding"]["original_segment_ids"])
    assert all(r["subject"]=="P01" and r["label_id"]==5 for r in rows if r["is_supplement"])
    for path,sha in saved["inputs"].items(): assert digest(ROOT/path) == sha
    return rows


def verify():
    saved = read(SOURCE); expected = validate_source(saved); info = read(OUT/"bundle_info.json")
    assert digest(SOURCE) == info["evaluation_sha256"] and digest(OUT/"samples.csv") == info["samples_sha256"]
    assert digest(Path(__file__).resolve()) == info["export_script_sha256"]
    with (OUT/"samples.csv").open(encoding="utf-8",newline="") as stream:
        reader = csv.DictReader(stream); assert reader.fieldnames == FIELDS; actual = list(reader)
    assert actual == [{k:str(r[k]) for k in FIELDS} for r in expected]
    np.testing.assert_array_equal([[float(r[f]) for f in FEATURES] for r in actual],saved["matrix"])
    assert info["feature_fields"] == dict(zip(FEATURES,H9_FEATURE_NAMES))
    assert info["sample_keys"] == saved["sample_keys"]
    assert info["source_csv_sha256"] == {str((ROOT/"captures"/recording/"features.csv").relative_to(ROOT)):
        digest(ROOT/"captures"/recording/"features.csv") for recording in sorted({k[1] for k in saved["sample_keys"]})}
    print("PASS: private120 bundle matches evaluated matrix/labels/identities, seven bindings, source hashes and CSV roundtrip; no training")


def run():
    if OUT.exists(): raise FileExistsError("Existing bundle preserved; use --verify")
    saved = read(SOURCE); rows = validate_source(saved)
    OUT.mkdir(exist_ok=False)
    with (OUT/"samples.csv").open("x",encoding="utf-8",newline="") as stream:
        writer = csv.DictWriter(stream,fieldnames=FIELDS); writer.writeheader(); writer.writerows(rows)
    source_paths = [ROOT/"captures"/recording/"features.csv" for recording in sorted({k[1] for k in saved["sample_keys"]})]
    write(OUT/"bundle_info.json",dict(scope="LOCAL_PRIVATE_EXPLORATORY_ONLY",samples=120,participants=2,
        subject_counts={"P01":60,"P02":60},class_counts={f"P{i}":20 for i in range(6)},
        composition="113 previously eligible segments plus seven prospectively bound P01 P5 supplements",
        exclusions="seven original technical failures retained separately; interrupted P02 runs and original24 not included",
        aggregation="unchanged H9 joint support and eligibility; F3 circular mean, other columns median",
        feature_fields=dict(zip(FEATURES,H9_FEATURE_NAMES)),sample_keys=saved["sample_keys"],
        evaluation_path=str(SOURCE.relative_to(ROOT)),evaluation_sha256=digest(SOURCE),
        samples_sha256=digest(OUT/"samples.csv"),export_script_sha256=digest(Path(__file__).resolve()),
        source_csv_sha256={str(p.relative_to(ROOT)):digest(p) for p in source_paths},
        evaluation_rule="participant LOSO; both sessions of P01 stay in the same fold; train-only scaler",
        canonical_status="local convenience export; not a frozen schema or formal selection manifest"))
    verify()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--verify",action="store_true")
    verify() if parser.parse_args().verify else run()
