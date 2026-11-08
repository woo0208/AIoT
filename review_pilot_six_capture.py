"""Read-only CSV/metadata audit of the new 6x10 exploratory captures.

python -X utf8 -B review_pilot_six_capture.py
Append --verify to check saved review hashes/report. No video or model execution.
"""
import argparse
from collections import Counter, defaultdict
import csv
import json
import math
from pathlib import Path

from review_lr_features import ROOT, read, digest
from capture_six_pilot import LABELS
from posture_geometry_probe import CSV_FIELDS, EXPLORATORY_ARTIFACT_KIND
from f1_sample_aggregator import H9_FEATURE_NAMES
from h6_offline import load_labeled_probe_h_samples, aggregation_audit

OUT = ROOT / "analysis/PILOT_SIX_CAPTURE_REVIEW_20261106"
SIX = (0, 2, 3, 5, 6, 7)


def csv_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        assert tuple(reader.fieldnames or ()) == CSV_FIELDS, f"CSV header: {path}"
        rows = list(reader)
    assert all(None not in r and all(v is not None for v in r.values()) for r in rows), f"CSV structure: {path}"
    return rows


def present(row, feature):
    value = row[feature]
    return bool(value.strip()) and math.isfinite(float(value))


def audit_run(directory):
    plan, summary = read(directory / "plan.json"), read(directory / "run_summary.json")
    assert plan["scope"] == summary["scope"] == "EXPLORATORY_PILOT_ONLY"
    assert plan["subject"] == summary["subject"] and plan["recording_id"] == summary["recording_id"] == directory.name
    assert plan["posture_order"] == list(LABELS) and plan["repeats"] == plan["hold_seconds"] == 10
    assert plan["target_segments"] == 60 and plan["transition_frames_in_features"] is False
    assert digest(directory / "features.csv") == summary["features_sha256"]
    source_matches = {name: digest(ROOT / name) == sha for name, sha in plan["source_sha256"].items()}
    assert all(source_matches.values()), f"capture source drift: {directory}"
    rows = csv_rows(directory / "features.csv")
    groups = defaultdict(list)
    for row in rows:
        assert row["artifact_kind"] == EXPLORATORY_ARTIFACT_KIND
        assert row["subject"] == plan["subject"] and row["recording_id"] == plan["recording_id"]
        assert row["label"] in LABELS  # excludes PREP/TRANSITION/reset rows
        groups[int(row["segment_id"])].append(row)
    segments = summary["segments"]
    assert len(segments) == summary["completed_segments"] == len(groups)
    assert set(groups) == set(range(1, len(segments)+1))
    counts = Counter(s["label"] for s in segments)
    assert {label:counts[label] for label in LABELS} == summary["counts"]
    assert len(summary["attempts"]) == len(list((directory / "attempts").glob("attempt_*.json")))
    for attempt in summary["attempts"]:
        sidecar = directory / "attempts" / f"attempt_{attempt['attempt_id']:03d}.json"
        assert read(sidecar) == attempt
        attempt_rows = csv_rows(sidecar.with_suffix(".csv"))
        assert len(attempt_rows) == attempt["frames"]
        if attempt["status"] == "COMPLETED":
            assert attempt in segments
            assert attempt_rows == groups[attempt["intended_segment"]]
        else:
            assert attempt["status"] == "ABORTED" and attempt not in segments
    timing = []
    for segment in segments:
        sid = segment["intended_segment"]
        records = groups[sid]
        assert segment["label"] == LABELS[(sid-1) % 6] and segment["status"] == "COMPLETED"
        assert all(r["label"] == segment["label"] for r in records)
        stamps = [float(r["device_timestamp_ms"]) for r in records]
        start, end = segment["first_device_ms"], segment["window_end_device_ms"]
        assert all(math.isfinite(t) and start <= t < end for t in stamps)
        assert all(b > a for a,b in zip(stamps, stamps[1:]))
        assert stamps[0] == start and stamps[-1] == segment["last_device_ms"]
        assert len(records) == segment["frames"]
        assert abs(end-start-10000) < 1e-6 and segment["observed_end_device_ms"] >= end
        assert segment["first_frame_index"] <= segment["last_frame_index"] < segment["end_boundary_frame_index"]
        timing.append(dict(segment_id=sid, frames=len(records), first_device_ms=start,
                           last_device_ms=stamps[-1], window_end_device_ms=end,
                           end_boundary_delay_ms=segment["observed_end_device_ms"]-end,
                           max_observed_interval_ms=max(b-a for a,b in zip(stamps,stamps[1:])) if len(stamps)>1 else None))
    if summary["status"] == "COMPLETED":
        assert len(segments) == 60 and set(counts.values()) == {10} and summary["error"] is None
    else:
        assert summary["status"] in ("INTERRUPTED", "FAILED")
    return dict(directory=str(directory.relative_to(ROOT)), subject=plan["subject"],
                recording_id=plan["recording_id"], status=summary["status"], error=summary["error"],
                completed_segments=len(segments), counts=summary["counts"], frames=len(rows),
                attempt_status_counts=dict(Counter(a["status"] for a in summary["attempts"])),
                source_hash_matches=source_matches, integrity="PASS", timing=timing,
                operator_metadata=plan["operator_metadata"]), rows


def report(saved):
    stats = saved["aggregation"]
    p5 = [s for s in saved["samples"] if s["subject"] == "P01" and s["label"] == "lean_forward"]
    bad_p5 = [s for s in p5 if not s["eligible"]]
    good_supports = Counter(s["common_valid"] for s in p5 if s["eligible"])
    supports_text = ", ".join(f"{count}/150 {n}구간" for count,n in sorted(good_supports.items()))
    lines = ["# P01/P02 추가 탐색 촬영 검토", "",
             f"**촬영 완료120구간, 기존 H9/6특징 공통 분석 적격 {stats['eligible_sample_count']}구간.** "
             "실제 새 CSV·메타데이터만 검토했으며 원본 영상 열람·모델 학습·분류 성능 평가·재촬영은 하지 않았다.", "",
             "## 촬영 완료와 분석 적격", "",
             "|참가자|촬영 완료|자세별 촬영|프레임|기존 기준 적격|부적격|",
             "|---|---:|---|---:|---:|---:|"]
    for person, quality in saved["participants"].items():
        lines.append(f"|{person}|60|P0~P5 각10|{quality['frames']}|{quality['eligible']}|{60-quality['eligible']}|")
    lines += ["", "기준은 기존 H9 9열 공동 유효 ≥30프레임·coverage ≥50%다. "
              "현재6특징 F1/F3/F4/F6/F7/F8만 보더라도 지원 프레임이 H9와 정확히 같았으므로 "
              "F2/F5/F9 제거로 누락 구간이 복구되지는 않는다. 기준을 완화하거나 결측을 채우지 않았다.", "",
              "|자세|전체 촬영|분석 적격|", "|---|---:|---:|"]
    for i,label in enumerate(LABELS):
        lines.append(f"|P{i} {label}|20|{saved['eligible_class_counts'][label]}|")
    lines += ["", "## 특징 결측", "",
              f"완료120구간의 전체 {stats['input_frame_count']:,}프레임 중 H9 공동 유효는 "
              f"{stats['common_valid_frame_count']:,}, 공동 support 밖 프레임은 {stats['excluded_frame_count']:,}개다.", "",
              "P01 P5(상체 전방)에서만2D 특징 F1~F5가 함께 누락됐다. 해당 프레임은 Pose 검출·코·귀 좌표가 "
              "유효했지만 양 iris·턱 좌표 flag와 Face matrix가 무효였다. "
              "F6~F9 Depth 특징 셀은 존재했다. 따라서 저장 관측상 직접적인 누락 지점은 FaceLandmarker 기반 "
              "iris/턱 관측이며, 전체 Pose나 Depth 특징이 함께 사라진 경우는 아니다.", "",
              f"P01 P5 중 부적격{len(bad_p5)}구간의 공동 유효는 "
              f"{min(s['common_valid'] for s in bad_p5)}~{max(s['common_valid'] for s in bad_p5)}/150이었다. "
              f"적격 구간은 {supports_text}이었다. 얼굴 가림·화면 이탈·머리 각도·검출 실패 중 "
              "물리적 원인은 CSV만으로 확정할 수 없다.", "",
              "## 파일·시간·전환 검증", "",
              "- 완료 실행은 참가자별 정확히1개였다. COMPLETED 상태·동일 identity·완료 수·클래스 균형을 확인해 "
              "두 실행을 검토 대상으로 연결했다. 파일명 최신순으로 선택하거나 서로 다른 실행을 이어붙이지 않았다.",
              "- P02에는 별도로 중단된 실행2개(완료2구간·7구간)가 있다. 원본을 보존했고 이번120구간에 합치지 않았다.",
              "- features.csv hash와 실행 당시 capture/probe/geometry/model-lock 코드 hash가 일치했다. "
              "각 완료 구간은 해당 attempt CSV 및 JSON과 행 단위로 정확히 같았다.",
              "- 모든 완료 구간이 기록된10초 반개구간 안에 있으며 device timestamp는 엄격 증가했다. "
              "완료 구간당150프레임이고 PREP/TRANSITION 라벨이나 완료 목록 밖 segment는 main CSV에 없었다.",
              "- 이 검사는 저장 경계와 라벨 기록을 확인한다. 사람이 실제로 자세를 안정적으로 취했는지, "
              "정상 복귀를 정확히 수행했는지를 영상 없이 독립 확인한 것은 아니다.", "",
              "## 다음 분석의 범위", "",
              "현재 기존 기준으로 사용할 수 있는 표본은 **113개**이며 P5는 전체13개, 다른 자세는각20개다. "
              "P01 P5는3개, P02 P5는10개여서 참가자·자세별 불균형을 반드시 보고해야 한다. "
              "이를120개 모두 적격인 결과로 계산하거나 결측을0으로 채우면 안 된다. "
              "기존24구간과 섞거나 후속 학습을 이번 검토에서 수행하지 않았다.", "",
              "카메라 높이·의자 거리·설치각·조명은 두 완료 실행 모두 operator metadata가unknown(null)이다. "
              "원본 RGB/Depth 영상은 수집기가 저장하지 않았으며, 카메라 배치·수행 라벨·측정 정확도·"
              "독립 sensor frame 누락률은 이번 검토로 확정할 수 없다. "
              "추가 촬영을 자동 실행하거나 기존 누락 구간을 다른 실행으로 대체하지 않았다.", "",
              "## 보존·검증", "",
              "review_pilot_six_capture.py는 원본을 읽기만 했다. 이 보고서 외에 참가자별 구간·실행 식별자·"
              "누락 flag·타이밍·입력 hash는 local_private/results.json과 DETAILS.md에 저장했다. "
              "원본 입력 bytes 불변, 완료/중단 실행 분리, attempt/main 일치, 시간 경계, 기존 loader 집계·"
              "6특징 support 일치와 요약 산술을 확인했다. 모델/카메라/전체 회귀 테스트는 실행하지 않았다. "
              "정식자료 승격·공식8조합/B6/IRB HOLD 변경·commit/push는 하지 않았다.", "",
              "실행: `python -X utf8 -B review_pilot_six_capture.py`. 저장 검증만: 같은 명령에 `--verify`.", ""]
    return "\n".join(lines)


def verify():
    saved = read(OUT / "local_private/results.json")
    for path, sha in saved["inputs"].items():
        assert digest(ROOT / path) == sha
    assert saved["aggregation"]["input_sample_count"] == 120
    assert sum(q["eligible"] for q in saved["participants"].values()) == saved["aggregation"]["eligible_sample_count"]
    assert sum(saved["eligible_class_counts"].values()) == saved["aggregation"]["eligible_sample_count"]
    assert report(saved) in (OUT / "REPORT.md").read_text(encoding="utf-8")
    print("PASS: stored source hashes, inventory/count arithmetic and report; no model execution")


def run():
    if OUT.exists():
        raise FileExistsError("Existing review preserved; use --verify")
    directories = sorted((ROOT / "captures").glob("*_pilot6_*"))
    assert directories, "No manual six-posture pilot directories"
    files = [path for directory in directories for path in directory.rglob("*")
             if path.is_file() and path.suffix in (".json", ".csv")]
    files += [Path(__file__).resolve()]
    hashes = {str(path.relative_to(ROOT)): digest(path) for path in files}
    inventory, selected, by_run = [], {}, {}
    for directory in directories:
        entry, rows = audit_run(directory)
        inventory.append(entry)
        if entry["status"] == "COMPLETED":
            assert entry["subject"] not in selected, "Multiple complete runs: operator selection required, no automatic newest run"
            selected[entry["subject"]] = directory / "features.csv"
            by_run[entry["recording_id"]] = rows
    assert set(selected) == {"P01", "P02"}
    samples = load_labeled_probe_h_samples([selected[p] for p in ("P01", "P02")])
    assert len(samples) == 120 and len({s.sample_key for s in samples}) == 120
    participants, sample_quality = {}, []
    for person in ("P01", "P02"):
        own = [s for s in samples if s.subject == person]
        assert len(own) == 60 and Counter(s.label for s in own) == Counter({label:10 for label in LABELS})
        participants[person] = dict(frames=sum(s.n_frames for s in own), eligible=sum(s.eligible for s in own),
                                    missing_counts=dict(sum((Counter(s.missing_counts) for s in own), Counter())))
    missing_flags = Counter()
    for sample in samples:
        rows = by_run[sample.sample_key[1]]
        records = [r for r in rows if r["segment_id"] == sample.sample_key[2]]
        h9_mask = [all(present(r, n) for n in H9_FEATURE_NAMES) for r in records]
        six_mask = [all(present(r, H9_FEATURE_NAMES[j]) for j in SIX) for r in records]
        assert h9_mask == six_mask and sum(h9_mask) == sample.common_valid_count
        sample_quality.append(dict(subject=sample.subject, sample_key=sample.sample_key, label=sample.label,
            frames=sample.n_frames, common_valid=sample.common_valid_count, coverage=sample.common_coverage,
            eligible=sample.eligible, reasons=sample.eligibility_reasons, missing_counts=dict(sample.missing_counts)))
        for r, valid in zip(records, h9_mask):
            if not valid:
                for key in ("pose_detected", "nose_landmark_valid", "left_ear_landmark_valid", "right_ear_landmark_valid",
                            "left_eye_landmark_valid", "right_eye_landmark_valid", "chin_landmark_valid", "face_matrix_valid"):
                    missing_flags[(sample.subject,sample.label,key,r[key])] += 1
    saved = dict(inputs=hashes, inventory=inventory, participants=participants, samples=sample_quality,
                 aggregation=aggregation_audit(samples), eligible_class_counts=dict(Counter(s.label for s in samples if s.eligible)),
                 missing_flags=[dict(subject=k[0],label=k[1],field=k[2],value=k[3],count=v) for k,v in missing_flags.items()])
    for path, sha in hashes.items():
        assert digest(ROOT / path) == sha
    private = OUT / "local_private"
    private.mkdir(parents=True, exist_ok=False)
    with (private / "results.json").open("x", encoding="utf-8") as stream:
        json.dump(saved, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    lines = ["# LOCAL PRIVATE — 구간 품질 검토", "", "|참가자|구간|자세|전체프레임|공동유효|coverage|적격|",
             "|---|---|---|---:|---:|---:|---|"]
    for s in sample_quality:
        lines.append(f"|{s['subject']}|{s['sample_key'][2]}|{s['label']}|{s['frames']}|{s['common_valid']}|{s['coverage']:.4f}|{s['eligible']}|")
    with (private / "DETAILS.md").open("x", encoding="utf-8") as stream:
        stream.write("\n".join(lines)+"\n")
    with (OUT / "REPORT.md").open("x", encoding="utf-8") as stream:
        stream.write(report(saved))
    verify()
    print(json.dumps(dict(aggregation=saved["aggregation"], participants=participants), ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true")
    verify() if parser.parse_args().verify else run()
