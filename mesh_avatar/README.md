# Mesh Avatar (표시 전용)

D455 + MediaPipe로 이미 계산된 3D 관절 위치(`GeometryResult.points_3d`)를 받아
리깅된 인체 메시(Mixamo X Bot)를 의자에 앉은 자세로 실시간 구동합니다.
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
`?cam_pitch=15` (D455가 아래로 15° 기울어 설치됨; 실행기는 `--cam-pitch 15`)

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
3. 관절 지터는 지수 평활(`SMOOTH`)로, 일시적 누락은 1초간 직전 값 유지

## 튜닝 (app.js 상단, 시각용)
`SMOOTH`, `HOLD_MS`, `NEUTRAL_NOSE_DOWN_DEG`(중립 머리가 숙여 보이면 조정), `TARGET_HEIGHT_M`

## 한계
- 하체는 관측하지 않은 고정 자세, 골반 위치는 고정(절대 이동은 표시하지 않음)
- 몸통 기울기는 hip 관절 신뢰도에 의존(책상에 가리면 MediaPipe 추정값)
- 머리 회전은 pitch 위주, 손가락/표정 없음

## 라이선스
- `models/X_Bot.fbx`: Adobe Mixamo 기본 캐릭터 (Adobe 약관 확인)
- `vendor/three`: three.js (MIT)
