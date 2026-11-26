"""
원 논문 데이터(Dataset.xlsx)와 우리 촬영 데이터 비교 스크립트

목적: "우리가 원 논문과 같은 자세를 같은 방식으로 찍었는가"를 확인.
      (v4 2단계의 공공데이터 호환성 판정 방법 (a) 특징 방향 일치를 우리 데이터에 먼저 적용)

비교는 해상도·거리와 무관한 값으로만 합니다.
  - A          : 본인 정상 자세 대비 얼굴 면적 비율 (원 논문 W열과 같은 정의,
                 우리 쪽은 박스가 거리 변화를 잘 반영하지 못해 외곽선(세그먼트) 면적 사용)
  - 각도 R     : 원 논문 R열 정의 = 2 × atan(|얼굴x - 화면왼쪽어깨x| / (어깨y - 얼굴y))
                 (Dataset.xlsx 100행 전부에서 이 식과 소수점까지 일치함을 확인)
  - 얼굴 높이  : (양어깨 중점 y - 얼굴 y) / 어깨 폭   (얼굴이 어깨보다 얼마나 위에 있나)
  - 좌우 치우침: (얼굴 x - 양어깨 중점 x) / 어깨 폭   (+ = 화면 오른쪽)
  각 값은 본인 첫 정상 자세 대비 변화량(Δ)도 함께 봅니다.

사용법 (analyze_d455.py 실행 후):
    pip install openpyxl
    python compare_paper.py P01 P02
결과: analysis/paper_compare.csv, analysis/fig4_paper_compare.png, 화면 요약
"""
import csv
import glob
import math
import os
import statistics
import sys
import urllib.request
import warnings

warnings.filterwarnings("ignore", message=".*Glyph.*")

OUT_DIR = "analysis"
XLSX_URL = "https://raw.githubusercontent.com/icml2410/posture/main/Dataset.xlsx"
POSTURE_KO = {"upright": "정상", "forward_head": "거북목", "lean_back": "뒤로 기울임",
              "lean_left": "왼쪽 기울임", "lean_right": "오른쪽 기울임", "body_forward": "몸 전체 앞으로"}
METRICS = [("A", "면적 비율 A (우리: 외곽선 기준)"), ("dR", "Δ각도 R (도)"), ("dH", "Δ얼굴 높이 (어깨폭 대비)"),
           ("off", "좌우 치우침 (어깨폭 대비)")]


def num(v):
    try:
        return float(str(v).strip().strip("(), "))
    except (TypeError, ValueError):
        return None


def feats(fx, fy, lx, ly, rx, ry):
    """lx,ly = 화면 왼쪽 어깨, rx,ry = 화면 오른쪽 어깨 (이미지 좌표)."""
    if None in (fx, fy, lx, ly, rx, ry):
        return None
    sw = abs(rx - lx)
    if sw < 1:
        return None
    my, mx = (ly + ry) / 2, (lx + rx) / 2
    R = 2 * math.degrees(math.atan2(abs(fx - lx), (ly - fy))) if ly != fy else None
    return {"R": R, "H": (my - fy) / sw, "off": (fx - mx) / sw}


# ---------------------------------------------------------------- 원 논문 데이터
def load_paper(path):
    import openpyxl
    ws = openpyxl.load_workbook(path, data_only=True).active
    rows = [r for r in ws.iter_rows(min_row=2, values_only=True) if r[0]]
    per = {}
    for r in rows:
        sub = str(r[0]).split("_")[1]
        # F,G=얼굴 중심 / P,Q=화면 왼쪽 어깨 / K,L=화면 오른쪽 어깨 (값 기준 확인)
        f = feats(num(r[5]), num(r[6]), num(r[15]), num(r[16]), num(r[10]), num(r[11]))
        if f:
            f.update({"A": num(r[22]), "pose": int(r[1])})
            per.setdefault(sub, {})[int(r[1])] = f
    out = []
    for sub, d in per.items():
        if 1 not in d:
            continue
        up = d[1]
        for pose, f in d.items():
            out.append({"subject": sub, "pose": pose, "A": f["A"],
                        "dR": f["R"] - up["R"] if f["R"] is not None and up["R"] is not None else None,
                        "dH": f["H"] - up["H"], "off": f["off"], "R": f["R"], "H": f["H"]})
    return out


# ---------------------------------------------------------------- 우리 데이터
def load_ours(subjects):
    out = []
    for sub in subjects:
        for path in sorted(glob.glob(os.path.join(OUT_DIR, f"{sub}_r*_frames.csv"))):
            with open(path, encoding="utf-8-sig") as f:
                frames = list(csv.DictReader(f))
            steps = {}
            for fr in frames:
                steps.setdefault(int(fr["step"]), []).append(fr)
            rnd = frames[0]["round"] if frames else "?"
            per = {}
            for stp, g in sorted(steps.items()):
                vals = {"R": [], "H": [], "off": [], "area": []}
                for fr in g:
                    # 우리 영상은 좌우 반전 없음: 사람의 오른쪽 어깨(rsh) = 화면 왼쪽
                    f = feats(num(fr.get("face_x")), num(fr.get("face_y")),
                              num(fr.get("rsh_x")), num(fr.get("rsh_y")),
                              num(fr.get("lsh_x")), num(fr.get("lsh_y")))
                    if f:
                        for k in ("R", "H", "off"):
                            if f[k] is not None:
                                vals[k].append(f[k])
                    a = num(fr.get("oval_area_px")) or None  # 박스 면적은 불안정하여 외곽선(세그먼트) 면적 사용
                    if a:
                        vals["area"].append(a)
                per[stp] = {"label": g[0]["label"],
                            **{k: (statistics.median(v) if v else None) for k, v in vals.items()}}
            ups = [s for s in sorted(per) if per[s]["label"] == "upright"]
            if not ups:
                continue
            up = per[ups[0]]  # 원 논문처럼 기준 정상 자세 1개 (각 회차 첫 20초)
            for stp, p in per.items():
                out.append({"subject": sub, "round": rnd, "step": stp, "label": p["label"],
                            "A": p["area"] / up["area"] if p["area"] and up["area"] else None,
                            "dR": p["R"] - up["R"] if p["R"] is not None and up["R"] is not None else None,
                            "dH": p["H"] - up["H"] if p["H"] is not None and up["H"] is not None else None,
                            "off": p["off"], "R": p["R"], "H": p["H"]})
    return out


# ---------------------------------------------------------------- 비교
def med(v):
    v = [x for x in v if x is not None]
    return statistics.median(v) if v else None


def main():
    subjects = sys.argv[1:] or ["P01"]
    os.makedirs(OUT_DIR, exist_ok=True)
    xlsx = next((p for p in ("Dataset.xlsx", os.path.join("data", "Dataset.xlsx")) if os.path.exists(p)), None)
    if not xlsx:
        print("[다운로드] 원 논문 Dataset.xlsx (GitHub icml2410/posture)")
        xlsx = "Dataset.xlsx"
        urllib.request.urlretrieve(XLSX_URL, xlsx)
    paper = load_paper(xlsx)
    ours = load_ours(subjects)
    if not ours:
        print("[오류] analysis 폴더에 *_frames.csv가 없습니다. 먼저 analyze_d455.py를 실행하세요.")
        sys.exit(1)

    # 원 논문 자세 4/5가 왼쪽/오른쪽 중 무엇인지: 좌우 치우침 부호로 추정
    p4 = med([r["off"] for r in paper if r["pose"] == 4])
    p5 = med([r["off"] for r in paper if r["pose"] == 5])
    ol = med([r["off"] for r in ours if r["label"] == "lean_left"])
    mapping = {1: "upright", 2: "forward_head", 3: "lean_back"}
    note = ""
    if ol is not None and p4 is not None and p5 is not None:
        if (ol > 0) == (p4 > 0):
            mapping.update({4: "lean_left", 5: "lean_right"})
        else:
            mapping.update({4: "lean_right", 5: "lean_left"})
        note = (f"원 논문 자세4 치우침 {p4:+.2f}, 자세5 {p5:+.2f} / 우리 왼쪽 기울임 {ol:+.2f}"
                f" → 자세4={POSTURE_KO[mapping[4]]}, 자세5={POSTURE_KO[mapping[5]]}로 추정")
    else:
        mapping.update({4: "lean_4?", 5: "lean_5?"})
    for r in paper:
        r["label"] = mapping.get(r["pose"], str(r["pose"]))

    labels = ["upright", "forward_head", "lean_back", "lean_left", "lean_right", "body_forward"]
    lines, table = [], []
    P = lines.append
    P("=" * 78)
    P(" 원 논문 데이터(20명) vs 우리 촬영 데이터 비교")
    P("=" * 78)
    if note:
        P(" " + note)
    P(" 판정: [범위 안] 우리 값이 원 논문 20명의 최소~최대 안 / [방향 일치] 정상 대비 변화 방향(부호)이 같음")
    for key, title in METRICS:
        P(f"\n■ {title}")
        P("   자세            원 논문 중앙값 [최소~최대]      " + "   ".join(f"{s:>10}" for s in subjects) + "   판정")
        for lab in labels:
            pv = [r[key] for r in paper if r["label"] == lab and r[key] is not None]
            if lab == "upright" and key in ("A", "dR", "dH"):
                continue
            ov = {s: [r[key] for r in ours if r["subject"] == s and r["label"] == lab and r[key] is not None]
                  for s in subjects}
            if not pv and not any(ov.values()):
                continue
            pm = statistics.median(pv) if pv else None
            ptxt = f"{pm:7.2f} [{min(pv):6.2f}~{max(pv):6.2f}]" if pv else "   (원 논문에 없는 자세)   "
            otxt, verdict = [], []
            for s in subjects:
                m = med(ov[s])
                otxt.append(f"{m:10.2f}" if m is not None else f"{'--':>10}")
                if m is not None and pv:
                    base = 1.0 if key == "A" else 0.0
                    inr = min(pv) <= m <= max(pv)
                    if key == "off" and lab not in ("lean_left", "lean_right"):
                        dtxt = ""  # 좌우 치우침은 좌/우 기울임에서만 방향을 봄
                    else:
                        dtxt = "/방향 일치" if (m - base) * (pm - base) > 0 else "/방향 다름"
                    verdict.append(f"{s}:{'범위 안' if inr else '범위 밖'}{dtxt}")
                table.append({"metric": key, "label": lab, "paper_median": pm,
                              "paper_min": min(pv) if pv else None, "paper_max": max(pv) if pv else None,
                              "subject": s, "ours_median": m, "ours_rounds": ";".join(f"{x:.3f}" for x in ov[s])})
            P(f"   {POSTURE_KO.get(lab, lab):<12} {ptxt}  " + "   ".join(otxt) + "   " + ", ".join(verdict))
    P("\n* 우리 값은 각 회차 첫 정상 자세(20초) 대비, 3회차의 중앙값")
    P("* 몸 전체 앞으로는 원 논문에 없는 자세 (교수님 지적 3번 검증용으로 추가)")
    P("* 카메라 높이·화각이 원 논문과 다르면 각도 R과 얼굴 높이는 절대값이 달라질 수 있음 → 방향 일치를 우선 확인")
    text = "\n".join(lines)
    print(text)
    with open(os.path.join(OUT_DIR, "paper_compare.txt"), "w", encoding="utf-8") as f:
        f.write(text)
    with open(os.path.join(OUT_DIR, "paper_compare.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(table[0].keys()))
        w.writeheader()
        w.writerows(table)
    plot(paper, ours, subjects, labels)


def plot(paper, ours, subjects, labels):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    for name in ("Malgun Gothic", "NanumGothic", "Noto Sans CJK KR", "Noto Sans CJK JP", "AppleGothic"):
        if any(name == f.name for f in font_manager.fontManager.ttflist):
            matplotlib.rcParams["font.family"] = name
            break
    matplotlib.rcParams["axes.unicode_minus"] = False
    marks = ["o", "s", "^", "D"]
    cols = ["#D85A30", "#378ADD", "#1D9E75", "#7F77DD"]
    fig, axes = plt.subplots(1, 4, figsize=(16, 4.6))
    for ax, (key, title) in zip(axes, METRICS):
        xt = []
        for i, lab in enumerate(labels):
            pv = [r[key] for r in paper if r["label"] == lab and r[key] is not None]
            if pv:
                ax.boxplot(pv, positions=[i], widths=0.5, showfliers=False,
                           medianprops={"color": "#444"}, boxprops={"color": "#999"},
                           whiskerprops={"color": "#999"}, capprops={"color": "#999"})
                ax.plot([i + (k % 5 - 2) * 0.04 for k in range(len(pv))], pv, ".", color="#B4B2A9", ms=4)
            for j, s in enumerate(subjects):
                ov = [r[key] for r in ours if r["subject"] == s and r["label"] == lab and r[key] is not None]
                ax.plot([i + 0.3 + j * 0.1] * len(ov), ov, marks[j % 4], color=cols[j % 4], ms=6)
            xt.append(POSTURE_KO[lab].replace(" ", "\n", 1))
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(xt, fontsize=8)
        ax.set_title(title, fontsize=10)
        ax.axhline(1.0 if key == "A" else 0.0, color="#aaa", lw=0.8)
    handles = [plt.Line2D([], [], marker=marks[j % 4], color=cols[j % 4], ls="", label=s) for j, s in enumerate(subjects)]
    handles.append(plt.Line2D([], [], marker="s", color="#999", ls="", mfc="none", label="원 논문 20명 (상자)"))
    fig.legend(handles=handles, loc="upper right", fontsize=9, ncol=len(handles))
    fig.suptitle("원 논문 데이터(회색 상자·점) vs 우리 촬영 데이터(색 점, 회차별)", fontsize=12, x=0.35)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(os.path.join(OUT_DIR, "fig4_paper_compare.png"), dpi=150)
    plt.close(fig)
    print(f"\n[그래프 저장] {OUT_DIR}/fig4_paper_compare.png")


if __name__ == "__main__":
    main()
