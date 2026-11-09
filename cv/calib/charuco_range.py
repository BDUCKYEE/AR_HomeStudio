"""ChArUco 검출 거리 시험 (합성): 현재 charuco.yaml 보드를 벽에 붙였다고 보고, 거리 × 정면 대비 각도별 코너 검출 수.

카메라: phone = 4000×3000, f=3000px (12MP 폰 메인 카메라와 비슷), webcam = 1920×1080, 수평 화각 78° 가정.
각 조건마다 방위 4개(좌/우/위/아래로 기울어진 시선)를 렌더링해 검출 코너 수를 센다.

사용: python -m cv.calib.charuco_range [--camera phone webcam]
"""
from __future__ import annotations

import argparse
import tempfile

import cv2
import numpy as np

from cv.calib.charuco import load_charuco
from cv.recon.test_charuco_scale import BOARD_CENTER, look_at, render_views

CAMS = {
    "phone": (4000, 3000, 3000.0),
    "webcam": (1920, 1080, 960 / np.tan(np.deg2rad(39))),
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", nargs="+", default=["phone", "webcam"], choices=list(CAMS))
    ap.add_argument("--dists", type=float, nargs="+", default=[1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0])
    ap.add_argument("--angles", type=float, nargs="+", default=[0, 30, 45, 60])
    a = ap.parse_args()

    spec = load_charuco()
    base = np.array([[1, 0, 0], [0, -1, 0], [0, 0, -1]], float)   # 보드 정자세로 벽(z=0)에 부착, 앞면 +Z
    tb = BOARD_CENTER - base @ spec.center_m
    n_all = (spec.squares_x - 1) * (spec.squares_y - 1)
    rng = np.random.default_rng(0)
    det = spec.make_detector()
    print(f"보드 {spec.squares_x}x{spec.squares_y}, 칸 {spec.square_m * 1000:g}mm, 마커 {spec.marker_m * 1000:g}mm, "
          f"{spec.dictionary}. 값 = 검출 코너 수/{n_all} (방위 4개)")
    for cam in a.camera:
        W, H, f = CAMS[cam]
        K = np.array([[f, 0, W / 2], [0, f, H / 2], [0, 0, 1]])
        print(f"\n[{cam}] {W}x{H}, f={f:.0f}px")
        print("| 거리 (m) | " + " | ".join(f"{t:g}°" for t in a.angles) + " |")
        print("|---:|" + "---|" * len(a.angles))
        for d in a.dists:
            row = []
            for th in a.angles:
                extr = []
                for az in [0, 90, 180, 270]:   # 시선이 기울어지는 방향 (0=오른쪽에서, 90=위에서 ...)
                    t, p = np.deg2rad(th), np.deg2rad(az)
                    off = np.array([np.sin(t) * np.cos(p), np.sin(t) * np.sin(p) * 0.6, np.cos(t)])  # 위/아래는 덜 기울임
                    off /= np.linalg.norm(off)
                    extr.append(look_at(BOARD_CENTER + d * off, BOARD_CENTER))
                with tempfile.TemporaryDirectory() as td:
                    paths = render_views(spec, base, tb, np.stack(extr), K, rng, td)
                    cnt = []
                    for pth in paths:
                        _, ids, _, _ = det.detectBoard(cv2.imread(str(pth), 0))
                        cnt.append(0 if ids is None else len(ids))
                row.append("/".join(str(c) for c in cnt))
            print(f"| {d:.1f} | " + " | ".join(row) + " |", flush=True)


if __name__ == "__main__":
    main()
