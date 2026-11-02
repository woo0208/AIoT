# 5-D-6 — pinned 촬영 입력 manifest / TimedSegment loader

기준은 AGENTS.md, 5-D-3 동결 문서, EXP-003/004, 5-D-4 어댑터다. 새 파일은 `f0_fcal_input.py`, `test_f0_fcal_input.py`, 이 보고서 3개다. 기존 capture/analyze/reader/6열 어댑터/8열 평가기와 frozen schema, H5/H9·모델·데이터·5-B·보호 파일은 수정하지 않았다.

## 사용 경계

`load_evaluation_input(manifest_path, manifest_sha256=사전고정해시, other_families=None)`는 아래 별도 manifest와 pinned sources를 읽어 기존 `prepare_samples` 및 `evaluation_input`에 전달한다. 학습·predict·metric·RGB 재분석·카메라 실행은 하지 않는다. 실제 참가자 자료는 이번 구현/테스트에 사용하지 않았다.

재사용 함수:

- `rf_experiment.read_pinned_json`, `verify_file`: JSON 읽기·원천 hash 확인 및 읽은 후 재확인.
- `rf_experiment.canonical_input`: completed analysis 소유권, exact frames header/identity, output hash와 immutable 디렉터리 구조 확인.
- `f1_csv_adapter.read_canonical_frame_rows`: 기존 canonical reader로 typed 관측/결측/boolean을 읽음. F1 특징은 계산하지 않음.
- `analyze_d455.load_markers`: marker 읽기. null timestamp 건너뛰기/옛 step 자동 생성에 기대지 않도록 선택한 원본 marker 행을 먼저 검증함.
- `f0_fcal_evaluation.prepare_samples`, `evaluation_input`: 기존 공동 support·threshold·고정 참조·참조 제외·클래스 매핑·공통 구간 정렬을 그대로 사용.

## 별도 manifest 입력 인터페이스

이는 **engineering loader 인터페이스**이며 scientific schema/selection 계약을 새로 freeze하거나 대체하지 않는다. 실제 참가자·참조 manifest 파일을 이번에 발급하지 않았다. manifest 자체의 예상 SHA-256을 외부에서 명시해야 한다. 경로는 manifest 디렉터리 상대 경로나 절대 경로다.

```json
{
  "interface": "f0-fcal-session-input-engineering-v1",
  "participant_splits": {"SYN01": "train"},
  "reference_keys": {"SYN01": ["ar_synthetic_0", "synthetic_r0", 1]},
  "segments": [{
    "subject": "SYN01", "session": "S1", "order": 0,
    "recording_id": "synthetic_r0", "analysis_run_id": "ar_synthetic_0",
    "round": "1", "step": 1, "label": "upright",
    "hold_start_marker_index": 0, "hold_end_marker_index": 1,
    "sources": {
      "frames": {"path": ".../analysis/<recording_id>/<ar_run>/..._frames.csv", "sha256": "..."},
      "analysis": {"path": ".../analysis_manifest.json", "sha256": "..."},
      "raw": {"path": ".../<recording_id>.bag", "sha256": "..."},
      "markers": {"path": ".../<recording_id>_markers.csv", "sha256": "..."},
      "capture": {"path": ".../<recording_id>_camera.json", "sha256": "..."},
      "clock_evidence": {"path": ".../clock.json", "sha256": "..."},
      "input_inventory": {"path": ".../delivered_frames.json", "sha256": "..."}
    }
  }]
}
```

예시의 SYN01은 합성 식별자이며 실제 참가자 배정이 아니다.

`order`는 참가자 내 사전 획득 순서이며 round/파일명으로 유추하지 않는다. marker index는 header를 제외한 CSV 데이터 레코드의 0-based index다. start는 해당 step/label의 hold, end는 바로 다음 prep/transition/end marker여야 하며 둘 다 실제 장치 timestamp와 recording_id가 있어야 한다. 종료 시간을 planned_sec나 host wall_time으로 대신하지 않는다. `reference_keys`는 참가자의 첫 upright key여야 하며 S1 검증은 기존 어댑터에서 수행한다. S2가 다른 recording/run이어도 동일 참가자의 고정 key를 재사용한다. 누락된 참조는 자동 지정하지 않는다.

## 실제 입력·시간축 근거

전체 입력은 **CSV 행 수만으로 증명하지 않는다**. analysis owner에 `analysis_mode=extract_raw`, `raw_extraction_applied=true`, 양쪽 trim=0, `step_effective=1`이 기록돼 있어야 한다. raw/markers/capture의 SHA가 owner.inputs와 일치해야 하고 capture identity도 검사한다. summarize/from-csv·trim·stride·설정 unknown 자료는 unprocessed다. 현재 기본 analyze 추출의 trim 1.0/0.5 자료는 이 경로에서 자동 통과하지 않는다.

추가 근거는 상위 추출/기록 단계가 보존한 두 JSON이다. 이 loader는 이 파일을 만들거나 raw 영상에서 그 정확성을 새로 검증하지 않는다.

- **clock_evidence:** `recording_id`, `raw_sha256`, `markers_sha256`, `frame_field="ts_ms"`, `marker_field="frame_timestamp_ms"`, `unit="ms"`, `same_clock=true`, 비어 있지 않은 `domain`. 단위/동일 시계의 출처를 upstream에서 확인한 뒤 pinned artifact로 제공해야 한다. manifest에 임의 선언만 추가해서 물리적 clock 정합성이 증명되는 것은 아니다.
- **input_inventory:** `recording_id`, `raw_sha256`, `clock_domain`, `scope="all_delivered_frames"`, `interval_ms=[시작,끝]`, `frames=[{"frame_index":1,"ts_ms":10000}, ...]`. 기록된 interval은 선택 hold 전체를 덮고, 실제 전달된 프레임을 관측 결측/모델 실패 여부와 무관하게 나열해야 한다. 중복 index·비유한/비증가 timestamp는 거부한다. 센서 생성 전체 프레임이나 예상 FPS 프레임 수를 뜻하지 않는다.

이러한 근거의 **생성·완전성에 대한 신뢰 경계는 upstream 생산자/검토자**다. hash는 내용 고정을 검증하며 거짓 inventory나 clock 주장의 과학적 진실성까지 증명하지 않는다. 따라서 실제 경로 검증 blocker를 유지한다. 기존 native 녹화에서 이 목록을 만드는 exporter·누락률 계산은 이번에 구현하지 않았다.

marker 장치시각으로 정한 `[종료-10000ms, 종료)` 안의 inventory와 해당 canonical step 행의 `(frame_index, ts_ms)`가 정확히 일치해야 한다. invalid 관측 행도 이 일치 검사와 분모에 포함하고 공동 support만 기존 어댑터에서 걸러낸다. 빠진 행을 None 관측으로 생성하거나 CSV를 원본 전체로 간주하지 않는다. trim/stride 검사를 통과해도 inventory 불일치는 unprocessed다. null인 마지막 end timestamp를 첫/마지막 프레임에서 추정하지 않는다.

## 결과·실패·정렬

`LoadedInput`은 status, manifest 순서의 timed_segments/samples, 키 정렬된 evaluation, 구간별 issues, 읽은 source_artifacts(path/SHA)를 반환한다. evaluation의 6열 배열·마스크·공통 key 의미는 5-D-4와 동일하다. sample key는 정확한 `(analysis_run_id, recording_id, int step)`다. 다른 특징군은 이 key로 명시적으로 연결해야 한다.

구간 원천/시간/세션/완전 입력 근거 부족은 빈 관측·시간 unknown의 placeholder를 통해 unprocessed로 전달하고 loader 사유를 보존한다. 참조가 unprocessed면 해당 참가자의 모든 F0/F_cal 표본도 unprocessed가 되며 다른 P0로 대체하지 않는다. 유효 입력이 준비돼도 30/50 또는 보정 요건을 실패하면 기존 어댑터가 ineligible로 처리한다. source hash·identity 모순도 임의 복구하지 않는다. manifest 자체의 필수 identity/참조 지정이 모순되면 전체 evaluation=None과 issues를 반환한다.

전역 `prepared`는 입력 준비 처리가 끝났다는 뜻이며 모든 구간 적격이나 정식 실행 승인이 아니다. H5/H9 자체 적격성을 수정하지 않고 특징군 간 원시 프레임 support도 교차 강제하지 않는다. frame_loss_rate는 None이며 재촬영/불완전 클래스/seed/metric 정책을 적용하지 않는다.

## 검증과 남은 차단

`python -B -m unittest -v test_f0_fcal_input test_f0_fcal_evaluation test_f0_fcal_features`: 신규 loader 8개 + 어댑터/core 22개, 총 **30개 PASS**. 모든 파일은 임시 디렉터리의 합성 CSV/marker/manifest·가상 raw bytes이며 native 녹화 재생이 아니다. 키 정렬·6열/라벨·반개구간·S2 참조 재사용·참조 고정·hash 고정·trim/stride 거부·실제 입력 분모/결측·marker/clock/session/reference 부족을 검증한다.

실제 적용에는 무trim/무stride canonical 산출과 검증된 실제 입력 inventory, clock 근거, 장치시각 hold 종료 marker, 사전 세션/참조 manifest가 필요하다. 이를 생성하는 upstream 연결과 실제 녹화 경로 검증은 남아 있다. 기존 8열 평가기·학습/지표 경로는 보존했다. 실제 참가자 분석·재학습·전체 감사·대규모 테스트·commit/push 없음.
