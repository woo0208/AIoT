# 5-D-7 — native D455 녹화의 독립 F0 입력 생성 경로

추가 파일: `f0_fcal_native.py`, `test_f0_fcal_native.py`, 이 보고서. 기존 capture/analyze/loader·frozen schema·H5/H9·보호 모델·원본·5-B·스냅샷은 수정하지 않았다. 실제 녹화나 참가자 자료를 실행하지 않았으며 commit/push 없음.

## 연결 범위

`generate_evaluation_input(request_path, request_sha256=..., output_root=새경로, model_dir=기존모델폴더)`를 명시적으로 호출하는 offline API다. import만으로 실행되지 않으며 CLI·촬영·다운로드·학습·metric 계산이 없다. 실제 사용 승인을 이 API가 대신하지 않는다.

native reader는 기존 `analyze_d455`와 같은 RealSense SDK의 `enable_device_from_file(..., repeat_playback=False)` 및 `set_real_time(False)`를 사용하고, 기존 `research_d455.PacketSource.receive` / `RGBDPacket.validate`로 모든 전달 frameset의 RGB/depth·각 frame number·timestamp/domain을 읽는다. 기존 분석 루프는 trim/stride/depth 조건이 있으므로 호출하지 않는다. SDK timeout은 EOF로 간주하지 않고 playback stopped를 확인한다.

관측은 기존 `verified_model_paths`로 face/pose lock을 검증하고 `research_d455.open_observer`의 detector를 재사용한다. bbox 중심·어깨 좌표/유효성은 `live_f1_d455.f1_frame_input`, 얼굴 선택은 같은 `largest_face_detection`을 직접 재사용하며 선택한 bbox의 실제 width×height를 추가한다. F1/H 특징·분류기는 계산하지 않는다. 모델 부재·lock 불일치·추출 예외는 unprocessed이며 모델을 내려받거나 바꾸지 않는다.

## 사전 고정 요청

요청 파일은 별도 engineering 인터페이스이며 frozen scientific schema가 아니다. 예시 구조:

```json
{
  "interface": "f0-fcal-native-request-engineering-v1",
  "reference_keys": {"SYN-P01": ["ar_SYN01", "SYN01", 1]},
  "participant_splits": {"SYN-P01": "train"},
  "recordings": [{
    "subject": "SYN-P01", "round": "1", "recording_id": "SYN01",
    "analysis_run_id": "ar_SYN01",
    "sources": {
      "raw": {"path": "SYN01.bag", "sha256": "..."},
      "markers": {"path": "SYN01_markers.csv", "sha256": "..."},
      "capture": {"path": "SYN01_camera.json", "sha256": "..."}
    },
    "segments": [{
      "session": "S1", "order": 0, "step": 1, "label": "upright",
      "hold_start_marker_index": 0, "hold_end_marker_index": 1
    }]
  }]
}
```

합성 예시이며 실제 참가자·녹화나 실행 승인을 뜻하지 않는다.

path는 요청 파일 기준 상대/절대 경로다. marker index는 CSV header를 제외한 0-based 레코드다. session·order·step·label·참조 key를 파일명/품질/예측으로 추정하지 않는다. run ID는 사전 지정 `ar_...`이며 출력 경로는 존재하지 않아야 한다. S1 첫 P0 지정과 참조 key를 검증하고 새 output manifest에 그대로 전달한다. S2는 같은 subject의 기존 참조를 재사용하며 다른 P0로 바꾸지 않는다.

## 전체 입력·clock 검증과 저장

- trim=0/0, stride=1로 **EOF까지 전달된 모든 frameset**의 inventory와 관측 JSONL을 보존한다. RGB/depth/landmark 결측도 프레임을 삭제하지 않는다. 센서 생성 전체 수·누락률을 주장하지 않는다.
- `all_observations.jsonl`은 prep·선택 밖 프레임까지 포함한 전체 관측이며 timestamp와 frame identity를 유지한다. `f0_frames.csv`는 명시적으로 선택한 완전한 hold 구간만 기존 60-field writer로 투영한다. hold 내부에는 앞뒤 trim·stride·depth gate를 적용하지 않는다. 미실행 mesh·depth·legacy θ 등은 unknown으로 두며 값을 발명하지 않는다. 전체 보존 목록과 hold CSV를 구분하는 설정을 provenance에 기록한다.
- 같은 기록의 source SHA·capture identity·record_file·marker recording_id를 검사한다. 선택 hold의 start/end는 인접한 실제 marker여야 하고 양쪽 장치 timestamp가 필요하다. 짧은 hold는 정책 미확정으로 차단한다. host wall time/planned duration/마지막 프레임을 종료 시각으로 대체하지 않는다.
- 현재 확인한 `capture_d455.py`는 `frame_timestamp_ms`를 `frames.get_timestamp()`에서 저장한다. camera에 기록된 `capture_script_sha256`이 그 현재 producer hash와 같아야 이 출처를 인정한다. 알 수 없는 구버전은 timestamp 범위가 겹쳐도 차단한다.
- native frameset timestamp는 유한·엄격 증가, domain은 동일해야 한다. 선택 start/end timestamp가 실제 replay 프레임에 정확히 대응해야 하며 marker에 color_frame_number가 있으면 그것도 일치해야 한다. 단순 숫자 overlap이 아니라 **알려진 producer의 직접 frameset timestamp 저장 + pinned 동일 raw + native frame/domain/선택 marker 대조**를 근거로 clock_evidence를 생성한다. 기록에 없는 capture domain 문자열을 추정 생성하거나 host/device clock을 빼지 않는다.
- 원본·요청·producer·모델 hash는 확인/재확인하고, generator·관측 dependency hash·모델/reader 종류·선택 marker↔프레임 대응과 추출 설정을 기록한다. synthetic injection이면 reader/observer 종류에 SYNTHETIC가 남는다.

모든 기록의 입력/clock/EOF 검증이 성공하기 전에는 출력 디렉터리를 만들지 않는다. 성공하면 새 `output_root/analysis/<recording_id>/<ar_run>/`에 전체 관측, input_inventory, clock_evidence, hold canonical CSV 및 owner manifest를 생성한다. 원본 경로에 파일을 쓰거나 capture metadata를 보완하지 않는다. output owner는 engineering interface로 표시하며 scientific schema/version을 새로 freeze하지 않는다. 원본 dataset_role은 승격하지 않는다.

마지막으로 새 `session_reference.json`의 hash를 고정해 기존 `f0_fcal_input.load_evaluation_input`으로 읽고 6열 어댑터 결과를 반환한다. 30/50, 참조 실패/제외·공통 구간 비교는 기존 5-D-3/6 경로가 처리한다. 기존 8열 평가기는 그대로다. 생성 중 쓰기/마지막 검증 실패 시 unprocessed이며, 남은 부분 산출물은 성공 manifest로 간주하지 않는다. 기존 경로를 덮어쓰거나 자동 삭제/재시도하지 않는다.

## 남은 차단과 촬영 코드 최소 수정안

실제 SDK/MediaPipe 경로는 실행하지 않아 native EOF·stream pairing·model/runtime 호환성에 대한 실제 검증은 남아 있다. timestamp domain 변경·중복 timestamp·선택 marker 미대응·알 수 없는 producer·불완전 replay는 추정 없이 unprocessed다. stream number 차이를 누락률로 변환하거나 재촬영을 선택하지 않는다. seed/metric·불완전 클래스·특징군 원시 프레임 교집합도 결정하지 않았다.

기존 연속 `capture_d455.record_phase`의 최종 end marker는 장치 timestamp/color frame number가 None이므로, 그 marker가 필요한 최종 hold는 차단된다. **최소 촬영 수정안만 제시:** 정상 hold 종료 전환 시점에 해당 frameset의 timestamp·domain·color frame number를 함께 저장하고, 중단/예외 종료와 정상 종료를 구분해 기록한다. cleanup wall time을 장치 종료시각으로 대체하지 않는다. 향후 구버전 producer도 지원하려면 timestamp 필드의 출처와 capture producer hash/clock domain을 검증 가능한 sidecar에 명시해야 한다. 이번에 촬영 코드는 변경하지 않았다.

## 합성 검증

`python -B -m unittest -v test_f0_fcal_native test_f0_fcal_input test_f0_fcal_evaluation test_f0_fcal_features`: 신규 native 경로 6개 + 기존 30개, 총 **36개 PASS**. SDK 녹화·보호 모델 대신 가상 RGB-D packet과 합성 detection만 사용했다. 전체 프레임·결측 보존, 시간 경계와 domain, 실제 입력 분모, 원본/설정/provenance hash, loader/6열 연결, timestamp/producer/EOF 부족 차단을 확인했다. 실제 연구 성능 검증·재학습·전체 감사가 아니다.
