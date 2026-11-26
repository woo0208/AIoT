"""
녹화 파일(.db3 / .bag) 확인 스크립트
사용법:  python check_recording.py data\\TEST_r0_20260928_130424.db3

- 컬러/깊이 프레임 수, 녹화 길이 출력
- 중간 지점의 컬러 사진과 깊이 사진을 PNG로 저장 (녹화가 제대로 됐는지 눈으로 확인)
"""
import os
import sys

import cv2
import numpy as np
import pyrealsense2 as rs


def main():
    if len(sys.argv) < 2:
        print("사용법: python check_recording.py <녹화파일 경로>")
        sys.exit(1)
    path = sys.argv[1]
    print(f"파일: {path}  ({os.path.getsize(path) / 1e9:.2f} GB)")

    pipe, cfg = rs.pipeline(), rs.config()
    cfg.enable_device_from_file(path, repeat_playback=False)
    profile = pipe.start(cfg)
    playback = profile.get_device().as_playback()
    playback.set_real_time(False)  # 빠르게 끝까지 읽기
    duration = playback.get_duration().total_seconds()

    n_color = n_depth = 0
    first_ts = last_ts = None
    color_imgs, depth_imgs = [], []
    try:
        while True:
            ok, frames = pipe.try_wait_for_frames(2000)
            if not ok:
                break
            c, d = frames.get_color_frame(), frames.get_depth_frame()
            ts = frames.get_timestamp()
            first_ts = ts if first_ts is None else first_ts
            last_ts = ts
            if c:
                n_color += 1
                if n_color % 15 == 0:  # 약 1초마다 한 장만 보관
                    color_imgs.append(np.asanyarray(c.get_data()).copy())
            if d:
                n_depth += 1
                if n_depth % 15 == 0:
                    depth_imgs.append(np.asanyarray(d.get_data()).copy())
    finally:
        pipe.stop()

    span = (last_ts - first_ts) / 1000 if first_ts else 0
    print(f"녹화 길이(파일 정보): {duration:.1f} 초")
    print(f"프레임 타임스탬프 기준 길이: {span:.1f} 초")
    print(f"컬러 프레임: {n_color}개, 깊이 프레임: {n_depth}개")
    if span > 0:
        print(f"평균 FPS: 컬러 {n_color / span:.1f}, 깊이 {n_depth / span:.1f}")

    base = os.path.splitext(path)[0]
    if color_imgs:
        cv2.imwrite(base + "_check_color.png", color_imgs[len(color_imgs) // 2])
    if depth_imgs:
        d = depth_imgs[len(depth_imgs) // 2]
        cv2.imwrite(base + "_check_depth.png",
                    cv2.applyColorMap(cv2.convertScaleAbs(d, alpha=0.08), cv2.COLORMAP_JET))
    print(f"확인용 사진 저장: {base}_check_color.png / _check_depth.png")
    if n_color == 0 or n_depth == 0:
        print("[문제] 컬러 또는 깊이 프레임이 없습니다. 이 결과를 알려주세요.")
    else:
        print("[정상] 녹화가 제대로 되었습니다.")


if __name__ == "__main__":
    main()
