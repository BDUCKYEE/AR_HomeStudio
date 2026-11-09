"""ChArUco 스케일 보정 자체 시험 (합성 데이터).

바닥(y=0)의 보드를 알려진 카메라 5대로 렌더링 → 임의 상사변환 G로 'VGGT 월드'를 만들고
바닥 정렬은 스케일/yaw/수평 위치를 일부러 틀리게 준 뒤, charuco_scale 이 미터 스케일과
보드 중심 원점, 축(보드 +X → 월드 +X, 보드 +Y → 월드 +Z)을 복원하는지 확인한다.

사용: python -m cv.recon.test_charuco_scale
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import cv2
import numpy as np

from cv.calib.charuco import load_charuco
from cv.common.config import load_yaml
from cv.recon.geometry import Sim3, extrinsic_after, rot_y
from cv.recon.scale import charuco_scale

IMG_W, IMG_H, F = 4000, 3000, 3000.0   # 12MP 폰과 비슷한 화각
V_W, V_H = 518, 392   # 'VGGT 해상도'


def look_at(pos, target):
    """월드(glTF, +Y 위) → OpenCV 카메라 [R|t]. 행 = (오른쪽, 아래, 앞)."""
    f = target - pos
    f /= np.linalg.norm(f)
    r = np.cross(f, [0, 1, 0])
    r /= np.linalg.norm(r)
    d = np.cross(f, r)
    R = np.stack([r, d, f])
    return np.hstack([R, (-R @ pos)[:, None]])


def main() -> None:
    spec = load_charuco()
    cfg = load_yaml("recon.yaml")["scale"]
    ppm = 3000  # 보드 이미지 px/m
    nx, ny = spec.squares_x, spec.squares_y
    bimg = spec.make_board().generateImage((round(nx * spec.square_m * ppm), round(ny * spec.square_m * ppm)), 0, 1)
    pad = 40
    bimg = cv2.copyMakeBorder(bimg, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=255)
    cx, cy = spec.center_m[:2]

    def board_px_to_world(u, v):  # 보드 이미지 연속 좌표(픽셀 경계 = 정수-0.5) → 월드 (X, 0, Z)
        bx, by = (u + 0.5 - pad) / ppm, (v + 0.5 - pad) / ppm
        return np.array([bx - cx, 0.0, by - cy])

    K = np.array([[F, 0, IMG_W / 2], [0, F, IMG_H / 2], [0, 0, 1]])
    # 보드 근접 사진 (카메라-보드 0.9~1.5m, 권장 촬영 방식). 2m 이상이면 12MP 폰에서도 검출 실패
    poses = [np.array(p, float) for p in [(0.6, 0.9, 0.6), (-0.7, 1.0, 0.5), (0.1, 1.1, 0.9), (0.9, 0.8, -0.4),
                                          (-0.4, 1.2, -0.7)]]
    extr_true = np.stack([look_at(p, np.array([0.05, 0.0, -0.03])) for p in poses])
    sx, sy = V_W / IMG_W, V_H / IMG_H
    Kv = np.diag([sx, sy, 1]) @ K

    rng = np.random.default_rng(1)
    with tempfile.TemporaryDirectory() as td:
        paths, metas = [], []
        hb, wb = bimg.shape
        src = np.float32([[0, 0], [wb, 0], [wb, hb], [0, hb]])
        for i, E in enumerate(extr_true):
            # 실제 사진처럼 경계가 부드럽도록 2배 해상도로 그린 뒤 면적 평균 축소
            # (픽셀 중심 규약: u2 = 2u + 0.5). 이진 경계를 그대로 쓰면 코너 검출이 ~0.6px/칸 안쪽으로 치우침
            K2 = np.diag([2.0, 2.0, 1.0]) @ K + np.array([[0, 0, 0.5], [0, 0, 0.5], [0, 0, 0]])
            dst = []
            for u, v in src:
                Xc = E[:, :3] @ board_px_to_world(u - 0.5, v - 0.5) + E[:, 3]   # 보드 이미지 픽셀 경계
                x = K2 @ Xc
                dst.append(x[:2] / x[2])
            Hm = cv2.getPerspectiveTransform(src - 0.5, np.float32(dst))
            img = cv2.warpPerspective(bimg, Hm, (2 * IMG_W, 2 * IMG_H), flags=cv2.INTER_LINEAR, borderValue=150)
            img = cv2.resize(img, (IMG_W, IMG_H), interpolation=cv2.INTER_AREA)
            img = cv2.GaussianBlur(img, (0, 0), 0.7)
            img = np.clip(img + rng.normal(0, 3, img.shape), 0, 255).astype(np.uint8)
            p = Path(td) / f"syn_{i}.png"
            cv2.imwrite(str(p), img)
            paths.append(p)
            metas.append(dict(orig_wh=(IMG_W, IMG_H), scale=(sx, sy), offset=(0.0, 0.0), valid=(0, 0, V_W, V_H)))

        # 임의 'VGGT 월드': X_v = G(X_true)
        a = rng.normal(size=3)
        a /= np.linalg.norm(a)
        G = Sim3(0.37, cv2.Rodrigues(a * 1.1)[0], np.array([0.3, -0.2, 0.5]))
        extr_v = extrinsic_after(extr_true, G)[:, :3, :]
        intr_v = np.repeat(Kv[None], len(poses), 0)
        Ginv = Sim3(1 / G.s, G.R.T, -G.R.T @ G.t / G.s)
        # 바닥 정렬은 맞지만 스케일/yaw/수평 위치는 틀린 상태
        T_align = Ginv.then(Sim3(2.7, rot_y(0.8), np.array([1.3, 0.0, -0.7])))
        S3, info = charuco_scale(paths, metas, extr_v, intr_v, np.zeros((len(poses), V_H, V_W)), T_align, spec, cfg)

    print("info:", {k: (round(v, 4) if isinstance(v, float) else v) for k, v in info.items()})
    assert S3 is not None, "ChArUco 스케일 실패"
    final = G.then(T_align).then(S3)   # 참 월드 → 최종 월드, 항등이어야 함
    err_s = abs(final.s - 1)
    err_R = np.rad2deg(np.arccos(np.clip((np.trace(final.R) - 1) / 2, -1, 1)))
    err_t = np.linalg.norm(final.t)
    print(f"스케일 오차 {err_s:.3%}, 회전 오차 {err_R:.3f}°, 원점 오차 {err_t * 1000:.2f} mm")
    # 알려진 한계: 합성 영상에서 스케일이 약 -0.43% 치우침 (보드가 작게 복원). 코너 검출 단계에서 생기며
    # cornerSubPix 창 크기로는 줄지 않음. 원인 미확정. 3.3m 기준 약 1.4cm로 VGGT 깊이 오차보다 작음
    ok = err_s < 0.01 and err_R < 0.5 and err_t < 0.005   # 1%, 0.5°, 5mm
    print("결과:", "통과" if ok else "실패")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
