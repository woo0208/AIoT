"""5-D-10 fixed SYNTHETIC six-person rehearsal; never a formal model freeze.

No real-data input parameter, camera, downloads, tuning or model changes. Uses
the unchanged 500-tree/three-seed formal settings even for this small fixture.
"""

import hashlib
import json
from pathlib import Path
import pickle
import warnings

import numpy as np
from sklearn.exceptions import ConvergenceWarning

import formal6_evaluation as ev
from f0_fcal_features import Segment
from f0_fcal_evaluation import TimedSegment, prepare_samples
from f1_sample_aggregator import HFrameRecord, aggregate_h5_h9_sample
from rf_experiment import file_identity, read_pinned_json, verify_file


KIND = "SYNTHETIC_STRUCTURAL_ONLY_NOT_FORMAL_MODEL_OR_RESEARCH_RESULT"
FIXTURE = "synthetic-six-minimal-v1"
DEVELOPMENT = ("SYN-F01", "SYN-F02")
HELDOUT = ("SYN-F03", "SYN-F04", "SYN-F05", "SYN-F06")


def _pin(path):
    value = file_identity(path)
    return {k: value[k] for k in ("path", "sha256")}


def _write(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)


class SyntheticFixture:
    """Held-out values are generated lazily only when the verified gate calls us."""

    def __init__(self, *, missing_heldout_class=None):
        if missing_heldout_class not in (None, 0, 1, 2, 3, 4, 5):
            raise ValueError("invalid synthetic missing-class case")
        self.missing_heldout_class = missing_heldout_class
        self.events = []
        self._released = False

    def development(self):
        self.events.append("development_fixture_generated")
        return self._batch(DEVELOPMENT)

    def heldout(self, subjects):
        if not self._released or tuple(subjects) != HELDOUT:
            raise ValueError("synthetic held-out values sealed until freeze verification")
        self.events.append("heldout_fixture_generated_after_freeze")
        return self._batch(HELDOUT)

    def _batch(self, subjects):
        if set(subjects) - set(DEVELOPMENT) and not self._released:
            raise ValueError("held-out fixture sealed")
        items, h_samples, refs, review, windows, key_map = [], [], {}, {}, {}, {}
        for subject in subjects:
            person = (DEVELOPMENT + HELDOUT).index(subject)
            # First P0 is calibration only; six separate target intervals follow.
            for step, klass in enumerate((0, 0, 1, 2, 3, 4, 5), 1):
                if subject in HELDOUT and step != 1 and klass == self.missing_heldout_class:
                    continue  # Explicit missingness structural case, not an ablation.
                label = ev.h6.LAB6[klass]
                core_label = "body_forward" if label == "lean_forward" else label
                session = "S1" if step <= 4 else "S2"
                rid, run = "recording_" + subject + "_" + session, "ar_" + subject + "_" + session
                key = (run, rid, step)
                start = step * 20
                frames = tuple(dict(frame_index=(step-1)*30+n+1, time_s=start+n/3,
                    phase="hold", face_x=100+person*2+klass*3, face_y=70+klass,
                    face_area_px=400+person*2+klass*15, lsh_x=60, lsh_y=160,
                    rsh_x=150, rsh_y=160, face_detected=True, lsh_valid=True, rsh_valid=True)
                    for n in range(30))
                items.append(TimedSegment(Segment(subject, rid, run, step, step, core_label, frames),
                                          session, start, start+10, "synthetic_device_seconds"))
                # Arbitrary finite H features, not a sensor/posture simulation.
                records = tuple(HFrameRecord(run, rid, (step-1)*30+n+1, subject, "1", str(step), label,
                    {name: klass*0.1+j*0.01+person*0.03 for j, name in enumerate(ev.H9_FEATURE_NAMES)})
                    for n in range(30))
                h_sample = aggregate_h5_h9_sample(records)
                h_samples.append(h_sample)
                key_map[h_sample.sample_key] = key
                windows[key] = (("synthetic_device_seconds", start, start+10), session)
                review[key] = "confirmed"
                if step == 1:
                    refs[subject] = key
        samples = prepare_samples(items, refs)
        if tuple(subjects) == DEVELOPMENT:
            families = ev.rows_from_f0(samples, items, review, subjects)
            families.update(ev.rows_from_h(h_samples, windows, review, subjects, key_map=key_map))
        else:
            families = ev._rows_from_f0(samples, items, review, subjects)
            families.update(ev._rows_from_h(h_samples, windows, review, subjects, key_map=key_map))
        return dict(kind=KIND, families=families, reference_keys=refs, f0_samples=samples)


def _training_digest(aligned, feature):
    content = dict(keys=aligned["sample_keys"], participants=aligned["participants"].tolist(),
                   X=aligned["X"][feature].tolist(), y=aligned["y"].tolist())
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()


def _fit_synthetic_final(candidate, aligned, seed):
    """Approved existing implementation only; all inputs are the development rows."""
    _, feature, model = next(c for c in ev.CANDIDATES if c[0] == candidate)
    X, y = aligned["X"][feature], aligned["y"]
    if set(aligned["participants"]) != set(DEVELOPMENT) or any(k[2] == 1 for k in aligned["sample_keys"]):
        raise ValueError("final synthetic fit must contain only development non-reference rows")
    scaler, weights = None, None
    if model == "LR_B0":
        ref = ev._reference()
        scaler = ref.StandardScaler().fit(X)
        fitted = ref.make_model("Logistic-Regression", 0)
        with warnings.catch_warnings():
            warnings.simplefilter("error", ConvergenceWarning)
            fitted.fit(scaler.transform(X), y)
    elif model == "M0":
        fitted = ev.rf.Forest(6, 500, 2, None, seed).fit(X, y)
    else:
        models, train_weights = ev.rf.fit_models(X, y, 6, 500, seed, [0.5])
        fitted = models["M1" if model == "M1" else "M2(λ=0.5)"].forest
        weights = train_weights if model == "M1" else None
    audit = dict(train_subjects=DEVELOPMENT, train_keys=aligned["sample_keys"],
        n_train=len(y), training_digest=_training_digest(aligned, feature),
        scaler_n_samples_seen=int(scaler.n_samples_seen_) if scaler is not None else None,
        scaler_mean=scaler.mean_.tolist() if scaler is not None else None)
    return dict(kind=KIND, fixture=FIXTURE, candidate=candidate, seed=seed,
                feature=feature, model=fitted, scaler=scaler, input_weights=weights, fit_audit=audit)


def infer_synthetic_frozen(freeze_path, *, freeze_sha256, fixture):
    """No fit/scaler.fit/ranking here; only our marked synthetic artifacts accepted."""
    if type(fixture) is not SyntheticFixture:
        raise ValueError("fixed synthetic fixture required; real input is unsupported")
    freeze_path = Path(freeze_path).resolve()
    freeze, pin = read_pinned_json(freeze_path)
    if (pin["sha256"] != freeze_sha256 or freeze.get("kind") != KIND or freeze.get("fixture") != FIXTURE
            or freeze.get("freeze_scope") != "SYNTHETIC_TEST_ONLY"
            or freeze.get("synthetic_runner_sha256") != file_identity(__file__)["sha256"]):
        raise ValueError("synthetic freeze identity/hash mismatch")
    def after_verified(subjects):
        fixture.events.append("freeze_verified_before_heldout_access")
        fixture._released = True
        try:
            return fixture.heldout(subjects)
        finally:
            fixture._released = False
    payload = ev.load_frozen_heldout(freeze_path, freeze_sha256=freeze_sha256, loader=after_verified)
    # Same candidate comparison scope as development; all-five alignment also
    # retained as a separate audit, without a cross-family frame intersection.
    aligned = ev._align_rows(payload["families"], HELDOUT, payload["reference_keys"], feature_sets=("H9", "H9-F9"))
    comparison = ev._align_rows(payload["families"], HELDOUT, payload["reference_keys"], feature_sets=tuple(ev.FEATURES))
    seeds, predictions, fit_audits = [], [], []
    for artifact in freeze["model_artifacts"]:
        path = freeze_path.parent / artifact["path"]
        verify_file(path, artifact["sha256"])
        # Only self-generated, hash-pinned SYNTHETIC test files, never a protected model.
        with path.open("rb") as stream:
            bundle = pickle.load(stream)
        if (bundle["kind"] != KIND or bundle["fixture"] != FIXTURE or bundle["candidate"] != freeze["candidate"]
                or bundle["seed"] != artifact["seed"] or tuple(bundle["fit_audit"]["train_subjects"]) != DEVELOPMENT
                or bundle["fit_audit"]["training_digest"] != freeze["training_digest"]):
            raise ValueError("synthetic model/freeze binding mismatch")
        X = aligned["X"][bundle["feature"]]
        if bundle["scaler"] is not None:
            X = bundle["scaler"].transform(X)
        if bundle["input_weights"] is not None:
            X = X * bundle["input_weights"]
        predictions.append(bundle["model"].predict(X) if len(X) else np.array([], dtype=int))
        seeds.append(bundle["seed"])
        fit_audits.append(bundle["fit_audit"])
        verify_file(path, artifact["sha256"])
    y, people = aligned["y"], aligned["participants"]
    summary = ev._summary(y, predictions, seeds)
    participant_metrics = {s: ev._summary(y[people == s], [p[people == s] for p in predictions], seeds) for s in HELDOUT}
    # Any missing participant class makes this independent rehearsal INCOMPLETE;
    # retain pooled diagnostics and all four participant/support records.
    if any(m["status"] == "INCOMPLETE" for m in participant_metrics.values()):
        summary["status"], summary["mean_macro_f1"] = "INCOMPLETE", None
        for row in summary["per_seed"]:
            row["status"], row["macro_f1"] = "INCOMPLETE", None
    verify_file(freeze_path, freeze_sha256)
    fixture.events.append("heldout_prediction_only_completed")
    return dict(kind=KIND, candidate=freeze["candidate"], aligned=aligned, comparison_alignment=comparison,
        reference_keys=payload["reference_keys"], predictions=tuple(p.tolist() for p in predictions), seeds=tuple(seeds),
        pooled=summary, participants=participant_metrics,
        sessions={s: ev._summary(y[aligned["sessions"] == s], [p[aligned["sessions"] == s] for p in predictions], seeds)
                  for s in ("S1", "S2")}, fit_audits=tuple(fit_audits),
        heldout_fit_count=0, heldout_scaler_fit_count=0, heldout_selection_count=0)


def run_synthetic_pipeline(output_root):
    """One fixed structural rehearsal, full unchanged settings; exclusive outputs."""
    if ev.TREE_COUNT != 500 or ev.SEEDS != (0, 1, 2):
        raise ValueError("synthetic end-to-end rehearsal requires unchanged formal settings")
    root = Path(output_root).resolve()
    if root.exists() or not root.parent.is_dir():
        raise ValueError("new synthetic output directory required")
    fixture = SyntheticFixture()
    development = fixture.development()
    report = ev.evaluate_development(development["families"], DEVELOPMENT, development["reference_keys"])
    if report["status"] != "DEVELOPMENT_COMPLETE" or report["baseline_comparison"]["status"] != "COMPARISON_COMPLETE":
        raise ValueError("synthetic development incomplete; no freeze or heldout access")
    fixture.events.append("development_eight_combinations_and_five_candidate_ranking_completed")
    candidate = report["selection"]["recommendation"]
    settings = ev.frozen_settings(candidate)
    bundles = [_fit_synthetic_final(candidate, report["aligned"], seed) for seed in settings["seeds"]]
    fixture.events.append("development_only_final_synthetic_fit_completed")
    root.mkdir()
    artifacts = []
    for bundle in bundles:
        path = root / f"SYNTHETIC_ONLY_model_seed_{bundle['seed']}.pkl"
        with path.open("xb") as stream:
            pickle.dump(bundle, stream, protocol=5)
        artifacts.append(dict(seed=bundle["seed"], path=path.name, sha256=_pin(path)["sha256"]))
    freeze = dict(kind=KIND, fixture=FIXTURE, freeze_scope="SYNTHETIC_TEST_ONLY", status="FROZEN",
        candidate=candidate, class_order=list(ev.h6.LAB6), settings=settings, code_hashes=ev.code_hashes(),
        synthetic_runner_sha256=file_identity(__file__)["sha256"],
        development_subjects=list(DEVELOPMENT), heldout_subjects=list(HELDOUT), model_artifacts=artifacts,
        reference_keys={s: list(k) for s, k in development["reference_keys"].items()},
        training_digest=bundles[0]["fit_audit"]["training_digest"],
        fit_audits=[b["fit_audit"] for b in bundles])
    freeze_path = root / "SYNTHETIC_ONLY_freeze.json"
    _write(freeze_path, freeze)
    freeze_sha = _pin(freeze_path)["sha256"]
    fixture.events.append("synthetic_freeze_written")
    heldout = infer_synthetic_frozen(freeze_path, freeze_sha256=freeze_sha, fixture=fixture)
    return dict(kind=KIND, development=report, heldout=heldout, events=tuple(fixture.events),
        freeze_path=str(freeze_path), freeze_sha256=freeze_sha,
        formal_model_frozen=False, research_performance_result=False)
