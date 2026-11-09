"""스케일(및 수평 위치/방향) 보정.

입력 점들은 이미 바닥 정렬된 좌표 (+Y 위, 바닥 y=0, 단위 임의)에 있다고 가정한다.
각 함수는 (Sim3, info) 를 반환하며, Sim3는 "바닥 정렬 좌표 → 최종 월드(glTF, 미터)" 변환이다.

ChArUco 보드 → 월드 축 대응 (잠정, interfaces.md 에서 확정 예정):
  보드 좌표계(OpenCV): 원점 보드 왼쪽 위, +X 오른쪽, +Y 아래(인쇄 방향), +Z 보드 안쪽(=바닥 아래)
  월드(glTF):  X = 보드 +X,  Y(위) = 보드 -Z,  Z = 보드 +Y,  원점 = 보드 중심
  (행렬 [[1,0,0],[0,0,-1],[0,1,0]], det=+1, 보드가 바닥에 앞면이 위로 놓인 경우)
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from cv.calib.charuco import CharucoSpec
from cv.recon.geometry import Sim3, rot_y, triangulate, umeyama_2d
from cv.recon.vggt_infer import open_rgb

DETECT_MAX_SIDE = 4000


def detect_charuco(paths: list[Path], metas: list[dict], spec: CharucoSpec) -> dict[int, list[tuple[int, np.ndarray]]]:
    """이미지별 ChArUco 코너 검출 → {corner_id: [(이미지 index, VGGT 전처리 픽셀 uv)]}."""
    det = spec.make_detector()
    obs: dict[int, list] = {}
    for i, (p, m) in enumerate(zip(paths, metas)):
        g = np.asarray(open_rgb(p).convert("L"))
        f = min(1.0, DETECT_MAX_SIDE / max(g.shape))
        if f < 1.0:
            g = cv2.resize(g, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
        corners, ids, _, _ = det.detectBoard(g)
        if ids is None or len(ids) < 4:
            continue
        uv = corners.reshape(-1, 2) / f                       # 원본 픽셀 (EXIF 회전 후)
        uv = uv * np.array(m["scale"]) + np.array(m["offset"])  # → VGGT 전처리 픽셀
        for cid, x in zip(ids.ravel(), uv):
            obs.setdefault(int(cid), []).append((i, x))
    return obs


def charuco_scale(paths, metas, extr, intr, depth, T_align: Sim3, spec: CharucoSpec, cfg: dict) -> tuple[Sim3 | None, dict]:
    """ChArUco 코너를 다시점 삼각측량(VGGT 카메라) → 바닥 정렬 좌표 → 보드 실측 좌표와 2D 상사 정합."""
    obs = detect_charuco(paths, metas, spec)
    views = sorted({i for v in obs.values() for i, _ in v})
    info = {"method": "charuco", "views_with_board": len(views), "corners_seen": len(obs),
            "square_mm": spec.square_m * 1000, "board_size_measured": spec.measured}
    if not obs:
        info["fail"] = "보드 미검출"
        return None, info
    Pm = [intr[i] @ extr[i] for i in range(len(extr))]
    ids, X = [], []
    reproj = []
    for cid, lst in obs.items():
        if len(lst) < 2:
            continue
        Xc = triangulate([Pm[i] for i, _ in lst], [uv for _, uv in lst])
        errs = []
        for i, uv in lst:
            h = Pm[i] @ np.append(Xc, 1)
            errs.append(np.linalg.norm(h[:2] / h[2] - uv) if h[2] > 0 else np.inf)
        if np.max(errs) < 3.0:   # VGGT 해상도 기준 px
            ids.append(cid)
            X.append(Xc)
            reproj.append(float(np.mean(errs)))
    mode = "triangulation"
    if len(ids) < cfg["charuco_min_corners"]:
        # 단일 시점: 깊이 맵 조회로 대체 (정밀도 낮음)
        mode = "depth-lookup"
        ids, X = [], []
        for cid, lst in obs.items():
            pts = []
            for i, uv in lst:
                u, v = int(round(uv[0])), int(round(uv[1]))
                H, W = depth[i].shape
                if 0 <= u < W and 0 <= v < H and depth[i][v, u] > 0:
                    z = depth[i][v, u]
                    K = intr[i]
                    pc = np.array([(uv[0] - K[0, 2]) / K[0, 0] * z, (uv[1] - K[1, 2]) / K[1, 1] * z, z])
                    R, t = extr[i][:, :3], extr[i][:, 3]
                    pts.append(R.T @ (pc - t))
            if pts:
                ids.append(cid)
                X.append(np.median(pts, 0))
    info["mode"] = mode
    info["corners_used"] = len(ids)
    if reproj and mode == "triangulation":
        info["reproj_px_mean"] = float(np.mean(reproj))
    if len(ids) < cfg["charuco_min_corners"]:
        info["fail"] = f"사용 가능한 코너 {len(ids)} < {cfg['charuco_min_corners']}"
        return None, info

    q = T_align.apply(np.asarray(X))                               # 바닥 정렬 좌표
    obj = spec.make_board().getChessboardCorners()[np.asarray(ids)]  # 보드 좌표 (m), z=0
    b = obj[:, :2] - spec.center_m[:2]                             # 보드 중심 원점, (bx, by) → 월드 (X, Z)
    s, R2, t2 = umeyama_2d(q[:, [0, 2]], b)
    res = (s * q[:, [0, 2]] @ R2.T + t2) - b
    rms_mm = float(np.sqrt((res ** 2).sum(1).mean()) * 1000)
    info.update(scale=s, rms_mm=rms_mm, board_height_m=float(np.mean(s * q[:, 1])))
    if rms_mm > cfg["charuco_max_rms_mm"]:
        info["fail"] = f"보드 정합 잔차 {rms_mm:.1f}mm > {cfg['charuco_max_rms_mm']}mm"
        return None, info
    alpha = float(np.arctan2(R2[1, 0], R2[0, 0]))   # R2 = [[c,-s],[s,c]] on (x,z) == rot_y(alpha)
    return Sim3(s, rot_y(alpha), np.array([t2[0], 0.0, t2[1]])), info


def _center_xz(Q: np.ndarray, s: float) -> Sim3:
    lo, hi = np.percentile(Q[:, [0, 2]], [1, 99], axis=0)
    c = (lo + hi) / 2
    return Sim3(s, np.eye(3), -s * np.array([c[0], 0.0, c[1]]))


def room_size_scale(Q: np.ndarray, size_m: tuple[float, float]) -> tuple[Sim3, dict]:
    """맨해튼 정렬된 점의 가로/세로 범위(1~99 백분위)를 실측 방 크기에 맞춤. 원점 = 바닥 범위 중심."""
    lo, hi = np.percentile(Q[:, [0, 2]], [1, 99], axis=0)
    ext = hi - lo
    s_long = max(size_m) / ext.max()
    s_short = min(size_m) / ext.min()
    s = (s_long + s_short) / 2
    return _center_xz(Q, s), {"method": "room-size", "room_size_m": list(size_m),
                              "extent_units": ext.tolist(), "scale": s,
                              "long_vs_short_scale_ratio": float(s_long / s_short)}


def cam_height_scale(Q: np.ndarray, cam_y: np.ndarray, height_m: float) -> tuple[Sim3, dict]:
    s = height_m / float(np.median(cam_y))
    return _center_xz(Q, s), {"method": "camera-height", "camera_height_m": height_m, "scale": s}


def factor_scale(Q: np.ndarray, s: float) -> tuple[Sim3, dict]:
    return _center_xz(Q, s), {"method": "factor", "scale": s}
