"""Verify the portable inputs and invoke the frozen, offline STEP 5E runner."""
import argparse
import csv
from dataclasses import asdict
from importlib import metadata
import os
from pathlib import Path
import platform
import re
import struct
import subprocess
import sys

PACKAGE = Path(__file__).resolve().parents[1]
SRC = PACKAGE / "src"
PROTOCOL = PACKAGE / "config/protocol.json"
METHODS = ("E0", "Fixed_2_matched", "Uniform_85", "V2_85")
INPUT_FILES = {"intake.json", "approvals.csv", "candidates.csv", "approval_record.json"}
OPTIONAL_REFERENCE = "reference_predictions.csv"
CLIP_FILES = {"recording.json", "frames.jsonl", "end.json"}
FRAME_COUNT = 2078
WINDOW_COUNT = 6
sys.path.insert(0, str(SRC))
from research_b_final_validation import LABELS, approved_source, digest, read, require, validate_intake, verify_protocol


def verify_package():
    pins = PACKAGE.joinpath("requirements.txt").read_text(encoding="utf-8").splitlines()
    require(platform.system() == "Windows" and struct.calcsize("P") == 8 and platform.python_version() == "3.12.10",
            "Use the benchmark's Windows x64 Python 3.12.10 interpreter")
    require(all(metadata.version(name) == version for line in pins if line and not line.startswith("#")
                for name, version in [line.split("==")]), "One or more Python distribution versions differ")
    try:
        contrib = metadata.version("opencv-contrib-python")
    except metadata.PackageNotFoundError:
        contrib = None
    require(contrib is None, "Use the reference OpenCV provider only; cv2 namespaces collide")
    public = read(PACKAGE / "manifests/code_sha256.json")
    for relative, checksum in public.items():
        path = checked_path(PACKAGE, relative)
        require(digest(path) == checksum, f"Code package fingerprint mismatch: {relative}")
    verify_protocol(read(PROTOCOL))
    print(f"CODE_SHA256_OK {len(public)} package files", flush=True)


def checked_path(root, relative):
    root = root.resolve(strict=True)
    part = Path(relative)
    require(not part.is_absolute() and not part.drive and not any(p == ".." for p in part.parts),
            "Only relative paths inside declared slots are allowed")
    path = root.joinpath(part).resolve(strict=True)
    require(path.is_file() and path.is_relative_to(root), "File is outside its selected slot")
    return path


def verify_transfer(args):
    from research_b_label_validation import csv_rows

    tasks = {item["filename"] for item in read(SRC / "mediapipe_model_lock.json")["artifacts"]}
    roots = {"clip": args.clip, "inputs": args.inputs, "tasks": SRC / "models"}
    rows = csv_rows(args.manifest)
    seen = {slot: set() for slot in (*roots, "artifact")}
    for row in rows:
        slot, relative = row["slot"], row["delivery_relative"]
        require(slot in seen and relative not in seen[slot], "Unexpected transfer slot or duplicate file")
        if slot == "artifact":
            require(relative == "model.pkl", "Unexpected model manifest entry")
            path = args.artifact.resolve(strict=True)
        else:
            path = checked_path(roots[slot], relative)
        require(re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) is not None
                and path.stat().st_size == int(row["bytes"]) and digest(path) == row["sha256"],
                f"Transfer SHA-256/size mismatch in {slot} slot: {relative}")
        seen[slot].add(relative)
    require(seen["artifact"] == {"model.pkl"} and seen["tasks"] == tasks
            and INPUT_FILES <= seen["inputs"] <= INPUT_FILES | {OPTIONAL_REFERENCE}
            and CLIP_FILES <= seen["clip"], "Missing required transfer manifest entries")
    extra = seen["clip"] - CLIP_FILES
    require(len(extra) == FRAME_COUNT and all(Path(name).suffix == ".npz" for name in extra),
            "Transfer manifest needs every original paired NPZ")
    print(f"TRANSFER_SHA256_OK {len(rows)} files", flush=True)


def verified_schedule(clip, inputs):
    from research_b_label_validation import approval_schedule, csv_rows, read_clock

    protocol = read(PROTOCOL)
    intake = read(inputs / "intake.json")
    validate_intake(intake, protocol["binding"])
    require(intake["cohort"] == "ENGINEERING" and intake["origin"] == "LOCAL" and intake["source_kind"] == "NPZ_CLIP",
            "This package is pinned to the approved development clip")
    require(all(w["label"] is None and w["label_status"] == "UNVERIFIED" and w.get("label_review_reference") is None
                for w in intake["windows"]), "Replay intake must contain no posture ground truth")
    evidence = read(inputs / "approval_record.json")
    require(evidence.get("status") == "VERIFIED" and evidence.get("fully_approved") == WINDOW_COUNT
            and evidence.get("classification_scope") == "DEVELOPMENT_CLIP2"
            and evidence.get("replay_input_has_ground_truth") is False, "Missing exact approval evidence")
    require(evidence["protocol_sha256"] == digest(PROTOCOL)
            and evidence["model_artifact_sha256"] == protocol["binding"]["artifact_sha256"]
            and evidence["clip_source_hashes"] == intake["source_hashes"], "Approval provenance differs from pinned inputs")
    approvals, candidates = inputs / "approvals.csv", inputs / "candidates.csv"
    require(digest(approvals) == evidence["approved_csv_sha256"]
            and digest(candidates) == evidence["candidate_csv_sha256"], "Approval/candidate fingerprint mismatch")
    source = approved_source(clip, intake)
    times = read_clock(source / "frames.jsonl")
    schedule = approval_schedule(csv_rows(candidates), csv_rows(approvals), times)
    require(len(times) == FRAME_COUNT and all(row["verified"] for row in schedule)
            and [row["posture"] for row in schedule] == list(LABELS), "Expected six fully approved P0–P5 windows")
    require(evidence["approved_windows"] == [dict(id=r["id"], posture=r["posture"], **asdict(r["bounds"])) for r in schedule],
            "Approval record differs from bounded source clock")
    require([(w["id"], w["start_ms"], w["end_ms"], w["closing_input_ms"]) for w in intake["windows"]]
            == [(r["id"], r["bounds"].start_ms, r["bounds"].end_ms, r["bounds"].closing_ms) for r in schedule],
            "Replay Start or closing event differs from the approval record")
    return intake, times, schedule


def private_output(destination):
    path = destination.resolve()
    require(not path.is_relative_to(PACKAGE), "Keep generated benchmark files outside the code package")
    return path


def runner(args, *, run):
    env = os.environ.copy()
    for key in ("PYTHONPATH", "PYTHONHOME"):
        env.pop(key, None)
    env["PYTHONNOUSERSITE"] = "1"
    command = [sys.executable, "-E", "-s", "-B", "-X", "utf8", str(SRC / "research_b_final_validation.py"),
               "run" if run else "inspect", "--protocol", str(PROTOCOL),
               "--intake", str(args.inputs.resolve() / "intake.json"), "--source", str(args.clip.resolve())]
    if run:
        command += ["--artifact", str(args.artifact.resolve()), "--hardware", str(args.hardware.resolve()),
                    "--pc-id", args.pc_id, "--output", str(private_output(args.output)),
                    "--repeats", str(args.repeats), "--pacing", "throughput"]
        if args.engineering_smoke:
            command.append("--engineering-smoke")
    subprocess.run(command, cwd=SRC, env=env, check=True)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    commands = cli.add_subparsers(dest="command", required=True)
    for operation in ("inspect", "run"):
        parser = commands.add_parser(operation)
        for name in ("manifest", "clip", "inputs", "artifact"):
            parser.add_argument("--" + name, type=Path, required=True)
    run = commands.choices["run"]
    for name in ("hardware", "output"):
        run.add_argument("--" + name, type=Path, required=True)
    run.add_argument("--pc-id", required=True)
    run.add_argument("--repeats", type=int, default=3)
    run.add_argument("--engineering-smoke", action="store_true")
    args = cli.parse_args()
    verify_package()
    intake = read(args.inputs / "intake.json")
    validate_intake(intake, read(PROTOCOL)["binding"])
    require(intake["origin"] == "LOCAL" and intake["cohort"] == "ENGINEERING",
            "This package accepts only the approved development clip")
    verify_transfer(args)
    verified_schedule(args.clip, args.inputs)
    print(f"APPROVED_SCHEDULE_OK {WINDOW_COUNT} windows, {FRAME_COUNT} pairs", flush=True)
    runner(args, run=args.command == "run")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, metadata.PackageNotFoundError, subprocess.CalledProcessError) as error:
        raise SystemExit(str(error)) from error
