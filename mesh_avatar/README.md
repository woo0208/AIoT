# Mesh Avatar (표시 전용)

D455 + MediaPipe로 이미 계산된 3D 관절 위치(`GeometryResult.points_3d`)를 받아
리깅된 인체 메시(기본: Mixamo X Bot)를 의자에 앉은 자세로 실시간 구동합니다.
정면(카메라 시점)과 측면을 동시에 보여 줍니다.

> 시각화 전용입니다. 아바타 자세는 측정값이나 F1/F2 특징이 아니며 어떤 연구 산출물도 쓰지 않습니다.
> 브라우저는 자세를 판정하지 않습니다. probe가 **같은 프레임**에서 계산한 engineering RF demo 예측
> (UPRIGHT / FORWARD HEAD / BODY FORWARD) 또는 `PREDICTION UNAVAILABLE`(이유 포함)만 그대로 표시합니다
> — `ENGINEERING RF DEMO — ACCURACY NOT VALIDATED`.

## 실행
```
python run_mesh_avatar.py              # D455 실시간 → 브라우저가 http://127.0.0.1:8765/ 로 열림 (RF 꺼짐 → UNAVAILABLE)
python run_mesh_avatar.py --f1-live --rf-demo-model f1_demo_rf.json   # + F1-5 패널 + 같은 프레임 RF 예측
python run_mesh_avatar.py --f1-live --rf-demo-model f1_demo_rf.json --pyvista   # + PyVista 창
python run_mesh_avatar.py --synthetic  # 카메라 없이 가짜 관절로 파이프라인 확인 (RF 예측 없음)
```
실행기 전용 옵션(`--port`, `--no-browser`, `--synthetic`, `--model`, `--cam-pitch`, `--smooth`, `--nose-down`) 외의
옵션은 `posture_geometry_probe.py`에 그대로 전달됩니다. `--views`를 주지 않으면 기존처럼 측면 아바타 창(`side`)이 켜집니다.
`models/X_Bot.fbx`가 없으면 실행 시 콘솔과 페이지에 이유가 표시되며, 자동으로 내려받지 않습니다.
카메라·Python 없이 모델만 확인: `mesh_avatar/web` 폴더에서 `python -m http.server 8000` 후
`http://127.0.0.1:8000/?demo=1`

URL 옵션: `?demo=1` (브라우저 단독 가짜 움직임), `?side=left` (측면에서 얼굴이 왼쪽을 향함),
`?cam_pitch=15` (D455가 아래로 15° 기울어 설치됨; 실행기는 `--cam-pitch 15`),
`?model=passive_marker_man.fbx` (다른 모델 파일), `?head=landmarks` (머리·목을 예전 귀·코 방식으로 비교), `?guide=0` (측면 어깨 기준선 숨김), `?smooth=0.45` / `?nose_down=10` (아래 "선택 시각 보조", 기본 꺼짐)

### 카메라 기울기 보정 (표시 전용)
기본 좌표 변환은 D455 광축이 수평이라고 가정합니다. 카메라가 아래를 내려다보면 반듯한 자세도
그 각도만큼 숙여 보이므로, 설치 각도를 `cam_pitch`(+ = 아래)로 주면 표시 좌표만 회전해 되돌립니다.
브라우저에서 `[` / `]` 1° (Shift 5°), `0` 초기화. 측정 좌표·특징·저장 데이터는 바뀌지 않습니다.
가능하면 수평계/각도기로 잰 설치 각도를 쓰고, 화면이 보기 좋아지는 값으로 고른 경우 그 사실을 기록하세요.

## 동작 방식
1. probe의 명시적 `frame_callback`이 완료된 각 프레임(`ProbeFrame`)을 받아 관절(m, RealSense 좌표), Face Matrix 머리 축,
   frame 번호·timestamp, 그 프레임의 RF 예측(또는 unavailable 이유)을 `/pose`(`mesh-avatar-pose/3`)로 공개
2. 브라우저(three.js)가 좌표를 아바타 좌표로 변환한 뒤 뼈 방향을 맞춤
   - 몸통: hip-mid → shoulder-mid 방향(척추 3단 분배) + 어깨선 비틀림
   - 목: 아바타 얼굴 앞면 점이 아바타 어깨 관절 중점에서 볼 때 **측정된 shoulder-mid → nose 방향**에 오도록 `Neck` 회전
     (머리 회전은 Face Matrix 유지). 기준점은 로드한 모델에서 한 번 계산(얼굴 정중앙 가장 앞 점, 양 어깨 관절 중점) — 사람별 값 없음.
     Face Matrix나 코가 없으면 shoulder-mid → ear-mid(예전 방식)로 대체. HUD `목:`에 표시
   - 측면 화면의 파란 점선: 아바타 어깨 관절 중점을 지나는 수직 기준선(그림 보조, 측정값 아님)
   - 머리 회전: probe가 이미 계산한 Face Matrix 각도 → 머리 축(PyVista Viewer의 `face_matrix_head_axes` 재사용).
     얼굴 미검출 시 ear-mid → nose로 대체. 사용 중인 방식은 HUD `머리:`에 표시
   - 팔: 어깨→팔꿈치, 팔꿈치→손목 (없으면 편안한 자세)
   - 하체: 앉은 자세로 고정(관측하지 않음), 골반은 의자에 고정
3. 일시적 누락은 1초(`HOLD_MS`)간 직전 값 유지. 관절 평활은 기본 꺼짐(아래 참조)

## 선택 시각 보조 (기본 꺼짐)
`VIEWER_3D_HANDOFF_RULES.md` §3-4에 따라 smoothing·중립 오프셋은 기본으로 적용하지 않습니다.
필요할 때만 명시적으로 켜고, 켠 상태의 화면을 측정 결과로 설명하지 않습니다. 화면 HUD에 현재 상태가 표시됩니다.

| 옵션 | URL / 실행기 | 효과 | 주의 |
|---|---|---|---|
| 관절 평활 | `?smooth=0.45` / `--smooth 0.45` | 새 값 비중(0.05~1). 낮을수록 부드럽지만 늦게 따라옴 | 실제 움직임이 지연·축소되어 보임 |
| 고개 중립 보정 | `?nose_down=10` / `--nose-down 10` | 코가 귀보다 아래 있는 각도를 가정해 머리 방향에서 뺌(−30~30°) | 근거 없는 고정값, 사람마다 다름 |

기타 상수(app.js 상단): `HOLD_MS`, `TARGET_HEIGHT_M`.

## 한계
- 하체는 관측하지 않은 고정 자세, 골반 위치는 고정(절대 이동은 표시하지 않음)
- 몸통 기울기는 hip 관절 신뢰도에 의존(책상에 가리면 MediaPipe 추정값)
- 목 위치는 표준 모델(X Bot)의 얼굴·어깨 비율을 기준으로 한 시각화 추정. 실제 사람과 머리 크기·어깨 관절 위치가 달라 중립 자세에서 몇 cm·몇 ° 차이가 날 수 있음(절대값 미검증).
- 실측 어깨 depth는 옷 표면이고 아바타 기준은 관절이라 차이가 남을 수 있음. 손가락/표정 없음

## 모델 에셋 (`VIEWER_3D_HANDOFF_RULES.md` §5)
`mesh_avatar/web/models/`는 `.gitignore`(`models/`)로 **Git에 포함되지 않습니다.** 받는 사람은 같은 파일을 직접 받아 넣어야 합니다.

| 항목 | `passive_marker_man.fbx` | `X_Bot.fbx` (기본) |
|---|---|---|
| 출처 | Adobe Mixamo 캐릭터 "Passive Marker Man" (파일 내부 제작 경로 `...Mixamo\Characters\Passive_marker_man`) | Adobe Mixamo 캐릭터 "X Bot" (내부 경로 `...Mixamo\Characters\X Bot`) |
| 받은 경위 | **미확인** (다운로드 날짜·계정·옵션 기록 없음) | **미확인** |
| 형식 | FBX Binary 7700 | FBX Binary 7700 |
| 크기 | 5,677,696 bytes | 1,750,032 bytes |
| SHA-256 | `e1a3f3c31c4f86e19fa357473a7be2326f32e2c8f0198738b6e85dea4fd00683` | `8ba2af54ec4dc62a736153172d4e5e24647b1b4630b9a36dcf07aa3158e924a8` |
| 단위 | `UnitScaleFactor = 1.0` (FBX 기준 cm). 로드 후 키 1.75 m로 정규화하므로 원본 단위와 무관 | 동일 |
| 좌표계 | Mixamo 표준(Y-up, 캐릭터 정면 +Z). 로드 후 T-pose 기준 회전을 저장해 사용 | 동일 |
| 뼈대 | Mixamo 표준 65개 (`mixamorig:` 접두사) | 동일 |

**라이선스:** Adobe Mixamo 이용 약관 적용. 연구용 사용·논문 그림 삽입·재배포 범위는 **Adobe 약관을 직접 확인해야 하며 아직 확인되지 않았습니다**(§5: Adobe 도구로 받았다는 사실만으로 권한이 보장되지 않음).
원본 FBX 파일 자체는 Git·공개 저장소에 올리지 않습니다.

### 측정 관절 → 모델 뼈 매핑 (표시용)
| 측정 관절 (`/pose`) | 구동하는 뼈 | 방식 | 없을 때 |
|---|---|---|---|
| hip-mid → shoulder-mid | `Spine`, `Spine1`, `Spine2` | 방향을 40% / 80% / 100%로 나눠 적용 | 수직 |
| left/right_shoulder | `Spine2` (비틀림) | 어깨선 방향 맞춤 | 회전 없음 |
| shoulder-mid → nose (+ Face Matrix) | `Neck` | 아바타 얼굴 앞면 점을 측정 방향에 맞춤(3회 반복) | shoulder-mid → ear-mid 방식 |
| shoulder-mid → ear-mid (대체) | `Neck` | 몸통 방향과 70% 섞어 적용 | 회전 없음 |
| Face Matrix 머리 축 (`/pose`의 `head`) | `Head` | 정면·위 축을 그대로 맞춤(좌우·상하·기울기 모두) | ear-mid → nose 방식으로 대체 |
| ear-mid → nose (대체) | `Head` | 얼굴 정면 축을 이 방향으로 | 회전 없음 |
| shoulder → elbow → wrist | `Left/RightArm`, `Left/RightForeArm` | 뼈 방향 맞춤 | 편안히 내린 고정 자세 |
| (관측 안 함) | `UpLeg`, `Leg`, `Foot`, `ToeBase` | 앉은 자세 고정 | — |

모델의 뼈 위치는 **시각화용 추정값**이며 측정된 해부학적 랜드마크가 아닙니다(§3-2, §5).

- `vendor/three`: three.js (MIT)
