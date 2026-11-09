"""ChArUco 월드 좌표계/스케일 자체 시험 (합성 데이터, 벽 부착 보드).

실험실 좌표(바닥 y=0, +Y 위)에서 벽(z=0 평면 근처)에 붙인 보드를 약간 기울여(뒤로 3°, 면 안 회전 2°)
카메라 5대로 렌더링 → 임의 상사변환 G로 'VGGT 월드'를 만든 뒤, charuco_world 결과가
interfaces.md 규약으로 직접 계산한 기대 월드와 같은지 확인한다:
  +Y = 바닥 법선, 원점 = 보드 중심의 바닥 투영, +X = 보드 +X의 바닥 투영, +Z = X×Y, 스케일 = 칸 크기.

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
from cv.recon.scale import charuco_world

IMG_W, IMG_H, F = 4000, 3000, 3000.0   # 12MP 폰과 비슷한 화각
V_W, V_H = 518, 392                    # 'VGGT 해상도'
BOARD_CENTER = np.array([0.4, 1.25, 0.0])   # 실험실 좌표, 보드 중심 높이 1.25m


def look_at(pos, target):
    """실험실(+Y 위) → OpenCV 카메라 [R|t]. 행 = (오른쪽, 아래, 앞)."""
    f = target - pos
    f /= np.linalg.norm(f)
    r = np.cross(f, [0, 1, 0])
    r /= np.linalg.norm(r)
    d = np.cross(f, r)
    R = np.stack([r, d, f])
    return np.hstack([R, (-R @ pos)[:, None]])


def board_pose(spec):
    """보드 좌표(m) → 실험실. 앞면이 +Z, 보드 +X ≈ +X, 보드 +Y ≈ -Y(아래)."""
    base = np.array([[1, 0, 0], [0, -1, 0], [0, 0, -1]], float)   # 열 = 보드 X, Y, Z 의 실험실 방향
    tilt_back = cv2.Rodrigues(np.array([np.deg2rad(-3), 0, 0]))[0]  # X축 기준 기울임
    roll = cv2.Rodrigues(np.array([0, 0, np.deg2rad(2)]))[0]        # 벽 법선 기준 면 안 회전
    Rb = tilt_back @ roll @ base
    tb = BOARD_CENTER - Rb @ spec.center_m
    return Rb, tb


def expected_world(Rb):
    """규약대로 실험실 → 월드 (스케일 1). 바닥 법선 = 실험실 +Y."""
    n = np.array([0.0, 1.0, 0.0])
    o = BOARD_CENTER - (BOARD_CENTER @ n) * n
    x = Rb[:, 0] - (Rb[:, 0] @ n) * n
    x /= np.linalg.norm(x)
    R = np.stack([x, n, np.cross(x, n)])
    return Sim3(1.0, R, -R @ o)


def render_views(spec, Rb, tb, extr, K, rng, td):
    """보드를 각 카메라로 렌더링해 파일로 저장. 2배 해상도로 그린 뒤 면적 평균 축소 (경계를 실제 사진처럼)."""
    ppm = 3000  # 보드 이미지 px/m
    nx, ny = spec.squares_x, spec.squares_y
    bimg = spec.make_board().generateImage((round(nx * spec.square_m * ppm), round(ny * spec.square_m * ppm)), 0, 1)
    pad = 60
    bimg = cv2.copyMakeBorder(bimg, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=255)
    hb, wb = bimg.shape
    src = np.float32([[0, 0], [wb, 0], [wb, hb], [0, hb]])
    K2 = np.diag([2.0, 2.0, 1.0]) @ K + np.array([[0, 0, 0.5], [0, 0, 0.5], [0, 0, 0]])  # u2 = 2u + 0.5
    W, H = int(K[0, 2] * 2), int(K[1, 2] * 2)
    paths = []
    for i, E in enumerate(extr):
        dst = []
        for u, v in src:   # 보드 이미지 연속 좌표 (픽셀 경계 = 정수-0.5)
            bp = np.array([(u - 0.5 + 0.5 - pad) / ppm, (v - 0.5 + 0.5 - pad) / ppm, 0.0])
            Xc = E[:, :3] @ (Rb @ bp + tb) + E[:, 3]
            x = K2 @ Xc
            dst.append(x[:2] / x[2])
        Hm = cv2.getPerspectiveTransform(src - 0.5, np.float32(dst))
        img = cv2.warpPerspective(bimg, Hm, (2 * W, 2 * H), flags=cv2.INTER_LINEAR, borderValue=150)
        img = cv2.resize(img, (W, H), interpolation=cv2.INTER_AREA)
        img = cv2.GaussianBlur(img, (0, 0), 0.7)
        img = np.clip(img + rng.normal(0, 3, img.shape), 0, 255).astype(np.uint8)
        p = Path(td) / f"syn_{i}.png"
        cv2.imwrite(str(p), img)
        paths.append(p)
    return paths


def main() -> None:
    spec = load_charuco()
    cfg = load_yaml("recon.yaml")["scale"]
    Rb, tb = board_pose(spec)
    K = np.array([[F, 0, IMG_W / 2], [0, F, IMG_H / 2], [0, 0, 1]])
    # 보드 앞 1.2~2.0m, 높이 1.0~1.6m
    poses = [np.array(p, float) for p in [(0.4, 1.4, 1.3), (-0.6, 1.2, 1.4), (1.3, 1.5, 1.2), (0.0, 1.0, 1.9),
                                          (0.9, 1.6, 1.7)]]
    extr_true = np.stack([look_at(p, BOARD_CENTER + np.array([0.02, -0.03, 0])) for p in poses])
    sx, sy = V_W / IMG_W, V_H / IMG_H
    Kv = np.diag([sx, sy, 1]) @ K
    rng = np.random.default_rng(1)

    with tempfile.TemporaryDirectory() as td:
        paths = render_views(spec, Rb, tb, extr_true, K, rng, td)
        metas = [dict(orig_wh=(IMG_W, IMG_H), scale=(sx, sy), offset=(0.0, 0.0), valid=(0, 0, V_W, V_H))
                 for _ in paths]
        # 임의 'VGGT 월드': X_v = G(X_lab)
        a = rng.normal(size=3)
        a /= np.linalg.norm(a)
        G = Sim3(0.37, cv2.Rodrigues(a * 1.1)[0], np.array([0.3, -0.2, 0.5]))
        extr_v = extrinsic_after(extr_true, G)[:, :3, :]
        intr_v = np.repeat(Kv[None], len(poses), 0)
        # find_floor 가 낼 형태의 바닥 정렬 (스케일 1, 행1 = VGGT 기준 바닥 법선, t[1] = d). yaw/수평 위치는 임의
        R0 = rot_y(0.8) @ G.R.T
        T_floor = Sim3(1.0, R0, -R0 @ G.t + np.array([1.3, 0.0, -0.7]))
        T, info = charuco_world(paths, metas, extr_v, intr_v, np.zeros((len(poses), V_H, V_W)), T_floor, spec, cfg)

    print("info:", {k: (round(v, 4) if isinstance(v, float) else v) for k, v in info.items()})
    assert T is not None, "ChArUco 실패"
    final = G.then(T)               # 실험실 → 최종 월드
    exp = expected_world(Rb)        # 실험실 → 기대 월드
    err_s = abs(final.s - 1)
    dR = final.R @ exp.R.T
    err_R = np.rad2deg(np.arccos(np.clip((np.trace(dR) - 1) / 2, -1, 1)))
    err_t = np.linalg.norm(final.t - exp.t)
    err_h = abs(info["board_center_height_m"] - BOARD_CENTER[1])
    print(f"스케일 오차 {err_s:.3%}, 회전 오차 {err_R:.3f}°, 원점 오차 {err_t * 1000:.2f} mm, "
          f"보드 중심 높이 {info['board_center_height_m']:.4f} m (참 {BOARD_CENTER[1]}), z_into_room={info['z_into_room']}")
    # 알려진 한계: 합성 영상에서 스케일이 약 -0.4% 치우침 (코너 검출 단계, 원인 미확정)
    ok = err_s < 0.01 and err_R < 0.5 and err_t < 0.01 and err_h < 0.01 and info["z_into_room"]
    print("결과:", "통과" if ok else "실패")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
