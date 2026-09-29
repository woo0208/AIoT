"""
바른자세 파일럿 촬영 스크립트 (Intel RealSense D455) - 자동 진행 + 자동 품질 확인

설치:  pip install pyrealsense2 opencv-python numpy pillow
사용법:
    python capture_d455.py P01 1          # 전체 자세 (정상/거북목/몸전체전방/뒤/왼/오른)
    python capture_d455.py P01 1 core     # 핵심 자세만 (정상/거북목/몸전체전방)

흐름:
  1) 거리 안내: 70~80cm 맞추면 2초 유지 후 3초 카운트다운 -> 녹화 시작
  2) 자동 진행: 화면 안내에 따라 자세만 바꾸면 됨 (키 누를 필요 없음)
       - "자세를 잡아주세요"  : 다음 자세로 바꾸는 준비 시간
       - "그대로 있으세요"    : 촬영 구간, 남은 시간이 0이 될 때까지 유지
       - "자세를 정확히 잡아주세요" : 촬영 구간 중 크게 움직였거나 사람이 안 보일 때
     (q: 중단 -> 재촬영 필요로 처리)
  3) 자동 확인: 녹화가 끝나면 cmd에 "정상적으로 촬영되었습니다" 또는 "재촬영이 필요합니다" 출력
"""
import csv
import json
import math
import os
import statistics
import sys
import time

import cv2
import numpy as np
import pyrealsense2 as rs

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_OK = True
except ImportError:
    PIL_OK = False

try:
    import winsound

    def beep(freq=1000, ms=80):
        try:
            winsound.Beep(freq, ms)
        except Exception:
            pass
except ImportError:
    def beep(freq=1000, ms=80):
        pass

# ---------------- 설정 ----------------
FPS = 15
TARGET_MIN_M, TARGET_MAX_M = 0.70, 0.80
HOLD_SEC_GUIDE = 2.0      # 거리 OK 유지 시간
COUNTDOWN_SEC = 3         # 녹화 시작 전 카운트다운
PREP_SEC = 4              # 각 자세 준비 시간
MOVE_WARN_M = 0.03        # 촬영 구간 중 흔들림 경고 기준 (최근 2초 표준편차 2cm, 품질판정 3cm)
LIVE_FWD_M = 0.04         # 거북목/몸 전체 앞으로: 앞 정상 자세보다 4cm 이상 가까워야 "그대로 있으세요"
LIVE_BACK_M = 0.02        # 뒤로 기울임: 2cm 이상 멀어져야 함
LIVE_SIDE_CX = 0.03       # 좌우 기울임: 얼굴 중심이 화면 폭의 3% 이상 이동해야 함
DISP_W, DISP_H = 960, 540

POSTURES = {
    "upright":      ("정상 자세",       "허리를 펴고 화면 표시점을 보세요",          "UPRIGHT"),
    "forward_head": ("거북목",          "시선은 그대로, 턱만 앞으로 내미세요",       "FORWARD HEAD"),
    "body_forward": ("몸 전체 앞으로",  "등을 등받이에서 떼고 상체 통째로 앞으로",   "BODY FORWARD"),
    "lean_back":    ("뒤로 기울임",     "등을 뒤로 젖히고 화면을 보세요",            "LEAN BACK"),
    "lean_left":    ("왼쪽 기울임",     "상체를 내 왼쪽으로, 고개는 돌리지 마세요",  "LEAN LEFT"),
    "lean_right":   ("오른쪽 기울임",   "상체를 내 오른쪽으로, 고개는 돌리지 마세요", "LEAN RIGHT"),
}
SEQ_CORE = [("upright", 20), ("forward_head", 10), ("upright", 5), ("body_forward", 10), ("upright", 5)]
SEQ_FULL = SEQ_CORE + [("lean_back", 10), ("lean_left", 10), ("lean_right", 10), ("upright", 5)]

# 색 (RGB, PIL용)
C_GREEN, C_RED, C_ORANGE, C_BLACK, C_WHITE = (0, 150, 0), (220, 0, 0), (230, 120, 0), (0, 0, 0), (255, 255, 255)

face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

# ---------------- 글꼴 ----------------
_FONT_CACHE = {}
FONT_PATHS = ["C:/Windows/Fonts/malgunbd.ttf", "C:/Windows/Fonts/malgun.ttf",
              "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
              "/usr/share/fonts/truetype/nanum/NanumGothic.ttf"]


def font(size):
    if size in _FONT_CACHE:
        return _FONT_CACHE[size]
    f = None
    for p in FONT_PATHS:
        if os.path.exists(p):
            try:
                f = ImageFont.truetype(p, size)
                break
            except Exception:
                pass
    _FONT_CACHE[size] = f
    return f


KOREAN_OK = PIL_OK and font(20) is not None

# ---------------- 측정 ----------------


def make_config(record_path=None):
    cfg = rs.config()
    cfg.enable_stream(rs.stream.depth, 848, 480, rs.format.z16, FPS)
    cfg.enable_stream(rs.stream.color, 1280, 720, rs.format.bgr8, FPS)
    if record_path:
        cfg.enable_record_to_file(record_path)
    return cfg


def face_distance(color_img, aligned_depth, depth_scale):
    small = cv2.resize(color_img, None, fx=0.5, fy=0.5)
    gray = cv2.equalizeHist(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY))  # 역광·어두운 얼굴 보정
    faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(40, 40))
    if len(faces) == 0:
        return None, None
    x, y, w, h = [int(v * 2) for v in max(faces, key=lambda f: f[2] * f[3])]
    patch = aligned_depth[y + h // 4: y + 3 * h // 4, x + w // 4: x + 3 * w // 4]
    valid = patch[patch > 0]
    if valid.size < 20:
        return None, (x, y, w, h)
    return float(np.median(valid)) * depth_scale, (x, y, w, h)


def body_distance(depth_img, depth_scale):
    h, w = depth_img.shape
    region = depth_img[int(h * 0.10):int(h * 0.60), int(w * 0.30):int(w * 0.70)].astype(float) * depth_scale
    valid = region[(region > 0.3) & (region < 1.5)]
    if valid.size < 200:
        return None
    return float(np.percentile(valid, 20))


def measure_distance(color_img, aligned_depth, depth_scale):
    dist, box = face_distance(color_img, aligned_depth, depth_scale)
    if dist is not None:
        return dist, box, "face"
    bdist = body_distance(aligned_depth, depth_scale)
    if bdist is not None:
        return bdist, None, "body"
    return None, None, "none"

# ---------------- 화면 ----------------


PANEL_TOP, PANEL_BOTTOM = 92, 30   # 영상 위/아래 안내 띠 높이 (영상은 가리지 않음)
C_PANEL = (32, 32, 32)


def make_display(img, box, info, msg, msg_color, sub, time_label, time_value, rec, footer, msg_en):
    img = img.copy()
    if box:
        x, y, w, h = box
        cv2.rectangle(img, (x, y), (x + w, y + h), (0, 200, 0), 3)
    video = cv2.flip(cv2.resize(img, (DISP_W, DISP_H)), 1)  # 거울처럼 좌우 반전 (녹화 파일은 원본)
    canvas = np.full((PANEL_TOP + DISP_H + PANEL_BOTTOM, DISP_W, 3), C_PANEL, np.uint8)
    canvas[PANEL_TOP:PANEL_TOP + DISP_H] = video

    if not KOREAN_OK:  # 한글 글꼴이 없을 때 영어로 표시
        cv2.putText(canvas, msg_en, (14, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 200, 255), 2)
        cv2.putText(canvas, f"{time_label}: {time_value}", (14, 72), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        return canvas

    pil = Image.fromarray(cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB))
    d = ImageDraw.Draw(pil)
    # 1줄: 왼쪽 정보
    d.text((14, 10), info, font=font(16), fill=(210, 210, 210))
    # 문구 상자
    bx0, by0, bx1, by1 = 470, 8, 800, 54
    d.rounded_rectangle((bx0, by0, bx1, by1), radius=8, fill=C_WHITE, outline=msg_color, width=3)
    f = font(22)
    tw = d.textlength(msg, font=f)
    d.text(((bx0 + bx1 - tw) / 2, by0 + 10), msg, font=f, fill=msg_color)
    # 남은 시간 상자
    tx0, tx1 = 808, 900
    d.rounded_rectangle((tx0, by0, tx1, by1), radius=8, fill=C_WHITE, outline=C_BLACK, width=2)
    f1, f2 = font(12), font(20)
    d.text(((tx0 + tx1 - d.textlength(time_label, font=f1)) / 2, by0 + 3), time_label, font=f1, fill=C_BLACK)
    d.text(((tx0 + tx1 - d.textlength(time_value, font=f2)) / 2, by0 + 20), time_value, font=f2, fill=C_BLACK)
    # 녹화 표시
    if rec:
        d.ellipse((912, 17, 940, 45), fill=C_RED)
    # 2줄: 자세 설명
    if sub:
        d.text((14, 62), sub, font=font(18), fill=C_WHITE)
    # 아래 띠: 키 안내
    d.text((14, PANEL_TOP + DISP_H + 6), footer, font=font(14), fill=(180, 180, 180))
    return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)


# ---------------- 1) 거리 안내 ----------------


def guide_phase(subject, rnd):
    pipe = rs.pipeline()
    profile = pipe.start(make_config())
    depth_scale = profile.get_device().first_depth_sensor().get_depth_scale()
    align = rs.align(rs.stream.color)
    ok_since, result = None, ("quit", None)
    print(f"[거리 안내] 얼굴까지 {TARGET_MIN_M*100:.0f}~{TARGET_MAX_M*100:.0f}cm에 맞춰주세요. (s: 건너뛰기, q: 종료)")
    try:
        while True:
            frames = align.process(pipe.wait_for_frames())
            color, depth = frames.get_color_frame(), frames.get_depth_frame()
            if not color or not depth:
                continue
            img = np.asanyarray(color.get_data())
            dist, box, mode = measure_distance(img, np.asanyarray(depth.get_data()), depth_scale)
            now = time.time()
            sub = "70~80cm에 앉아 화면 표시점을 보세요"
            if dist is None:
                msg, col, msg_en, ok_since = "사람이 보이지 않아요", C_RED, "PERSON NOT FOUND", None
            elif dist < TARGET_MIN_M:
                msg, col, ok_since = f"뒤로 {(TARGET_MIN_M - dist) * 100:.0f}cm 가세요", C_RED, None
                msg_en = "MOVE BACK"
            elif dist > TARGET_MAX_M:
                msg, col, ok_since = f"앞으로 {(dist - TARGET_MAX_M) * 100:.0f}cm 오세요", C_ORANGE, None
                msg_en = "MOVE CLOSER"
            else:
                ok_since = ok_since or now
                held = now - ok_since
                if held < HOLD_SEC_GUIDE:
                    msg, col, msg_en = "OK! 그대로 있으세요", C_GREEN, "OK - HOLD"
                else:
                    remain = COUNTDOWN_SEC - (held - HOLD_SEC_GUIDE)
                    if remain <= 0:
                        result = ("start", {"distance_m": dist, "mode": mode})
                        break
                    msg, col, msg_en = f"{math.ceil(remain)}초 후 녹화 시작", C_GREEN, f"REC IN {math.ceil(remain)}"
            dval = f"{dist * 100:.0f}cm" if dist else "--"
            disp = make_display(img, box, f"{subject} {rnd}회차 · 거리 안내 ({mode})", msg, col, sub,
                                "현재 거리", dval, False, "s: 안내 건너뛰기   q: 종료", msg_en)
            cv2.imshow("capture", disp)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                result = ("quit", None)
                break
            if key == ord("s"):
                result = ("start", {"distance_m": dist, "mode": mode + "_skipped"})
                break
    finally:
        pipe.stop()
    return result

# ---------------- 2) 녹화 + 자동 진행 ----------------


def intr_to_dict(i):
    return {"width": i.width, "height": i.height, "fx": i.fx, "fy": i.fy,
            "ppx": i.ppx, "ppy": i.ppy, "model": str(i.model), "coeffs": list(i.coeffs)}


def record_phase(subject, rnd, start_info, seq):
    os.makedirs("data", exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    base = os.path.join("data", f"{subject}_r{rnd}_{stamp}")

    profile, rec_file, pipe = None, None, None
    for ext in (".db3", ".bag"):
        pipe = rs.pipeline()
        try:
            profile = pipe.start(make_config(base + ext))
            rec_file = base + ext
            break
        except RuntimeError as e:
            print(f"[안내] {ext} 형식 녹화 불가, 다른 형식 시도: {e}")
    if profile is None:
        raise RuntimeError("녹화를 시작하지 못했습니다.")

    dev = profile.get_device()
    depth_sensor = dev.first_depth_sensor()
    depth_scale = depth_sensor.get_depth_scale()
    align = rs.align(rs.stream.color)
    cs = profile.get_stream(rs.stream.color).as_video_stream_profile()
    ds = profile.get_stream(rs.stream.depth).as_video_stream_profile()
    ex = ds.get_extrinsics_to(cs)
    info = {
        "subject": subject, "round": rnd, "start_time": stamp,
        "record_file": os.path.basename(rec_file), "start_distance": start_info,
        "target_range_m": [TARGET_MIN_M, TARGET_MAX_M], "fps": FPS,
        "sequence": seq, "prep_sec": PREP_SEC,
        "device": dev.get_info(rs.camera_info.name),
        "serial": dev.get_info(rs.camera_info.serial_number),
        "firmware": dev.get_info(rs.camera_info.firmware_version),
        "usb": dev.get_info(rs.camera_info.usb_type_descriptor)
        if dev.supports(rs.camera_info.usb_type_descriptor) else "unknown",
        "depth_scale_m": depth_scale,
        "color_intrinsics": intr_to_dict(cs.get_intrinsics()),
        "depth_intrinsics": intr_to_dict(ds.get_intrinsics()),
        "depth_to_color_extrinsics": {"rotation": list(ex.rotation), "translation": list(ex.translation)},
    }
    try:
        info["stereo_baseline_mm"] = depth_sensor.get_option(rs.option.stereo_baseline)
    except Exception:
        info["stereo_baseline_mm"] = None
    with open(base + "_camera.json", "w", encoding="utf-8") as f:
        json.dump(info, f, indent=2, ensure_ascii=False)
    if not str(info["usb"]).startswith("3"):
        print(f"[경고] USB 연결이 {info['usb']} 입니다. USB 3 포트에 꽂으세요.")

    cin = cs.get_intrinsics()
    fxfy = cin.fx * cin.fy  # 픽셀 면적 -> 실제 면적 환산용

    phases = []
    for i, (key, sec) in enumerate(seq):
        phases.append({"step": i + 1, "kind": "prep", "key": key, "dur": PREP_SEC})
        phases.append({"step": i + 1, "kind": "hold", "key": key, "dur": sec})

    markers, samples = [], []
    ph_i, ph_start, aborted = -1, None, False
    ref_up = {"dist": None, "cx": None}  # 바로 앞 정상 자세 기준값
    dist, box, mode, n = None, None, "none", 0
    rec_t0 = time.time()
    print(f"[녹화 시작] {rec_file}  (화면 안내를 따라 자세만 바꾸세요, q: 중단)")
    try:
        while True:
            frames = pipe.wait_for_frames()
            color = frames.get_color_frame()
            if not color:
                continue
            now = time.time()

            # 단계 전환
            if ph_i == -1 or now - ph_start >= phases[ph_i]["dur"]:
                if ph_i >= 0 and phases[ph_i]["kind"] == "hold" and phases[ph_i]["key"] == "upright":
                    ud = [x["distance_m"] for x in samples if x["phase_idx"] == ph_i and x["t"] > 1.0
                          and x["distance_m"] is not None]
                    uc = [x["face_cx"] for x in samples if x["phase_idx"] == ph_i and x["t"] > 1.0
                          and x["face_cx"] is not None]
                    if ud:
                        ref_up["dist"] = statistics.median(ud)
                    if uc:
                        ref_up["cx"] = statistics.median(uc)
                ph_i += 1
                if ph_i >= len(phases):
                    break
                ph_start = now
                ph = phases[ph_i]
                markers.append({"wall_time": now, "frame_timestamp_ms": frames.get_timestamp(),
                                "color_frame_number": color.get_frame_number(), "step": ph["step"],
                                "phase": ph["kind"], "label": ph["key"] if ph["kind"] == "hold" else "transition",
                                "planned_sec": ph["dur"], "distance_m": dist, "distance_mode": mode})
                beep(1300 if ph["kind"] == "hold" else 700, 90)
            ph = phases[ph_i]
            t_in = now - ph_start

            img = np.asanyarray(color.get_data())
            n += 1
            if n % 3 == 0:  # 초당 약 5회 측정
                adepth = align.process(frames).get_depth_frame()
                if adepth:
                    dist, box, mode = measure_distance(img, np.asanyarray(adepth.get_data()), depth_scale)
                    cx = (box[0] + box[2] / 2) / img.shape[1] if box else None
                    area_px = box[2] * box[3] if box else None
                    # 실제 얼굴 크기(cm²) = 픽셀 면적 × 거리² ÷ (fx·fy)  ← 깊이가 있어야 계산 가능
                    size_cm2 = area_px * dist ** 2 / fxfy * 1e4 if (box and mode == "face" and dist) else None
                    samples.append({"phase_idx": ph_i, "step": ph["step"], "phase": ph["kind"], "label": ph["key"],
                                    "t": round(t_in, 3), "distance_m": dist, "mode": mode, "face_cx": cx,
                                    "face_w_px": box[2] if box else None, "face_h_px": box[3] if box else None,
                                    "face_area_px": area_px, "face_size_cm2": size_cm2})

            name, how, name_en = POSTURES[ph["key"]]
            remain = max(0.0, ph["dur"] - t_in)
            if ph["kind"] == "prep":
                msg, col, msg_en = "자세를 잡아주세요", C_ORANGE, f"GET READY: {name_en}"
                sub = f"다음: {name} - {how}"
                if ph["key"] in ("forward_head", "body_forward", "lean_back") and dist and ref_up["dist"]:
                    sub += f"  (지금 {(ref_up['dist'] - dist) * 100:+.0f}cm)"
            else:
                recent = [x for x in samples if x["phase_idx"] == ph_i and x["t"] > 0.5][-10:]  # 최근 약 2초
                rd = [x["distance_m"] for x in recent if x["distance_m"] is not None]
                rc = [x["face_cx"] for x in recent if x["face_cx"] is not None]
                hint = None  # 자세가 충분하지 않을 때의 안내
                if len(rd) >= 3 and ref_up["dist"] is not None:
                    dnow = statistics.median(rd[-5:])
                    closer = ref_up["dist"] - dnow
                    if ph["key"] in ("forward_head", "body_forward") and closer < LIVE_FWD_M:
                        hint = f"조금 더 앞으로 (지금 {closer*100:.0f}cm, 목표 8~12cm)"
                    elif ph["key"] == "lean_back" and -closer < LIVE_BACK_M:
                        hint = f"조금 더 뒤로 (지금 {-closer*100:.0f}cm)"
                if hint is None and ph["key"] in ("lean_left", "lean_right") and len(rc) >= 3 \
                        and ref_up["cx"] is not None and abs(statistics.median(rc[-5:]) - ref_up["cx"]) < LIVE_SIDE_CX:
                    hint = "조금 더 옆으로 기울이세요"
                if dist is None:
                    msg, col, msg_en = "자세를 정확히 잡아주세요", C_RED, "ADJUST POSTURE"
                    sub = f"{name} - 사람이 잘 보이지 않아요"
                elif hint:
                    msg, col, msg_en = "자세를 정확히 잡아주세요", C_RED, "ADJUST POSTURE"
                    sub = f"{name} - {hint}"
                elif len(rd) >= 5 and statistics.pstdev(rd) > 0.02:
                    msg, col, msg_en = "자세를 정확히 잡아주세요", C_RED, "DON'T MOVE"
                    sub = f"{name} - 움직이지 마세요"
                else:
                    msg, col, msg_en = "그대로 있으세요", C_GREEN, f"HOLD: {name_en}"
                    sub = f"{name} - {how}"
            dtxt = f"{dist * 100:.1f}cm ({mode})" if dist else "--"
            disp = make_display(img, box,
                                f"{subject} {rnd}회차 · {ph['step']}/{len(seq)}단계 · 거리 {dtxt}",
                                msg, col, sub, "남은 시간", f"{math.ceil(remain)}초", True,
                                "q: 촬영 중단", msg_en)
            cv2.imshow("capture", disp)
            if (cv2.waitKey(1) & 0xFF) == ord("q"):
                aborted = True
                break
    finally:
        pipe.stop()
        total_sec = time.time() - rec_t0
        markers.append({"wall_time": time.time(), "frame_timestamp_ms": None, "color_frame_number": None,
                        "step": None, "phase": "end", "label": "aborted" if aborted else "end",
                        "planned_sec": None, "distance_m": dist, "distance_mode": mode})
        with open(base + "_markers.csv", "w", newline="", encoding="utf-8") as f:
            wr = csv.DictWriter(f, fieldnames=list(markers[0].keys()))
            wr.writeheader()
            wr.writerows(markers)
        if samples:
            with open(base + "_samples.csv", "w", newline="", encoding="utf-8") as f:
                wr = csv.DictWriter(f, fieldnames=list(samples[0].keys()))
                wr.writeheader()
                wr.writerows(samples)
        beep(1000, 150); beep(1000, 150)
        print(f"[녹화 종료] {rec_file}")
    return base, rec_file, phases, samples, aborted, total_sec

# ---------------- 3) 자동 품질 확인 ----------------


def quality_check(phases, samples, aborted):
    fails, warns, rows = [], [], []
    if aborted:
        fails.append("촬영이 중간에 중단되었습니다")

    def seg(pi):
        dur = phases[pi]["dur"]
        return [s for s in samples if s["phase_idx"] == pi and 1.0 < s["t"] < dur - 0.5]

    stats = {}
    for pi, ph in enumerate(phases):
        if ph["kind"] != "hold":
            continue
        ss = seg(pi)
        if not ss:
            if not aborted:
                fails.append(f"{ph['step']}단계 {POSTURES[ph['key']][0]}: 측정값 없음")
            continue
        d = [s["distance_m"] for s in ss if s["distance_m"] is not None]
        cx = [s["face_cx"] for s in ss if s["face_cx"] is not None]
        person_ratio = len(d) / len(ss)
        face_ratio = sum(1 for s in ss if s["mode"] == "face") / len(ss)
        med = statistics.median(d) if d else None
        sd = statistics.pstdev(d) if len(d) >= 2 else 0.0
        ar = [s["face_area_px"] for s in ss if s.get("face_area_px") and s["mode"] == "face"]
        sz = [s["face_size_cm2"] for s in ss if s.get("face_size_cm2")]
        stats[pi] = {"med": med, "sd": sd, "cx": statistics.median(cx) if cx else None,
                     "area": statistics.median(ar) if ar else None, "size": statistics.median(sz) if sz else None}
        name = f"{ph['step']}단계 {POSTURES[ph['key']][0]}"
        rows.append([name, med, sd, person_ratio, face_ratio, stats[pi]["area"], None, stats[pi]["size"], pi])
        if person_ratio < 0.5:
            fails.append(f"{name}: 사람이 잘 검출되지 않음 ({person_ratio*100:.0f}%)")
        elif face_ratio < 0.5:
            warns.append(f"{name}: 얼굴 검출이 적음 ({face_ratio*100:.0f}%)")
        if sd > MOVE_WARN_M:
            warns.append(f"{name}: 움직임이 큼 (흔들림 ±{sd*100:.1f}cm)")

    ups = [pi for pi, ph in enumerate(phases) if ph["kind"] == "hold" and ph["key"] == "upright"
           and pi in stats and stats[pi]["med"] is not None]
    # 원 논문 방식 면적 비율 A = 현재 픽셀 면적 / 바로 앞 정상 자세 픽셀 면적
    for row in rows:
        pi = row[8]
        prev = [u for u in ups if u < pi and stats[u]["area"]]
        if phases[pi]["key"] == "upright":
            row[6] = 1.0 if stats[pi]["area"] else None
        elif prev and stats[pi]["area"]:
            row[6] = stats[pi]["area"] / stats[prev[-1]]["area"]
    if ups:
        base_up = stats[ups[0]]["med"]
        base_cx = stats[ups[0]]["cx"]
        if not (0.65 <= base_up <= 0.85):
            warns.append(f"첫 정상 자세 거리 {base_up*100:.1f}cm (권장 70~80cm)")
        for pi in ups[1:]:
            diff = stats[pi]["med"] - base_up
            if abs(diff) > 0.05:
                warns.append(f"{phases[pi]['step']}단계 정상 자세 복귀 위치 차이 {diff*100:+.1f}cm")
        shifts = {}
        for pi, ph in enumerate(phases):
            if ph["kind"] != "hold" or pi not in stats or stats[pi]["med"] is None:
                continue
            name = f"{ph['step']}단계 {POSTURES[ph['key']][0]}"
            prev_ups = [u for u in ups if u < pi]  # 바로 앞의 정상 자세를 기준으로 비교
            ref_up = stats[prev_ups[-1]]["med"] if prev_ups else base_up
            closer = ref_up - stats[pi]["med"]
            if ph["key"] in ("forward_head", "body_forward") and closer < 0.015:
                fails.append(f"{name}: 얼굴이 앞으로 거의 나오지 않음 ({closer*100:+.1f}cm)")
            if ph["key"] == "lean_back" and -closer < 0.015:
                warns.append(f"{name}: 뒤로 거의 이동하지 않음 ({-closer*100:+.1f}cm)")
            if ph["key"] in ("lean_left", "lean_right") and stats[pi]["cx"] is not None and base_cx is not None:
                shifts[ph["key"]] = stats[pi]["cx"] - base_cx
                if abs(shifts[ph["key"]]) < 0.03:
                    warns.append(f"{name}: 좌우 이동이 작음")
        if "lean_left" in shifts and "lean_right" in shifts and shifts["lean_left"] * shifts["lean_right"] > 0:
            warns.append("왼쪽/오른쪽 기울임이 같은 방향으로 측정됨 (방향 확인 필요)")
    return fails, warns, rows


def count_frames(path):
    pipe, cfg = rs.pipeline(), rs.config()
    cfg.enable_device_from_file(path, repeat_playback=False)
    profile = pipe.start(cfg)
    profile.get_device().as_playback().set_real_time(False)
    nc = nd = 0
    try:
        while True:
            ok, fr = pipe.try_wait_for_frames(2000)
            if not ok:
                break
            nc += 1 if fr.get_color_frame() else 0
            nd += 1 if fr.get_depth_frame() else 0
    finally:
        pipe.stop()
    return nc, nd


def report(subject, rnd, base, rec_file, phases, samples, aborted, total_sec):
    fails, warns, rows = quality_check(phases, samples, aborted)

    print("\n[파일 확인 중] 녹화 파일의 프레임 수를 세는 중입니다... (잠시 기다려주세요)")
    try:
        nc, nd = count_frames(rec_file)
        expected = total_sec * FPS
        ratio = min(nc, nd) / expected if expected > 0 else 0
        frame_line = f"컬러 {nc} / 깊이 {nd} 프레임 (예상 약 {expected:.0f}, {ratio*100:.0f}%)"
        if nc == 0 or nd == 0:
            fails.append("녹화 파일에 컬러 또는 깊이 프레임이 없음")
        elif ratio < 0.85:
            fails.append(f"프레임 누락이 많음 ({ratio*100:.0f}%)")
    except Exception as e:
        frame_line = f"확인 실패: {e}"
        warns.append("녹화 파일 프레임 확인 실패 (check_recording.py로 따로 확인하세요)")

    print("\n" + "=" * 64)
    print(f" 촬영 결과: {subject} {rnd}회차   ({os.path.basename(rec_file)})")
    print("=" * 64)
    print(f" 녹화 길이 {total_sec:.1f}초 | {frame_line}")
    print(" 단계별 측정")
    print("   단계              거리     흔들림   사람  얼굴 | 얼굴면적(px) 면적비율A 실제얼굴크기")
    for name, med, sd, pr, fr, area, a_ratio, size, _ in rows:
        m = f"{med*100:5.1f}cm" if med else "   -- "
        ar = f"{area:8.0f}" if area else "      --"
        ra = f"{a_ratio:5.2f}" if a_ratio else "  -- "
        sz = f"{size:6.0f}cm²" if size else "    --"
        print(f"   {name:<16} {m}  ±{sd*100:4.1f}cm  {pr*100:3.0f}%  {fr*100:3.0f}% | {ar}      {ra}    {sz}")
    print("   * 면적비율A: 바로 앞 정상 자세 대비 (원 논문 방식, 일반 웹캠으로도 계산 가능)")
    print("   * 실제얼굴크기: 픽셀 면적 × 거리² ÷ 초점거리² (스테레오 깊이가 있어야 계산 가능)")
    print("     -> 가까이 가도 거의 일정해야 정상. 사람 간 차이는 실제 얼굴 크기 차이")
    print("-" * 64)
    if fails:
        print(" [재촬영이 필요합니다]")
        for x in fails:
            print(f"   - {x}")
        for x in warns:
            print(f"   (주의) {x}")
        verdict = "retake"
    elif warns:
        print(" [정상적으로 촬영되었습니다 - 주의 사항 있음, 사용 가능]")
        for x in warns:
            print(f"   (주의) {x}")
        verdict = "ok_with_warnings"
    else:
        print(" [정상적으로 촬영되었습니다]")
        verdict = "ok"
    print("=" * 64 + "\n")

    with open(base + "_quality.json", "w", encoding="utf-8") as f:
        json.dump({"verdict": verdict, "fails": fails, "warnings": warns, "frames": frame_line,
                   "total_sec": total_sec,
                   "steps": [{"name": r[0], "median_m": r[1], "sd_m": r[2], "person_ratio": r[3],
                              "face_ratio": r[4], "face_area_px": r[5], "area_ratio_A": r[6],
                              "face_size_cm2": r[7]} for r in rows]},
                  f, indent=2, ensure_ascii=False)
    if verdict == "retake":
        print(f" 같은 회차 번호로 다시 찍으세요:  python capture_d455.py {subject} {rnd}"
              + (" core" if len(phases) == len(SEQ_CORE) * 2 else ""))
        print(" (실패한 파일은 지우거나 이름 앞에 X_ 를 붙여 구분하세요)\n")


def main():
    if len(sys.argv) < 3:
        print("사용법: python capture_d455.py <참가자ID> <회차> [core]")
        sys.exit(1)
    subject, rnd = sys.argv[1], sys.argv[2]
    seq = SEQ_CORE if (len(sys.argv) > 3 and sys.argv[3].lower() == "core") else SEQ_FULL
    if not KOREAN_OK:
        print("[안내] 한글 표시를 위해 'pip install pillow'를 설치하세요. 지금은 영어로 표시합니다.")
    total = sum(s for _, s in seq) + PREP_SEC * len(seq)
    print(f"[설정] {'핵심' if seq is SEQ_CORE else '전체'} 자세 {len(seq)}단계, 예상 녹화 약 {total}초 "
          f"(약 {total * 0.05:.1f}GB)")
    try:
        action, start_info = guide_phase(subject, rnd)
        if action != "start":
            print("녹화 없이 종료했습니다.")
            return
        result = record_phase(subject, rnd, start_info, seq)
    finally:
        cv2.destroyAllWindows()
    report(subject, rnd, *result)


if __name__ == "__main__":
    main()
