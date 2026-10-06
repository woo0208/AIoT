"""
바른자세 분류기 비교 실험: M0 (일반 RF) vs M1 (원 논문 입력 가중 WRF) vs M2 (분할 점수 가중 RF)

세 가지 데이터로 비교합니다 (v4 설계).
  [A] 원 논문 Dataset.xlsx (20명 × 5자세)  : 참가자 단위 LOSO (주 실험, v4 E1)
  [B] MultiPosture (13명, 공개 데이터)      : 별도 트랙 LOSO (독립 재현)
  [C] 우리 촬영 데이터 (analysis/*_frames.csv): 원 논문 데이터로 학습 → 우리 데이터에 적용 (외부 확인)

모델 (모두 같은 직접 구현 RF, 같은 난수·같은 트리 수·max_features)
  M0      : 일반 RF (CART, Gini, bootstrap, max_features=2)
  M1      : 원 논문 방식. 입력 특징 x_j 에 가중치 w_j 를 곱한 뒤 일반 RF
  M2(λ)   : 분할 후보 점수 = [(1-λ) + λ·w_j/mean(w)] × ΔGini  (λ=0 이면 M0와 동일)
  가중치 w : 학습 fold 안에서 M0의 MDI 중요도 순위 → 원 논문 Table 5 값(0.30,0.20,0.15,0.15,0.15,0.05) 배정

특징 6개 (원 논문과 같은 구성, 각도는 좌표에서 다시 계산 → 라벨 유출 열(T/U) 미사용)
  A      : 본인 정상 자세 대비 얼굴 면적 비율
  x_c,y_c: 얼굴 중심 좌표 (640×480 기준)
  θL, θR : 얼굴 중심 → 화면 왼쪽/오른쪽 어깨 선이 아래 수직선과 이루는 각
  θ1     : θL + θR

사용법:
  python rf_experiment.py                      # [A] 원 논문 데이터만
  python rf_experiment.py --multiposture multiposture.csv
  python rf_experiment.py --ours P01 P02       # [C] 우리 데이터 (analyze_d455.py 실행 후)
  python rf_experiment.py --multiposture multiposture.csv --ours P01 P02   # 전부
  python rf_experiment.py --ours P01 P02 --features all invariant relative --seeds 1
                                               # 특징 구성별 비교 (0.40 붕괴 원인 확인)
  옵션: --trees 500 --seeds 3 --stride 5 (MultiPosture 프레임 간격)
결과: analysis/rf_results.txt, analysis/rf_results.csv, analysis/fig5_rf_compare.png
"""
import argparse
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
import shutil
import statistics
import subprocess
import sys
import time
import uuid
import warnings

import numpy as np

warnings.filterwarnings("ignore", message=".*Glyph.*")
OUT_DIR = "analysis"
RESULTS_DIR = "results"
REPO_ROOT = Path(__file__).resolve().parent
FEAT_NAMES = ["A", "x_c", "y_c", "thetaL", "thetaR", "theta1"]
PAPER_RANK_W = [0.30, 0.20, 0.15, 0.15, 0.15, 0.05]
LAB5 = ["upright", "forward_head", "lean_back", "lean_left", "lean_right"]
LAB_KO = {"upright": "정상", "forward_head": "거북목", "lean_back": "뒤로", "lean_left": "왼쪽",
          "lean_right": "오른쪽", "body_forward": "몸 전체 앞으로", "trunk_forward": "몸통 앞으로(TLF)"}

LINEAGE_SCHEMA = "rf-sample-lineage/1.0.0"
LINEAGE_FIELDS = (
    "schema_version", "experiment_run_id", "dataset_track", "feature_mode", "sample_index",
    "source_kind", "subject", "round", "step", "label", "recording_id", "analysis_run_id",
    "frames_path", "frames_sha256", "source_dataset_id", "source_file_path", "source_file_sha256",
    "source_row_number", "calibration_reference_step", "relative_reference_step",
    "reference_recording_id", "reference_analysis_run_id",
)
RESULT_LINEAGE_FIELDS = ("experiment_run_id", "dataset_manifest_sha256",
                         "lineage_manifest_path", "lineage_manifest_sha256")


def file_identity(path):
    """Hash exact bytes, rejecting mutation/replacement during the streaming read."""
    path = Path(path).resolve(strict=True)
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
        closed = os.fstat(stream.fileno())
    # Windows path-stat and fstat expose different ctime semantics; compare content
    # mutation/replacement evidence shared by both APIs.
    signature = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
    if len({signature(s) for s in (before, opened, closed, path.stat())}) != 1:
        raise ValueError(f"file changed while hashing: {path}")
    return dict(path=str(path), size_bytes=before.st_size, sha256=digest.hexdigest())


def verify_file(path, sha256):
    if file_identity(path)["sha256"] != sha256:
        raise ValueError(f"SHA-256 mismatch: {path}")


def read_pinned_json(path):
    artifact = file_identity(path)
    with open(artifact["path"], encoding="utf-8") as stream:
        value = json.load(stream)
    verify_file(artifact["path"], artifact["sha256"])
    return value, artifact


def canonical_input(path, analysis_dir):
    """Consumable canonical input: ownership must be completed."""
    return validate_frames_output(path, analysis_dir, require_completed=True)


def validate_frames_output(path, analysis_dir, *, require_completed):
    """Pure recorded-output validation; historical audits may omit completion only."""
    from analyze_d455 import FRAME_FIELDS, FRAME_SCHEMA_VERSION
    path, root = Path(path).resolve(strict=True), Path(analysis_dir).resolve()
    if (path.parent.parent.parent != root or not path.parent.name.startswith("ar_") or
            not path.name.endswith("_frames.csv")):
        raise ValueError("--ours-frames requires immutable analysis/<recording_id>/<ar_*>/*_frames.csv")
    artifact = file_identity(path)
    owner_path = path.parent / "analysis_manifest.json"
    owner, owner_artifact = read_pinned_json(owner_path)
    if require_completed and owner.get("status") != "completed":
        raise ValueError("frames owner analysis manifest must be completed")
    identity, labels = None, {}
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != FRAME_FIELDS:
            raise ValueError("canonical frames requires exact 60-field header")
        for row in reader:
            if None in row or any(v is None for v in row.values()):
                raise ValueError("malformed canonical frame row")
            current = tuple(row[k] for k in ("recording_id", "analysis_run_id", "subject", "round"))
            if not all(current) or row["frame_schema_version"] != FRAME_SCHEMA_VERSION:
                raise ValueError("missing canonical identity or wrong frames schema version")
            if identity is not None and current != identity:
                raise ValueError("conflicting canonical frame identity metadata")
            identity = current
            step = int(row["step"])
            if not row["label"] or (step in labels and labels[step] != row["label"]):
                raise ValueError("conflicting canonical step label")
            labels[step] = row["label"]
    if identity is None:
        raise ValueError("canonical frames has no identity rows")
    rid, run, subject, rnd = identity
    if (rid != path.parent.parent.name or run != path.parent.name or
            rid != owner.get("recording_id") or run != owner.get("analysis_run_id")):
        raise ValueError("frames/owner/path identity mismatch")
    outputs = [o for o in owner.get("outputs", []) if o.get("kind") == "frames" and
               Path(o.get("path", "")).resolve() == path]
    if len(outputs) != 1 or outputs[0].get("sha256") != artifact["sha256"]:
        raise ValueError("frames not uniquely referenced by owner output SHA-256")
    verify_file(path, artifact["sha256"])
    verify_file(owner_path, owner_artifact["sha256"])
    return dict(recording_id=rid, analysis_run_id=run, subject=subject, round=rnd,
                frames_schema_version=FRAME_SCHEMA_VERSION, frames_path=str(path),
                frames_sha256=artifact["sha256"], analysis_manifest_path=str(owner_path),
                analysis_manifest_sha256=owner_artifact["sha256"])


def reject_input_ambiguity(entries):
    recordings, positions, paths = {}, {}, set()
    for entry in entries:
        rid, run = entry["recording_id"], entry["analysis_run_id"]
        position = (entry["subject"], entry["round"])
        if (rid in recordings and recordings[rid] != run or
                position in positions and positions[position] != rid):
            raise ValueError("ambiguous recording/run input; use exact --ours-frames without conflicts")
        if entry["frames_path"] in paths:
            raise ValueError("duplicate canonical frames input")
        recordings[rid], positions[position] = run, rid
        paths.add(entry["frames_path"])


def resolve_ours_inputs(subjects=None, paths=None, analysis_dir=None):
    root = Path(OUT_DIR if analysis_dir is None else analysis_dir).resolve()
    if paths is not None:
        entries = [canonical_input(path, root) for path in paths]
    else:
        entries = []
        for subject in subjects or []:
            for flat in sorted(root.glob(f"{subject}_r*_frames.csv")):
                flat_artifact = file_identity(flat)
                link, _ = read_pinned_json(str(flat) + ".provenance.json")
                if flat_artifact["sha256"] != link["frames_sha256"]:
                    raise ValueError("flat frames/sidecar SHA-256 mismatch")
                owner_path = (flat.parent / link["analysis_manifest"]).resolve(strict=True)
                owner, owner_artifact = read_pinned_json(owner_path)
                if owner_artifact["sha256"] != link["analysis_manifest_sha256"]:
                    raise ValueError("sidecar/analysis manifest SHA-256 mismatch")
                outputs = [o for o in owner.get("outputs", []) if o.get("kind") == "frames" and
                           o.get("sha256") == flat_artifact["sha256"]]
                if len(outputs) != 1:
                    raise ValueError("flat frames must resolve to one immutable owner output")
                entry = canonical_input(outputs[0]["path"], root)
                if (entry["analysis_manifest_path"] != str(owner_path) or
                        entry["analysis_manifest_sha256"] != owner_artifact["sha256"] or
                        any(entry[k] != link[k] for k in ("recording_id", "analysis_run_id")) or
                        entry["subject"] != subject):
                    raise ValueError("flat sidecar/owner/canonical identity mismatch")
                entries.append(entry)
        # All completed frames-producing runs count, even if flat publication points to only one.
        for entry in entries:
            candidates = set()
            for path in root.glob("*/ar_*/analysis_manifest.json"):
                manifest, _ = read_pinned_json(path)
                if (manifest.get("recording_id") == entry["recording_id"] and
                        manifest.get("status") == "completed" and
                        any(o.get("kind") == "frames" for o in manifest.get("outputs", []))):
                    candidates.add(manifest.get("analysis_run_id"))
            if len(candidates) > 1:
                raise ValueError("multiple completed frames runs; use exact --ours-frames")
    reject_input_ambiguity(entries)
    return entries


def external_source(artifact, row_number, subject, label):
    return dict(source_kind="external_table", source_dataset_id=artifact["source_dataset_id"],
                source_file_path=artifact["path"], source_file_sha256=artifact["sha256"],
                source_row_number=row_number, subject=subject, label=label)


def lineage_rows(sources, experiment_id, track, mode, reference_steps=None):
    rows = []
    for index, source in enumerate(sources):
        row = dict.fromkeys(LINEAGE_FIELDS)
        row.update(source)
        row.update(schema_version=LINEAGE_SCHEMA, experiment_run_id=experiment_id,
                   dataset_track=track, feature_mode=mode, sample_index=index)
        if row["source_kind"] == "canonical_frames":
            key = (row["recording_id"], row["analysis_run_id"])
            for field, expected in zip(("reference_recording_id", "reference_analysis_run_id"), key):
                if row[field] is not None and row[field] != expected:
                    raise ValueError("cross-recording/run RF reference")
            if mode == "relative":
                row["relative_reference_step"] = (reference_steps or {}).get(key)
            if row["calibration_reference_step"] is not None or row["relative_reference_step"] is not None:
                row["reference_recording_id"], row["reference_analysis_run_id"] = key
        rows.append(row)
    return rows


def validate_sample_lineage_row(row, keys):
    """Pure row validation; keys holds the already validated sample identities."""
    if set(row) != set(LINEAGE_FIELDS):
        raise ValueError("invalid sample lineage fields")
    if (row["schema_version"] != LINEAGE_SCHEMA or
            row["dataset_track"] not in ("paper_loso", "ours_external", "multiposture_loso") or
            row["feature_mode"] not in FEATURE_SETS or
            (row["dataset_track"] == "multiposture_loso" and row["feature_mode"] != "all")):
        raise ValueError("invalid sample lineage schema/track/mode")
    canonical = ("recording_id", "analysis_run_id", "frames_path", "frames_sha256")
    external = ("source_dataset_id", "source_file_path", "source_file_sha256", "source_row_number")
    if row["source_kind"] == "canonical_frames":
        required, absent = canonical + ("subject", "round", "step", "label"), external
        for ref, src in (("reference_recording_id", "recording_id"),
                         ("reference_analysis_run_id", "analysis_run_id")):
            if row[ref] is not None and row[ref] != row[src]:
                raise ValueError("cross-recording/run RF reference")
    elif row["source_kind"] == "external_table":
        required, absent = external, canonical + ("reference_recording_id", "reference_analysis_run_id")
        if row["source_dataset_id"] not in ("paper_dataset", "multiposture_dataset"):
            raise ValueError("invalid external dataset ID")
        if not isinstance(row["source_row_number"], int) or row["source_row_number"] < 2:
            raise ValueError("invalid physical source row number")
    else:
        raise ValueError("invalid lineage source kind")
    if any(row[k] is None for k in required) or any(row[k] is not None for k in absent):
        raise ValueError("invalid sample source lineage")
    key = tuple(row[k] for k in ("experiment_run_id", "dataset_track", "feature_mode", "sample_index"))
    if key in keys:
        raise ValueError("duplicate sample lineage key")
    keys.add(key)


def write_sample_lineage(directory, rows):
    keys = set()
    path = Path(directory) / "sample_lineage.jsonl"
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            validate_sample_lineage_row(row, keys)
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    return dict(schema_version=LINEAGE_SCHEMA, path=path.name,
                sha256=file_identity(path)["sha256"], row_count=len(rows))


def write_experiment_manifest(directory, manifest):
    path = Path(directory) / "experiment_manifest.json"
    if path.exists():
        with path.open(encoding="utf-8") as stream:
            if json.load(stream)["status"] != "running":
                raise ValueError("cannot overwrite a terminal experiment manifest")
    temporary = Path(directory) / ".experiment_manifest.tmp"
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(manifest, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def new_experiment_id():
    return f"er_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}_{uuid.uuid4().hex}"


def start_experiment(options):
    run_id = new_experiment_id()
    directory = Path(RESULTS_DIR).resolve() / run_id
    directory.mkdir(parents=True, exist_ok=False)
    manifest = dict(schema_version="rf-experiment-provenance/1.0.0", experiment_run_id=run_id,
                    started_at=datetime.now(timezone.utc).isoformat(), ended_at=None, status="running",
                    dataset_manifest=dict(dataset_manifest_id=None, path=None, sha256=None),
                    inputs=dict(paper=None, multiposture=None, ours=[]),
                    code=dict(git_commit=None, git_dirty=None, rf_script_sha256=None,
                              path=str(Path(__file__).resolve())),
                    environment=dict.fromkeys(("python", "os", "architecture", "numpy", "matplotlib", "openpyxl")),
                    options=dict(argv=sys.argv[1:], **vars(options)),
                    sample_lineage=dict(schema_version=LINEAGE_SCHEMA, path="sample_lineage.jsonl",
                                        sha256=None, row_count=0),
                    outputs=[], errors=[], provenance_unknown_reasons={})
    write_experiment_manifest(directory, manifest)
    return directory, manifest


def record_runtime(manifest):
    script = Path(__file__).resolve()
    manifest["code"] = dict(git_commit=None, git_dirty=None,
                            rf_script_sha256=file_identity(script)["sha256"], path=str(script))
    reasons = manifest["provenance_unknown_reasons"]
    for key, args in (("git_commit", ["rev-parse", "HEAD"]),
                      ("git_dirty", ["status", "--porcelain", "--untracked-files=normal"])):
        try:
            value = subprocess.run(["git", *args], cwd=script.parent, capture_output=True,
                                   text=True, encoding="utf-8", check=True, timeout=3).stdout.strip()
            manifest["code"][key] = bool(value) if key == "git_dirty" else value
        except (OSError, subprocess.SubprocessError) as error:
            reasons["code." + key] = str(error)
    manifest["environment"] = dict(python=platform.python_version(), os=platform.platform(),
                                   architecture=platform.machine())
    for name in ("numpy", "matplotlib", "openpyxl"):
        try:
            manifest["environment"][name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError as error:
            manifest["environment"][name] = None
            reasons["environment." + name] = str(error)


def verify_inputs(inputs):
    for key in ("paper", "multiposture"):
        if inputs[key] is not None:
            verify_file(inputs[key]["path"], inputs[key]["sha256"])
    for entry in inputs["ours"]:
        verify_file(entry["frames_path"], entry["frames_sha256"])
        verify_file(entry["analysis_manifest_path"], entry["analysis_manifest_sha256"])


def verify_dataset_selection(manifest):
    reference = manifest["dataset_manifest"]
    if reference["path"] is not None:
        from selection_manifest import resolve_dataset_manifest
        inputs, current = resolve_dataset_manifest(reference["path"], REPO_ROOT, reference["sha256"])
        if current != reference or inputs != manifest["inputs"]["ours"]:
            raise ValueError("dataset manifest resolved inputs changed during experiment")


# ================================================================ 랜덤 포레스트 (직접 구현)
class Tree:
    def __init__(self, n_classes, max_features, split_w, rng):
        self.K, self.mf, self.sw, self.rng = n_classes, max_features, split_w, rng
        self.feat, self.thr, self.left, self.right, self.value = [], [], [], [], []
        self.mdi = None

    def fit(self, X, Y1h):
        self.mdi = np.zeros(X.shape[1])
        self.n_root = len(X)
        self._grow(X, Y1h, np.arange(len(X)))
        self.feat, self.thr = np.array(self.feat), np.array(self.thr)
        self.left, self.right = np.array(self.left), np.array(self.right)
        self.value = np.array(self.value)
        return self

    def _new(self):
        for a in (self.feat, self.thr, self.left, self.right):
            a.append(-1)
        self.value.append(None)
        return len(self.feat) - 1

    def _grow(self, X, Y1h, idx):
        node = self._new()
        counts = Y1h[idx].sum(0)
        n = len(idx)
        self.value[node] = counts / n
        if n < 2 or (counts > 0).sum() <= 1:
            return node
        g_parent = 1.0 - ((counts / n) ** 2).sum()
        order_f = self.rng.permutation(X.shape[1])
        best = None  # (score, dgini, f, thr, left_mask)
        for k, f in enumerate(order_f):
            if k >= self.mf and best is not None:
                break  # sklearn처럼: max_features개 본 뒤 유효 분할이 있으면 중단
            xs = X[idx, f]
            o = np.argsort(xs, kind="mergesort")
            xs_s = xs[o]
            valid = xs_s[1:] > xs_s[:-1]
            if not valid.any():
                continue
            cum = np.cumsum(Y1h[idx][o], axis=0)[:-1]
            nl = np.arange(1, n, dtype=float)
            nr = n - nl
            right = counts - cum
            gl = 1.0 - (cum ** 2).sum(1) / nl ** 2
            gr = 1.0 - (right ** 2).sum(1) / nr ** 2
            dg = g_parent - nl / n * gl - nr / n * gr
            dg = np.where(valid, dg, -np.inf)
            i = int(np.argmax(dg))
            score = dg[i] * self.sw[f]
            if best is None or score > best[0]:
                thr = (xs_s[i] + xs_s[i + 1]) / 2.0
                best = (score, dg[i], f, thr)
        if best is None:
            return node
        _, dgb, f, thr = best
        self.mdi[f] += n / self.n_root * dgb
        mask = X[idx, f] <= thr
        self.feat[node], self.thr[node] = f, thr
        self.left[node] = self._grow(X, Y1h, idx[mask])
        self.right[node] = self._grow(X, Y1h, idx[~mask])
        return node

    def predict_proba(self, X):
        out = np.empty((len(X), self.K))
        for r in range(len(X)):
            nd = 0
            while self.feat[nd] >= 0:
                nd = self.left[nd] if X[r, self.feat[nd]] <= self.thr[nd] else self.right[nd]
            out[r] = self.value[nd]
        return out


class Forest:
    def __init__(self, n_classes, n_trees=500, max_features=2, split_w=None, seed=0):
        self.K, self.T, self.mf, self.sw, self.seed = n_classes, n_trees, max_features, split_w, seed

    def fit(self, X, y):
        boot_seed, tree_seed = np.random.SeedSequence(self.seed).spawn(2)
        boot_rng = np.random.default_rng(boot_seed)
        tree_seeds = tree_seed.spawn(self.T)
        sw = self.sw if self.sw is not None else np.ones(X.shape[1])
        Y1h = np.eye(self.K)[y]
        self.trees, mdi = [], np.zeros(X.shape[1])
        # Bootstrap과 각 트리의 난수를 분리해 분할 구조가 다음 트리에 영향을 주지 않도록 한다.
        for seed in tree_seeds:
            b = boot_rng.integers(0, len(X), len(X))
            rng = np.random.default_rng(seed)
            t = Tree(self.K, self.mf, sw, rng).fit(X[b], Y1h[b])
            self.trees.append(t)
            mdi += t.mdi / max(t.mdi.sum(), 1e-12)
        self.mdi = mdi / self.T
        return self

    def predict(self, X):
        p = sum(t.predict_proba(X) for t in self.trees)
        return np.argmax(p, axis=1)


def rank_weights(mdi):
    """MDI 순위대로 Table 5 가중치 배정; 6개 미만이면 상위 p개를 재정규화."""
    p = len(mdi)
    if p > len(PAPER_RANK_W):
        raise ValueError(
            "rank-based paper weights are defined for at most 6 features; "
            "define a weighting policy explicitly before using more features"
        )
    rank_w = np.array(PAPER_RANK_W[:p])
    if p < len(PAPER_RANK_W):
        rank_w = rank_w / rank_w.sum()
    w = np.zeros(p)
    for rank, j in enumerate(np.argsort(-mdi)):
        w[j] = rank_w[rank]
    return w


def fit_models(Xtr, ytr, K, trees, seed, lams):
    """한 학습 세트에서 M0, M1, M2(λ...) 학습. 반환: {이름: (예측 함수)}"""
    m0 = Forest(K, trees, 2, None, seed).fit(Xtr, ytr)
    w = rank_weights(m0.mdi)
    m1 = Forest(K, trees, 2, None, seed).fit(Xtr * w, ytr)
    models = {"M0": lambda X: m0.predict(X), "M1": lambda X: m1.predict(X * w)}
    # 예측 함수의 기존 인터페이스를 유지하면서 관찰용 모델 참조만 제공한다.
    models["M0"].forest, models["M0"].lam = m0, None
    models["M1"].forest, models["M1"].lam = m1, None
    for lam in lams:
        sw = (1 - lam) + lam * w / w.mean()
        m2 = Forest(K, trees, 2, sw, seed).fit(Xtr, ytr)
        models[f"M2(λ={lam:g})"] = (lambda m: (lambda X: m.predict(X)))(m2)
        models[f"M2(λ={lam:g})"].forest = m2
        models[f"M2(λ={lam:g})"].lam = float(lam)
    return models, w


def root_statistics(forest, feature_set):
    """학습된 트리만 읽는다. percentage의 분모는 root split이 존재하는 트리 수."""
    names = {
        "all": FEAT_NAMES,
        "invariant": [FEAT_NAMES[i] for i in (0, 3, 4, 5)],
        "relative": ["A", "delta_x_c", "delta_y_c", "delta_thetaL", "delta_thetaR", "delta_theta1"],
    }[feature_set]
    if len(names) != len(forest.mdi):
        raise ValueError("root feature names must match the fitted feature count")
    roots = [int(t.feat[0]) if len(t.feat) and t.feat[0] >= 0 else None for t in forest.trees]
    counts = {name: roots.count(i) for i, name in enumerate(names)}
    split_trees = sum(counts.values())
    return dict(total_trees=len(roots), split_trees=split_trees,
                leaf_only_trees=len(roots) - split_trees, feature_names=list(names),
                root_feature_indices=roots, counts=counts,
                percentages={name: 100 * count / split_trees if split_trees else None
                             for name, count in counts.items()})


def log_root_statistics(models, records, dataset, feature_set, held_out_subject, log):
    """각 학습 실행을 독립 기록한다. 기존 사용자 정의 예측 함수에는 forest가 없을 수 있다."""
    stats = {m: root_statistics(fn.forest, feature_set)
             for m, fn in models.items() if hasattr(fn, "forest")}
    for m, stat in stats.items():
        fn = models[m]
        record = dict(dataset=dataset, feature_set=feature_set, model=m,
                      seed=int(fn.forest.seed), tree_count=fn.forest.T, max_features=fn.forest.mf,
                      **{"lambda": fn.lam}, held_out_subject=held_out_subject, root_statistics=stat)
        if m == "M1" and "M0" in stats:
            record["root_features_equal_m0"] = stat["root_feature_indices"] == stats["M0"]["root_feature_indices"]
        records.setdefault(m, []).append(record)
        log(f"   [ROOT] {dataset}, features={feature_set}, held_out={held_out_subject}, "
            f"model={m}, seed={record['seed']} (0-based), trees={record['tree_count']}, "
            f"max_features={record['max_features']}, lambda={record['lambda']}")
        log(f"     root split trees={stat['split_trees']}/{stat['total_trees']}; "
            f"leaf-only={stat['leaf_only_trees']}; percentage denominator=root split trees")
        for name, count in stat["counts"].items():
            percentage = stat["percentages"][name]
            value = f"{percentage:.2f}%" if percentage is not None else "N/A"
            log(f"     {name}: {count}/{stat['split_trees']} = {value}")
        if "root_features_equal_m0" in record:
            log(f"     M1 root features identical to M0: {record['root_features_equal_m0']}")


# ================================================================ 평가 지표
def macro_f1(y, p, K):
    f = []
    for k in range(K):
        tp = np.sum((p == k) & (y == k))
        fp = np.sum((p == k) & (y != k))
        fn = np.sum((p != k) & (y == k))
        if tp + fn == 0:
            continue
        pr = tp / (tp + fp) if tp + fp else 0.0
        rc = tp / (tp + fn)
        f.append(2 * pr * rc / (pr + rc) if pr + rc else 0.0)
    return float(np.mean(f)) if f else 0.0


def boot_ci(vals, n=5000, seed=0):
    rng = np.random.default_rng(seed)
    v = np.array(vals)
    m = [rng.choice(v, len(v), replace=True).mean() for _ in range(n)]
    return float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))


# ================================================================ 특징 계산
def feats_from_points(fx, fy, lx, ly, rx, ry):
    """fx,fy=얼굴 중심, (lx,ly)=화면 왼쪽 어깨, (rx,ry)=화면 오른쪽 어깨."""
    tl = math.degrees(math.atan2(abs(fx - lx), (ly - fy)))
    tr = math.degrees(math.atan2(abs(rx - fx), (ry - fy)))
    return tl, tr, tl + tr


def num(v):
    try:
        return float(str(v).strip().strip("(), "))
    except (TypeError, ValueError):
        return None


def load_paper(path, lineage=None, artifact=None):
    import openpyxl
    artifact = artifact or dict(source_dataset_id="paper_dataset", **file_identity(path))
    verify_file(path, artifact["sha256"])
    workbook = openpyxl.load_workbook(path, data_only=True)
    ws = workbook.active
    X, y, g = [], [], []
    for row_number, r in enumerate(ws.iter_rows(min_row=2, values_only=True), 2):
        if not r[0]:
            continue
        fx, fy = num(r[5]), num(r[6])
        lx, ly, rx, ry = num(r[15]), num(r[16]), num(r[10]), num(r[11])  # P,Q=화면 왼쪽 / K,L=화면 오른쪽
        tl, tr, t1 = feats_from_points(fx, fy, lx, ly, rx, ry)
        X.append([num(r[22]), fx, fy, tl, tr, t1])
        y.append(int(r[1]) - 1)
        g.append(str(r[0]).split("_")[1])
        if lineage is not None:
            lineage.append(external_source(artifact, row_number, g[-1], int(y[-1])))
    workbook.close()
    verify_file(path, artifact["sha256"])
    return np.array(X, float), np.array(y), np.array(g)


def load_multiposture(path, stride, lineage=None, artifact=None):
    artifact = artifact or dict(source_dataset_id="multiposture_dataset", **file_identity(path))
    verify_file(path, artifact["sha256"])
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        fields = next(reader)
        rows = []
        while True:
            physical_row = reader.line_num + 1
            values = next(reader, None)
            if values is None:
                break
            if not values:
                continue  # DictReader also skips blank physical lines.
            row = dict(zip(fields, values))
            row.update({key: None for key in fields[len(values):]})
            row["_source_row_number"] = physical_row
            rows.append(row)
    lab = {"TUP": 0, "TLB": 2, "TLL": 3, "TLR": 4, "TLF": 1}  # TLF(몸통 앞으로)는 5번째 클래스 자리로
    per_sub = {}
    for i, r in enumerate(rows):
        per_sub.setdefault(r["subject"], []).append(r)
    X, y, g = [], [], []
    for sub, rs in per_sub.items():
        def pt(r, n):
            return float(r[n + "_x"]), float(r[n + "_y"])
        # 얼굴 크기 대용: 양 귀 사이 거리 (면적 ∝ 거리²), 본인 TUP 중앙값 대비
        def ear(r):
            (ax, ay), (bx, by) = pt(r, "left_ear"), pt(r, "right_ear")
            return math.hypot(ax - bx, ay - by)
        base = [ear(r) for r in rs if r["upperbody_label"] == "TUP"]
        if not base:
            continue
        e0 = statistics.median(base)
        for i, r in enumerate(rs):
            if i % stride or r["upperbody_label"] not in lab:
                continue
            pts = [pt(r, n) for n in ("nose", "left_eye", "right_eye", "mouth_left", "mouth_right")]
            fx = sum(p[0] for p in pts) / len(pts)
            fy = sum(p[1] for p in pts) / len(pts)
            (lx, ly), (rx, ry) = pt(r, "right_shoulder"), pt(r, "left_shoulder")  # 사람 오른쪽 = 화면 왼쪽
            tl, tr, t1 = feats_from_points(fx, fy, lx, ly, rx, ry)
            X.append([(ear(r) / e0) ** 2, fx, fy, tl, tr, t1])
            y.append(lab[r["upperbody_label"]])
            g.append(sub)
            if lineage is not None:
                lineage.append(external_source(artifact, r["_source_row_number"], sub, int(y[-1])))
    verify_file(path, artifact["sha256"])
    return np.array(X, float), np.array(y), np.array(g)


def load_ours(subjects=None, log=print, inputs=None, lineage=None):
    """analysis/*_frames.csv → 회차·단계별 중앙값 1개 샘플 (원 논문처럼 사람·자세당 대표값)."""
    X, y, meta = [], [], []
    lab_idx = {l: i for i, l in enumerate(LAB5)}
    keys = ("face_x", "face_y", "rsh_x", "rsh_y", "lsh_x", "lsh_y", "oval_area_px")
    dropped, drop_counts = 0, {}

    def record_drop(sub, s, rs, reasons, missing):
        nonlocal dropped
        dropped += 1
        for reason in reasons:
            drop_counts[reason] = drop_counts.get(reason, 0) + 1
        log(f"[DROP] {sub} r{rs[0].get('round', '?')} step{s} {rs[0]['label']}: "
            f"{'; '.join(reasons)}; missing features: {', '.join(missing) or 'none'}")

    inputs = resolve_ours_inputs(subjects) if inputs is None else inputs
    reject_input_ambiguity(inputs)
    for entry in inputs:
        sub = entry["subject"]
        for path in [entry["frames_path"]]:
            verify_file(path, entry["frames_sha256"])
            verify_file(entry["analysis_manifest_path"], entry["analysis_manifest_sha256"])
            with open(path, encoding="utf-8-sig") as f:
                fr = list(csv.DictReader(f))
            verify_file(path, entry["frames_sha256"])
            steps = {}
            for r in fr:
                steps.setdefault(int(r["step"]), []).append(r)
            def med(rs, k):
                v = [num(r.get(k)) for r in rs if num(r.get(k)) is not None]
                return statistics.median(v) if v else None
            ups = [s for s in sorted(steps) if steps[s][0]["label"] == "upright"]
            if not ups:
                for s, rs in sorted(steps.items()):
                    record_drop(sub, s, rs, ["missing upright calibration"],
                                [k for k in keys if med(rs, k) is None])
                continue
            a0 = med(steps[ups[0]], "oval_area_px")
            for s, rs in sorted(steps.items()):
                lab = rs[0]["label"]
                vals = [med(rs, k) for k in keys]
                if None in vals or not a0:
                    missing = [k for k, v in zip(keys, vals) if v is None]
                    reasons = ["missing feature median"] if missing else []
                    if not a0:
                        reasons.append("missing calibration oval_area_px" if a0 is None
                                       else "zero calibration oval_area_px")
                    record_drop(sub, s, rs, reasons, missing)
                    continue
                fx, fy, lx, ly, rx, ry, oa = vals
                # 원 논문 해상도(640x480, 4:3)로 환산: 1280x720(16:9) 가운데를 960x720(4:3)으로 자른 뒤
                # 가로·세로 같은 비율(2/3)로 축소 -> 사람 모양(각도)이 왜곡되지 않음
                scale, x_off = 480 / 720, (1280 - 720 * 4 / 3) / 2
                cx = lambda x: (x - x_off) * scale
                cy = lambda y: y * scale
                tl, tr, t1 = feats_from_points(cx(fx), cy(fy), cx(lx), cy(ly), cx(rx), cy(ry))
                X.append([oa / a0, cx(fx), cy(fy), tl, tr, t1])
                y.append(lab_idx.get(lab, -1))
                meta.append((sub, rs[0]["round"], s, lab))
                if lineage is not None:
                    lineage.append(dict(source_kind="canonical_frames", subject=sub, round=rs[0]["round"],
                                        step=s, label=lab, calibration_reference_step=ups[0],
                                        **{k: entry[k] for k in ("recording_id", "analysis_run_id",
                                                                 "frames_path", "frames_sha256")}))
    log(f"[OURS] loaded samples: {len(X)}; dropped samples: {dropped}")
    for reason, count in sorted(drop_counts.items()):
        log(f"   drop reason: {reason}: {count}")
    return np.array(X, float), np.array(y), meta


# ================================================================ 특징 구성
FEATURE_SETS = {
    "all": "A, x_c, y_c, θL, θR, θ1 (원 논문 구성)",
    "invariant": "A, θL, θR, θ1 (화면상 절대 위치 x_c·y_c 제외)",
    "relative": "A, Δx_c, Δy_c, ΔθL, ΔθR, Δθ1 (본인 정상 자세 대비 변화량)",
}


def transform(X, groups, is_ref, mode):
    """groups: 사람(또는 사람·회차) 구분, is_ref: 그 그룹의 기준 정상 자세 샘플 여부."""
    if mode == "all":
        return X.copy()
    if mode == "invariant":
        return X[:, [0, 3, 4, 5]].copy()
    Xr = X.copy()
    for gk in set(groups):
        m = groups == gk
        ref = X[m & is_ref]
        if len(ref) == 0:
            continue
        Xr[m, 1:] = X[m, 1:] - ref.mean(axis=0)[1:]
    return Xr


# ================================================================ 실험
def loso(X, y, g, K, trees, seeds, lams, name, log, ref_mask=None, feature_set="all"):
    subs = sorted(set(g), key=lambda s: (len(s), s))
    names = None
    acc = {}        # model -> list over seeds of overall acc
    f1 = {}
    per_sub = {}    # model -> subject -> list of acc over seeds
    agree01 = []
    nonref = ~ref_mask if ref_mask is not None else None
    nonref_acc, nonref_f1 = {}, {}
    root_records = {}
    t0 = time.time()
    for seed in range(seeds):
        preds = {}
        for si, s in enumerate(subs):
            te, tr = g == s, g != s
            models, _ = fit_models(X[tr], y[tr], K, trees, seed, lams)
            log_root_statistics(models, root_records, name, feature_set, str(s), log)
            names = list(models)
            for m, fn in models.items():
                preds.setdefault(m, np.empty(len(y), int))[te] = fn(X[te])
            print(f"   [{name}] seed {seed + 1}/{seeds}, fold {si + 1}/{len(subs)} ({time.time() - t0:.0f}s)", end="\r")
        for m in names:
            acc.setdefault(m, []).append(float(np.mean(preds[m] == y)))
            f1.setdefault(m, []).append(macro_f1(y, preds[m], K))
            if nonref is not None:
                nonref_acc.setdefault(m, []).append(
                    float(np.mean(preds[m][nonref] == y[nonref])) if nonref.any() else float("nan"))
                nonref_f1.setdefault(m, []).append(
                    macro_f1(y[nonref], preds[m][nonref], K) if nonref.any() else float("nan"))
            for s in subs:
                per_sub.setdefault(m, {}).setdefault(s, []).append(float(np.mean(preds[m][g == s] == y[g == s])))
        agree01.append(float(np.mean(preds["M0"] == preds["M1"])))
    print()
    log(f"\n■ {name}: LOSO {len(subs)}명, 샘플 {len(y)}개, 트리 {trees}, 시드 {seeds}")
    log("   모델            Accuracy(평균±시드SD)   Macro F1(평균±시드SD)   최저 참가자 정확도")
    rows = []
    for m in names:
        ps = {s: np.mean(v) for s, v in per_sub[m].items()}
        log(f"   {m:<14} {np.mean(acc[m]):.3f} ± {np.std(acc[m]):.3f}          "
            f"{np.mean(f1[m]):.3f} ± {np.std(f1[m]):.3f}          {min(ps.values()):.2f}")
        rows.append({"dataset": name, "model": m, "acc": np.mean(acc[m]), "acc_sd": np.std(acc[m]),
                     "f1": np.mean(f1[m]), "f1_sd": np.std(f1[m]), "min_subject_acc": min(ps.values())})
    log(f"   M0와 M1 예측 일치율: {np.mean(agree01) * 100:.1f}% (입력 양수배는 결정트리 분할을 바꾸지 않는다는 v4 H1 확인)")
    base = {s: np.mean(v) for s, v in per_sub["M1"].items()}
    for m in names:
        if not m.startswith("M2"):
            continue
        d = [np.mean(per_sub[m][s]) - base[s] for s in subs]
        lo, hi = boot_ci(d)
        pos = sum(1 for x in d if x > 0)
        neg = sum(1 for x in d if x < 0)
        verdict = "안정적 개선" if lo > 0 and pos > len(subs) / 2 else ("차이 없음/불확실" if lo <= 0 <= hi else "악화")
        log(f"   {m} − M1: 참가자 평균 {np.mean(d):+.3f} (95% CI {lo:+.3f}~{hi:+.3f}), "
            f"개선 {pos}명 / 악화 {neg}명 → {verdict}")
    if nonref is not None:
        log("\n   추가: relative non-reference evaluation (calibration upright excluded)")
        log("   [A] 참가자당 나머지 4개 posture 평가; 정상 class 평가 샘플 0개.")
        log("   Macro F1은 기존 함수로 평가에 존재하는 class만 평균 (5-class Macro F1 아님).")
        log(f"   평가 샘플 {int(nonref.sum())}개; 모델별 Accuracy / Macro F1 (평균±시드SD)")
        for row in rows:
            m = row["model"]
            row.update(relative_nonref_n=int(nonref.sum()),
                       relative_nonref_note="calibration upright excluded; 4 postures; no upright class",
                       relative_nonref_acc=np.mean(nonref_acc[m]),
                       relative_nonref_acc_sd=np.std(nonref_acc[m]),
                       relative_nonref_f1=np.mean(nonref_f1[m]),
                       relative_nonref_f1_sd=np.std(nonref_f1[m]))
            log(f"   {m:<14} {row['relative_nonref_acc']:.3f} ± {row['relative_nonref_acc_sd']:.3f} / "
                f"{row['relative_nonref_f1']:.3f} ± {row['relative_nonref_f1_sd']:.3f}")
    for row in rows:
        if row["model"] in root_records:
            row["root_provenance"] = json.dumps(root_records[row["model"]], ensure_ascii=False)
    return rows


def external(Xtr, ytr, Xte, yte, meta, K, trees, seeds, lams, log, ref_mask=None, feature_set="all"):
    log(f"\n■ [C] 원 논문 데이터로 학습 → 우리 데이터 적용 (샘플 {len(yte)}개, 트리 {trees}, 시드 {seeds})")
    known = yte >= 0
    names, votes, accs = None, {}, {}
    root_records = {}
    for seed in range(seeds):
        models, _ = fit_models(Xtr, ytr, K, trees, seed, lams)
        log_root_statistics(models, root_records, "C_ours_external", feature_set, None, log)
        names = list(models)
        for m, fn in models.items():
            p = fn(Xte)
            votes.setdefault(m, []).append(p)
            accs.setdefault(m, []).append(float(np.mean(p[known] == yte[known])) if known.any() else float("nan"))
    log("   모델            5종 자세 정확도(평균±시드SD)")
    rows = []
    for m in names:
        log(f"   {m:<14} {np.mean(accs[m]):.3f} ± {np.std(accs[m]):.3f}")
        rows.append({"dataset": "C_ours_external", "model": m, "acc": np.mean(accs[m]), "acc_sd": np.std(accs[m])})
    log("\n   자세별 예측 (시드 1, M0 / M1 / M2 마지막 λ)")
    last = names[-1]
    for i, (sub, rnd, step, lab) in enumerate(meta):
        pr = [LAB_KO[LAB5[votes[m][0][i]]] for m in ("M0", "M1", last)]
        mark = "" if yte[i] < 0 or votes["M0"][0][i] == yte[i] else "  ← 오답"
        log(f"   {sub} r{rnd} 단계{step:<2} 실제 {LAB_KO.get(lab, lab):<10} → {pr[0]} / {pr[1]} / {pr[2]}{mark}")
    bf = [i for i, m in enumerate(meta) if m[3] == "body_forward"]
    if bf:
        cnt = {}
        for i in bf:
            k = LAB_KO[LAB5[votes["M0"][0][i]]]
            cnt[k] = cnt.get(k, 0) + 1
        log(f"\n   * '몸 전체 앞으로'(원 논문에 없는 자세) {len(bf)}개를 M0가 판정한 결과: {cnt}")
        log("     → 거북목으로 판정되는 비율이 높다면, 얼굴 면적 기반 특징만으로는 두 자세가 섞인다는 근거 (교수님 지적 3번)")
    subjects = np.array([item[0] for item in meta])
    log("\n   추가 5종 지표: Macro F1 및 참가자별 지표는 시드 평균±SD; body_forward 제외")
    log(f"   confusion matrix: 시드별 정수 count, 행=실제 / 열=예측; 순서={LAB5}")
    for row in rows:
        m = row["model"]
        f1s = [macro_f1(yte[known], p[known], K) if known.any() else float("nan") for p in votes[m]]
        row.update(external_n=int(known.sum()), external_f1=np.mean(f1s), external_f1_sd=np.std(f1s),
                   external_class_order=json.dumps(LAB5))
        log(f"   {m}: Macro F1 {row['external_f1']:.3f} ± {row['external_f1_sd']:.3f}")
        matrices = []
        for seed, p in enumerate(votes[m]):
            cm = np.zeros((len(LAB5), len(LAB5)), dtype=int)
            np.add.at(cm, (yte[known], p[known]), 1)
            matrices.append(cm.tolist())
            log(f"   {m} confusion matrix (seed {seed + 1}, n={int(known.sum())}):")
            for label, counts in zip(LAB5, cm):
                log(f"     {label}: {counts.tolist()}")
        row["external_confusion_matrices"] = json.dumps(matrices)
        recalls = {}
        for k, label in enumerate(LAB5):
            mask = known & (yte == k)
            recalls[label] = float(np.mean([np.mean(p[mask] == k) for p in votes[m]])) if mask.any() else None
            value = f"{recalls[label]:.3f}" if mask.any() else "N/A"
            log(f"   {m} recall {label}: {value} (n={int(mask.sum())}, 시드 평균)")
        row["external_recalls"] = json.dumps(recalls)
        participants = {}
        for sub in sorted(set(subjects)):
            mask = known & (subjects == sub)
            if mask.any():
                acc = [float(np.mean(p[mask] == yte[mask])) for p in votes[m]]
                f1 = [macro_f1(yte[mask], p[mask], K) for p in votes[m]]
                result = dict(n=int(mask.sum()), acc=float(np.mean(acc)), acc_sd=float(np.std(acc)),
                              f1=float(np.mean(f1)), f1_sd=float(np.std(f1)))
                log(f"   {m} participant {sub}: n={result['n']}, Accuracy {result['acc']:.3f} ± "
                    f"{result['acc_sd']:.3f}, Macro F1 {result['f1']:.3f} ± {result['f1_sd']:.3f}")
            else:
                result = dict(n=0, acc=None, acc_sd=None, f1=None, f1_sd=None)
                log(f"   {m} participant {sub}: n=0, Accuracy N/A, Macro F1 N/A")
            participants[str(sub)] = result
        row["external_participants"] = json.dumps(participants, ensure_ascii=False)
    if ref_mask is not None:
        nonref = known & ~ref_mask
        log("\n   추가: relative non-reference evaluation (calibration upright excluded)")
        log("   [C] 각 회차 첫 정상 reference만 제외; 이후 upright 유지; body_forward는 기존대로 제외.")
        log(f"   평가 샘플 {int(nonref.sum())}개; 모델별 Accuracy (평균±시드SD)")
        for row in rows:
            m = row["model"]
            values = [float(np.mean(p[nonref] == yte[nonref])) if nonref.any() else float("nan")
                      for p in votes[m]]
            row.update(relative_nonref_n=int(nonref.sum()),
                       relative_nonref_note="calibration upright excluded; other upright retained; known labels only",
                       relative_nonref_acc=np.mean(values), relative_nonref_acc_sd=np.std(values))
            log(f"   {m:<14} {row['relative_nonref_acc']:.3f} ± {row['relative_nonref_acc_sd']:.3f}")
            f1s = [macro_f1(yte[nonref], p[nonref], K) if nonref.any() else float("nan") for p in votes[m]]
            row.update(relative_nonref_f1=np.mean(f1s), relative_nonref_f1_sd=np.std(f1s))
            log(f"   {m} non-reference Macro F1: {row['relative_nonref_f1']:.3f} ± "
                f"{row['relative_nonref_f1_sd']:.3f}")
    for row in rows:
        if row["model"] in root_records:
            row["root_provenance"] = json.dumps(root_records[row["model"]], ensure_ascii=False)
    return rows


def plot(rows):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    for nm in ("Malgun Gothic", "NanumGothic", "Noto Sans CJK KR", "Noto Sans CJK JP"):
        if any(nm == f.name for f in font_manager.fontManager.ttflist):
            matplotlib.rcParams["font.family"] = nm
            break
    ds = [d for d in dict.fromkeys(r["dataset"] for r in rows)]
    fig, axes = plt.subplots(1, len(ds), figsize=(5 * len(ds), 4), squeeze=False)
    for ax, d in zip(axes[0], ds):
        rr = [r for r in rows if r["dataset"] == d]
        key = "f1" if "f1" in rr[0] else "acc"
        vals = [r[key] for r in rr]
        sds = [r.get(key + "_sd", 0) for r in rr]
        cols = ["#B4B2A9" if r["model"] == "M0" else "#D85A30" if r["model"] == "M1" else "#378ADD" for r in rr]
        ax.bar(range(len(rr)), vals, yerr=sds, color=cols, capsize=3)
        ax.set_xticks(range(len(rr)))
        ax.set_xticklabels([r["model"] for r in rr], rotation=20, fontsize=8)
        ax.set_ylim(0, 1.05)
        ax.set_title(f"{d}\n({'Macro F1' if key == 'f1' else 'Accuracy'}, 오차막대=시드 SD)", fontsize=9)
        for i, v in enumerate(vals):
            ax.text(i, v + 0.02, f"{v:.3f}", ha="center", fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT_DIR, "fig5_rf_compare.png"), dpi=150)
    plt.close(fig)


def main():
    global OUT_DIR
    ap = argparse.ArgumentParser()
    ap.add_argument("--paper", default="Dataset.xlsx")
    ap.add_argument("--multiposture", default=None)
    ours = ap.add_mutually_exclusive_group()
    ours.add_argument("--ours", nargs="*", default=None)
    ours.add_argument("--ours-frames", nargs="+", default=None)
    ours.add_argument("--dataset-manifest", default=None)
    ap.add_argument("--trees", type=int, default=500)
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--stride", type=int, default=5)
    ap.add_argument("--lams", type=float, nargs="*", default=[0.5, 1.0])
    ap.add_argument("--skip-paper-loso", action="store_true")
    ap.add_argument("--features", nargs="*", default=["all"], choices=list(FEATURE_SETS),
                    help="특징 구성 (여러 개 지정 시 차례로 비교): all invariant relative")
    a = ap.parse_args()
    compatibility_dir = OUT_DIR
    directory, manifest = start_experiment(a)
    try:
        record_runtime(manifest)
        manifest["inputs"]["paper"] = dict(source_dataset_id="paper_dataset", **file_identity(a.paper))
        if a.multiposture:
            manifest["inputs"]["multiposture"] = dict(source_dataset_id="multiposture_dataset",
                                                      **file_identity(a.multiposture))
        if a.dataset_manifest is not None:
            from selection_manifest import resolve_dataset_manifest
            manifest["inputs"]["ours"], manifest["dataset_manifest"] = resolve_dataset_manifest(
                a.dataset_manifest, REPO_ROOT)
        else:
            manifest["inputs"]["ours"] = resolve_ours_inputs(a.ours, a.ours_frames, compatibility_dir)
        write_experiment_manifest(directory, manifest)
        OUT_DIR = str(directory)
        execute_experiment(a, directory, manifest)
        verify_inputs(manifest["inputs"])
        verify_dataset_selection(manifest)
        verify_file(directory / "sample_lineage.jsonl", manifest["sample_lineage"]["sha256"])
        for name in ("rf_results.csv", "rf_results.txt", "fig5_rf_compare.png"):
            path = directory / name
            if name != "fig5_rf_compare.png" or path.exists():
                item = dict(kind=name, **file_identity(path))
                previous = next((o for o in manifest["outputs"] if o["kind"] == name), None)
                if previous is not None:
                    if previous != item:
                        raise ValueError(f"output changed before completion: {name}")
                else:
                    manifest["outputs"].append(item)
        manifest.update(status="completed", ended_at=datetime.now(timezone.utc).isoformat())
        write_experiment_manifest(directory, manifest)
    except BaseException as error:
        manifest.update(status="failed", ended_at=datetime.now(timezone.utc).isoformat())
        manifest["errors"].append(str(error))
        write_experiment_manifest(directory, manifest)
        raise
    finally:
        OUT_DIR = compatibility_dir
    # Publication happens only after canonical completion. Never rewrite the run on copy failure.
    os.makedirs(compatibility_dir, exist_ok=True)
    for output in manifest["outputs"]:
        try:
            shutil.copyfile(output["path"], os.path.join(compatibility_dir, Path(output["path"]).name))
        except OSError as error:
            print(f"[compatibility copy failed] {error}", file=sys.stderr)
    return directory


def execute_experiment(a, directory, manifest):
    lines = []

    def log(s=""):
        print(s)
        lines.append(s)

    log("=" * 78)
    log(" 분류기 비교: M0(일반 RF) / M1(원 논문 입력 가중) / M2(분할 점수 가중, 본 팀 제안)")
    log("=" * 78)
    rows = []
    paper_sources, ours_sources, multi_sources, lineage = [], [], [], []
    Xp0, yp, gp = load_paper(a.paper, lineage=paper_sources, artifact=manifest["inputs"]["paper"])
    if len(paper_sources) != len(yp):
        raise ValueError("paper sample lineage does not match model sample order")
    ref_p = yp == 0  # 원 논문: 사람마다 정상 자세 1장이 기준
    Xo0 = yo = meta = None
    if a.ours or a.ours_frames or a.dataset_manifest is not None:
        Xo0, yo, meta = load_ours(a.ours, log=log, inputs=manifest["inputs"]["ours"], lineage=ours_sources)
        if len(ours_sources) != len(yo):
            raise ValueError("canonical sample lineage does not match model sample order")
        go = np.array([json.dumps([s["recording_id"], s["analysis_run_id"]]) for s in ours_sources])
        # 우리 데이터: 각 회차 첫 정상 자세(20초 구간)가 기준
        first_up = {}
        for i, m in enumerate(meta):
            k = go[i]
            if m[3] == "upright" and (k not in first_up or m[2] < meta[first_up[k]][2]):
                first_up[k] = i
        ref_o = np.zeros(len(meta), bool)
        ref_o[list(first_up.values())] = True
        reference_steps = {(ours_sources[i]["recording_id"], ours_sources[i]["analysis_run_id"]): meta[i][2]
                           for i in first_up.values()}
    if a.multiposture:
        Xm, ym, gm = load_multiposture(a.multiposture, a.stride, lineage=multi_sources,
                                      artifact=manifest["inputs"]["multiposture"])
        if len(multi_sources) != len(ym):
            raise ValueError("MultiPosture sample lineage does not match model sample order")
    for fs in a.features:
        lineage += lineage_rows(paper_sources, manifest["experiment_run_id"], "paper_loso", fs)
        if a.ours or a.ours_frames or a.dataset_manifest is not None:
            lineage += lineage_rows(ours_sources, manifest["experiment_run_id"], "ours_external", fs,
                                    reference_steps)
    if a.multiposture:
        lineage += lineage_rows(multi_sources, manifest["experiment_run_id"], "multiposture_loso", "all")
    verify_inputs(manifest["inputs"])
    verify_dataset_selection(manifest)
    # Persist before fitting: even a failed numerical execution retains every model input sample.
    manifest["sample_lineage"] = write_sample_lineage(directory, lineage)
    write_experiment_manifest(directory, manifest)
    for fs in a.features:
        log(f"\n######## 특징 구성: {fs} — {FEATURE_SETS[fs]}")
        Xp = transform(Xp0, gp, ref_p, fs)
        if not a.skip_paper_loso:
            rows += [dict(r, features=fs) for r in
                     loso(Xp, yp, gp, 5, a.trees, a.seeds, a.lams, f"[A] 원 논문 Dataset.xlsx ({fs})", log,
                          ref_mask=ref_p if fs == "relative" else None, feature_set=fs)]
        if a.ours or a.ours_frames or a.dataset_manifest is not None:
            if len(yo):
                Xo = transform(Xo0, go, ref_o, fs)
                rows += [dict(r, features=fs, dataset=f"C_ours_external ({fs})") for r in
                         external(Xp, yp, Xo, yo, meta, 5, a.trees, a.seeds, a.lams, log,
                                  ref_mask=ref_o if fs == "relative" else None, feature_set=fs)]
            else:
                log("\n[C] analysis 폴더에서 우리 데이터를 찾지 못했습니다 (analyze_d455.py 먼저 실행).")
    Xp = transform(Xp0, gp, ref_p, "all")
    if a.multiposture:
        rows += loso(Xm, ym, gm, 5, min(a.trees, 200), a.seeds, a.lams,
                     f"[B] MultiPosture (별도 트랙, {a.stride}프레임 간격)", log)
        log("   * MultiPosture의 '앞으로(TLF)'는 몸통 기울임이라 원 논문 거북목과 다른 자세 (클래스 번호만 같은 자리)")
    log("\n* 모든 모델은 같은 직접 구현 RF(트리 수·max_features=2·시드 동일)로 비교 (v4 §3.2)")
    log("* M2의 λ는 탐색적으로 여러 값을 모두 보고함. 최종 결론은 학습 fold 안에서 λ를 고른 결과로 내야 함")
    keys = sorted({k for r in rows for k in r}) + list(RESULT_LINEAGE_FIELDS)
    for row in rows:
        row.update(experiment_run_id=manifest["experiment_run_id"],
                   dataset_manifest_sha256=manifest["dataset_manifest"]["sha256"],
                   lineage_manifest_path="sample_lineage.jsonl",
                   lineage_manifest_sha256=manifest["sample_lineage"]["sha256"])
    with open(os.path.join(OUT_DIR, "rf_results.csv"), "x", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    manifest["outputs"].append(dict(kind="rf_results.csv", **file_identity(directory / "rf_results.csv")))
    with open(os.path.join(OUT_DIR, "rf_results.txt"), "x", encoding="utf-8") as f:
        f.write("\n".join(lines))
    try:
        plot(rows)
        print(f"[그래프 저장] {OUT_DIR}/fig5_rf_compare.png")
    except Exception as e:
        print(f"[그래프 생략] {e}")
        manifest["errors"].append(f"optional plot failure: {e}")
        partial = Path(OUT_DIR) / "fig5_rf_compare.png"
        if partial.exists():
            partial.unlink()


if __name__ == "__main__":
    main()
