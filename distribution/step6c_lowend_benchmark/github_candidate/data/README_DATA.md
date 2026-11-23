# 별도 승인 입력과 보관 위치

자료 관리자의 승인 범위에 맞는 로컬 보관소를 사용한다. 원본과 사람 승인표에는 참여자와 촬영 정보가 담긴다. 파일, 해시 매니페스트, 촬영 승인 문구 및 원시 실행 로그의 접근 권한을 제한한다.

```text
<private>/
  DATA_TRANSFER_MANIFEST.csv
  clip_0002/
    recording.json
    frames.jsonl
    end.json
    <index가 참조하는 2,078개의 NPZ 경로>
  inputs/
    intake.json
    approvals.csv
    candidates.csv
    approval_record.json
    reference_predictions.csv     (승인된 선택 자료)
  model/
    model.pkl
  tasks/
    blaze_face_short_range.tflite
    face_landmarker.task
    pose_landmarker_full.task
```

각 NPZ에는 대응되는 RGB와 Depth 한 쌍이 들어 있다. `recording.json`은 보정과 Depth scale을 제공하고 `frames.jsonl`은 원본 순서·타임스탬프·페이로드 해시와 대응 정보를 제공한다. 원본 하위 구조는 인덱스와 매니페스트의 경로를 유지한다. `intake.json`의 라벨은 비워 두고 승인된 오프라인 Start 이벤트만 사용한다. `approvals.csv`와 `candidates.csv`는 사후 채점에 필요하다. 각 창에는 10,000ms보다 이른 입력만 들어가며, 10초 도달 후 첫 입력은 닫힘이다.

`model.pkl`은 동결 SVM과 scaler를 함께 담은 Python pickle이다. 응용 프로그램이 이를 역직렬화하므로 승인된 보관처에서 받은 정확한 파일만 사용한다. MediaPipe 가중치는 `src/mediapipe_model_lock.json`의 버전과 SHA-256을 사용한다. 저장소 밖에 보관된 `tasks`를 실행용 `src/models`에 연결해 기존 실행기의 상대 경로를 충족한다. 다른 경로 배치가 필요하면 별도 실행 사본의 `src/models` 아래에 관리자가 허가한 파일을 준비한다.

매니페스트의 `slot`과 `delivery_relative`는 실행 경로 기준이다. 승인된 자료 인수 담당자가 원래 해시를 유지한다. 참조 예측을 전달받지 못하면 담당자가 해당 선택 행을 제외한 매니페스트를 제공하고 사후 채점에서 비교 옵션을 생략한다. 저사양 실험 결과는 위 입력 위치와 공개 코드 저장소 밖에 저장한다.
