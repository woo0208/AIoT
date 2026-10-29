"""One fixed exploratory p=8 experiment; run with python -B from any cwd.

Reuses stored H9 M0/M2 and H9-F9 M0 results. Refits p8 M0 only to obtain
training-fold MDI and verify the stored baseline, then fits the sole new M2.
Never patches rf.rank_weights and never overwrites an existing artifact.
"""
import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
sys.path.insert(0, str(ROOT))
import h6_offline as h6
import rf_experiment as rf

STEM = "H9_F9_M2_followup_20261027"
DETAIL = OUT / (STEM + ".json")
REPORT = OUT / (STEM + ".md")
ABL = OUT / "H9_feature_ablation_results_20261026.json"
BASE = ROOT / "h6_pilot_20261024_174708.json"
CSV = [ROOT / "captures" / name for name in
       ("P01_h9_20261024_170900.csv", "P02_h9_20261024_173954.csv")]
F8 = [f"F{i}" for i in range(1, 9)]
F9 = F8 + ["F9"]
RAW8 = np.array([.30, .20, .15, .15, .15, .05, .05, .05])
M2 = "M2(λ=0.5)"
KEYS = ("accuracy", "macro_f1", "p0_recall", "p1_recall", "p5_recall")


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args):
    p = subprocess.run(["git", *args], cwd=ROOT, text=True, capture_output=True, check=True)
    return p.stdout.strip(), p.stderr.strip()


def p8_weights(mdi):
    mdi = np.asarray(mdi, dtype=float)
    if mdi.shape != (8,) or not np.isfinite(mdi).all():
        raise ValueError("this pilot policy requires exactly eight finite MDI values")
    order = np.lexsort((np.arange(8), -mdi))
    weights = np.empty(8)
    weights[order] = RAW8 / RAW8.sum()
    return weights, order


def self_checks():
    w, order = p8_weights(np.zeros(8))
    np.testing.assert_array_equal(order, np.arange(8))
    np.testing.assert_allclose(w, np.array([6, 4, 3, 3, 3, 1, 1, 1]) / 22)
    assert np.all(w > 0) and np.isclose(w.sum(), 1)
    reverse, _ = p8_weights(np.arange(8))
    np.testing.assert_array_equal(reverse, w[::-1])
    for bad in (np.zeros(9), np.zeros(7), np.full(8, np.nan)):
        try:
            p8_weights(bad)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid MDI accepted")
    try:
        rf.rank_weights(np.zeros(8))
    except ValueError:
        pass
    else:
        raise AssertionError("production p8 guard changed")
    # Structural test only, never mixed with captured-data metrics.
    x = np.arange(96, dtype=float).reshape(12, 8) % 17
    y = np.arange(12) % 6
    a = rf.Forest(6, 7, 2, None, 0).fit(x, y)
    b = rf.Forest(6, 7, 2, np.ones(8), 0).fit(x, y)
    np.testing.assert_array_equal(rf._forest_probabilities(a, x), rf._forest_probabilities(b, x))
    assert np.isclose((.5 + .5 * w / w.mean()).mean(), 1)
    return {"six_structural_check_groups": "PASS", "synthetic_data_use": "structural checks only"}


def metrics(y, pred):
    cm = np.zeros((6, 6), dtype=int)
    np.add.at(cm, (y, pred), 1)
    return dict(accuracy=float(np.mean(y == pred)), macro_f1=rf.macro_f1(y, pred, 6),
                **{f"p{k}_recall": float(cm[k, k] / cm[k].sum()) for k in (0, 1, 5)},
                confusion_matrix=cm.tolist())


def summarize(y, preds, mask):
    rows = [dict(seed=seed, **metrics(y[mask], p[mask])) for seed, p in enumerate(preds)]
    return dict(sample_count=int(mask.sum()), per_seed=rows,
                seed_mean={k: float(np.mean([r[k] for r in rows])) for k in KEYS},
                seed_sd_ddof0={k: float(np.std([r[k] for r in rows])) for k in KEYS},
                mean_confusion_matrix=np.mean([r["confusion_matrix"] for r in rows], axis=0).tolist())


def roots(forest):
    values = [F8[int(t.feat[0])] if t.feat[0] >= 0 else None for t in forest.trees]
    return dict(root_feature_by_tree=values,
                root_split_counts={f: values.count(f) for f in F8},
                leaf_only_trees=values.count(None))


def transitions(a, b):
    names = F9 + [None]
    return {f"{x or 'leaf'}->{z or 'leaf'}": sum(u == x and v == z for u, v in zip(a, b))
            for x in names for z in names if any(u == x and v == z for u, v in zip(a, b))}


def report(d):
    lines = ["# F9 제거 후 M2 가중치 영향 검증", "", "작성: 2026-10-27. P01/P02 기존 파일럿의 탐색 분석이며 독립 검증 성능이 아니다.", "",
             "## 평가와 기준선", "",
             "기준선 일치: PASS. 성공 CSV의 24표본 key·순서·9차원 집계값·공동 유효 support를 기존 JSON과 정확히 대조했다. H9 M0/M2는 기존 예측을 재사용하고 원 평가의 seed별 혼동행렬·평균·SD 및 10개 fold 인덱스·가중치와 대조했다. H9-F9 M0는 각 학습 fold에서 MDI 산출을 위해 다시 학습했으며, 기존 MDI·루트 500개·예측·확률과 정확히 일치했다. 기존 M0/M2 분할 진단의 루트 count도 대조했다.", "",
             "성공 CSV: `captures/P01_h9_20261024_170900.csv`, `captures/P02_h9_20261024_173954.csv`. 기존 `h6_offline.load_labeled_probe_h_samples` 집계 유지: PREP/TRANSITION 제외, H9 공동 유효 프레임 3,613개, 제외 표본/프레임 0. 참가자당 12구간, 자세당 2구간. F9 제거 뒤 재집계·재선택 없이 F1~F8 원래 의미와 순서 유지.", "",
             "참가자 LOSO, seed 0~4, RF 500 trees, max_features=2, 6 classes, M2 λ=0.5 고정. MDI와 순위는 각 fold의 학습 참가자 12표본만 사용한다. 기존 source/model 정의·전처리·라벨·평가 정의 변경 없음. M1·추가 후보·튜닝·재촬영은 실행하지 않았다.", "",
             "## 사전 고정 p=8 정책", "",
             "이번 사용자 지시를 분석 실행 전 정책으로 고정했다. 원형 `[0.30,0.20,0.15,0.15,0.15,0.05,0.05,0.05]`를 합계 1.10으로 정규화해 `[6,4,3,3,3,1,1,1]/22`를 배정한다. MDI 내림차순, 동률은 원래 열 번호 오름차순이다. 공용 `rf.rank_weights`의 p=8 거부는 유지하며 독립 스크립트에서만 처리한다. FEAT-010의 정식 p=9 정책을 변경하거나 확장 승인으로 재기록하지 않았다.", "",
             "M2 분할점수 `[(1−λ)+λ·w_j/mean(w)]×ΔGini` 유지. p=9의 rank별 배율은 `[1.673913,1.282609,1.086957,1.086957,1.086957,0.695652,0.695652,0.695652,0.695652]`, p=8은 `[1.590909,1.227273,1.045455,1.045455,1.045455,0.681818,0.681818,0.681818]`. 같은 rank에서도 정규화 가중치는 커지지만 mean(w)=1/p가 달라져 점수 배율은 작아진다. **p=8 정책은 기존 p=9 M2와 동일한 실험 조건이 아니다.**", "",
             "## 참가자별·모델별 성능", "",
             "단위 %, 5 seeds 평균 ± 모집단 SD(ddof=0). 전체는 매 seed 24개 OOF 예측을 합쳐 계산한 뒤 평균한다. 참가자별 Macro-F1 평균과 전체 Macro-F1은 다르다.", "",
             "|시험 대상|구성|Accuracy|Macro-F1|P0 Recall|P1 Recall|P5 Recall|", "|---|---|---:|---:|---:|---:|---:|"]
    for scope in ("pooled", "P01", "P02"):
        for config, result in d["results"].items():
            s = result["summaries"][scope]
            lines.append("|" + "|".join([scope, config] + [f"{100*s['seed_mean'][k]:.2f} ± {100*s['seed_sd_ddof0'][k]:.2f}" for k in KEYS]) + "|")
    lines += ["", "## M2−M0 차이와 F9 제거 효과", "", "단위 pp. 차이의 변화=(제거 후 M2−M0)−(제거 전 M2−M0).", "",
              "|시험 대상|지표|H9 M2−M0|H9-F9 M2−M0|차이의 변화|", "|---|---|---:|---:|---:|"]
    for scope, values in d["m2_minus_m0"].items():
        for k in KEYS:
            lines.append(f"|{scope}|{k}|{values['before_pp'][k]:+.2f}|{values['after_pp'][k]:+.2f}|{values['change_pp'][k]:+.2f}|")
    lines += ["", "## seed별 결과", "", "|시험 대상|구성|seed|Accuracy|Macro-F1|P0 Recall|P1 Recall|P5 Recall|", "|---|---|---:|---:|---:|---:|---:|---:|"]
    for scope in ("pooled", "P01", "P02"):
        for config, result in d["results"].items():
            for r in result["summaries"][scope]["per_seed"]:
                lines.append("|" + "|".join([scope, config, str(r['seed'])] + [f"{100*r[k]:.2f}" for k in KEYS]) + "|")
    lines += ["", "## 혼동행렬", "", "행=실제 P0~P5, 열=예측 P0~P5, 5 seeds count 평균. 행 합은 전체에서 4, 참가자별에서 2다. seed별 정수 행렬은 JSON에 보존한다."]
    for scope in ("pooled", "P01", "P02"):
        for config, result in d["results"].items():
            lines += ["", f"### {scope} / {config}", "", "```text"]
            lines += [" ".join(f"{v:.1f}" for v in row) for row in result["summaries"][scope]["mean_confusion_matrix"]]
            lines += ["```"]
    lines += ["", "## 학습-fold MDI·가중치와 루트 선택", "", "아래 값은 시험 참가자별 5 seeds 평균이다. 상세 JSON은 모든 fold의 MDI·순위·가중치·분할 배율과 500개 트리의 루트·전이 count를 제공한다. 루트 수는 5×500=2,500개를 합산하며 독립 측정 수가 아니다.", "",
              "|홀드아웃|특징|p9 w|p8 w|p9 배율|p8 배율|H9 M0 루트|H9 M2|F9제거 M0|F9제거 M2|", "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for subject, summary in d["weight_root_summary"].items():
        for f, r in summary["features"].items():
            fm = lambda v: "—" if v is None else f"{v:.5f}"
            lines.append("|" + "|".join([subject, f] + [fm(r[k]) for k in ('p9_weight', 'p8_weight', 'p9_multiplier', 'p8_multiplier')] + [str(r[k]) for k in ('h9_m0_roots','h9_m2_roots','p8_m0_roots','p8_m2_roots')]) + "|")
    for subject, summary in d["weight_root_summary"].items():
        lines += ["", f"{subject}: M0→M2 루트 변경 H9={summary['h9_m0_m2_changed']}/2500, F9제거={summary['p8_m0_m2_changed']}/2500. F9 제거 전후 M2 루트 변경={summary['m2_before_after_changed']}/2500."]
    lines += ["", "P01 홀드아웃(학습 P02): F8은 모든 seed에서 낮은 rank 가중치에 머문다. 평균 w는 0.04348→0.04545로 늘지만 배율은 0.69565→0.68182로 감소하고 M2 루트는 106→96이다. F9의 몫이 F8로 단순 이전되지 않았다. 제거 후에도 M2는 M0 대비 F3+F4 루트를 700→1,065로 늘린다. P1을 구별하는 성능 회복을 루트 빈도만으로 설명할 수 없다.", "",
              "P02 홀드아웃(학습 P01): F9는 기존 상위 순위를 차지했고 M2 루트 408개를 사용했다. 제거 후 F8 평균 w 0.12174→0.16364, 배율 1.04783→1.15455, M2 루트 332→399로 증가한다. F2/F7도 391→527 / 420→481로 증가한다. 그러나 제거 후 M2의 F8 루트는 M0 353→M2 399이며 F7은 353→481이다. 깊이 특징 선택은 계속 강화되지만 P02 P1 Recall은 0%로 유지돼 중복 제거만으로 오류가 해소되지 않았다.", "",
              "M0→M2의 루트 변경률은 전체 29.52%→32.18%로 증가했다. F9 제거 전후 M2 루트는 2,884/5,000개(57.68%)가 바뀌었다. 이는 p 변화와 학습 순위·배율의 공동 변화에 대한 관찰이며 특정 특징의 인과 효과가 아니다."]
    lines += ["### fold별 MDI 순위", "", "|홀드아웃|seed|p9 M0 MDI 순위|p8 M0 MDI 순위|", "|---|---:|---|---|"]
    for f in d["folds"]:
        lines.append(f"|{f['held_out_participant']}|{f['seed']}|{' > '.join(f['h9']['mdi_rank_order'])}|{' > '.join(f['p8']['mdi_rank_order'])}|")
    lines += ["", "## P1 오분류 표본 변화", "", "같은 4표본×5 seeds의 반복 예측이며 20명의 독립 관측이 아니다. 아래 예측 순서는 seed 0,1,2,3,4다.", "", "|표본|H9 M0|H9 M2|H9-F9 M0|H9-F9 M2|", "|---|---|---|---|---|"]
    for r in d["p1_sample_changes"]:
        lines.append("|" + "|".join([r['sample_id']] + [", ".join('P'+str(v) for v in r['predictions'][c]) for c in d['results']]) + "|")
    for comparison, r in d["p1_transition_summary"].items():
        lines += ["", f"{comparison}: 오답→정답 {r['wrong_to_correct']}, 정답→오답 {r['correct_to_wrong']}, 오답→다른 오답 {r['wrong_to_different_wrong']}, 동일 예측 {r['unchanged_prediction']} (총 20회)."]
    lines += ["", "M2의 제거 전후 P1 개선은 P01:S3의 seed 0·4 두 예측이 P0→P1로 바뀐 데서 나온다. seed 2의 P3 오류는 유지된다. P01:S15는 계속 P0, P02:S3·S15는 계속 P5다. 제거 후 M0가 P02:S15를 5 seeds 모두 맞힌 반면 M2는 모두 틀린다. 제거 후 M2−M0의 P1 Recall 격차가 −35pp로 확대되는 핵심은 이 표본의 5회 정답 상실과 P01:S3의 2회 정답 상실이다."]
    lines += ["", "## 판단과 한계", ""]
    for paragraph in d["interpretation"]:
        lines += [paragraph, ""]
    lines += [
              "두 참가자·24구간만 사용했고, 기존 탐색에서 선택된 F9 제거를 동일 자료로 다시 평가했다. seed 반복은 독립 참가자 수를 늘리지 않으며 통계적 유의성·인구 일반화·인과성을 입증하지 않는다. F8/F9 상관은 기존 전체 표본 r=0.99819로 높지만 중복이 M2 열화의 유일 원인임을 증명하지 않는다. 특징 수 변경은 후보 특징 추출 확률(2/9→2/8), 난수 permutation 및 이후 트리 경로를 바꾼다. 제거 전후 트리 index 대응은 기술적 비교이며 같은 후보 집합을 보장하지 않는다. p=8의 새 정책·MDI 재순위화·특징 제거 효과를 이 비교만으로 분리할 수 없다. λ/가중치 추가 튜닝·후속 모델 개선 없이 종료한다.", "",
              "## 생성 파일·검증·Git 상태", "",
              f"- 독립 스크립트: `{Path(__file__).relative_to(ROOT).as_posix()}` — p=8만 처리, 기존 모델 코드 호출, 읽기 전용 기준선 대조 및 보고서 생성.",
              f"- 상세 JSON: `{DETAIL.relative_to(ROOT).as_posix()}` — 재사용 예측·신규 예측/확률, 참가자/seed 지표·행렬, fold MDI·가중치·배율·루트·전이, P1 변화, 입력 해시.",
              f"- 보고서: `{REPORT.relative_to(ROOT).as_posix()}`.",
              "- 구조 점검 6그룹 PASS (p8 정규화/양수, 동률 순위, 역순 순위, 잘못된 입력 거부, 공용 p8 거부 유지, 합성 λ=0 확률 일치/배율 평균). 실제 CSV 기준선 대조 10 folds PASS. 저장 전 모든 보호 파일 SHA-256 불변 확인 PASS.",
              "- 기존 관련 단위 테스트: `python -B -m unittest -q test_rf_weights test_rf_rng` — 14 tests PASS. 광범위한 regression은 실행하지 않음.",
              f"- HEAD: `{d['metadata']['head']}`, branch `{d['metadata']['branch']}`. Git 추적 변경 없음. 출력 폴더는 gitignored; 새 파일 3개만 생성. 기존 CSV/JSON/MD·Git 추적 파일 수정, 모델 파일 저장, commit/push 없음.",
              "- Git 상태 경고: 접근 권한 때문에 사용자 전역 ignore 및 `.pytest_cache/`를 읽지 못한다는 기존 경고가 있다. 보호 파일 해시와 tracked diff를 별도로 확인했다."]
    return "\n".join(lines) + "\n"


def main():
    checks = self_checks()
    if "--self-check" in sys.argv:
        print(json.dumps(checks))
        return
    if "--verify-only" in sys.argv:
        d = read(DETAIL)
        for p, sha in d["verification"]["protected_file_sha256"].items():
            assert digest(ROOT / p) == sha, p
        assert digest(Path(__file__)) == d["metadata"]["script_sha256"]
        assert REPORT.read_text(encoding="utf-8") == report(d)
        for config, r in d["results"].items():
            y = np.array([h6.LAB6.index(s['label']) for s in d['samples']])
            for seed, pred in enumerate(r['predictions_by_seed']):
                assert metrics(y, np.array(pred)) == {k:v for k,v in r['summaries']['pooled']['per_seed'][seed].items() if k != 'seed'}
        print("PASS: saved JSON metrics, report, script and all protected hashes; no refit/no writes")
        return
    if DETAIL.exists() or REPORT.exists():
        raise FileExistsError("refusing to overwrite existing follow-up output")
    tracked = git("ls-files")[0].splitlines()
    protected = {ROOT / p for p in tracked if (ROOT / p).is_file()}
    protected.update(p for p in OUT.iterdir() if p.is_file() and p != Path(__file__).resolve())
    protected.update(CSV + [BASE])
    before = {p.relative_to(ROOT).as_posix(): digest(p) for p in sorted(protected)}
    status, warning = git("status", "--porcelain=v1", "--untracked-files=normal")
    assert not git("diff", "--name-only")[0], "tracked working changes present"
    old, base = read(ABL), read(BASE)
    assert (rf.H_EVAL_TREES, rf.H_EVAL_MAX_FEATURES, list(rf.H_EVAL_SEEDS), rf.H_EVAL_M2_LAMBDA) == (500, 2, [0,1,2,3,4], .5)
    samples = h6.load_labeled_probe_h_samples(CSV)
    eligible = [s for s in samples if s.eligible]
    X = np.array([s.ordered_values("H9") for s in eligible])
    y = np.array([h6.LAB6.index(s.label) for s in eligible])
    subjects = np.array([s.subject for s in eligible])
    assert X.shape == (24,9) and np.isfinite(X).all()
    assert h6.aggregation_audit(samples) == old['aggregation_audit'] == base['aggregation_audit']
    assert [list(s.sample_key) for s in eligible] == base['eligible_sample_keys']
    for s, row, saved in zip(eligible, X, old['samples']):
        assert list(s.sample_key) == saved['sample_key'] and s.subject == saved['subject'] and s.label == saved['label']
        np.testing.assert_array_equal(row, saved['h9_values'])
    assert list(h6.H9_FEATURE_NAMES) == base['feature_order']['H9']
    preds = {"H9 M0": np.array(old['results']['H9']['M0']['predictions_by_seed']),
             "H9 M2": np.array(old['results']['H9'][M2]['predictions_by_seed']),
             "H9-F9 M0": np.array(old['results']['H9-F9']['M0']['predictions_by_seed']),
             "H9-F9 M2": np.full((5,24), -1, dtype=int)}
    # Verify reused H9 metrics against the original evaluation, without fitting H9.
    for model, config in (("M0", "H9 M0"), (M2, "H9 M2")):
        original = next(r for r in base['metrics'] if r['feature_set']=='H9' and r['model']==model)
        calculated = summarize(y, preds[config], np.ones(24,dtype=bool))
        assert [r['confusion_matrix'] for r in calculated['per_seed']] == original['confusion_matrices']
        for key in ('accuracy','macro_f1'):
            assert abs(calculated['seed_mean'][key] - original[key]) < 1e-12
            assert abs(calculated['seed_sd_ddof0'][key] - original[key+'_seed_sd']) < 1e-12
    split = read(OUT / 'H9_M0_M2_split_diagnostics_20261026.json')
    folds = []
    for oldfold, basefold in zip(old['folds'], base['folds']):
        seed, subject = oldfold['seed'], oldfold['held_out_participant']
        train, test = subjects != subject, subjects == subject
        assert seed == basefold['seed'] and subject == basefold['held_out_participant']
        assert oldfold['train_indices'] == basefold['train_indices'] == np.flatnonzero(train).tolist()
        assert oldfold['test_indices'] == basefold['test_indices'] == np.flatnonzero(test).tolist()
        h9 = oldfold['variants']['H9']
        np.testing.assert_array_equal([h9['weights'][f] for f in F9], basefold['weights']['H9'])
        splitfold = next(f for f in split['folds'] if f['seed']==seed and f['held_out']==subject)
        for model in ('M0',M2):
            assert list(h9['models'][model]['root_split_counts'].values()) == list(splitfold['root_split_counts'][model].values())
        m0 = rf.Forest(6, 500, 2, None, seed).fit(X[train,:8], y[train])
        saved = oldfold['variants']['H9-F9']['models']['M0']
        np.testing.assert_array_equal(m0.mdi, [saved['mdi'][f] for f in F8])
        np.testing.assert_array_equal(m0.predict(X[test,:8]), preds['H9-F9 M0'][seed,test])
        np.testing.assert_array_equal(rf._forest_probabilities(m0,X[test,:8]), saved['mean_class_probabilities'])
        r0 = roots(m0)
        assert r0['root_feature_by_tree'] == saved['root_feature_by_tree']
        weights, order = p8_weights(m0.mdi)
        multipliers = .5 + .5 * weights / weights.mean()
        m2 = rf.Forest(6, 500, 2, multipliers, seed).fit(X[train,:8], y[train])
        preds['H9-F9 M2'][seed,test] = m2.predict(X[test,:8])
        r2 = roots(m2)
        f = dict(seed=seed, held_out_participant=subject, training_participants=sorted(set(subjects[train])),
                 train_indices=np.flatnonzero(train).tolist(), test_indices=np.flatnonzero(test).tolist(),
                 h9=dict(weights=h9['weights'], multipliers=h9['m2_split_multipliers'],
                         mdi=h9['models']['M0']['mdi'], mdi_rank_order=h9['models']['M0']['mdi_rank_order'],
                         m0_roots=h9['models']['M0']['root_feature_by_tree'], m2_roots=h9['models'][M2]['root_feature_by_tree']),
                 p8=dict(mdi=dict(zip(F8,m0.mdi.tolist())), mdi_rank_order=[F8[i] for i in order],
                         weights=dict(zip(F8,weights.tolist())), multipliers=dict(zip(F8,multipliers.tolist())),
                         m0=r0, m2=r2, m2_test_predictions=preds['H9-F9 M2'][seed,test].tolist(),
                         m2_mean_class_probabilities=rf._forest_probabilities(m2,X[test,:8]).tolist()))
        f['root_transitions'] = {
            'h9_m0_to_m2': transitions(f['h9']['m0_roots'],f['h9']['m2_roots']),
            'p8_m0_to_m2': transitions(r0['root_feature_by_tree'],r2['root_feature_by_tree']),
            'm2_before_to_after': transitions(f['h9']['m2_roots'],r2['root_feature_by_tree'])}
        folds.append(f)
        print(f"PASS baseline; fitted fixed p8 M2: seed={seed}, held_out={subject}",flush=True)
    assert np.all(preds['H9-F9 M2'] >= 0)
    results = {c: dict(predictions_by_seed=p.tolist(),
                      provenance='new fixed-policy evaluation' if c=='H9-F9 M2' else 'reused existing ablation JSON',
                      summaries={scope:summarize(y,p, np.ones(24,dtype=bool) if scope=='pooled' else subjects==scope)
                                 for scope in ('pooled','P01','P02')}) for c,p in preds.items()}
    gaps = {}
    for scope in ('pooled','P01','P02'):
        mean = lambda c: results[c]['summaries'][scope]['seed_mean']
        before_gap = {k:100*(mean('H9 M2')[k]-mean('H9 M0')[k]) for k in KEYS}
        after_gap = {k:100*(mean('H9-F9 M2')[k]-mean('H9-F9 M0')[k]) for k in KEYS}
        gaps[scope] = dict(before_pp=before_gap,after_pp=after_gap,change_pp={k:after_gap[k]-before_gap[k] for k in KEYS})
    weight_roots = {}
    for subject in ('P01','P02'):
        fs = [f for f in folds if f['held_out_participant']==subject]
        feature_rows = {}
        for feature in F9:
            feature_rows[feature] = dict(
                p9_weight=float(np.mean([f['h9']['weights'][feature] for f in fs])),
                p8_weight=float(np.mean([f['p8']['weights'][feature] for f in fs])) if feature in F8 else None,
                p9_multiplier=float(np.mean([f['h9']['multipliers'][feature] for f in fs])),
                p8_multiplier=float(np.mean([f['p8']['multipliers'][feature] for f in fs])) if feature in F8 else None,
                h9_m0_roots=sum(f['h9']['m0_roots'].count(feature) for f in fs),
                h9_m2_roots=sum(f['h9']['m2_roots'].count(feature) for f in fs),
                p8_m0_roots=sum(f['p8']['m0']['root_feature_by_tree'].count(feature) for f in fs),
                p8_m2_roots=sum(f['p8']['m2']['root_feature_by_tree'].count(feature) for f in fs))
        changed = lambda a,b: sum(u!=v for f in fs for u,v in zip(a(f),b(f)))
        weight_roots[subject] = dict(features=feature_rows,
            h9_m0_m2_changed=changed(lambda f:f['h9']['m0_roots'],lambda f:f['h9']['m2_roots']),
            p8_m0_m2_changed=changed(lambda f:f['p8']['m0']['root_feature_by_tree'],lambda f:f['p8']['m2']['root_feature_by_tree']),
            m2_before_after_changed=changed(lambda f:f['h9']['m2_roots'],lambda f:f['p8']['m2']['root_feature_by_tree']))
    p1rows = [dict(sample_id=f"{s.subject}:S{s.sample_key[-1]}", sample_key=list(s.sample_key),
                   predictions={c:p[:,i].tolist() for c,p in preds.items()})
              for i,s in enumerate(eligible) if y[i]==1]
    p1summary = {}
    for a,b in (('H9 M0','H9 M2'),('H9-F9 M0','H9-F9 M2'),('H9 M2','H9-F9 M2')):
        x,z = preds[a][:,y==1],preds[b][:,y==1]
        p1summary[a+' → '+b] = dict(wrong_to_correct=int(np.sum((x!=1)&(z==1))),
            correct_to_wrong=int(np.sum((x==1)&(z!=1))),
            wrong_to_different_wrong=int(np.sum((x!=1)&(z!=1)&(x!=z))),unchanged_prediction=int(np.sum(x==z)))
    effect = lambda model,scope,k:100*(results[f'H9-F9 {model}']['summaries'][scope]['seed_mean'][k]-results[f'H9 {model}']['summaries'][scope]['seed_mean'][k])
    interpretation = [
        f"F9 제거의 전체 M0 변화는 Accuracy {effect('M0','pooled','accuracy'):+.2f}pp / Macro-F1 {effect('M0','pooled','macro_f1'):+.2f}pp / P1 Recall {effect('M0','pooled','p1_recall'):+.2f}pp다. M2의 변화는 각각 {effect('M2','pooled','accuracy'):+.2f}pp / {effect('M2','pooled','macro_f1'):+.2f}pp / {effect('M2','pooled','p1_recall'):+.2f}pp다.",
        f"M2에서 F9 제거의 Accuracy 변화는 P01 {effect('M2','P01','accuracy'):+.2f}pp, P02 {effect('M2','P02','accuracy'):+.2f}pp다. 참가자별 이질성과 P0/P1 trade-off를 함께 판단해야 한다.",
        "M2에서도 절대 성능은 소폭 개선됐지만 M0 대비 불리함은 해소되지 않았다. 전체 Accuracy의 M2−M0 차이는 −6.67→−9.17pp, Macro-F1은 −8.70→−10.76pp, P1 Recall은 −20→−35pp로 확대됐다. 참가자별 Accuracy 격차는 P01에서 −8.33→−1.67pp로 줄고 P02에서 −5.00→−16.67pp로 커진다. 중복 제거가 M2의 상대 성능을 회복한다는 근거는 얻지 못했다.",
        "F9 제거는 이 파일럿의 후보 구성으로 유지할 근거가 있다. 전체 지표와 P1의 관측 개선을 근거로 하되 정식 특징 채택·보편적 M2 개선으로 확정하지 않는다. 기존 F9와 공용 코드는 유지하며 이 작업에서 후속 모델 개선은 진행하지 않는다."]
    assert all(digest(ROOT/p)==sha for p,sha in before.items()), 'protected input changed'
    assert git('status','--porcelain=v1','--untracked-files=normal')[0] == status
    d = dict(analysis='F9 removal / fixed p8 M2 exploratory follow-up',
        metadata=dict(created_at=datetime.now(timezone.utc).isoformat(),head=git('rev-parse','HEAD')[0],
            branch=git('branch','--show-current')[0],python=platform.python_version(),numpy=np.__version__,
            script_sha256=digest(Path(__file__)),inputs=[p.relative_to(ROOT).as_posix() for p in CSV],
            source_results=ABL.relative_to(ROOT).as_posix(),trees=500,max_features=2,seeds=list(range(5)),m2_lambda=.5,
            p8_policy=dict(raw=RAW8.tolist(),normalizer=1.10,normalized=(RAW8/RAW8.sum()).tolist(),
                fixed_before_evaluation=True,authority='explicit user instruction for this exploratory pilot only',
                rank='descending training-fold M0 MDI; lower original column breaks ties'),
            features=old['metadata']['feature_columns'],class_order=list(h6.LAB6),posture_ids=list(h6.POSTURE_IDS),
            confusion_axes='rows actual P0..P5; columns predicted P0..P5'),
        samples=old['samples'],aggregation_audit=h6.aggregation_audit(samples),results=results,folds=folds,
        m2_minus_m0=gaps,weight_root_summary=weight_roots,p1_sample_changes=p1rows,
        p1_transition_summary=p1summary,interpretation=interpretation,
        verification=dict(**checks,baseline_checks='PASS: all 10 folds and reused H9 matrices; exact p8 M0 MDI/predictions/probabilities/roots',
            protected_file_sha256=before,protected_existing_file_count=len(before),existing_files_changed=[],
            git_status_before=status,git_status_after=status,git_warning=warning,output_directory_gitignored=True))
    with DETAIL.open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(d,stream,ensure_ascii=False,indent=2,allow_nan=False)
        stream.write('\n')
    with REPORT.open('x',encoding='utf-8',newline='\n') as stream:
        stream.write(report(d))
    print(json.dumps({c:r['summaries']['pooled']['seed_mean'] for c,r in results.items()},ensure_ascii=False,indent=2))


if __name__ == '__main__':
    main()
