# teammate_feature_ablation_20261029

「AIoT 앉은 자세 분류 연구 — 팀원용 분석 업무 가이드」(원본 파일명 `AIoT_팀원용_H5_H9_특징기여_및_RF분석_작업가이드_20261029.md`, 작성 기준 2026-10-29)의 업무 A~D 결과 폴더다. `config.json`의 `guide` 항목에는 로컬 보관 경로 `guide/20261029.md`로 적혀 있다. 같은 파일이다.
가이드 §8 "결과 디렉터리 예시"의 `README.md`(코드 기준 SHA, 데이터 출처, 실행 방법)에 해당한다.

- 범위: P01/P02 기존 파일럿 자료의 **오프라인 탐색 분석**만 한다. 정식 IRB 데이터가 아니며, 독립 검증이나 모델 선정도 아니다. 신규 촬영과 D455/Patch 8 실행은 하지 않는다.
- 모델: 가이드 §3.3 고정 조건인 **M0**만 사용한다(트리 500개, `max_features=2`, seed 0~4, 참가자 단위 LOSO).
- 기존 코드, 모델, CSV, 기존 결과는 변경하지 않는다. 기존 코드는 불러와서 쓰기만 한다.

## 코드 기준 SHA

| 항목 | 값 |
|---|---|
| 브랜치 | `research/h5-h9-ablation` |
| 기준 커밋 (작업 시작점) | `8252b7b3f161fdbd467474563b2e7270941cf643` |
| 기존 코드 수정 | 없음 |
| 실행 환경 | Python 3.14.4, numpy 2.5.0 |

결과 JSON마다 실행 당시의 커밋, 기존 코드 4개(`h6_offline.py`, `rf_experiment.py`, `f1_sample_aggregator.py`, `posture_geometry_probe.py`)의 SHA-256, `ablation.py`의 SHA-256이 `provenance`에 기록된다.

## 데이터 출처

원자료와 파생 특징 CSV는 로컬 보호 경로에만 보관하며 Git에 올리지 않는다(가이드 §2 데이터 관리).

| 구분 | 식별자 | SHA-256 |
|---|---|---|
| P01 H9 파생 특징 CSV | `P01_h9_20261024_170900.csv` | `1d8f0c7e40b87f750bb4a351f52ed55b083a1c37e777a2e9088f54111ded3122` |
| P02 H9 파생 특징 CSV | `P02_h9_20261024_173954.csv` | `6bbad505e9333e4029fe1be155e73ce745c9709077b57fda65eb49e3fc8b9f2e` |
| 기준 결과 (가이드 §2) | `h6_pilot_20261024_174708.json` | `850552faee27e6da61335f9dd6e5440dfe5c6f82b12d1f95386d318b14e22dd1` |

- 부적격 구간과 실행 오류(가이드 §8 필수 기록): 부적격 구간은 0개다. 입력 프레임 3,613개가 모두 H9 9개 특징의 공동 유효 프레임이다(`baseline_check.json`의 `samples`: `excluded_sample_count` 0, `input_frame_count` = `common_valid_frame_count` = 3613). A-1, A-2 실행 중 오류는 없었다. `ablation.py`는 오류가 나면 결과 파일을 만들지 않고 멈춘다.
- `baseline_check.json`의 `method.command`에 적힌 `데이터/`는 로컬 데이터 폴더 이름을 `pilot_data/`로 바꾸기 전의 경로다. 그때 실제로 실행한 명령이라 그대로 두었다. 파일 내용(SHA-256)은 같다.
- 사용하지 않은 P02 녹화 4개(`P02_h9_20261024_172010` / `172217` / `172501` / `173706`)는 기준 결과에 쓰이지 않은 녹화다. 이유는 `config.json`의 `excluded_recordings`에 적었다.
- 표본: 안정 자세 구간 1개 = 표본 1개. H9 9개 특징의 공동 유효 프레임이 30개 이상이고 공동 유효 비율이 50% 이상인 **24개 구간**을 쓴다(P01 12개, P02 12개, 자세마다 4개). 모든 조건에서 같은 24개 구간을 같은 순서로 쓴다.
- 클래스 순서: P0 upright, P1 forward_head, P2 lean_back, P3 lean_left, P4 lean_right, P5 lean_forward

## 파일

| 파일 | 내용 | 상태 |
|---|---|---|
| `config.json` | 특징 집합, 클래스, seed, RF 설정, 적격 조건, 13개 조건. 결과가 나오기 전에 고정함 | 완료 |
| `baseline_check.json` | 기존 H5/H9 기준선 재현 대조 (H5 62.50 / 56.88, H9 78.33 / 75.72 완전 일치) | 완료 |
| `ablation.py` | 업무 A-1 / A-2 / B 실행 도구 (M0만) | 완료 |
| `test_ablation.py` | 시험 21개: 구조 시험 16개, 실제 자료 기준선 재현 2개, 연구 주담당자 자료와의 대조 3개(A-2 예측값, 재사용한 상관계수) | 완료 |
| `depth_add_one.json` | 업무 A-1 | 완료 (2026-10-30) |
| `depth_drop_one.json` | 업무 A-2 | 완료 (2026-10-30) |
| `h5_drop_one.json` | 업무 B | 아직 안 함 |
| `f0_h5_comparison.md` | 업무 C | 아직 안 함 |
| `rf_failure_analysis.md` | 업무 D | 아직 안 함 |
| `summary.md` | 논문용 주요 표, 해석, 한계 | 업무 A 완료 (2026-10-30), B~D는 아직 |

## 실행 방법

저장소 맨 위 폴더에서 실행한다. `<...>` 부분은 각자의 로컬 보호 경로로 바꾼다.

```bash
# 업무 A-1 (결과: depth_add_one.json). A-2는 --task A-2, B는 --task B
python -B analysis/teammate_feature_ablation_20261029/ablation.py \
    --task A-1 \
    --probe-csv <P01_h9_20261024_170900.csv 경로> <P02_h9_20261024_173954.csv 경로> \
    --baseline-json <h6_pilot_20261024_174708.json 경로>

# 도구 시험
python -B -m unittest discover -s analysis/teammate_feature_ablation_20261029 -p "test_*.py"
```

다시 실행해서 저장된 결과와 비교할 때는 `provenance`(실행 당시 커밋, 코드 지문, 실행 환경)와 `run_date`(실행 날짜)를 빼고 비교한다. 이 두 항목은 실행할 때의 상태를 기록하는 값이라, 커밋이나 날짜가 바뀌면 달라진다. 나머지(조건, 예측값, 점수, 표본, fold)는 같아야 한다. `--out`으로 다른 파일 이름을 주면 기존 결과를 덮어쓰지 않는다.

```bash
python -B -c "import json,sys; a,b=(json.load(open(f,encoding='utf-8')) for f in sys.argv[1:3]); [d.pop(k) for d in (a,b) for k in ('provenance','run_date')]; print('SAME' if a==b else 'DIFFERENT')" <저장된 결과 JSON> <다시 실행한 결과 JSON>
```

`ablation.py`는 실행할 때 다음을 스스로 확인하고, 하나라도 다르면 결과를 만들지 않고 멈춘다.
1. 입력 CSV와 기준 JSON의 SHA-256이 `config.json`과 같은지
2. 표본이 24개인지
3. 기준선(H5 또는 H9)의 구간 명단, seed별 혼동행렬, 점수가 기존 결과와 완전히 같은지
4. 같은 이름의 결과 파일이 이미 있는지 (있으면 덮어쓰지 않음)

`test_ablation.py`의 실제 자료 시험과 대조 시험은 위 CSV를 저장소의 `pilot_data/`에서, 기준 JSON과 연구 주담당자의 진단 자료(`H9_feature_ablation_results_20261026.json`, `H9_feature_diagnostics_20261026.json`)를 `pilot/`에서 찾는다. 파일이 없으면 실패가 아니라 **건너뜀(skip)**으로 나온다.
