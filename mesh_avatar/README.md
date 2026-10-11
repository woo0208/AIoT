# Mesh Avatar (표시 전용)

D455 + MediaPipe로 이미 계산된 3D 관절 위치(`GeometryResult.points_3d`)를 받아
리깅된 인체 메시(기본: Mixamo X Bot)를 의자에 앉은 자세로 실시간 구동합니다.
정면(카메라 시점)과 측면을 동시에 보여 줍니다.

> 시각화 전용입니다. 측정값이나 F1/F2 특징, 분류 결과가 아니며 어떤 연구 산출물도 쓰지 않습니다.
> 기존 `posture_geometry_probe.py` / `posture_3d_viewer.py`는 수정하지 않았습니다.

## 실행
```
python run_mesh_avatar.py              # D455 실시간 → 브라우저가 http://127.0.0.1:8765/ 로 열림
python run_mesh_avatar.py --synthetic  # 카메라 없이 가짜 관절로 파이프라인 확인
```
카메라·Python 없이 모델만 확인: `mesh_avatar/web` 폴더에서 `python -m http.server 8000` 후
`http://127.0.0.1:8000/?demo=1`

URL 옵션: `?demo=1` (브라우저 단독 가짜 움직임), `?side=left` (측면에서 얼굴이 왼쪽을 향함),
`?cam_pitch=15` (D455가 아래로 15° 기울어 설치됨; 실행기는 `--cam-pitch 15`),
`?model=passive_marker_man.fbx` (다른 모델 파일), `?smooth=0.45` / `?nose_down=10` (아래 "선택 시각 보조", 기본 꺼짐)

### 카메라 기울기 보정 (표시 전용)
기본 좌표 변환은 D455 광축이 수평이라고 가정합니다. 카메라가 아래를 내려다보면 반듯한 자세도
그 각도만큼 숙여 보이므로, 설치 각도를 `cam_pitch`(+ = 아래)로 주면 표시 좌표만 회전해 되돌립니다.
브라우저에서 `[` / `]` 1° (Shift 5°), `0` 초기화. 측정 좌표·특징·저장 데이터는 바뀌지 않습니다.
가능하면 수평계/각도기로 잰 설치 각도를 쓰고, 화면이 보기 좋아지는 값으로 고른 경우 그 사실을 기록하세요.

## 동작 방식
1. probe 루프의 3D 뷰 호출을 감싸 각 프레임의 관절(m, RealSense 좌표)을 `/pose`로 공개
2. 브라우저(three.js)가 좌표를 아바타 좌표로 변환한 뒤 뼈 방향을 맞춤
   - 몸통: hip-mid → shoulder-mid 방향(척추 3단 분배) + 어깨선 비틀림
   - 목/머리: shoulder-mid → ear-mid, ear-mid → nose
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
- 머리 회전은 pitch 위주, 손가락/표정 없음

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
| shoulder-mid → ear-mid | `Neck` | 몸통 방향과 70% 섞어 적용 | 회전 없음 |
| ear-mid → nose | `Head` | 얼굴 정면 축을 이 방향으로 | 회전 없음 |
| shoulder → elbow → wrist | `Left/RightArm`, `Left/RightForeArm` | 뼈 방향 맞춤 | 편안히 내린 고정 자세 |
| (관측 안 함) | `UpLeg`, `Leg`, `Foot`, `ToeBase` | 앉은 자세 고정 | — |

모델의 뼈 위치는 **시각화용 추정값**이며 측정된 해부학적 랜드마크가 아닙니다(§3-2, §5).

- `vendor/three`: three.js (MIT)
