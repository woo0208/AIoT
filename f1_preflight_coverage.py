"""Read-only F1-5 coverage audit of ONE canonical frames CSV (Gate 1.9, NON-FORMAL ENGINEERING).

Usage:
    python f1_preflight_coverage.py <canonical_frames.csv> [--expected-sha256 HEX] [--json]

The CSV path is explicit; no recording is ever selected automatically.  Every
frame goes through the unchanged FEAT-009 frame calculator (via
``f1_csv_adapter``), then the report gives whole-recording, per-step and
per-label FS / SH / SO / joint coverage, hip-validity diagnostics, the
unchanged Gate 1.8 aggregator under ``support="joint"`` and ``"family"``, and
integrity invariants.  Nothing is written; the source SHA-256 is computed
before and after reading and must not change.

These are canonical-validity counts of one recording.  They are not anatomical
localisation accuracy, not Patch 8 validation, not sample eligibility and not
classification evidence.  No threshold, N_min, R_min or imputation is applied.
"""

import argparse
from collections import Counter
import hashlib
import json
import os
import sys

from f1_csv_adapter import F1_CSV_ADAPTER_ID, group_by_sample, load_f1_frame_records
from f1_features import F1_5_FEATURE_NAMES, F1_CORE_DECISION, F1_FAMILIES
from f1_sample_aggregator import F1_AGGREGATION_SPEC_ID, SUPPORT_POLICIES, aggregate_f1_sample


AUDIT_STATUS = "NON-FORMAL ENGINEERING COVERAGE AUDIT"
SUPPORTS = (*F1_FAMILIES, "joint")
_HIP_PREFIXES = ("left_hip", "right_hip")


# ---------------------------------------------------------------- pure functions
def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def percent(count: int, total: int) -> float:
    if total <= 0:
        raise ValueError("coverage denominator must be positive")
    return 100.0 * count / total


def _in_support(record, support: str) -> bool:
    available = record.result.family_available
    if support == "joint":
        return all(available[f] for f in F1_FAMILIES)
    return available[support]


def coverage_counts(records) -> dict:
    """``{"n_frames": n, "FS": .., "SH": .., "SO": .., "joint": ..}`` frame counts."""

    records = tuple(records)
    counts = {"n_frames": len(records)}
    counts.update({s: sum(_in_support(r, s) for r in records) for s in SUPPORTS})
    return counts


def reason_distribution(records) -> dict:
    """Per family, how many frames carry each ``family_reasons`` string (a frame may carry several)."""

    return {family: dict(sorted(Counter(reason for r in records
                                        for reason in r.result.family_reasons[family]).items()))
            for family in F1_FAMILIES}


def step_coverage(groups) -> list:
    """One entry per sample group (step), in first-appearance order."""

    table = []
    for (run, rec, step), members in groups.items():
        table.append({
            "analysis_run_id": run, "recording_id": rec, "step": step,
            "label": members[0].label, "subject": members[0].subject, "round": members[0].round,
            "counts": coverage_counts(members),
            "frame_indices": tuple(r.frame_index for r in members),
            "invalid_reasons": reason_distribution(members),
        })
    return table


def label_coverage(step_table) -> list:
    """Pool steps that share a label: pooled count / pooled frames (never an average of percentages)."""

    pooled: dict[str, dict] = {}
    for entry in step_table:
        item = pooled.setdefault(entry["label"], {"label": entry["label"], "steps": [],
                                                  "counts": dict.fromkeys(("n_frames", *SUPPORTS), 0)})
        item["steps"].append(entry["step"])
        for key in item["counts"]:
            item["counts"][key] += entry["counts"][key]
    return list(pooled.values())


def _state(value) -> str:
    return "true" if value is True else "false" if value is False else "unknown"


def hip_diagnostics(rows, records) -> dict:
    """Canonical hip/shoulder validity counts and SH-failure attribution for one frame set.

    Validity here is the Schema section F geometric/state flag, not anatomical accuracy.
    SH failures are split by the SH ``family_reasons`` of each frame into hip-only,
    shoulder/other-only and both (mutually exclusive).
    """

    rows, records = tuple(rows), tuple(records)
    if len(rows) != len(records):
        raise ValueError("rows and records differ in length")
    out = {"n_frames": len(rows)}
    for field in ("left_hip_valid", "right_hip_valid", "lsh_valid", "rsh_valid", "pose_detected"):
        out[field] = dict(Counter(_state(row.get(field)) for row in rows))
    out["both_hips_valid"] = sum(row.get("left_hip_valid") is True and row.get("right_hip_valid") is True
                                 for row in rows)
    out["both_shoulders_valid"] = sum(row.get("lsh_valid") is True and row.get("rsh_valid") is True
                                      for row in rows)
    sh_ok = hip_only = other_only = both = 0
    for row, record in zip(rows, records):
        if row.get("frame_index") != record.frame_index:
            raise ValueError("rows and records are not aligned by frame_index")
        reasons = record.result.family_reasons["SH"]
        if not reasons:
            sh_ok += 1
            continue
        hip = any(reason.startswith(_HIP_PREFIXES) for reason in reasons)
        other = any(not reason.startswith(_HIP_PREFIXES) for reason in reasons)
        hip_only += hip and not other
        other_only += other and not hip
        both += hip and other
    out.update(SH_available=sh_ok, SH_fail_hip_only=hip_only,
               SH_fail_shoulder_or_other_only=other_only, SH_fail_hip_and_other=both)
    return out


def _subset(rows, records, predicate):
    pairs = [(row, rec) for row, rec in zip(rows, records) if predicate(rec)]
    return [p[0] for p in pairs], [p[1] for p in pairs]


def hip_breakdown(rows, records, step_table) -> dict:
    """Hip diagnostics for the whole recording, each step and each label."""

    rows, records = tuple(rows), tuple(records)
    by_step = {}
    for entry in step_table:
        key = (entry["analysis_run_id"], entry["recording_id"], entry["step"])
        by_step[entry["step"]] = hip_diagnostics(*_subset(
            rows, records, lambda r, key=key: (r.analysis_run_id, r.recording_id, r.step) == key))
    labels = list(dict.fromkeys(entry["label"] for entry in step_table))
    by_label = {label: hip_diagnostics(*_subset(rows, records, lambda r, label=label: r.label == label))
                for label in labels}
    return {"recording": hip_diagnostics(rows, records), "steps": by_step, "labels": by_label}


def summarize_sample(result) -> dict:
    defined = [n for n in F1_5_FEATURE_NAMES if result.features[n] is not None]
    return {
        "support_policy": result.support_policy,
        "n_frames": result.n_frames,
        "feature_n_used": dict(result.feature_n_used),
        "defined": defined,
        "undefined": {n: result.undefined_reasons[n] for n in F1_5_FEATURE_NAMES
                      if result.features[n] is None},
        "features": dict(result.features),
        "so_beta_resultant": result.so_beta_resultant,
        "defined_features_same_frames": result.defined_features_same_frames,
        "all_five_defined": len(defined) == len(F1_5_FEATURE_NAMES),
    }


def aggregate_samples(groups) -> list:
    """Run the unchanged aggregator with each explicit support policy, per sample group."""

    samples = []
    for key, members in groups.items():
        results = {policy: aggregate_f1_sample(members, support=policy) for policy in SUPPORT_POLICIES}
        joint, family = (summarize_sample(results[p]) for p in ("joint", "family"))
        samples.append({
            "sample_key": key, "label": members[0].label,
            "results": results, "joint": joint, "family": family,
            "defined_only_under_family": [n for n in family["defined"] if n not in joint["defined"]],
            "defined_only_under_joint": [n for n in joint["defined"] if n not in family["defined"]],
        })
    return samples


def check_invariants(records, groups, whole, step_table, label_table, hips, samples) -> list:
    """``[(name, ok, detail)]``; any ``ok == False`` means the audit itself is inconsistent."""

    checks = []

    def check(name, ok, detail=""):
        checks.append((name, bool(ok), detail))

    for scope, counts in [("recording", whole)] + [(f"step {e['step']}", e["counts"]) for e in step_table] \
            + [(f"label {e['label']}", e["counts"]) for e in label_table]:
        n = counts["n_frames"]
        check(f"{scope}: 0 <= joint <= min(FS, SH, SO)",
              0 <= counts["joint"] <= min(counts[f] for f in F1_FAMILIES), str(counts))
        check(f"{scope}: every count <= n_frames (coverage <= 100%)",
              n > 0 and all(0 <= counts[s] <= n for s in SUPPORTS), str(counts))
    for key in ("n_frames", *SUPPORTS):
        check(f"per-step {key} totals reconcile with recording",
              sum(e["counts"][key] for e in step_table) == whole[key])
        check(f"per-label {key} totals reconcile with recording",
              sum(e["counts"][key] for e in label_table) == whole[key])
    keys = [r.frame_key for r in records]
    grouped = [r.frame_key for members in groups.values() for r in members]
    check("every source frame in exactly one sample group",
          len(grouped) == len(keys) == len(set(grouped)) and set(grouped) == set(keys),
          f"records={len(keys)} grouped={len(grouped)} unique={len(set(grouped))}")
    for entry, sample in zip(step_table, samples):
        for policy, result in sample["results"].items():
            check(f"step {entry['step']} {policy}: aggregator counts equal audit counts",
                  result.n_frames == entry["counts"]["n_frames"]
                  and all(result.family_valid_counts[f] == entry["counts"][f] for f in F1_FAMILIES)
                  and result.joint_valid_count == entry["counts"]["joint"]
                  and result.input_frame_indices == tuple(sorted(entry["frame_indices"])))
    for scope, diag in [("recording", hips["recording"])] + list(hips["steps"].items()):
        n = diag["n_frames"]
        check(f"hip {scope}: SH outcome categories partition frames",
              diag["SH_available"] + diag["SH_fail_hip_only"] + diag["SH_fail_shoulder_or_other_only"]
              + diag["SH_fail_hip_and_other"] == n)
        check(f"hip {scope}: SH_available <= min(both hips valid, both shoulders valid)",
              diag["SH_available"] <= min(diag["both_hips_valid"], diag["both_shoulders_valid"]))
    check("hip SH_available equals recording SH count", hips["recording"]["SH_available"] == whole["SH"])
    return checks


def sidecar_provenance(path: str, sha256: str) -> dict:
    """Read-only check of the existing ``<frames>.provenance.json`` -> ``analysis_manifest.json`` link.

    Mirrors the link verified by ``analyze_d455.start_analysis_run`` for ``--from-csv`` input,
    but reports every gap/mismatch instead of raising.  It does not establish Patch 6
    selection authority.
    """

    status = {"sidecar": None, "manifest": None, "dataset_role": None, "protocol_version": None,
              "manifest_status": None, "findings": []}
    link_path = path + ".provenance.json"
    if not os.path.exists(link_path):
        status["findings"].append("GAP: no .provenance.json sidecar next to the CSV")
        return status
    status["sidecar"] = link_path
    with open(link_path, encoding="utf-8") as f:
        link = json.load(f)
    if link.get("frames_sha256") != sha256:
        status["findings"].append("MISMATCH: sidecar frames_sha256 differs from source SHA-256")
    manifest_path = os.path.join(os.path.dirname(link_path), link.get("analysis_manifest") or "")
    if not link.get("analysis_manifest") or not os.path.isfile(manifest_path):
        status["findings"].append("GAP: analysis manifest referenced by sidecar not found")
        return status
    status["manifest"] = manifest_path
    if sha256_file(manifest_path) != link.get("analysis_manifest_sha256"):
        status["findings"].append("MISMATCH: analysis manifest SHA-256 differs from sidecar")
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)
    status.update(dataset_role=manifest.get("dataset_role"), protocol_version=manifest.get("protocol_version"),
                  manifest_status=manifest.get("status"),
                  manifest_recording_id=manifest.get("recording_id"),
                  manifest_analysis_run_id=manifest.get("analysis_run_id"),
                  manifest_git_commit=(manifest.get("code") or {}).get("git_commit"))
    if manifest.get("status") != "completed":
        status["findings"].append(f"MISMATCH: analysis run status {manifest.get('status')!r}")
    if (manifest.get("recording_id"), manifest.get("analysis_run_id")) != \
            (link.get("recording_id"), link.get("analysis_run_id")):
        status["findings"].append("MISMATCH: sidecar / manifest identity differ")
    if not any(o.get("kind") == "frames" and o.get("sha256") == sha256
               and o.get("filename") == os.path.basename(path) for o in manifest.get("outputs", [])):
        status["findings"].append("MISMATCH: CSV not listed (name + SHA-256) in manifest frames outputs")
    if manifest.get("provenance_unknown_reasons"):
        status["findings"].append(f"GAP: manifest provenance_unknown_reasons "
                                  f"{sorted(manifest['provenance_unknown_reasons'])}")
    return status


def run_audit(path: str) -> dict:
    """Pure audit of one CSV (no hashing, no printing)."""

    rows, records = load_f1_frame_records(path)
    groups = group_by_sample(records)
    whole = coverage_counts(records)
    step_table = step_coverage(groups)
    label_table = label_coverage(step_table)
    hips = hip_breakdown(rows, records, step_table)
    samples = aggregate_samples(groups)
    return {
        "identity": {
            "frame_schema_version": sorted({row["frame_schema_version"] for row in rows}),
            "analysis_run_id": records[0].analysis_run_id, "recording_id": records[0].recording_id,
            "subject": records[0].subject, "round": records[0].round,
            "steps": [(e["step"], e["label"]) for e in step_table],
        },
        "whole": whole, "whole_reasons": reason_distribution(records),
        "steps": step_table, "labels": label_table, "hips": hips, "samples": samples,
        "invariants": check_invariants(records, groups, whole, step_table, label_table, hips, samples),
    }


# ---------------------------------------------------------------- report
def _fmt_counts(counts: dict) -> str:
    n = counts["n_frames"]
    return " | ".join(f"{counts[s]} ({percent(counts[s], n):.2f}%)" for s in SUPPORTS)


def _fmt_value(v):
    return "None" if v is None else f"{v:.4f}"


def format_report(audit: dict, path: str, sha_before: str, sha_after: str, provenance: dict) -> str:
    ident = audit["identity"]
    out = [f"# {AUDIT_STATUS}", "",
           f"source: {path}", f"sha256 before: {sha_before}", f"sha256 after:  {sha_after}",
           f"adapter: {F1_CSV_ADAPTER_ID} | aggregation: {F1_AGGREGATION_SPEC_ID} | core: {F1_CORE_DECISION}",
           f"frame_schema_version: {ident['frame_schema_version']}",
           f"analysis_run_id: {ident['analysis_run_id']}", f"recording_id: {ident['recording_id']}",
           f"subject: {ident['subject']} | round: {ident['round']}",
           f"steps (step, label): {ident['steps']}", "",
           "## provenance (sidecar -> analysis manifest; Patch 6 selection NOT evaluated)"]
    for key in ("sidecar", "manifest", "manifest_status", "dataset_role", "protocol_version",
                "manifest_recording_id", "manifest_analysis_run_id", "manifest_git_commit"):
        if key in provenance:
            out.append(f"- {key}: {provenance[key]}")
    out += [f"- finding: {f}" for f in provenance["findings"]] or ["- finding: none"]

    out += ["", "## A. whole recording (count (% of n_frames))",
            "| n_frames | FS | SH | SO | joint |", "|---:|---:|---:|---:|---:|",
            f"| {audit['whole']['n_frames']} | {_fmt_counts(audit['whole'])} |", "",
            "invalid reasons (frames carrying each reason):"]
    for family, reasons in audit["whole_reasons"].items():
        out.append(f"- {family}: {reasons or '{}'}")

    out += ["", "## B. per step", "| step | label | n | FS | SH | SO | joint |", "|---|---|---:|---:|---:|---:|---:|"]
    for e in audit["steps"]:
        out.append(f"| {e['step']} | {e['label']} | {e['counts']['n_frames']} | {_fmt_counts(e['counts'])} |")
    out.append("")
    for e in audit["steps"]:
        out.append(f"step {e['step']} ({e['label']}) invalid reasons: "
                   + "; ".join(f"{f}={r or '{}'}" for f, r in e["invalid_reasons"].items()))

    out += ["", "## C. per label (pooled frame counts; not an average of step percentages)",
            "| label | steps | n | FS | SH | SO | joint |", "|---|---|---:|---:|---:|---:|---:|"]
    for e in audit["labels"]:
        out.append(f"| {e['label']} | {','.join(e['steps'])} | {e['counts']['n_frames']} | {_fmt_counts(e['counts'])} |")

    out += ["", "## D. hip / shoulder canonical validity (not anatomical accuracy)",
            "| scope | n | L hip true/false/unk | R hip true/false/unk | both hips | both shoulders "
            "| SH ok | SH fail hip-only | SH fail shoulder/other-only | SH fail both |",
            "|---|---:|---|---|---:|---:|---:|---:|---:|---:|"]
    hips = audit["hips"]
    rows = [("recording", hips["recording"])] + [(f"step {s}", d) for s, d in hips["steps"].items()] \
        + [(f"label {lab}", d) for lab, d in hips["labels"].items()]
    for scope, d in rows:
        tri = lambda c: f"{c.get('true', 0)}/{c.get('false', 0)}/{c.get('unknown', 0)}"
        out.append(f"| {scope} | {d['n_frames']} | {tri(d['left_hip_valid'])} | {tri(d['right_hip_valid'])} "
                   f"| {d['both_hips_valid']} | {d['both_shoulders_valid']} | {d['SH_available']} "
                   f"| {d['SH_fail_hip_only']} | {d['SH_fail_shoulder_or_other_only']} | {d['SH_fail_hip_and_other']} |")

    out += ["", "## E. joint vs family aggregation (engineering candidate outputs; NOT model-eligible samples)",
            "| step | label | policy | n_used fs_x,fs_y,sh_x,sh_y,so_beta | defined | undefined | so_beta R | all five |",
            "|---|---|---|---|---|---|---:|---|"]
    for s in audit["samples"]:
        for policy in ("joint", "family"):
            r = s[policy]
            n_used = ",".join(str(r["feature_n_used"][n]) for n in F1_5_FEATURE_NAMES)
            undefined = "; ".join(f"{n}:{why}" for n, why in r["undefined"].items()) or "-"
            out.append(f"| {s['sample_key'][2]} | {s['label']} | {policy} | {n_used} | {','.join(r['defined']) or '-'} "
                       f"| {undefined} | {_fmt_value(r['so_beta_resultant'])} | {r['all_five_defined']} |")
    out.append("")
    for s in audit["samples"]:
        out.append(f"step {s['sample_key'][2]}: defined only under family = {s['defined_only_under_family'] or '-'}; "
                   f"family support same frames = {s['family']['defined_features_same_frames']}")
        for policy in ("joint", "family"):
            values = ", ".join(f"{n}={_fmt_value(v)}" for n, v in s[policy]["features"].items())
            out.append(f"  {policy}: {values}")

    failed = [c for c in audit["invariants"] if not c[1]]
    out += ["", f"## F. integrity invariants: {len(audit['invariants']) - len(failed)} / "
                f"{len(audit['invariants'])} PASS"]
    out += [f"- FAIL {name} {detail}" for name, _, detail in failed]
    return "\n".join(out) + "\n"


def _jsonable(audit: dict) -> dict:
    data = dict(audit)
    data["samples"] = [{k: v for k, v in s.items() if k != "results"} for s in audit["samples"]]
    data["invariants"] = [{"name": n, "ok": ok, "detail": d} for n, ok, d in audit["invariants"]]
    return data


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("csv_path", help="explicit canonical frames-schema/1.0.0 CSV (never auto-selected)")
    parser.add_argument("--expected-sha256", help="fail if the source SHA-256 differs")
    parser.add_argument("--json", action="store_true", help="print JSON instead of the text report")
    args = parser.parse_args(argv)

    path = os.path.abspath(args.csv_path)
    sha_before = sha256_file(path)
    if args.expected_sha256 and sha_before != args.expected_sha256.lower():
        print(f"source SHA-256 {sha_before} != expected {args.expected_sha256}", file=sys.stderr)
        return 2
    audit = run_audit(path)
    provenance = sidecar_provenance(path, sha_before)
    sha_after = sha256_file(path)
    if sha_after != sha_before:
        print("source CSV changed during the audit", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({"status": AUDIT_STATUS, "source": path, "sha256": sha_before,
                          "provenance": provenance, **_jsonable(audit)}, indent=2, default=list))
    else:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        print(format_report(audit, path, sha_before, sha_after, provenance), end="")
    return 0 if all(ok for _, ok, _ in audit["invariants"]) else 1


if __name__ == "__main__":
    sys.exit(main())
