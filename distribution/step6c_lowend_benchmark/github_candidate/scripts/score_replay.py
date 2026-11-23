"""Join frozen Replay predictions to separately approved ground truth after inference."""
import argparse
import csv
from pathlib import Path
from statistics import median

from benchmark import METHODS, PROTOCOL, private_output, verified_schedule, verify_package
from research_b_final_validation import digest, read, require, save
from research_b_label_validation import archived_windows, csv_rows, score_schedule


def baseline_predictions(path, schedule):
    rows = csv_rows(path)
    expected = {row["id"]: row for row in schedule}
    result = {}
    repeats = {}
    for row in rows:
        key = row["method"], row["window_id"]
        window = expected[key[1]]
        bounds = window["bounds"]
        require(key[0] in METHODS and row["truth"] == window["posture"]
                and int(row["start_frame"]) == bounds.start_frame and int(row["closing_frame"]) == bounds.closing_frame,
                "Reference predictions use a different window or policy")
        values = (int(row["prediction_class"]) if row["prediction_class"] else None, row["h9_pass"] == "True")
        require(key not in result or result[key] == values, "Reference repeats disagree")
        rep = int(row["repeat"])
        refs = repeats.setdefault(key, set())
        require(rep in (1, 2, 3) and rep not in refs, "Reference repeat identifier is invalid")
        refs.add(rep)
        result[key] = values
    require(len(result) == len(METHODS) * len(schedule) and all(len(records) == 3 for records in repeats.values()),
            "Reference predictions incomplete for approved schedule")
    return result


def csv_output(path, rows):
    with path.open("x", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def collect(runs, intake, times, schedule, reference):
    plan = read(runs / "plan.json")
    sequence = intake["array_and_clock_sequence_sha256"]
    result = read(runs / "result.json")
    require(plan["intake"] == intake and plan["protocol_sha256"] == digest(PROTOCOL)
            and plan["pacing"] == "throughput" and result["sequence"] == sequence and result["fault_mode"] == "NO_INJECTION",
            "Run does not match approved source, policy lock, or measured workload")
    require(len(plan["order"]) == plan["repeats"] == result["repeats"]
            and ((plan["mode"] == "ENGINEERING_SMOKE" and plan["repeats"] == 1 and plan["warmups"] == 0)
                 or (plan["mode"] == "STANDARD_REPEATED" and plan["repeats"] >= 3 and plan["warmups"] == 1)),
            "Invalid run or warmup configuration")
    predictions, costs = [], []
    summaries = {method: {"scores_by_repeat": []} for method in METHODS}
    for i, order in enumerate(plan["order"], 1):
        require(len(order) == len(METHODS) and set(order) == set(METHODS), "Missing/repeated policy in block")
        for method in order:
            directory = runs / f"repeat_{i:02d}" / method
            stored, archive = archived_windows(directory, method, times, sequence)
            require(not archive["incomplete_windows"], "Incomplete on-stream H9 window")
            metrics = read(directory / "final_metrics.json")
            replay = read(directory / "replay.json")
            require(read(directory.parent / f"{method}_launch.json")["exit_code"] == 0
                    and all(w["label"] is None and w["label_status"] == "UNVERIFIED" for w in metrics["windows"]),
                    "Worker failed or ground truth leaked into Replay")
            scored = score_schedule(schedule, stored)
            require(scored["status"] == "DEVELOPMENT_SIX_COMPUTED", "Exact six approved windows required for scoring")
            sums = scored["full_six"]
            summaries[method]["scores_by_repeat"].append(dict(repeat=i, prediction_rate=metrics["predictions"] / len(schedule), **sums))
            for truth, row in zip(schedule, replay["segments"], strict=True):
                bounds, label = truth["bounds"], row["prediction_label"]
                numeric = row.get("prediction")
                require((type(numeric) is int and label == f"P{numeric}") if row["prediction_success"]
                        else numeric is None and label is None, "Unexpected numeric class mapping")
                key = method, truth["id"]
                compare = reference[key] == (numeric, row["eligible"]) if reference is not None else None
                predictions.append(dict(method=method, repeat=i, window_id=truth["id"], start_frame=bounds.start_frame,
                    closing_frame=bounds.closing_frame, truth=truth["posture"], prediction_class=numeric,
                    prediction_label=label, outcome="NO_PREDICTION" if label is None else "CORRECT" if label == truth["posture"] else "WRONG",
                    h9_pass=row["eligible"], h9_valid_frames=row["valid_frames"], h9_inputs=row["input_frames"],
                    coverage=row["coverage"], same_as_step5e=compare))
            calls = metrics["calls"]
            costs.append(dict(method=method, repeat=i, input_frames=metrics["total_inputs"], full=metrics["full_total"],
                full_inside=metrics["full_active"], full_outside=metrics["full_total"]-metrics["full_active"],
                face=calls["face"], face_detected=calls["face"]-metrics["face_failures"], pose=calls["pose"],
                align=calls["align"], depth=calls["depth"], cpu_s=metrics["process_cpu_s"], wall_s=metrics["wall_s"],
                p50_ms=metrics["p50_ms"], p95_ms=metrics["p95_ms"], h9_valid=metrics["valid_frames"],
                h9_pass=metrics["h9_pass"], predictions=metrics["predictions"], errors=len(replay["errors"]),
                dropped=replay["dropped_or_rejected_frames"]))
    for method, summary in summaries.items():
        samples = [row for row in costs if row["method"] == method]
        summary["cost_medians"] = {key: median(row[key] for row in samples) for key in samples[0] if key not in ("method", "repeat")}
        summary["rss_by_repeat"] = [row["rss"] for row in result["methods"][method]["runs"]]
        summary["predictions_and_h9_agree"] = result["methods"][method]["repeat_windows_agree"]
    return predictions, costs, dict(scope="DEVELOPMENT_CLIP2", mode=plan["mode"], repeats=plan["repeats"],
        environment=plan["environment"], order=plan["order"], warmups=plan["warmups"], methods=summaries,
        step5e_rows_compared=len(predictions) if reference is not None else 0,
        step5e_mismatches=sum(row["same_as_step5e"] is False for row in predictions))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("clip", "inputs", "runs", "output"):
        parser.add_argument("--" + key, type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args()
    verify_package()
    output = private_output(args.output)
    require(not output.is_relative_to(args.clip.resolve()), "Keep scoring outputs outside the raw source")
    intake, times, schedule = verified_schedule(args.clip, args.inputs)
    reference = baseline_predictions(args.baseline, schedule) if args.baseline else None
    predictions, costs, summary = collect(args.runs, intake, times, schedule, reference)
    output.mkdir(parents=True, exist_ok=False)
    csv_output(output / "window_predictions.csv", predictions)
    csv_output(output / "cost_by_repeat.csv", costs)
    save(output / "development_metrics.json", summary)
    print(f"{len(predictions)} prediction rows; {summary['step5e_mismatches']} disagreements "
          f"over {summary['step5e_rows_compared']} STEP 5E comparisons")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError) as error:
        raise SystemExit(str(error)) from error
