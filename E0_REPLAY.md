# 연구 B B-1 — E0 원본 Replay

`run_research_b.py --replay`는 DB3/BAG 파일 또는 NPZ 세션/클립 디렉터리를
기존 `posture_geometry_probe.run_probe`의 **전체 E0 경로**에 연결한다.
별도 특징식/분류기는 없다. Live E0/B1, 원본 저장 버튼, 10초/H9/FS3 규칙은 유지한다.
공식 평가·B6·Patch 8 HOLD는 유지하며 B-Fixed/B-Adaptive를 구현하지 않는다.

## 실행

```powershell
python -X utf8 -B run_research_b.py --replay "C:\path\P03_original.db3" --variant E0 --pacing throughput --expected-sha256 3e960a23a865ad42cd8673d3cd584e753c6c98ec8e7801c4a970009f4413e246 --replay-arm-at-first-frame --output-dir analysis/RESEARCH_B/local_private/replay_01
python -X utf8 -B run_research_b.py --replay "C:\path\P03_original.db3" --variant E0 --pacing realtime15 --replay-arm-at-first-frame --output-dir analysis/RESEARCH_B/local_private/realtime_01
python -X utf8 -B run_research_b.py --replay "C:\path\session" --pacing throughput --output-dir analysis/RESEARCH_B/local_private/npz_01
python -X utf8 -B run_research_b.py --check-only --variant E0 --save-raw off
```

출력 디렉터리는 새 경로이고 **부모 디렉터리가 존재**해야 한다. 원본 내부 출력/덮어쓰기는 거부한다.
NPZ 세션은 `recording_metadata/session_manifest.json`이 있는 디렉터리,
클립은 `recording.json`/`frames.jsonl`/`end.json`이 있는 `clip_0001` 등이다.
미완료 원본은 명시적 `--allow-incomplete`가 필요하며 무결성 오류를 무시하지 않는다.
Replay는 GUI/물리 카메라 검색·fallback, 새 녹화, 모델 다운로드·학습을 하지 않는다.
기존 로컬 MediaPipe model lock과 SVM artifact binding을 그대로 검증한다.

`throughput`은 대기 없이 순서대로 전부 처리한다. `realtime15`는 host perf-counter의
15FPS 일정에 맞추는 **lossless backpressure** 방식이다. 느려도 따라잡기용 프레임 삭제를 하지 않는다.
따라서 부하가 크면 실제 FPS가 15에 미달할 수 있으며 lateness를 기록한다.
원래 센서 timestamp를 재생 속도/host 시간으로 바꾸지 않는다.

기본은 측정 구간을 arm하지 않고 모든 프레임의 Align/Pose/Face/Depth/특징을 계산한다.
`--replay-arm-at-first-frame`은 명시적인 **무라벨 공학 점검**용이다. 첫 입력에서
기존 10초 구간을 arm하며 실제 안정 자세/정답/참가자 움직임을 의미하지 않는다.
원본 이벤트를 임의로 안정 구간 또는 정답으로 해석하지 않는다.
10초 미만 입력은 구간 INCOMPLETE, 실제 SVM 호출 0이다. 루프/구간 패딩/강제 집계는 없다.

## 재사용과 보존

- 기존 `raw_rgbd_replay` NPZ reader 및 파일 전용 `db3_packets`를 재사용한다.
  DB3 reader가 선택적으로 원래 SDK frameset handle도 전달하며 기존 배열/clock 반환은 유지한다.
- DB3는 native frameset을, NPZ는 저장 보정값과 native BGR8/Z16 배열로 만든
  SDK software-device frameset을 같은 `rs.align(color)`에 전달한다.
  Software device는 물리 장치가 아니며 설정 변경도 물리 장치에 도달하지 않는다.
- NPZ의 대응 프레임은 syncer가 다시 짝짓지 않고 명시적 composite로 만든다.
  SDK child frame의 timestamp/domain/number가 원본과 같은지 검사한다.
  frameset clock은 원본 view를 유지한다. intrinsics/extrinsics/depth scale을 복원한다.
- SDK의 초소형 프로필 처리에서 발견한 native heap 오류를 막기 위해 software 입력은
  width≥64, width가 4의 배수, height≥48인 정상 영상 프로필로 제한한다.
  D455 원본 1280×720 / 848×480은 범위에 포함된다. 작은 합성 NPZ의 reader 검증은 별개다.
- VIDEO에는 원본 frameset timestamp를 정수 ms로 전달한다. 비정상 범위/domain 변경,
  정수 ms 중복/역행은 보정하지 않고 원인과 해당 입력 skip을 기록한다.
  진행 중 구간은 취소하고, 이후 유효 입력의 전체 처리로 복귀한다. 자동 재-arm은 없다.
  센서별 번호 gap/중복/역행은 독립 진단이며 실제 센서 누락률로 확정하지 않는다.
- I/O/무결성/추론 오류는 재시도 없이 실패 종료하고 기존 파일은 보존한다.
  `replay_failure.json`, 가능한 경우 부분 `replay.json`과 E0 요약에 실패를 남긴다.
  SHA pin 오류처럼 출력 예약 전 오류는 새 결과 디렉터리도 만들지 않는다.

## 측정 경계

`summary.json`, `frames.jsonl`, `segments.jsonl`, `resources.jsonl`, `timing/`은 기존 E0 계측이다.
`input_scope=raw_replay`, `timing_valid_for_live_performance=false`로 Live 지표와 구분한다.
추가 `replay.json`은 원본/시퀀스 SHA, 원래 시각·번호·대응, 호출 수, 단계 시간,
프로세스 CPU/RSS, 성공/거부 수, 구간·예측 상태와 오류를 기록한다.

|지표|경계·해석|
|---|---|
|stream wall / process CPU / CPU per input|모델/소스 준비 후부터 EOF/예외까지; 모든 프로세스 thread·observer 포함; 자원 monitor join과 최종 보고는 제외|
|input / processed FPS|위 동일 stream 분모; EOF 확인 wait/최종 검증 포함. EOF read 제외 FPS도 별도 제공|
|read_decode|동기 reader next 호출. NPZ 파일 SHA/디코드 및 DB3 배열 copy 포함; SDK 비동기 디코드의 독점 비용은 아님|
|prefetch_setup_ms|첫 packet은 프로필 준비 때 읽음. 초기화 비용으로 별도 기록하며 첫 frame read에 다시 더하지 않음|
|adapter_and_identity|시퀀스 hash/센서 진단 및 NPZ SDK reconstruction; 실제 입력 복사·감사 비용 포함|
|processing|reader·adapter·재생 대기 반환 직후부터 기존 E0 완료 hook까지; Align/변환/Pose/Face/Depth/특징 및 해당 시 구간·SVM 포함|
|inference_kernel_ms|동일 프레임의 원래 단계 duration 합. 파일 I/O·pacing·외부 observer 제외. frame tag가 없는 FS3 aggregate/scale/SVM은 별도 unframed total|
|read_to_complete|read 진입부터 E0 완료 hook까지; 읽기·adapter·identity·pacing 포함|
|service_excluding_pacing|위 값에서 측정한 pacing wait만 제외|
|RSS mean / peak|완료 프레임마다 process RSS 관측. 프레임 가중 평균·샘플 peak이며 연속 peak 보증 아님. 기존 1초 resource monitor와 OS process-lifetime peak도 별도 기록|
|invocation|run_probe 진입부터 session/report 발행까지의 wall/CPU; 모델 초기화/EOF/종료 포함; 사전 SHA/model binding 검증은 제외|

지연 분포는 성공 처리 프레임을 분모로 하고 거부/미처리 수를 함께 표시한다.
처음 프레임/첫 추론을 제외하지 않는다. Windows process CPU clock의 coarse tick 때문에
프레임별 CPU는 0 또는 큰 tick으로 보일 수 있으므로 전체 CPU/입력 CPU를 함께 사용한다.
SDK decoder와 observer가 같은 프로세스에 있어 **순수 추론 전용 CPU는 NOT_ISOLATED**다.
순수 처리 경로 wall stage와 전체 process CPU를 혼동하지 않는다.
이는 host 측 API 관측이며 센서 노출→추론/화면 물리 지연 또는 하드웨어 성능 인증이 아니다.

## 검증과 다음 단계

```powershell
python -X utf8 -B -m pytest -q -p no:cacheprovider test_e0_replay.py test_raw_rgbd_followup.py test_raw_rgbd_recording.py test_research_b.py test_e0_fs3.py test_e0_p2.py test_e0_p3.py test_e0_e1_ui.py test_run_e0_check.py test_e0_guided_panel.py test_h9_probe_integration.py test_probe_timing.py test_performance_output.py test_h9_probe_timing.py test_frame_provenance.py
```

실제 결과·반복 명령·환경·전체 source 해시는
`analysis/RESEARCH_B_E0_REPLAY_20261117_6ee16cb3/REPORT.md`와 같은 디렉터리에 보존한다.
실행 전의 과거 Live E0 14.95FPS/p95 약52ms와 Replay의 개선율은 계산하지 않는다.
P03은 145쌍/약9.68초이며 10초 구간이 부족하다. 정답/움직임 주석이 없어
Accuracy/Macro-F1/P0·P1 Recall/전환 지연은 NOT_MEASURED다.
카메라/GUI는 이번 파일 검증에서 NOT_TESTED_HARDWARE/GUI_NOT_TESTED다.
