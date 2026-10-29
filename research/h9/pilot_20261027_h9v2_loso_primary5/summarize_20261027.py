"""Read-only summary of the pre-registered metrics (PREREGISTRATION_20261027.md).

No fitting. Reads the h9_v2_loso.py output and the existing 6-class H9 pilot
JSON (context only; not directly comparable). Writes one new JSON file.
Usage: python -B summarize_20261027.py RESULT.json H6_PILOT.json OUT.json
"""

import json
import sys
from pathlib import Path

import numpy as np

MODELS = ("M0", "M1", "M2", "M3-G")
COMPARISONS = (("M3-G", "M0"), ("M3-G", "M2"), ("M2", "M0"))
THRESHOLD = 0.05


def load(path):
    with open(path, encoding="utf-8-sig") as stream:
        return json.load(stream)


def cm_stats(cms):
    cms = np.asarray(cms)
    p1_support = cms[:, 1, :].sum(axis=1)
    p1_pred = cms[:, :, 1].sum(axis=0 if cms.ndim == 2 else 1)
    tp = cms[:, 1, 1]
    out = dict(
        p1_recall_per_seed=(tp / p1_support).tolist(),
        p1_precision_per_seed=[float(t / p) if p else 0.0 for t, p in zip(tp, p1_pred)],
        p1_to_p0_per_seed=cms[:, 1, 0].tolist(),
        p0_to_p1_per_seed=cms[:, 0, 1].tolist(),
        p1_support=int(p1_support[0]), p0_support=int(cms[0, 0].sum()),
    )
    if cms.shape[1] == 6:
        out["p1_to_p5_per_seed"] = cms[:, 1, 5].tolist()
    for key in [k for k in out if k.endswith("_per_seed")]:
        out[key.replace("_per_seed", "_mean")] = float(np.mean(out[key]))
    return out


def model_summary(metrics):
    pooled = metrics["per_seed"]
    row = dict(accuracy_mean=metrics["accuracy_mean"], accuracy_seed_sd=metrics["accuracy_seed_sd"],
               macro_f1_mean=metrics["macro_f1_mean"], macro_f1_seed_sd=metrics["macro_f1_seed_sd"],
               participant_macro_f1_mean=metrics["participant_macro_f1_mean"],
               complete_participant_class_support=metrics["complete_participant_class_support"],
               **cm_stats([seed["confusion_matrix"] for seed in pooled]))
    row["participants"] = {
        subject: dict(accuracy_mean=item["accuracy_mean"], accuracy_seed_sd=item["accuracy_seed_sd"],
                      macro_f1_mean=item["macro_f1_mean"], macro_f1_seed_sd=item["macro_f1_seed_sd"],
                      **cm_stats([seed["confusion_matrix"] for seed in item["per_seed"]]))
        for subject, item in metrics["participants"].items()}
    return row


def label(pooled_diff, participant_diffs):
    if pooled_diff >= THRESHOLD and all(d >= 0 for d in participant_diffs):
        return "개선 방향(탐색적)"
    if pooled_diff <= -THRESHOLD and all(d <= 0 for d in participant_diffs):
        return "악화 방향(탐색적)"
    return "차이 불확실"


def main(result_path, h6_path, out_path):
    result = load(result_path)
    if (result["scope"] != "primary5" or result["trees"] != 500 or result["max_features"] != 2
            or list(result["seeds"]) != [0, 1, 2, 3, 4] or result["m2_lambda"] != 0.5):
        raise ValueError("result does not match the pre-registered run conditions")
    models = {name: model_summary(result["metrics"][name]) for name in MODELS}
    subjects = sorted(models["M0"]["participants"])
    comparisons = {}
    for a, b in COMPARISONS:
        f1 = models[a]["macro_f1_mean"] - models[b]["macro_f1_mean"]
        part = {s: models[a]["participants"][s]["macro_f1_mean"]
                - models[b]["participants"][s]["macro_f1_mean"] for s in subjects}
        rec = models[a]["p1_recall_mean"] - models[b]["p1_recall_mean"]
        part_rec = {s: models[a]["participants"][s]["p1_recall_mean"]
                    - models[b]["participants"][s]["p1_recall_mean"] for s in subjects}
        comparisons[f"{a} - {b}"] = dict(
            accuracy_diff=models[a]["accuracy_mean"] - models[b]["accuracy_mean"],
            macro_f1_diff=f1, participant_macro_f1_diff=part,
            macro_f1_label=label(f1, part.values()),
            p1_recall_diff=rec, participant_p1_recall_diff=part_rec,
            p1_recall_label=label(rec, part_rec.values()))

    preds = result["predictions"]
    m0_m1_equal = [a == b for a, b in zip(preds["M0"], preds["M1"])]
    samples = result["samples"]
    audit = {}
    for sample in samples:
        key = (sample["subject"], sample["label"], sample["status"])
        audit["|".join(key)] = audit.get("|".join(key), 0) + 1

    h6 = load(h6_path)
    h9_context = {}
    for row in h6["metrics"]:
        if row["feature_set"] == "H9":
            h9_context[row["model"]] = dict(
                accuracy_mean=row["accuracy"], accuracy_seed_sd=row["accuracy_seed_sd"],
                macro_f1_mean=row["macro_f1"], macro_f1_seed_sd=row["macro_f1_seed_sd"],
                **cm_stats(row["confusion_matrices"]))

    summary = dict(
        kind="h9-v2-primary5-pilot-exploratory-summary",
        preregistration="PREREGISTRATION_20261027.md", threshold=THRESHOLD,
        result_file=Path(result_path).name, class_order=result["class_order"],
        sample_count=result["sample_count"], sample_status_counts=audit,
        m0_m1_predictions_identical_per_seed=m0_m1_equal,
        models=models, comparisons=comparisons,
        existing_h9_6class_context=dict(
            source=Path(h6_path).name, class_order=h6["class_order"], sample_count=h6["sample_count"],
            note="6-class; not directly comparable to primary5", models=h9_context))
    with open(out_path, "x", encoding="utf-8") as stream:
        stream.write(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    main(*sys.argv[1:4])
