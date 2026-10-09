"""
바른자세 녹화 파일 분석 스크립트 (Intel RealSense D455 .db3/.bag)

녹화 파일에서 매 프레임마다 얼굴·양어깨를 찾고(MediaPipe, 원 논문과 같은 계열),
깊이를 붙여 아래 값을 다시 계산합니다. 옛 버전 capture 코드로 찍은 파일도 그대로 됩니다.

  [원 논문 방식 - 일반 웹캠으로도 가능]
    얼굴 면적(px), 얼굴 중심 x·y, 얼굴-어깨 각도 θ1·θ2·θ3(근사 재구성), 면적 비율 A
  [스테레오 깊이가 있어야 가능]
    얼굴 깊이 Z_f, 어깨 깊이 Z_s, 얼굴 전방 이동 ΔZ_f, 어깨 전방 이동 ΔZ_s,
    어깨 대비 머리 전방 이동 D_head = ΔZ_f - ΔZ_s, 실제 얼굴 크기 S(cm²)
  [측정 품질 / 교수님 보충: 해상도·픽셀·세그먼트]
    얼굴 박스 폭(px), 정상 자세 20초 동안의 흔들림, 면적 상대오차 추정(2δ/w),
    얼굴 외곽선(세그먼트) 면적 - 머리카락·배경을 뺀 얼굴 영역, 박스/외곽선 비율,
    눈 사이 실제 거리(깊이·보정값 점검용)

설치 (한 번만):
    pip install mediapipe matplotlib pyrealsense2 opencv-python numpy
사용법:
    python analyze_d455.py P01            # data 폴더의 P01_r*.db3 전부 분석
    python analyze_d455.py P01 P02        # 두 사람 함께 분석 (실제 얼굴 크기 비교 포함)
    python analyze_d455.py P01 --step 2   # 2프레임마다 1장 분석 (빠르게)
    python analyze_d455.py P01 P02 --from-csv   # 이미 분석한 CSV로 요약·그래프만 다시 (수 초)
    # provenance 없는 과거 pilot raw/CSV에는 --legacy-pilot을 명시해야 합니다.

결과: analysis 폴더 (기존 평면 출력 + recording/run별 불변 사본 및 analysis_manifest.json)
    <파일>_frames.csv     프레임별 모든 값
    summary_steps.csv     회차·단계별 요약 (중앙값, 흔들림, 정상 자세 대비 변화량)
    summary_report.txt    발표용 요약 문장
    fig1_timeline_*.png   회차별 얼굴·어깨 전방 이동 시간 그래프
    fig2_fh_vs_bf.png     거북목 vs 몸 전체 앞으로 비교 (A, ΔZ_f, ΔZ_s, D_head)
    fig3_face_size.png    픽셀 면적 vs 실제 얼굴 크기
"""
import argparse
import bisect
import csv
from datetime import datetime, timezone
import glob
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
import uuid
import warnings

warnings.filterwarnings("ignore", message=".*Glyph.*")

import cv2
import numpy as np

DATA_DIR = "data"
OUT_DIR = "analysis"
MODEL_DIR = "models"
MODEL_LOCK_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mediapipe_model_lock.json")
MODEL_FILENAMES = {
    "face": "blaze_face_short_range.tflite",
    "mesh": "face_landmarker.task",
    "pose": "pose_landmarker_full.task",
}
MODEL_SOURCE_PATHS = {
    "face": "/mediapipe-models/face_detector/blaze_face_short_range/float16/",
    "mesh": "/mediapipe-models/face_landmarker/face_landmarker/float16/",
    "pose": "/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/",
}
# 얼굴 외곽선(턱선~이마) 랜드마크 순서 - 머리카락·배경을 제외한 얼굴 영역(세그먼트)
FACE_OVAL = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377,
             152, 148, 176, 149, 150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109]
IRIS_L, IRIS_R = 468, 473   # 양쪽 홍채 중심 (눈 사이 거리 점검용)
TRIM_START, TRIM_END = 1.0, 0.5   # 각 자세 구간 앞 1초, 뒤 0.5초 제외
BOUNDARY_DELTA_PX = 2.0           # 면적 상대오차 추정용 경계 오차 가정 (2δ/w)
# 기존 runtime literal을 provenance와 공유한다. 값/계산 규칙은 변경하지 않는다.
FACE_MIN_DETECTION_CONFIDENCE = 0.5
FACE_NUM_FACES, POSE_NUM_POSES = 1, 1
LANDMARK_RUNNING_MODE = "VIDEO"
SHOULDER_L, SHOULDER_R = 11, 12
HIP_L, HIP_R = 23, 24
FACE_DEPTH_ROI_MIN, FACE_DEPTH_ROI_MAX = 0.25, 0.75
OVAL_DEPTH_HALF_WIDTH_PX, SHOULDER_DEPTH_HALF_WIDTH_PX = 15, 6
DEPTH_MIN_VALID_PIXELS = 10

FRAME_SCHEMA_VERSION = "frames-schema/1.0.0"
LEGACY_FRAME_FIELDS = (
    "subject", "round", "step", "label", "t", "ts_ms",
    "face_x", "face_y", "face_w_px", "face_h_px", "face_area_px", "face_score",
    "z_face_m", "face_size_cm2", "oval_area_px", "oval_size_cm2", "ipd_px", "ipd_cm",
    "box_to_oval", "lsh_x", "lsh_y", "rsh_x", "rsh_y", "lsh_vis", "rsh_vis",
    "z_lsh_m", "z_rsh_m", "z_sh_m", "theta1_deg", "theta2_deg", "theta3_deg",
)
FRAME_STATE_FIELDS = (
    "frame_schema_version", "recording_id", "analysis_run_id", "frame_index",
    "color_frame_number", "depth_frame_number", "mediapipe_ts_ms", "face_depth_source",
    "face_detected", "face_mesh_detected", "pose_detected", "face_depth_valid",
    "lsh_valid", "rsh_valid", "lsh_depth_valid", "rsh_depth_valid", "shoulder_depth_source",
)
HIP_FRAME_FIELDS = (
    "left_hip_x_px", "left_hip_y_px", "left_hip_depth_m", "left_hip_visibility",
    "left_hip_valid", "left_hip_depth_valid", "right_hip_x_px", "right_hip_y_px",
    "right_hip_depth_m", "right_hip_visibility", "right_hip_valid", "right_hip_depth_valid",
)
FRAME_FIELDS = LEGACY_FRAME_FIELDS + FRAME_STATE_FIELDS + HIP_FRAME_FIELDS
FRAME_BOOL_FIELDS = frozenset((
    "face_detected", "face_mesh_detected", "pose_detected", "face_depth_valid",
    "lsh_valid", "rsh_valid", "lsh_depth_valid", "rsh_depth_valid",
    "left_hip_valid", "left_hip_depth_valid", "right_hip_valid", "right_hip_depth_valid",
))
FRAME_TEXT_FIELDS = frozenset((
    "subject", "round", "step", "label", "frame_schema_version", "recording_id",
    "analysis_run_id", "face_depth_source", "shoulder_depth_source",
))
FRAME_ENUMS = {
    "face_depth_source": frozenset(("bbox_roi", "oval_center_roi", "missing")),
    "shoulder_depth_source": frozenset(("both", "left_only", "right_only", "missing")),
}

POSTURE_KO = {"upright": "정상", "forward_head": "거북목", "body_forward": "몸 전체 앞으로",
              "lean_back": "뒤로 기울임", "lean_left": "왼쪽 기울임", "lean_right": "오른쪽 기울임"}


# ---------------------------------------------------------------- provenance (수치 계산과 별도)
def utc_now():
    return datetime.now(timezone.utc)


def new_analysis_id():
    return f"ar_{utc_now().strftime('%Y%m%dT%H%M%S%fZ')}_{uuid.uuid4().hex}"


def provenance_unknown(reasons, field, error):
    reasons[field] = str(error)
    print(f"[경고] analysis provenance {field}: {error}", file=sys.stderr)


def artifact_info(path, reasons):
    """전체 byte streaming hash. mtime/size를 내용 hash 대신 사용하지 않는다."""
    result = {"filename": os.path.basename(path), "path": os.path.abspath(path),
              "size_bytes": None, "mtime_ns": None, "sha256": None, "hash_status": "unavailable"}
    try:
        before = os.stat(path)
        result.update(size_bytes=before.st_size, mtime_ns=before.st_mtime_ns)
        digest = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(chunk)
        after = os.stat(path)
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise OSError("file changed while hashing")
        result.update(sha256=digest.hexdigest(), hash_status="complete")
    except OSError as error:
        provenance_unknown(reasons, os.path.abspath(path), error)
    return result


def analysis_environment(reasons):
    versions = {}
    for field, getter in (("python", platform.python_version), ("os", platform.platform),
                          ("architecture", platform.machine)):
        try:
            versions[field] = getter()
        except Exception as error:
            versions[field] = None
            provenance_unknown(reasons, "environment." + field, error)
    for package in ("mediapipe", "pyrealsense2", "opencv-python", "numpy", "matplotlib"):
        try:
            versions[package] = importlib.metadata.version(package)
        except Exception as error:
            versions[package] = None
            provenance_unknown(reasons, "environment." + package, error)
    return versions


def analysis_code(reasons):
    script = os.path.abspath(__file__)
    code = {"git_commit": None, "git_dirty": None,
            "analyze_script_sha256": artifact_info(script, reasons)["sha256"], "path": script}
    for key, args in (("git_commit", ["rev-parse", "HEAD"]),
                      ("git_dirty", ["status", "--porcelain", "--untracked-files=normal"])):
        try:
            value = subprocess.run(["git", *args], cwd=os.path.dirname(script),
                                   capture_output=True, text=True, check=True, timeout=3).stdout.strip()
            if key == "git_commit" and not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value):
                raise ValueError("Git HEAD unavailable")
            code[key] = bool(value) if key == "git_dirty" else value
        except (OSError, subprocess.SubprocessError, ValueError) as error:
            provenance_unknown(reasons, "code." + key, error)
    return code


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path, value):
    fd, temporary = tempfile.mkstemp(prefix=".manifest-", suffix=".tmp", dir=os.path.dirname(os.path.abspath(path)))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(value, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def csv_identity(path, field="recording_id"):
    """파일에 존재하는 ID만 확인. 없는 ID는 외부 metadata로 보완하지 않는다."""
    if not os.path.exists(path):
        return {field: None, "identity_status": "missing_file"}
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if field not in (reader.fieldnames or []):
            return {field: None, "identity_status": "legacy_no_id_column"}
        values = {row[field] for row in reader if row.get(field) not in (None, "")}
    if len(values) > 1:
        raise ValueError(f"inconsistent {field} in {path}")
    return {field: next(iter(values), None), "identity_status": "verified" if values else "empty_id_column"}


def json_identity(path):
    if not os.path.exists(path):
        return {"recording_id": None, "identity_status": "missing_file"}
    value = read_json(path).get("recording_id")
    if value not in (None, ""):
        safe_recording_id(value)
    return {"recording_id": value or None,
            "identity_status": "verified" if value else "legacy_no_id_field"}


def new_recording_name(path, from_csv=False):
    stem = os.path.splitext(os.path.basename(path))[0]
    if from_csv and stem.endswith("_frames"):
        stem = stem[:-len("_frames")]
    return bool(re.fullmatch(r"[A-Za-z0-9-]+_r[0-9]+_[0-9]{8}_[0-9]{6}_[0-9]{6}_[a-fA-F0-9]{32}", stem))


def known_frames_output(path, sha256):
    # 이전 출력인지 확인만 한다. 최신 run 선택이나 lineage 자동 복구는 하지 않는다.
    for manifest_path in glob.glob(os.path.join(OUT_DIR, "*", "ar_*", "analysis_manifest.json")):
        for output in read_json(manifest_path).get("outputs", []):
            if output.get("kind") == "frames" and (
                    os.path.abspath(path) in (output.get("path"), output.get("compatibility_path")) or
                    (sha256 is not None and output.get("sha256") == sha256)):
                return True
    return False


def processing_settings(from_csv):
    settings = {"raw_extraction_applied": not from_csv, "boundary_delta_px": BOUNDARY_DELTA_PX}
    if not from_csv:
        settings.update(
            trim_start_s=TRIM_START, trim_end_s=TRIM_END, depth_alignment_target="color",
            face_oval_indices=FACE_OVAL, iris_indices=[IRIS_L, IRIS_R], shoulder_indices=[SHOULDER_L, SHOULDER_R],
            hip_indices=[HIP_L, HIP_R],
            tasks={"face": {"min_detection_confidence": FACE_MIN_DETECTION_CONFIDENCE,
                            "running_mode": None, "running_mode_source": "SDK default; recorded at runtime"},
                   "mesh": {"num_faces": FACE_NUM_FACES, "running_mode": LANDMARK_RUNNING_MODE},
                   "pose": {"num_poses": POSE_NUM_POSES, "running_mode": LANDMARK_RUNNING_MODE}},
            depth_roi={"face_bbox_fraction": [FACE_DEPTH_ROI_MIN, FACE_DEPTH_ROI_MAX],
                       "oval_center_half_width_px": OVAL_DEPTH_HALF_WIDTH_PX,
                       "shoulder_half_width_px": SHOULDER_DEPTH_HALF_WIDTH_PX,
                       "min_valid_pixels": DEPTH_MIN_VALID_PIXELS, "valid_rule": "raw_depth > 0",
                       "bounds": "int truncation, clip to image, half-open slice",
                       "reduction": "median(raw valid pixels) * playback depth_scale"},
            face_selection="largest bbox area", face_depth_fallback="oval center when bbox depth is None",
            shoulder_depth_reduction="mean of available nonzero shoulder depths",
            video_timestamp_rule="int(ts_ms); previous+1 if not strictly increasing")
    return settings


def safe_recording_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("unsafe or missing recording_id")
    return value


def legacy_recording_id(path, artifact, from_csv):
    if artifact["sha256"] is None:
        raise ValueError("legacy identity requires a full input SHA-256")
    stem = os.path.splitext(os.path.basename(path))[0]
    stem = re.sub(r"[^A-Za-z0-9_-]", "-", stem)
    prefix = "legacy_csv_" if from_csv else "legacy_"
    candidate = prefix + stem + "_" + artifact["sha256"][:16]
    # Prefix collision 확인만 수행. 기존 실행을 입력으로 자동 선택하지 않는다.
    for manifest_path in glob.glob(os.path.join(OUT_DIR, candidate, "ar_*", "analysis_manifest.json")):
        prior = read_json(manifest_path)
        key = "frames" if from_csv else "recording"
        previous_hash = prior["inputs"].get(key, {}).get("sha256")
        if previous_hash is not None and previous_hash != artifact["sha256"]:
            return prefix + stem + "_" + artifact["sha256"]
    return candidate


def validate_raw_identity(raw_sha256, recording_id, analysis_dir=None):
    """DF-1: all recorded raw identity evidence, including failed/running runs."""
    index = {}
    root = OUT_DIR if analysis_dir is None else analysis_dir
    for path in sorted(glob.glob(os.path.join(root, "*", "ar_*", "analysis_manifest.json"))):
        manifest = read_json(path)
        digest = (manifest.get("inputs", {}).get("recording") or {}).get("sha256")
        identity = manifest.get("recording_id")
        if (manifest.get("analysis_mode") == "extract_raw" and
                isinstance(identity, str) and identity.strip() and
                isinstance(digest, str) and re.fullmatch(r"[a-fA-F0-9]{64}", digest)):
            index.setdefault(digest.lower(), set()).add(identity)
    if any(len(ids) > 1 for ids in index.values()):
        raise ValueError("repository raw identity conflict: same raw SHA-256 has multiple recording IDs")
    if raw_sha256 is None:
        raise ValueError("raw identity requires a full input SHA-256")
    if index.get(raw_sha256.lower(), {recording_id}) != {recording_id}:
        raise ValueError("raw identity conflict: same raw SHA-256 has another recording_id")


def start_analysis_run(path, args, batch_id):
    reasons = {}
    legacy_pilot = bool(getattr(args, "legacy_pilot", False))
    legacy_reason = None
    print(f"[입력 SHA-256] {path} (전체 파일 streaming 읽기)")
    artifact = artifact_info(path, reasons)
    inputs, parent, models = {}, None, []
    if args.from_csv:
        inputs["frames"] = artifact
        frame_identity = csv_identity(path)
        frame_run = csv_identity(path, "analysis_run_id")
        inputs["frames"].update(frame_identity)
        link_path = path + ".provenance.json"
        if os.path.exists(link_path):
            link = read_json(link_path)
            if artifact["sha256"] is None or link["frames_sha256"] != artifact["sha256"]:
                raise ValueError(f"frames provenance hash mismatch: {path}")
            manifest_path = os.path.join(os.path.dirname(link_path), link["analysis_manifest"])
            parent_artifact = artifact_info(manifest_path, reasons)
            if parent_artifact["sha256"] is None or parent_artifact["sha256"] != link["analysis_manifest_sha256"]:
                raise ValueError(f"parent manifest hash mismatch: {path}")
            previous = read_json(manifest_path)
            if previous["status"] != "completed":
                raise ValueError("source analysis run is not completed")
            recording_id = safe_recording_id(previous["recording_id"])
            parent = previous["analysis_run_id"]
            if parent != link["analysis_run_id"] or recording_id != link["recording_id"]:
                raise ValueError("frames/parent identity mismatch")
            if ((frame_identity["recording_id"] is not None and frame_identity["recording_id"] != recording_id) or
                    (frame_run["analysis_run_id"] is not None and frame_run["analysis_run_id"] != parent) or
                    (new_recording_name(path, True) and
                     os.path.splitext(os.path.basename(path))[0][:-len("_frames")] != recording_id)):
                raise ValueError("frames/parent identity mismatch")
            if not any(o.get("kind") == "frames" and o.get("sha256") == artifact["sha256"]
                       and o.get("filename") == os.path.basename(path)
                       for o in previous["outputs"]):
                raise ValueError("frames not listed in parent outputs")
            role, protocol = previous["dataset_role"], previous["protocol_version"]
            models = [dict(m, used_in_this_run=False, source_analysis_run_id=parent)
                      for m in previous["models"]]
            inputs["parent_manifest"] = parent_artifact
            inputs["frames_provenance"] = artifact_info(link_path, reasons)
            identity_status = "linked_parent"
        else:
            if (new_recording_name(path, True) or frame_identity["identity_status"] != "legacy_no_id_column" or
                    frame_run["identity_status"] != "legacy_no_id_column" or
                    os.path.exists(os.path.join(os.path.dirname(path), "analysis_manifest.json")) or
                    known_frames_output(path, artifact["sha256"])):
                raise ValueError("provenance-aware frames require a verified provenance sidecar")
            if not legacy_pilot:
                raise ValueError("legacy CSV requires explicit --legacy-pilot")
            recording_id = legacy_recording_id(path, artifact, True)
            role, protocol, identity_status = "pilot", "unknown_legacy", "unresolved_raw"
            legacy_reason = "no provenance sidecar, ID columns, or known modern output identity"
            provenance_unknown(reasons, "parent_analysis_run_id", "legacy CSV without verified provenance sidecar")
        inputs["frames"]["analysis_run_id"] = parent
    else:
        inputs["recording"] = artifact
        base = os.path.splitext(path)[0]
        inputs["capture_metadata"] = artifact_info(base + "_camera.json", reasons)
        capture = read_json(base + "_camera.json") if os.path.exists(base + "_camera.json") else {}
        inputs["markers"] = artifact_info(base + "_markers.csv", reasons)
        inputs["markers"].update(csv_identity(base + "_markers.csv"))
        inputs["quality"] = artifact_info(base + "_quality.json", reasons)
        inputs["quality"].update(json_identity(base + "_quality.json"))
        observed_ids = {value for value in (capture.get("recording_id"), inputs["markers"]["recording_id"],
                                            inputs["quality"]["recording_id"]) if value not in (None, "")}
        if len(observed_ids) > 1:
            raise ValueError("capture/markers/quality recording_id mismatch")
        if capture.get("recording_id"):
            recording_id = safe_recording_id(capture["recording_id"])
            if capture.get("record_file") != os.path.basename(path):
                raise ValueError("capture metadata record_file mismatch")
            if recording_id != os.path.basename(base):
                raise ValueError("capture metadata recording_id/filename mismatch")
            role, protocol = capture.get("dataset_role"), capture.get("protocol_version")
            if role not in ("pilot", "formal", "external"):
                raise ValueError("invalid capture dataset_role")
            identity_status = "capture_metadata"
        else:
            if (new_recording_name(path) or observed_ids or "recording_id" in capture or
                    (capture.get("schema_version") or "").startswith("capture-provenance/") or
                    capture.get("protocol_version") not in (None, "", "unknown_legacy") or
                    capture.get("dataset_role") in ("formal", "external") or
                    inputs["markers"]["identity_status"] in ("verified", "empty_id_column")):
                raise ValueError("new recording requires capture metadata recording_id; legacy downgrade forbidden")
            if not legacy_pilot:
                raise ValueError("legacy raw recording requires explicit --legacy-pilot")
            recording_id = legacy_recording_id(path, artifact, False)
            role, protocol, identity_status = "pilot", "unknown_legacy", "legacy_raw"
            legacy_reason = "no capture recording_id or modern filename/metadata/sidecar identity"
        if role == "formal" and any(inputs[k]["sha256"] is None for k in ("recording", "markers")):
            raise ValueError("formal input requires full recording/markers hashes")
    if legacy_pilot and role in ("formal", "external"):
        raise ValueError("--legacy-pilot conflicts with formal/external dataset_role")
    if not args.from_csv:
        validate_raw_identity(artifact["sha256"], recording_id)
    directory = os.path.join(OUT_DIR, recording_id)
    os.makedirs(directory, exist_ok=True)
    if not args.from_csv and artifact["sha256"] is not None:
        for manifest_path in glob.glob(os.path.join(directory, "ar_*", "analysis_manifest.json")):
            previous_hash = read_json(manifest_path)["inputs"].get("recording", {}).get("sha256")
            if previous_hash is not None and previous_hash != artifact["sha256"]:
                raise ValueError("same recording_id has different raw content")
    while True:
        run_id = new_analysis_id()
        run_dir = os.path.join(directory, run_id)
        try:
            os.mkdir(run_dir)
            break
        except FileExistsError:
            continue
    manifest = {
        "schema_version": "analysis-provenance/1.0.0", "analysis_run_id": run_id,
        "analysis_batch_id": batch_id, "recording_id": recording_id,
        "analysis_mode": "summarize_existing_frames" if args.from_csv else "extract_raw",
        "parent_analysis_run_id": parent, "dataset_role": role, "protocol_version": protocol,
        "legacy_input": None if legacy_reason is None else {
            "reason": legacy_reason, "original_recording_id": None,
            "id_generation": "legacy[_csv]_<sanitized input stem>_<SHA-256 prefix; expanded on collision>",
            "identity_source_input": "frames" if args.from_csv else "recording",
            "historical_provenance": "unknown",
        },
        "identity_status": identity_status, "started_at": utc_now().isoformat(), "ended_at": None,
        "status": "running", "inputs": inputs, "code": analysis_code(reasons),
        "environment": analysis_environment(reasons), "models": models, "inference_performed": False,
        "options": {"argv": sys.argv[1:], "subjects": args.subjects, "from_csv": args.from_csv,
                    "legacy_pilot": legacy_pilot,
                    "step_requested": args.step, "step_effective": None if args.from_csv else max(1, args.step)},
        "processing_settings": processing_settings(args.from_csv),
        "playback_calibration": None, "outputs": [], "errors": [], "provenance_unknown_reasons": reasons,
    }
    write_json(os.path.join(run_dir, "analysis_manifest.json"), manifest)
    return run_dir, manifest


def record_model_artifacts(manifest, paths, lock=None):
    lock = load_model_lock() if lock is None else lock
    manifest["models"] = [dict(verify_model_artifact(paths[role], entry),
                               role=role, source_url=entry["source_url"], source_url_kind="configured_download_url",
                               version_identifier=entry["version_identifier"], used_in_this_run=False)
                          for role, entry in lock.items()]


def mark_model_used(manifest, role):
    if manifest is not None:
        manifest["inference_performed"] = True
        for model in manifest["models"]:
            if model["role"] == role:
                model["used_in_this_run"] = True


def record_task_options(manifest, role, options):
    if manifest is None:
        return
    values = manifest["processing_settings"]["tasks"][role]
    for name in ("running_mode", "min_detection_confidence", "min_suppression_threshold", "num_faces", "num_poses",
                 "min_face_detection_confidence", "min_face_presence_confidence", "min_tracking_confidence",
                 "min_pose_detection_confidence", "min_pose_presence_confidence", "output_face_blendshapes",
                 "output_facial_transformation_matrixes", "output_segmentation_masks"):
        if hasattr(options, name):
            value = getattr(options, name)
            values[name] = getattr(value, "name", value)
    if "running_mode_source" in values and hasattr(options, "running_mode"):
        values["running_mode_source"] = "runtime options"


def archive_output(path, directory, manifest, kind, row_count=None):
    destination = os.path.join(directory, os.path.basename(path))
    # 신규 run 경로에서도 기존 artifact를 덮어쓰지 않는다.
    if os.path.abspath(path) != os.path.abspath(destination):
        with open(path, "rb") as source, open(destination, "xb") as target:
            shutil.copyfileobj(source, target)
    item = artifact_info(destination, manifest["provenance_unknown_reasons"])
    item.update(kind=kind, row_count=row_count, schema_version=None, compatibility_path=os.path.abspath(path))
    manifest["outputs"].append(item)
    return item


def finished_manifest(manifest, error=None, ended_at=None):
    result = dict(manifest, ended_at=ended_at or utc_now().isoformat(),
                  status="failed" if error is not None else "completed", errors=list(manifest["errors"]))
    if error is not None:
        result["errors"].append(str(error))
    return result


def finish_analysis_run(directory, manifest, error=None, ended_at=None):
    if manifest["status"] != "running":
        return  # terminal 상태를 뒤집지 않는다.
    result = finished_manifest(manifest, error, ended_at)
    write_json(os.path.join(directory, "analysis_manifest.json"), result)
    manifest.update(result)


# ---------------------------------------------------------------- 준비
def load_model_lock(path=None):
    """Validate the tracked artifact contract before raw inference/provisioning."""
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate model lock JSON key: {key}")
            result[key] = value
        return result

    path = MODEL_LOCK_PATH if path is None else path
    try:
        with open(path, encoding="utf-8") as source:
            value = json.load(source, object_pairs_hook=unique_object)
    except (OSError, ValueError) as error:
        raise ValueError(f"cannot load model lock {path}: {error}") from error
    if not isinstance(value, dict) or set(value) != {"lock_schema_version", "artifacts"}:
        raise ValueError("invalid model lock top-level structure")
    if value["lock_schema_version"] != "mediapipe-model-lock/1.0.0":
        raise ValueError(f"unsupported model lock schema: {value['lock_schema_version']!r}")
    if not isinstance(value["artifacts"], list):
        raise ValueError("malformed model lock artifacts collection")
    lock = {}
    fields = {"role", "filename", "source_url", "version_identifier", "sha256"}
    for entry in value["artifacts"]:
        if not isinstance(entry, dict) or set(entry) != fields or any(
                not isinstance(entry[field], str) or not entry[field] for field in fields):
            raise ValueError("invalid model lock artifact fields")
        role = entry["role"]
        if role not in MODEL_FILENAMES:
            raise ValueError(f"unknown model lock role: {role}")
        if role in lock:
            raise ValueError(f"duplicate model lock role: {role}")
        if entry["filename"] != MODEL_FILENAMES[role]:
            raise ValueError(f"invalid model lock filename for {role}: {entry['filename']}")
        if re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]) is None:
            raise ValueError(f"invalid canonical SHA-256 for {role}: {entry['sha256']}")
        validate_model_source(entry)
        lock[role] = entry
    if set(lock) != set(MODEL_FILENAMES):
        raise ValueError(f"missing model lock roles: {sorted(set(MODEL_FILENAMES) - set(lock))}")
    return {role: lock[role] for role in MODEL_FILENAMES}


def validate_model_source(entry):
    role, source, version = entry["role"], entry["source_url"], entry["version_identifier"]
    url = urllib.parse.urlsplit(source)
    prefix = MODEL_SOURCE_PATHS[role]
    suffix = "/" + entry["filename"]
    if (url.geturl() != source or any(char.isspace() for char in source) or
            url.scheme != "https" or url.netloc != "storage.googleapis.com" or url.fragment or
            not url.path.startswith(prefix) or not url.path.endswith(suffix)):
        raise ValueError(f"invalid model lock source_url for {role}: {source}")
    locator = url.path[len(prefix):-len(suffix)]
    if re.fullmatch(r"[1-9][0-9]*", locator) and not url.query and version == locator:
        return
    generation = re.fullmatch(r"generation=([1-9][0-9]*)", url.query)
    if (role == "pose" and locator == "latest" and generation and
            version == "gcs-generation:" + generation[1]):
        return
    raise ValueError(f"invalid model lock source/version contract for {role}: {source} / {version}")


def verify_model_artifact(path, entry):
    """Return actual filesystem provenance only after a complete matching hash."""
    info = artifact_info(path, {})
    if info["hash_status"] != "complete":
        raise OSError(f"cannot completely hash model artifact: {os.path.abspath(path)}")
    if info["sha256"] != entry["sha256"]:
        raise ValueError(f"model artifact SHA-256 mismatch: {os.path.abspath(path)}\n"
                         f"expected SHA-256: {entry['sha256']}\nactual SHA-256: {info['sha256']}")
    return info


def provision_model_artifact(path, entry):
    if os.path.lexists(path):
        verify_model_artifact(path, entry)
        return
    fd, temporary = tempfile.mkstemp(prefix=".model-", suffix=".tmp", dir=os.path.dirname(path))
    os.close(fd)
    try:
        print(f"[모델 다운로드] {entry['filename']} ...")
        urllib.request.urlretrieve(entry["source_url"], temporary)
        verify_model_artifact(temporary, entry)
        try:
            # Atomic publication without replacement; both paths are on the same filesystem.
            os.link(temporary, path)
        except FileExistsError:
            verify_model_artifact(path, entry)
    finally:
        os.unlink(temporary)


def ensure_models(lock=None):
    lock = load_model_lock() if lock is None else lock
    os.makedirs(MODEL_DIR, exist_ok=True)
    paths = {role: os.path.join(MODEL_DIR, entry["filename"]) for role, entry in lock.items()}
    # Diagnose every cached artifact before any network operation.
    for role, path in paths.items():
        if os.path.lexists(path):
            verify_model_artifact(path, lock[role])
    for role, path in paths.items():
        if not os.path.lexists(path):
            provision_model_artifact(path, lock[role])
    return paths


def find_recordings(subjects):
    files = []
    for sub in subjects:
        found = sorted(glob.glob(os.path.join(DATA_DIR, f"{sub}_r*_*.db3")) +
                       glob.glob(os.path.join(DATA_DIR, f"{sub}_r*_*.bag")))
        if not found:
            print(f"[경고] {DATA_DIR} 폴더에서 {sub} 녹화 파일을 찾지 못했습니다.")
        files += found
    return files


def load_markers(rec_path):
    base = os.path.splitext(rec_path)[0]
    path = base + "_markers.csv"
    if not os.path.exists(path):
        print(f"[경고] 자세 표시 파일이 없습니다: {path}")
        return []
    marks = []
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("frame_timestamp_ms") in (None, "", "None"):
                continue
            marks.append({"ts": float(r["frame_timestamp_ms"]), "label": r["label"],
                          "phase": r.get("phase") or ("transition" if r["label"] == "transition" else "hold"),
                          "step": r.get("step") or ""})
    marks.sort(key=lambda m: m["ts"])
    # 옛 버전(키 입력) 파일: step 정보가 없으면 순서대로 번호 부여
    k = 0
    for m in marks:
        if m["phase"] == "hold" and not m["step"]:
            k += 1
            m["step"] = str(k)
    return marks


def parse_name(rec_path):
    name = os.path.basename(rec_path)
    parts = name.split("_")
    subject = parts[0]
    rnd = parts[1][1:] if len(parts) > 1 and parts[1].startswith("r") else "?"
    return subject, rnd


# ---------------------------------------------------------------- 프레임 처리
def median_depth(depth, x0, y0, x1, y1, scale):
    h, w = depth.shape
    x0, x1 = max(0, int(x0)), min(w, int(x1))
    y0, y1 = max(0, int(y0)), min(h, int(y1))
    if x1 <= x0 or y1 <= y0:
        return None
    patch = depth[y0:y1, x0:x1]
    v = patch[patch > 0]
    if v.size < DEPTH_MIN_VALID_PIXELS:
        return None
    return float(np.median(v)) * scale


def polygon_area(pts):
    a = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        a += x1 * y2 - x2 * y1
    return abs(a) / 2


def angle_from_down(fx, fy, sx, sy):
    """얼굴 중심 -> 어깨 선이 아래쪽 수직선과 이루는 각도(도)."""
    return math.degrees(math.atan2(abs(sx - fx), sy - fy))


def landmark_in_frame(landmark):
    if landmark is None:
        return False
    try:
        x, y = landmark.x, landmark.y
        return math.isfinite(x) and math.isfinite(y) and 0 <= x < 1 and 0 <= y < 1
    except (AttributeError, TypeError, ValueError):
        return False


def hip_observation(landmark, width, height, depth, depth_scale):
    visibility = getattr(landmark, "visibility", None) if landmark is not None else None
    if not landmark_in_frame(landmark):
        return None, None, None, visibility, False, False
    x_px, y_px = landmark.x * width, landmark.y * height
    z_m = median_depth(depth, x_px - SHOULDER_DEPTH_HALF_WIDTH_PX, y_px - SHOULDER_DEPTH_HALF_WIDTH_PX,
                       x_px + SHOULDER_DEPTH_HALF_WIDTH_PX, y_px + SHOULDER_DEPTH_HALF_WIDTH_PX, depth_scale)
    return x_px, y_px, z_m, visibility, True, z_m is not None


def process_recording(rec_path, models, step, provenance=None, output_dir=None):
    if not isinstance(provenance, dict):
        raise ValueError("canonical frame extraction requires analysis provenance")
    recording_id = provenance.get("recording_id")
    analysis_run_id = provenance.get("analysis_run_id")
    if not isinstance(recording_id, str) or not recording_id or not isinstance(analysis_run_id, str) or not analysis_run_id:
        raise ValueError("canonical frame extraction requires recording_id and analysis_run_id")

    import mediapipe as mp
    import pyrealsense2 as rs
    from mediapipe.tasks import python as mpt
    from mediapipe.tasks.python import vision

    subject, rnd = parse_name(rec_path)
    marks = load_markers(rec_path)
    mts = [m["ts"] for m in marks]

    face_options = vision.FaceDetectorOptions(
        base_options=mpt.BaseOptions(model_asset_path=models["face"]),
        min_detection_confidence=FACE_MIN_DETECTION_CONFIDENCE)
    mesh_options = vision.FaceLandmarkerOptions(
        base_options=mpt.BaseOptions(model_asset_path=models["mesh"]),
        running_mode=getattr(vision.RunningMode, LANDMARK_RUNNING_MODE), num_faces=FACE_NUM_FACES)
    pose_options = vision.PoseLandmarkerOptions(
        base_options=mpt.BaseOptions(model_asset_path=models["pose"]),
        running_mode=getattr(vision.RunningMode, LANDMARK_RUNNING_MODE), num_poses=POSE_NUM_POSES)
    for role, options in (("face", face_options), ("mesh", mesh_options), ("pose", pose_options)):
        record_task_options(provenance, role, options)
    face_det = vision.FaceDetector.create_from_options(face_options)
    mesh_det = vision.FaceLandmarker.create_from_options(mesh_options)
    pose_det = vision.PoseLandmarker.create_from_options(pose_options)

    pipe, cfg = rs.pipeline(), rs.config()
    cfg.enable_device_from_file(rec_path, repeat_playback=False)
    profile = pipe.start(cfg)
    playback = profile.get_device().as_playback()
    playback.set_real_time(False)
    depth_scale = profile.get_device().first_depth_sensor().get_depth_scale()
    align = rs.align(rs.stream.color)
    cin = profile.get_stream(rs.stream.color).as_video_stream_profile().get_intrinsics()
    fxfy = cin.fx * cin.fy
    duration = playback.get_duration().total_seconds()
    if provenance is not None:
        provenance["playback_calibration"] = {
            "depth_scale_m": depth_scale,
            "color_intrinsics": {k: getattr(cin, k) for k in ("width", "height", "fx", "fy", "ppx", "ppy")},
        }
        provenance["playback_calibration"]["color_intrinsics"].update(model=str(cin.model), coeffs=list(cin.coeffs))

    rows, n, last_ts_ms = [], 0, -1
    print(f"[분석] {os.path.basename(rec_path)}  (약 {duration:.0f}초 분량)")
    try:
        while True:
            ok, frames = pipe.try_wait_for_frames(3000)
            if not ok:
                break
            n += 1
            ts = frames.get_timestamp()
            # 자세 구간 판정
            i = bisect.bisect_right(mts, ts) - 1
            if i < 0:
                continue
            mk = marks[i]
            t_in = (ts - mk["ts"]) / 1000.0
            if mk["phase"] != "hold" or mk["label"] in ("transition", "end", "aborted"):
                continue
            nxt = marks[i + 1]["ts"] if i + 1 < len(marks) else None
            seg_len = (nxt - mk["ts"]) / 1000.0 if nxt else None
            if t_in < TRIM_START or (seg_len and t_in > seg_len - TRIM_END):
                continue
            if n % step:
                continue

            source_color, source_depth = frames.get_color_frame(), frames.get_depth_frame()
            color_frame_number = source_color.get_frame_number() if source_color else None
            depth_frame_number = source_depth.get_frame_number() if source_depth else None
            af = align.process(frames)
            color, depth = af.get_color_frame(), af.get_depth_frame()
            if not color or not depth:
                continue
            img = np.asanyarray(color.get_data())
            dep = np.asanyarray(depth.get_data())
            H, W = img.shape[:2]
            rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            mimg = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

            row = {"subject": subject, "round": rnd, "step": mk["step"], "label": mk["label"],
                   "t": round(t_in, 3), "ts_ms": ts}

            mark_model_used(provenance, "face")
            fres = face_det.detect(mimg)
            face_detected = bool(fres.detections)
            if fres.detections:
                d = max(fres.detections, key=lambda x: x.bounding_box.width * x.bounding_box.height)
                bb = d.bounding_box
                x, y, w, h = bb.origin_x, bb.origin_y, bb.width, bb.height
                cxp, cyp = x + w / 2, y + h / 2
                zf = median_depth(dep, x + w * FACE_DEPTH_ROI_MIN, y + h * FACE_DEPTH_ROI_MIN,
                                  x + w * FACE_DEPTH_ROI_MAX, y + h * FACE_DEPTH_ROI_MAX, depth_scale)
                row.update({"face_x": cxp, "face_y": cyp, "face_w_px": w, "face_h_px": h,
                            "face_area_px": w * h, "face_score": d.categories[0].score if d.categories else None,
                            "z_face_m": zf,
                            "face_size_cm2": (w * h * zf ** 2 / fxfy * 1e4) if zf else None})
            bbox_zf = row.get("z_face_m")

            ts_int = int(ts)
            if ts_int <= last_ts_ms:
                ts_int = last_ts_ms + 1
            last_ts_ms = ts_int
            mark_model_used(provenance, "mesh")
            mres = mesh_det.detect_for_video(mimg, ts_int)
            face_mesh_detected = bool(mres.face_landmarks)
            if mres.face_landmarks:
                fl = mres.face_landmarks[0]
                oval = [(fl[i].x * W, fl[i].y * H) for i in FACE_OVAL]
                oa = polygon_area(oval)
                row["oval_area_px"] = oa
                zf = row.get("z_face_m")
                if zf is None:  # 얼굴 박스가 없으면 외곽선 중심 근처 깊이
                    ox = [p[0] for p in oval]; oy = [p[1] for p in oval]
                    cx0, cy0 = sum(ox) / len(ox), sum(oy) / len(oy)
                    zf = median_depth(dep, cx0 - OVAL_DEPTH_HALF_WIDTH_PX, cy0 - OVAL_DEPTH_HALF_WIDTH_PX,
                                      cx0 + OVAL_DEPTH_HALF_WIDTH_PX, cy0 + OVAL_DEPTH_HALF_WIDTH_PX, depth_scale)
                    row["z_face_m"] = zf
                if zf:
                    row["oval_size_cm2"] = oa * zf ** 2 / fxfy * 1e4
                if len(fl) > IRIS_R:
                    ipd_px = math.hypot((fl[IRIS_L].x - fl[IRIS_R].x) * W, (fl[IRIS_L].y - fl[IRIS_R].y) * H)
                    row["ipd_px"] = ipd_px
                    if zf:
                        row["ipd_cm"] = ipd_px * zf / cin.fx * 100
                if row.get("face_area_px"):
                    row["box_to_oval"] = row["face_area_px"] / oa if oa else None

            mark_model_used(provenance, "pose")
            pres = pose_det.detect_for_video(mimg, ts_int)
            pose_detected = bool(pres.pose_landmarks)
            lm = None
            ls = rsh = None
            if pres.pose_landmarks:
                lm = pres.pose_landmarks[0]
                ls, rsh = lm[SHOULDER_L], lm[SHOULDER_R]  # 사람 기준 왼쪽/오른쪽 어깨
                lx, ly, rx, ry = ls.x * W, ls.y * H, rsh.x * W, rsh.y * H
                zl = median_depth(dep, lx - SHOULDER_DEPTH_HALF_WIDTH_PX, ly - SHOULDER_DEPTH_HALF_WIDTH_PX,
                                  lx + SHOULDER_DEPTH_HALF_WIDTH_PX, ly + SHOULDER_DEPTH_HALF_WIDTH_PX, depth_scale)
                zr = median_depth(dep, rx - SHOULDER_DEPTH_HALF_WIDTH_PX, ry - SHOULDER_DEPTH_HALF_WIDTH_PX,
                                  rx + SHOULDER_DEPTH_HALF_WIDTH_PX, ry + SHOULDER_DEPTH_HALF_WIDTH_PX, depth_scale)
                zs = [z for z in (zl, zr) if z]
                row.update({"lsh_x": lx, "lsh_y": ly, "rsh_x": rx, "rsh_y": ry,
                            "lsh_vis": getattr(ls, "visibility", None), "rsh_vis": getattr(rsh, "visibility", None),
                            "z_lsh_m": zl, "z_rsh_m": zr, "z_sh_m": sum(zs) / len(zs) if zs else None})
                if "face_x" in row:
                    fx, fy = row["face_x"], row["face_y"]
                    th3 = angle_from_down(fx, fy, lx, ly)   # 얼굴-왼쪽 어깨 (근사)
                    th2 = angle_from_down(fx, fy, rx, ry)   # 얼굴-오른쪽 어깨 (근사)
                    row.update({"theta1_deg": th2 + th3, "theta2_deg": th2, "theta3_deg": th3})

            lsh_valid = landmark_in_frame(ls)
            rsh_valid = landmark_in_frame(rsh)
            lsh_depth_valid = lsh_valid and row.get("z_lsh_m") is not None
            rsh_depth_valid = rsh_valid and row.get("z_rsh_m") is not None
            if lsh_depth_valid and rsh_depth_valid:
                shoulder_depth_source = "both"
            elif lsh_depth_valid:
                shoulder_depth_source = "left_only"
            elif rsh_depth_valid:
                shoulder_depth_source = "right_only"
            else:
                shoulder_depth_source = "missing"

            left_hip = lm[HIP_L] if lm is not None and len(lm) > HIP_L else None
            right_hip = lm[HIP_R] if lm is not None and len(lm) > HIP_R else None
            left_hip_values = hip_observation(left_hip, W, H, dep, depth_scale)
            right_hip_values = hip_observation(right_hip, W, H, dep, depth_scale)
            final_zf = row.get("z_face_m")
            face_depth_source = ("bbox_roi" if bbox_zf is not None else
                                 "oval_center_roi" if final_zf is not None else "missing")
            row.update({
                "frame_schema_version": FRAME_SCHEMA_VERSION,
                "recording_id": recording_id,
                "analysis_run_id": analysis_run_id,
                "frame_index": n,
                "color_frame_number": color_frame_number,
                "depth_frame_number": depth_frame_number,
                "mediapipe_ts_ms": ts_int,
                "face_depth_source": face_depth_source,
                "face_detected": face_detected,
                "face_mesh_detected": face_mesh_detected,
                "pose_detected": pose_detected,
                "face_depth_valid": final_zf is not None,
                "lsh_valid": lsh_valid,
                "rsh_valid": rsh_valid,
                "lsh_depth_valid": lsh_depth_valid,
                "rsh_depth_valid": rsh_depth_valid,
                "shoulder_depth_source": shoulder_depth_source,
                "left_hip_x_px": left_hip_values[0],
                "left_hip_y_px": left_hip_values[1],
                "left_hip_depth_m": left_hip_values[2],
                "left_hip_visibility": left_hip_values[3],
                "left_hip_valid": left_hip_values[4],
                "left_hip_depth_valid": left_hip_values[5],
                "right_hip_x_px": right_hip_values[0],
                "right_hip_y_px": right_hip_values[1],
                "right_hip_depth_m": right_hip_values[2],
                "right_hip_visibility": right_hip_values[3],
                "right_hip_valid": right_hip_values[4],
                "right_hip_depth_valid": right_hip_values[5],
            })
            rows.append(row)
            if len(rows) % 150 == 0:
                print(f"   ... {len(rows)} 프레임 처리")
    finally:
        pipe.stop()
        face_det.close()
        mesh_det.close()
        pose_det.close()

    out = os.path.join(OUT_DIR if output_dir is None else output_dir,
                       os.path.splitext(os.path.basename(rec_path))[0] + "_frames.csv")
    write_frames_csv(out, rows)
    print(f"   -> {len(rows)} 프레임 저장: {out}")
    return rows


def _validate_frame_row(row):
    unknown = set(row) - set(FRAME_FIELDS)
    if unknown:
        raise ValueError(f"unexpected canonical frame fields: {sorted(unknown)}")
    if row.get("frame_schema_version") != FRAME_SCHEMA_VERSION:
        raise ValueError("invalid canonical frame schema version")
    for field in ("recording_id", "analysis_run_id"):
        if not isinstance(row.get(field), str) or not row[field]:
            raise ValueError(f"missing canonical {field}")
    for field, allowed in FRAME_ENUMS.items():
        if row.get(field) not in allowed:
            raise ValueError(f"invalid canonical {field}: {row.get(field)!r}")
    for field in FRAME_BOOL_FIELDS:
        value = row.get(field)
        if value is not None and type(value) is not bool:
            raise ValueError(f"invalid canonical boolean {field}: {value!r}")
    for field, value in row.items():
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(f"non-finite canonical value {field}")


def write_frames_csv(path, rows):
    if not rows:
        return
    seen = set()
    projected = []
    file_identity = None
    for row in rows:
        _validate_frame_row(row)
        frame_index = row.get("frame_index")
        if type(frame_index) is not int or frame_index < 1:
            raise ValueError(f"invalid canonical frame_index: {frame_index!r}")
        identity = (row["recording_id"], row["analysis_run_id"])
        if file_identity is None:
            file_identity = identity
        elif identity != file_identity:
            raise ValueError("inconsistent canonical frame identity")
        key = (row["analysis_run_id"], row["recording_id"], frame_index)
        if key in seen:
            raise ValueError(f"duplicate canonical frame key: {key}")
        seen.add(key)
        out = {}
        for field in FRAME_FIELDS:
            value = row.get(field)
            if field in FRAME_BOOL_FIELDS and value is not None:
                value = "true" if value else "false"
            elif value is None:
                value = ""
            out[field] = value
        projected.append(out)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FRAME_FIELDS, restval="", extrasaction="raise")
        w.writeheader()
        w.writerows(projected)


def write_csv(path, rows):
    if not rows:
        return
    keys = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


# ---------------------------------------------------------------- 요약
FEATS = ["face_area_px", "face_w_px", "face_x", "face_y", "theta1_deg", "theta2_deg", "theta3_deg",
         "z_face_m", "z_sh_m", "face_size_cm2", "oval_area_px", "oval_size_cm2", "ipd_cm", "box_to_oval"]
SUMMARY_SCHEMA_VERSION = "summary-schema/1.0.0"
SUMMARY_FIELDS = (
    "subject", "round", "step", "label", "n_frames", "face_detect_ratio", "pose_detect_ratio",
) + tuple(field for feature in FEATS for field in (feature, feature + "_sd")) + (
    "ref_step", "A_ratio", "A_ratio_oval", "dZ_face_cm", "dZ_sh_cm", "D_head_cm",
    "sh_face_ratio", "area_err_est_pct", "area_cv_pct", "summary_schema_version",
    "recording_id", "analysis_run_id", "source_frames_analysis_run_id", "dataset_role",
    "protocol_version", "reference_recording_id", "reference_analysis_run_id",
)


def med(vals):
    v = [x for x in vals if x is not None]
    return statistics.median(v) if v else None


def sd(vals):
    v = [x for x in vals if x is not None]
    return statistics.pstdev(v) if len(v) >= 2 else None


def summarize(all_rows, run_context=None):
    groups = {}
    sources = {}
    for r in all_rows:
        rid, source = r.get("recording_id"), r.get("analysis_run_id")
        if not rid:
            raise ValueError("summary requires recording_id provenance")
        if rid in sources and sources[rid] != source:
            raise ValueError("multiple source frame runs for one recording in summary")
        sources[rid] = source
        groups.setdefault((rid, source, int(r["step"])), []).append(r)
    summary = []
    for (rid, source, stp), g in sorted(groups.items()):
        for field in ("subject", "round", "label", "recording_id", "analysis_run_id",
                      "dataset_role", "protocol_version"):
            if any(r.get(field) != g[0].get(field) for r in g):
                raise ValueError(f"conflicting summary identity metadata: {field}")
        sub, rnd = g[0]["subject"], g[0]["round"]
        context = (run_context or {}).get(rid, {})
        for field in ("dataset_role", "protocol_version"):
            if field in g[0] and field in context and g[0][field] != context[field]:
                raise ValueError(f"summary context {field} mismatch")
        s = {"subject": sub, "round": rnd, "step": stp, "label": g[0]["label"], "n_frames": len(g),
             "face_detect_ratio": sum(1 for r in g if r.get("face_area_px")) / len(g),
             "pose_detect_ratio": sum(1 for r in g if r.get("z_sh_m") is not None) / len(g)}
        for k in FEATS:
            s[k] = med([r.get(k) for r in g])
            s[k + "_sd"] = sd([r.get(k) for r in g])
        s.update(summary_schema_version=SUMMARY_SCHEMA_VERSION, recording_id=rid,
                 analysis_run_id=context.get("analysis_run_id", source),
                 source_frames_analysis_run_id=source,
                 dataset_role=context.get("dataset_role", g[0].get("dataset_role")),
                 protocol_version=context.get("protocol_version", g[0].get("protocol_version")))
        summary.append(s)
    # 바로 앞 정상 자세 대비 변화량
    for s in summary:
        prev = [u for u in summary if u["subject"] == s["subject"] and u["round"] == s["round"]
                and u["recording_id"] == s["recording_id"]
                and u["source_frames_analysis_run_id"] == s["source_frames_analysis_run_id"]
                and u["label"] == "upright" and u["step"] < s["step"]]
        ref = prev[-1] if prev else (s if s["label"] == "upright" else None)
        if s["label"] == "upright" and not prev:
            ref = s
        s["ref_step"] = ref["step"] if ref else None
        s["reference_recording_id"] = ref["recording_id"] if ref else None
        s["reference_analysis_run_id"] = ref["source_frames_analysis_run_id"] if ref else None

        def diff(k):
            return (ref[k] - s[k]) if (ref and ref.get(k) is not None and s.get(k) is not None) else None
        s["A_ratio"] = (s["face_area_px"] / ref["face_area_px"]) if (ref and ref.get("face_area_px") and s.get("face_area_px")) else None
        s["A_ratio_oval"] = (s["oval_area_px"] / ref["oval_area_px"]) if (ref and ref.get("oval_area_px") and s.get("oval_area_px")) else None
        s["dZ_face_cm"] = diff("z_face_m") * 100 if diff("z_face_m") is not None else None
        s["dZ_sh_cm"] = diff("z_sh_m") * 100 if diff("z_sh_m") is not None else None
        s["D_head_cm"] = (s["dZ_face_cm"] - s["dZ_sh_cm"]) if (s["dZ_face_cm"] is not None and s["dZ_sh_cm"] is not None) else None
        # 어깨 이동 ÷ 얼굴 이동: 거북목 ≈ 0 (어깨 제자리), 몸 전체 앞으로 ≈ 0.7~0.9 (엉덩이 축 회전)
        s["sh_face_ratio"] = (s["dZ_sh_cm"] / s["dZ_face_cm"]) if (s["dZ_face_cm"] is not None and s["dZ_sh_cm"] is not None
                                                                   and abs(s["dZ_face_cm"]) >= 2.0) else None
        if s.get("face_w_px"):
            s["area_err_est_pct"] = 2 * BOUNDARY_DELTA_PX / s["face_w_px"] * 100
        s["area_cv_pct"] = (s["face_area_px_sd"] / s["face_area_px"] * 100) if (s.get("face_area_px_sd") and s.get("face_area_px")) else None
    with open(os.path.join(OUT_DIR, "summary_steps.csv"), "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        writer.writerows(summary)
    return summary


def fmt(v, f="{:.1f}", none="--"):
    return f.format(v) if v is not None else none


def report(summary):
    lines = []
    P = lines.append
    P("=" * 70)
    P(" 바른자세 스테레오 예비 분석 요약")
    P("=" * 70)
    for sub in sorted({s["subject"] for s in summary}):
        P(f"\n[{sub}] 회차·단계별 (정상 자세 대비 변화량)")
        P("  회차 단계 자세          A(외곽선) A(박스) 얼굴전방  어깨전방  D_head  어깨/얼굴  실제얼굴(외곽선) 검출(얼굴/어깨)")
        for s in [x for x in summary if x["subject"] == sub]:
            P(f"  r{s['round']:<3} {s['step']:<3} {POSTURE_KO.get(s['label'], s['label']):<12}"
              f" {fmt(s['A_ratio_oval'], '{:5.2f}'):>6}  {fmt(s['A_ratio'], '{:5.2f}'):>6}"
              f" {fmt(s['dZ_face_cm'], '{:+6.1f}'):>7}cm {fmt(s['dZ_sh_cm'], '{:+6.1f}'):>7}cm"
              f" {fmt(s['D_head_cm'], '{:+5.1f}'):>6}cm {fmt(s['sh_face_ratio'], '{:5.2f}'):>7}"
              f"   {fmt(s['oval_size_cm2'], '{:6.0f}'):>7}cm²"
              f"      {s['face_detect_ratio']*100:3.0f}%/{s['pose_detect_ratio']*100:3.0f}%")

        # 측정 안정성: 각 회차 첫 정상 자세
        P(f"\n[{sub}] 측정 안정성 (각 회차 첫 정상 자세, 가만히 있는 구간)")
        for s in [x for x in summary if x["subject"] == sub and x["label"] == "upright" and x["ref_step"] == x["step"]]:
            P(f"  r{s['round']}: 얼굴 깊이 흔들림 ±{fmt(s['z_face_m_sd'] and s['z_face_m_sd']*1000, '{:.1f}')}mm,"
              f" 어깨 깊이 흔들림 ±{fmt(s['z_sh_m_sd'] and s['z_sh_m_sd']*1000, '{:.1f}')}mm,"
              f" 얼굴 면적 흔들림 {fmt(s['area_cv_pct'], '{:.1f}')}%"
              f" (얼굴 폭 {fmt(s['face_w_px'], '{:.0f}')}px → 경계 2px 오차 시 이론 면적오차 {fmt(s.get('area_err_est_pct'), '{:.1f}')}%)")

        # 핵심 비교
        for lab in ("forward_head", "body_forward"):
            g = [x for x in summary if x["subject"] == sub and x["label"] == lab]
            if not g:
                continue
            P(f"\n[{sub}] {POSTURE_KO[lab]} {len(g)}회 평균:"
              f" A(외곽선) {fmt(mean([x['A_ratio_oval'] for x in g]), '{:.2f}')},"
              f" 어깨/얼굴 {fmt(mean([x['sh_face_ratio'] for x in g]), '{:.2f}')},"
              f" 얼굴 전방 {fmt(mean([x['dZ_face_cm'] for x in g]), '{:+.1f}')}cm,"
              f" 어깨 전방 {fmt(mean([x['dZ_sh_cm'] for x in g]), '{:+.1f}')}cm,"
              f" D_head {fmt(mean([x['D_head_cm'] for x in g]), '{:+.1f}')}cm")
        alls = [x["face_size_cm2"] for x in summary if x["subject"] == sub and x["face_size_cm2"]]
        if alls:
            P(f"\n[{sub}] 실제 얼굴 크기(박스 기준, 참고): 전체 단계 중앙값 {statistics.median(alls):.0f}cm²"
              f" (범위 {min(alls):.0f}~{max(alls):.0f}, 변동 {(max(alls)-min(alls))/statistics.median(alls)*100:.0f}%)")
        # 박스 vs 외곽선(세그먼트) 비교 - 머리카락·배경 영향 점검
        g = [x for x in summary if x["subject"] == sub]
        P(f"\n[{sub}] 얼굴 면적 방식 비교 (박스 = 원 논문 방식, 외곽선 = 머리카락 제외한 얼굴 영역)")
        P(f"  박스/외곽선 면적비 중앙값 {fmt(med([x['box_to_oval'] for x in g]), '{:.2f}')}"
          f" (단계 간 흔들림 ±{fmt(sd([x['box_to_oval'] for x in g]), '{:.2f}')})")
        for lab in ("forward_head", "body_forward"):
            gg = [x for x in g if x["label"] == lab]
            if gg:
                P(f"  {POSTURE_KO[lab]}: A(박스) {fmt(mean([x['A_ratio'] for x in gg]), '{:.2f}')}"
                  f" / A(외곽선) {fmt(mean([x['A_ratio_oval'] for x in gg]), '{:.2f}')}")
        ov = [x["oval_size_cm2"] for x in g if x.get("oval_size_cm2")]
        if ov:
            P(f"  실제 얼굴 크기(외곽선 기준): 중앙값 {statistics.median(ov):.0f}cm²"
              f" (범위 {min(ov):.0f}~{max(ov):.0f}, 변동 {(max(ov)-min(ov))/statistics.median(ov)*100:.0f}%)")
        ipd = med([x["ipd_cm"] for x in g])
        if ipd:
            P(f"  측정 점검: 눈(홍채) 사이 실제 거리 {ipd:.1f}cm (성인 평균 약 6~7cm 근처면 깊이·보정값이 정상)")
    subs = sorted({s["subject"] for s in summary})
    if len(subs) >= 2:
        P("\n[사람 간 비교] 정상 자세 기준")
        for sub in subs:
            u = [x for x in summary if x["subject"] == sub and x["label"] == "upright"]
            P(f"  {sub}: 픽셀 면적 {fmt(med([x['face_area_px'] for x in u]), '{:.0f}')}px,"
              f" 거리 {fmt(med([x['z_face_m'] for x in u]) and med([x['z_face_m'] for x in u])*100, '{:.1f}')}cm,"
              f" 실제 얼굴 크기 {fmt(med([x['face_size_cm2'] for x in u]), '{:.0f}')}cm²"
              f" (외곽선 {fmt(med([x['oval_size_cm2'] for x in u]), '{:.0f}')}cm²),"
              f" 눈 사이 {fmt(med([x['ipd_cm'] for x in u]), '{:.1f}')}cm")
    P("\n* A비율: 바로 앞 정상 자세 대비 픽셀 면적 비율 (원 논문 방식)")
    P("* 얼굴/어깨 전방: 바로 앞 정상 자세보다 카메라에 가까워진 거리 (+ = 앞으로)")
    P("* D_head = 얼굴 전방 - 어깨 전방. 거북목은 크고, 몸 전체 앞으로는 0에 가까울 것으로 기대(가설)")
    P("* 각도 θ는 원 논문 그림을 근사 재구성한 값으로, 사람 내부 비교용")
    P("* 외곽선 면적: 얼굴 랜드마크의 턱선~이마 외곽선 내부 면적 (머리카락·배경 제외, 세그먼트 방식)")
    text = "\n".join(lines)
    print(text)
    with open(os.path.join(OUT_DIR, "summary_report.txt"), "w", encoding="utf-8") as f:
        f.write(text)


def mean(v):
    v = [x for x in v if x is not None]
    return sum(v) / len(v) if v else None


# ---------------------------------------------------------------- 그래프
def setup_font():
    import matplotlib
    from matplotlib import font_manager
    for name in ("Malgun Gothic", "NanumGothic", "Noto Sans CJK KR", "Noto Sans CJK JP", "AppleGothic"):
        if any(name == f.name for f in font_manager.fontManager.ttflist):
            matplotlib.rcParams["font.family"] = name
            break
    matplotlib.rcParams["axes.unicode_minus"] = False


def plot_all(all_rows, summary):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    setup_font()
    colors = {"upright": "#B4B2A9", "forward_head": "#D85A30", "body_forward": "#378ADD",
              "lean_back": "#7F77DD", "lean_left": "#1D9E75", "lean_right": "#639922"}

    # fig1: 회차별 시간 그래프 (첫 정상 자세 대비 얼굴·어깨 전방 이동)
    for (sub, rnd) in sorted({(r["subject"], r["round"]) for r in all_rows}):
        rows = [r for r in all_rows if r["subject"] == sub and r["round"] == rnd]
        base = [r for r in rows if r["label"] == "upright" and int(r["step"]) == min(int(x["step"]) for x in rows)]
        zf0, zs0 = med([r.get("z_face_m") for r in base]), med([r.get("z_sh_m") for r in base])
        if zf0 is None or zs0 is None:
            continue
        t0 = rows[0]["ts_ms"]
        fig, ax = plt.subplots(figsize=(11, 4.2))
        for stp in sorted({int(r["step"]) for r in rows}):
            seg = [r for r in rows if int(r["step"]) == stp]
            tt = [(r["ts_ms"] - t0) / 1000 for r in seg]
            ax.axvspan(min(tt), max(tt), color=colors.get(seg[0]["label"], "#ddd"), alpha=0.15, lw=0)
            ax.text((min(tt) + max(tt)) / 2, 1.02, POSTURE_KO.get(seg[0]["label"], ""), transform=ax.get_xaxis_transform(),
                    ha="center", va="bottom", fontsize=9)
        tf = [((r["ts_ms"] - t0) / 1000, (zf0 - r["z_face_m"]) * 100) for r in rows if r.get("z_face_m")]
        tsh = [((r["ts_ms"] - t0) / 1000, (zs0 - r["z_sh_m"]) * 100) for r in rows if r.get("z_sh_m")]
        if tf:
            ax.plot(*zip(*tf), ".", ms=3, color="#D85A30", label="얼굴 전방 이동 ΔZ_f")
        if tsh:
            ax.plot(*zip(*tsh), ".", ms=3, color="#1D9E75", label="어깨 전방 이동 ΔZ_s")
        ax.axhline(0, color="#888", lw=0.8)
        ax.set_xlabel("녹화 시간 (초)")
        ax.set_ylabel("첫 정상 자세 대비 앞으로 (cm)")
        ax.set_title(f"{sub} {rnd}회차: 얼굴과 어깨의 앞뒤 이동", pad=22)
        ax.legend(loc="lower left", fontsize=9)
        fig.tight_layout()
        fig.savefig(os.path.join(OUT_DIR, f"fig1_timeline_{sub}_r{rnd}.png"), dpi=150)
        plt.close(fig)

    # fig2: 거북목 vs 몸 전체 앞으로
    subs = sorted({s["subject"] for s in summary})
    metrics = [("A_ratio_oval", "면적 비율 A (외곽선)\n웹캠으로도 계산 가능"), ("dZ_face_cm", "얼굴 전방 이동 (cm)\n스테레오"),
               ("dZ_sh_cm", "어깨 전방 이동 (cm)\n스테레오"), ("sh_face_ratio", "어깨 이동 ÷ 얼굴 이동\n스테레오")]
    fig, axes = plt.subplots(1, 4, figsize=(14, 4.3))
    for ax, (k, title) in zip(axes, metrics):
        xpos, labels = 0, []
        for sub in subs:
            for lab in ("forward_head", "body_forward"):
                vals = [s[k] for s in summary if s["subject"] == sub and s["label"] == lab and s[k] is not None]
                if not vals:
                    continue
                m = sum(vals) / len(vals)
                ax.bar(xpos, m, color=colors[lab], alpha=0.85, width=0.7)
                ax.plot([xpos] * len(vals), vals, "o", color="black", ms=4)
                labels.append((xpos, f"{sub}\n{POSTURE_KO[lab]}"))
                xpos += 1
            xpos += 0.5
        ax.set_xticks([p for p, _ in labels])
        ax.set_xticklabels([l for _, l in labels], fontsize=8)
        ax.set_title(title, fontsize=10)
        ax.axhline(1.0 if k.startswith("A_ratio") else 0, color="#888", lw=0.8)
    fig.suptitle("거북목 vs 몸 전체 앞으로 (막대=평균, 점=각 회차)", fontsize=12)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT_DIR, "fig2_fh_vs_bf.png"), dpi=150)
    plt.close(fig)

    # fig3: 픽셀 면적 vs 실제 얼굴 크기 (거리에 따른 변화)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    markers = ["o", "s", "^", "D"]
    for i, sub in enumerate(subs):
        g = [s for s in summary if s["subject"] == sub and s.get("z_face_m") and s.get("oval_area_px")]
        for s in g:
            c = colors.get(s["label"], "#888")
            axes[0].plot(s["z_face_m"] * 100, s["oval_area_px"], markers[i % 4], color=c, ms=7)
            if s.get("oval_size_cm2"):
                axes[1].plot(s["z_face_m"] * 100, s["oval_size_cm2"], markers[i % 4], color=c, ms=7)
        axes[0].plot([], [], markers[i % 4], color="black", label=sub)
    axes[0].set_title("픽셀 얼굴 면적(외곽선): 거리에 따라 변함 (웹캠으로 보이는 값)", fontsize=10)
    axes[0].set_xlabel("얼굴까지 거리 (cm)")
    axes[0].set_ylabel("얼굴 면적 (px)")
    axes[1].set_title("실제 얼굴 크기 = 픽셀 면적 × 거리²/f²: 사람마다 다르고 거리와 무관 (스테레오 필요)", fontsize=10)
    axes[1].set_xlabel("얼굴까지 거리 (cm)")
    axes[1].set_ylabel("실제 얼굴 크기 (cm²)")
    ymax = max([s["oval_size_cm2"] for s in summary if s.get("oval_size_cm2")] or [1])
    axes[1].set_ylim(0, ymax * 1.3)
    for lab, c in colors.items():
        if any(s["label"] == lab for s in summary):
            axes[1].plot([], [], "o", color=c, label=POSTURE_KO[lab])
    axes[0].legend(fontsize=8)
    axes[1].legend(fontsize=8, ncol=2)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT_DIR, "fig3_face_size.png"), dpi=150)
    plt.close(fig)
    print(f"[그래프 저장] {OUT_DIR} 폴더의 fig1_*, fig2_fh_vs_bf.png, fig3_face_size.png")


def load_frames_csv(subjects, paths=None):
    rows = []
    if paths is None:
        paths = [path for sub in subjects
                 for path in sorted(glob.glob(os.path.join(OUT_DIR, f"{sub}_r*_frames.csv")))]
    for path in paths:
        with open(path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            canonical = "frame_schema_version" in (reader.fieldnames or [])
            if canonical and tuple(reader.fieldnames or ()) != FRAME_FIELDS:
                raise ValueError(f"canonical frame header mismatch: {path}")
            canonical_identity = None
            for r in reader:
                if canonical:
                    if r.get("frame_schema_version") != FRAME_SCHEMA_VERSION:
                        raise ValueError("invalid canonical frame schema version")
                    for field in ("recording_id", "analysis_run_id"):
                        if not r.get(field):
                            raise ValueError(f"missing canonical {field}")
                    identity = (r["recording_id"], r["analysis_run_id"])
                    if canonical_identity is None:
                        canonical_identity = identity
                    elif identity != canonical_identity:
                        raise ValueError("inconsistent canonical frame identity")
                    for field, allowed in FRAME_ENUMS.items():
                        if r.get(field) not in allowed:
                            raise ValueError(f"invalid canonical {field}: {r.get(field)!r}")
                out = {}
                for k, v in r.items():
                    if canonical and k == "frame_index":
                        if v in ("", None):
                            raise ValueError("missing canonical frame_index")
                        try:
                            frame_index = float(v)
                        except ValueError:
                            raise ValueError(f"invalid canonical frame_index: {v!r}")
                        if not math.isfinite(frame_index):
                            raise ValueError("non-finite canonical value frame_index")
                        if not frame_index.is_integer() or frame_index < 1:
                            raise ValueError(f"invalid canonical frame_index: {v!r}")
                        out[k] = int(frame_index)
                    elif canonical and k in FRAME_BOOL_FIELDS:
                        if v == "true":
                            out[k] = True
                        elif v == "false":
                            out[k] = False
                        elif v in ("", None):
                            out[k] = None
                        else:
                            raise ValueError(f"invalid canonical boolean {k}: {v!r}")
                    elif k in FRAME_TEXT_FIELDS:
                        out[k] = v
                    elif v in ("", None):
                        out[k] = None
                    else:
                        try:
                            number = float(v)
                        except ValueError:
                            if canonical:
                                raise ValueError(f"invalid canonical numeric {k}: {v!r}")
                            out[k] = v
                        else:
                            if canonical and not math.isfinite(number):
                                raise ValueError(f"non-finite canonical value {k}")
                            out[k] = number
                rows.append(out)
        print(f"[읽기] {os.path.basename(path)}")
    return rows


def run_analysis(files, args):
    """기존 batch 집계 유지. per-recording run과 공동 출력의 기여 관계만 기록."""
    global OUT_DIR
    while True:
        batch_id = new_analysis_id()
        batch_dir = os.path.join(OUT_DIR, "batches", batch_id)
        try:
            os.makedirs(batch_dir, exist_ok=False)
            break
        except FileExistsError:
            continue
    runs, all_rows = [], []
    try:
        for path in files:
            directory, manifest = start_analysis_run(path, args, batch_id)
            runs.append((path, directory, manifest))
        if len({m["recording_id"] for _, _, m in runs}) != len(runs):
            raise ValueError("multiple analysis runs for one recording in summary operation")
        lock = None if args.from_csv else load_model_lock()
        models = None if args.from_csv else ensure_models(lock)
        for path, directory, manifest in runs:
            if args.from_csv:
                snapshot = archive_output(path, directory, manifest, "source_frames")
                if snapshot["sha256"] is None or snapshot["sha256"] != manifest["inputs"]["frames"]["sha256"]:
                    raise ValueError("source frames changed before reprocessing")
                rows = load_frames_csv(args.subjects, paths=[snapshot["path"]])
            else:
                record_model_artifacts(manifest, models, lock)
                rows = process_recording(path, models, max(1, args.step), provenance=manifest, output_dir=directory)
                if rows:
                    frame_path = os.path.join(directory, os.path.splitext(os.path.basename(path))[0] + "_frames.csv")
                    frame = archive_output(frame_path, directory, manifest, "frames", len(rows))
                    frame["schema_version"] = FRAME_SCHEMA_VERSION
                    frame["compatibility_path"] = os.path.abspath(os.path.join(OUT_DIR, os.path.basename(frame_path)))
            manifest["input_frame_rows"] = len(rows)
            # In-memory context only; never rewrite archived historical frame identity.
            rows = [dict(r) for r in rows]
            for r in rows:
                if r.get("recording_id") and r["recording_id"] != manifest["recording_id"]:
                    raise ValueError("frame/manifest recording_id mismatch")
                expected_source = (manifest["parent_analysis_run_id"] if args.from_csv
                                   else manifest["analysis_run_id"])
                if r.get("analysis_run_id") and r["analysis_run_id"] != expected_source:
                    raise ValueError("frame/manifest source analysis_run_id mismatch")
                if not r.get("recording_id"):
                    r["recording_id"] = manifest["recording_id"]
                if not r.get("analysis_run_id"):
                    r["analysis_run_id"] = (manifest["parent_analysis_run_id"] if args.from_csv
                                            else manifest["analysis_run_id"])
                for field in ("dataset_role", "protocol_version"):
                    if field in r and r[field] != manifest[field]:
                        raise ValueError(f"frame/manifest {field} mismatch")
                    r[field] = manifest[field]
            all_rows += rows
        if not all_rows:
            raise RuntimeError("분석된 프레임이 없습니다.")

        # 공통 summary/graph 계산은 그대로 실행하고, 새 batch 경로에서만 생성한다.
        # 이후 기존 평면 파일명으로 호환 사본을 제공한다. 과거 run 사본은 불변이다.
        compatibility_dir = OUT_DIR
        try:
            OUT_DIR = batch_dir
            summary = summarize(all_rows, {m["recording_id"]: m for _, _, m in runs})
            report(summary)
            plot_all(all_rows, summary)
        finally:
            OUT_DIR = compatibility_dir
        shared = []
        reasons = {}
        contributors = [m["analysis_run_id"] for _, _, m in runs]
        for filename in sorted(os.listdir(batch_dir)):
            path = os.path.join(batch_dir, filename)
            if not os.path.isfile(path):
                continue
            item = artifact_info(path, reasons)
            item.update(kind="batch_output", schema_version=SUMMARY_SCHEMA_VERSION if filename == "summary_steps.csv" else None,
                        row_count=len(summary) if filename == "summary_steps.csv" else None,
                        analysis_run_ids=contributors)
            shared.append(item)
            shutil.copyfile(path, os.path.join(compatibility_dir, filename))
        for path, directory, manifest in runs:
            manifest["outputs"].extend(shared)
            manifest["provenance_unknown_reasons"].update(reasons)
        write_json(os.path.join(batch_dir, "analysis_batch.json"), {
            "analysis_batch_id": batch_id, "analysis_run_ids": contributors, "outputs": shared,
            "run_manifests": [os.path.abspath(os.path.join(d, "analysis_manifest.json")) for _, d, _ in runs],
        })
        ended_at = utc_now().isoformat()
        for path, directory, manifest in runs:
            if not args.from_csv and manifest["input_frame_rows"]:
                frame = next(o for o in manifest["outputs"] if o["kind"] == "frames")
                shutil.copyfile(frame["path"], frame["compatibility_path"])
                manifest_path = os.path.join(directory, "analysis_manifest.json")
                write_json(frame["compatibility_path"] + ".provenance.json", {
                    "recording_id": manifest["recording_id"], "analysis_run_id": manifest["analysis_run_id"],
                    "frames_sha256": frame["sha256"],
                    "analysis_manifest": Path(manifest_path).relative_to(compatibility_dir).as_posix(),
                    # 최종 JSON과 동일한 bytes의 hash를 먼저 연결한다. 모든 publish가
                    # 성공한 뒤에만 completed로 확정하며, 그 전에는 parent 검증이 거부한다.
                    "analysis_manifest_sha256": hashlib.sha256(json.dumps(
                        finished_manifest(manifest, ended_at=ended_at), indent=2,
                        ensure_ascii=False).encode("utf-8")).hexdigest(),
                })
        for _, directory, manifest in runs:
            finish_analysis_run(directory, manifest, ended_at=ended_at)
    except BaseException as error:
        for _, directory, manifest in runs:
            try:
                finish_analysis_run(directory, manifest, error)
            except OSError as save_error:
                print(f"[경고] failed manifest 저장 불가: {save_error}", file=sys.stderr)
        raise


# ---------------------------------------------------------------- 실행
def main():
    ap = argparse.ArgumentParser(description="바른자세 녹화 파일 분석")
    ap.add_argument("subjects", nargs="+", help="참가자 ID (예: P01 P02)")
    ap.add_argument("--step", type=int, default=1, help="N프레임마다 1장 분석 (기본 1 = 전부)")
    ap.add_argument("--from-csv", action="store_true",
                    help="녹화 파일을 다시 읽지 않고 analysis 폴더의 *_frames.csv로 요약·그래프만 다시 만들기 (빠름)")
    ap.add_argument("--legacy-pilot", action="store_true",
                    help="modern provenance가 없는 과거 pilot raw/CSV만 명시적으로 허용 (깨진 modern provenance 우회 불가)")
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    if args.from_csv:
        files = [path for sub in args.subjects
                 for path in sorted(glob.glob(os.path.join(OUT_DIR, f"{sub}_r*_frames.csv")))]
        if not files:
            print("[오류] analysis 폴더에 *_frames.csv가 없습니다. --from-csv 없이 먼저 실행하세요.")
            sys.exit(1)
        run_analysis(files, args)
        print(f"\n[완료] 결과는 {OUT_DIR} 폴더에 있습니다.")
        return
    files = find_recordings(args.subjects)
    if not files:
        sys.exit(1)
    print(f"[대상] {len(files)}개 파일: " + ", ".join(os.path.basename(f) for f in files))
    run_analysis(files, args)
    print(f"\n[완료] 결과는 {OUT_DIR} 폴더에 있습니다.")


if __name__ == "__main__":
    main()
