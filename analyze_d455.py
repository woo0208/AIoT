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

결과: analysis 폴더
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
import glob
import math
import os
import statistics
import sys
import urllib.request
import warnings

warnings.filterwarnings("ignore", message=".*Glyph.*")

import cv2
import numpy as np

DATA_DIR = "data"
OUT_DIR = "analysis"
MODEL_DIR = "models"
MODELS = {
    "face": ("blaze_face_short_range.tflite",
             "https://storage.googleapis.com/mediapipe-models/face_detector/"
             "blaze_face_short_range/float16/latest/blaze_face_short_range.tflite"),
    "mesh": ("face_landmarker.task",
             "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
             "face_landmarker/float16/latest/face_landmarker.task"),
    "pose": ("pose_landmarker_full.task",
             "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
             "pose_landmarker_full/float16/latest/pose_landmarker_full.task"),
}
# 얼굴 외곽선(턱선~이마) 랜드마크 순서 - 머리카락·배경을 제외한 얼굴 영역(세그먼트)
FACE_OVAL = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377,
             152, 148, 176, 149, 150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109]
IRIS_L, IRIS_R = 468, 473   # 양쪽 홍채 중심 (눈 사이 거리 점검용)
TRIM_START, TRIM_END = 1.0, 0.5   # 각 자세 구간 앞 1초, 뒤 0.5초 제외
BOUNDARY_DELTA_PX = 2.0           # 면적 상대오차 추정용 경계 오차 가정 (2δ/w)

POSTURE_KO = {"upright": "정상", "forward_head": "거북목", "body_forward": "몸 전체 앞으로",
              "lean_back": "뒤로 기울임", "lean_left": "왼쪽 기울임", "lean_right": "오른쪽 기울임"}


# ---------------------------------------------------------------- 준비
def ensure_models():
    os.makedirs(MODEL_DIR, exist_ok=True)
    paths = {}
    for key, (fname, url) in MODELS.items():
        path = os.path.join(MODEL_DIR, fname)
        if not os.path.exists(path):
            print(f"[모델 다운로드] {fname} ...")
            try:
                urllib.request.urlretrieve(url, path)
            except Exception as e:
                print(f"[오류] 모델 다운로드 실패: {e}\n  아래 주소에서 직접 받아 {MODEL_DIR} 폴더에 넣어주세요:\n  {url}")
                sys.exit(1)
        paths[key] = path
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
    if v.size < 10:
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


def process_recording(rec_path, models, step):
    import mediapipe as mp
    import pyrealsense2 as rs
    from mediapipe.tasks import python as mpt
    from mediapipe.tasks.python import vision

    subject, rnd = parse_name(rec_path)
    marks = load_markers(rec_path)
    mts = [m["ts"] for m in marks]

    face_det = vision.FaceDetector.create_from_options(vision.FaceDetectorOptions(
        base_options=mpt.BaseOptions(model_asset_path=models["face"]), min_detection_confidence=0.5))
    mesh_det = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
        base_options=mpt.BaseOptions(model_asset_path=models["mesh"]),
        running_mode=vision.RunningMode.VIDEO, num_faces=1))
    pose_det = vision.PoseLandmarker.create_from_options(vision.PoseLandmarkerOptions(
        base_options=mpt.BaseOptions(model_asset_path=models["pose"]),
        running_mode=vision.RunningMode.VIDEO, num_poses=1))

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

            fres = face_det.detect(mimg)
            if fres.detections:
                d = max(fres.detections, key=lambda x: x.bounding_box.width * x.bounding_box.height)
                bb = d.bounding_box
                x, y, w, h = bb.origin_x, bb.origin_y, bb.width, bb.height
                cxp, cyp = x + w / 2, y + h / 2
                zf = median_depth(dep, x + w * 0.25, y + h * 0.25, x + w * 0.75, y + h * 0.75, depth_scale)
                row.update({"face_x": cxp, "face_y": cyp, "face_w_px": w, "face_h_px": h,
                            "face_area_px": w * h, "face_score": d.categories[0].score if d.categories else None,
                            "z_face_m": zf,
                            "face_size_cm2": (w * h * zf ** 2 / fxfy * 1e4) if zf else None})

            ts_int = int(ts)
            if ts_int <= last_ts_ms:
                ts_int = last_ts_ms + 1
            last_ts_ms = ts_int
            mres = mesh_det.detect_for_video(mimg, ts_int)
            if mres.face_landmarks:
                fl = mres.face_landmarks[0]
                oval = [(fl[i].x * W, fl[i].y * H) for i in FACE_OVAL]
                oa = polygon_area(oval)
                row["oval_area_px"] = oa
                zf = row.get("z_face_m")
                if zf is None:  # 얼굴 박스가 없으면 외곽선 중심 근처 깊이
                    ox = [p[0] for p in oval]; oy = [p[1] for p in oval]
                    cx0, cy0 = sum(ox) / len(ox), sum(oy) / len(oy)
                    zf = median_depth(dep, cx0 - 15, cy0 - 15, cx0 + 15, cy0 + 15, depth_scale)
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

            pres = pose_det.detect_for_video(mimg, ts_int)
            if pres.pose_landmarks:
                lm = pres.pose_landmarks[0]
                ls, rsh = lm[11], lm[12]  # 사람 기준 왼쪽/오른쪽 어깨
                lx, ly, rx, ry = ls.x * W, ls.y * H, rsh.x * W, rsh.y * H
                zl = median_depth(dep, lx - 6, ly - 6, lx + 6, ly + 6, depth_scale)
                zr = median_depth(dep, rx - 6, ry - 6, rx + 6, ry + 6, depth_scale)
                zs = [z for z in (zl, zr) if z]
                row.update({"lsh_x": lx, "lsh_y": ly, "rsh_x": rx, "rsh_y": ry,
                            "lsh_vis": getattr(ls, "visibility", None), "rsh_vis": getattr(rsh, "visibility", None),
                            "z_lsh_m": zl, "z_rsh_m": zr, "z_sh_m": sum(zs) / len(zs) if zs else None})
                if "face_x" in row:
                    fx, fy = row["face_x"], row["face_y"]
                    th3 = angle_from_down(fx, fy, lx, ly)   # 얼굴-왼쪽 어깨 (근사)
                    th2 = angle_from_down(fx, fy, rx, ry)   # 얼굴-오른쪽 어깨 (근사)
                    row.update({"theta1_deg": th2 + th3, "theta2_deg": th2, "theta3_deg": th3})
            rows.append(row)
            if len(rows) % 150 == 0:
                print(f"   ... {len(rows)} 프레임 처리")
    finally:
        pipe.stop()
        face_det.close()
        mesh_det.close()
        pose_det.close()

    out = os.path.join(OUT_DIR, os.path.splitext(os.path.basename(rec_path))[0] + "_frames.csv")
    write_csv(out, rows)
    print(f"   -> {len(rows)} 프레임 저장: {out}")
    return rows


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


def med(vals):
    v = [x for x in vals if x is not None]
    return statistics.median(v) if v else None


def sd(vals):
    v = [x for x in vals if x is not None]
    return statistics.pstdev(v) if len(v) >= 2 else None


def summarize(all_rows):
    groups = {}
    for r in all_rows:
        groups.setdefault((r["subject"], r["round"], int(r["step"])), []).append(r)
    summary = []
    for (sub, rnd, stp), g in sorted(groups.items()):
        s = {"subject": sub, "round": rnd, "step": stp, "label": g[0]["label"], "n_frames": len(g),
             "face_detect_ratio": sum(1 for r in g if r.get("face_area_px")) / len(g),
             "pose_detect_ratio": sum(1 for r in g if r.get("z_sh_m") is not None) / len(g)}
        for k in FEATS:
            s[k] = med([r.get(k) for r in g])
            s[k + "_sd"] = sd([r.get(k) for r in g])
        summary.append(s)
    # 바로 앞 정상 자세 대비 변화량
    for s in summary:
        prev = [u for u in summary if u["subject"] == s["subject"] and u["round"] == s["round"]
                and u["label"] == "upright" and u["step"] < s["step"]]
        ref = prev[-1] if prev else (s if s["label"] == "upright" else None)
        if s["label"] == "upright" and not prev:
            ref = s
        s["ref_step"] = ref["step"] if ref else None

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
    write_csv(os.path.join(OUT_DIR, "summary_steps.csv"), summary)
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


def load_frames_csv(subjects):
    rows = []
    for sub in subjects:
        for path in sorted(glob.glob(os.path.join(OUT_DIR, f"{sub}_r*_frames.csv"))):
            with open(path, encoding="utf-8-sig") as f:
                for r in csv.DictReader(f):
                    out = {}
                    for k, v in r.items():
                        if k in ("subject", "round", "step", "label"):
                            out[k] = v
                        elif v in ("", None):
                            out[k] = None
                        else:
                            try:
                                out[k] = float(v)
                            except ValueError:
                                out[k] = v
                    rows.append(out)
            print(f"[읽기] {os.path.basename(path)}")
    return rows


# ---------------------------------------------------------------- 실행
def main():
    ap = argparse.ArgumentParser(description="바른자세 녹화 파일 분석")
    ap.add_argument("subjects", nargs="+", help="참가자 ID (예: P01 P02)")
    ap.add_argument("--step", type=int, default=1, help="N프레임마다 1장 분석 (기본 1 = 전부)")
    ap.add_argument("--from-csv", action="store_true",
                    help="녹화 파일을 다시 읽지 않고 analysis 폴더의 *_frames.csv로 요약·그래프만 다시 만들기 (빠름)")
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    if args.from_csv:
        all_rows = load_frames_csv(args.subjects)
        if not all_rows:
            print("[오류] analysis 폴더에 *_frames.csv가 없습니다. --from-csv 없이 먼저 실행하세요.")
            sys.exit(1)
        summary = summarize(all_rows)
        report(summary)
        plot_all(all_rows, summary)
        print(f"\n[완료] 결과는 {OUT_DIR} 폴더에 있습니다.")
        return
    files = find_recordings(args.subjects)
    if not files:
        sys.exit(1)
    print(f"[대상] {len(files)}개 파일: " + ", ".join(os.path.basename(f) for f in files))
    models = ensure_models()
    all_rows = []
    for f in files:
        all_rows += process_recording(f, models, max(1, args.step))
    if not all_rows:
        print("[오류] 분석된 프레임이 없습니다.")
        sys.exit(1)
    summary = summarize(all_rows)
    report(summary)
    plot_all(all_rows, summary)
    print(f"\n[완료] 결과는 {OUT_DIR} 폴더에 있습니다.")


if __name__ == "__main__":
    main()
