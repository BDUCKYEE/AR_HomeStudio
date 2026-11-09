"""스케일 보정과 월드 좌표계 결정.

ChArUco (charuco_world): docs/interfaces.md 1절 규약 (2026-11-10)
  +Y(위) = 바닥 평면(RANSAC) 법선, 바닥 y=0
  원점   = 보드 중심을 바닥 평면에 수직으로 내린 점
  +X     = 보드 +X(인쇄물 가로 방향)를 바닥 평면에 투영한 방향
  +Z     = X × Y (오른손). 벽에 바로 붙인 보드면 보드 앞면(방 안쪽)을 향한다
  스케일 = 보드 칸 크기 (charuco.yaml 실측값)
  보드 좌표계(OpenCV): 원점 보드 왼쪽 위 모서리, +X 오른쪽, +Y 아래(인쇄 방향), +Z 보드 안쪽(앞면의 반대)

대체 방법 (room_size / cam_height / factor): 입력은 바닥 정렬 + 벽 방향 yaw 정렬된 점 (+Y 위, 바닥 y=0, 단위 임의),
반환 Sim3 는 "바닥 정렬 좌표 → 월드(미터)", 원점은 바닥 범위 중심.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from cv.calib.charuco import CharucoSpec
from cv.recon.geometry import Sim3, camera_centers, triangulate, umeyama_3d
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


def _board_corners_vggt(paths, metas, extr, intr, depth, spec, cfg, info) -> tuple[list, np.ndarray]:
    """코너 검출 → 2개 이상 시점이면 DLT 삼각측량, 부족하면 깊이 맵 조회. VGGT 월드 좌표 반환."""
    obs = detect_charuco(paths, metas, spec)
    info.update(views_with_board=len({i for v in obs.values() for i, _ in v}), corners_seen=len(obs))
    if not obs:
        return [], np.zeros((0, 3))
    Pm = [intr[i] @ extr[i] for i in range(len(extr))]
    ids, X, reproj = [], [], []
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
    info["mode"] = "triangulation"
    if reproj:
        info["reproj_px_mean"] = float(np.mean(reproj))
    if len(ids) < cfg["charuco_min_corners"]:
        info["mode"] = "depth-lookup"   # 단일 시점: 깊이 맵 조회 (정밀도 낮음)
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
                    pts.append(R.T @ (pc - t))     # OpenCV 카메라 → VGGT 월드
            if pts:
                ids.append(cid)
                X.append(np.median(pts, 0))
    return ids, np.asarray(X).reshape(-1, 3)


def charuco_world(paths, metas, extr, intr, depth, T_floor: Sim3, spec: CharucoSpec, cfg: dict
                  ) -> tuple[Sim3 | None, dict]:
    """VGGT 월드 → 월드(glTF, 미터) 변환을 보드 + 바닥 평면으로 결정 (모듈 docstring 규약).

    T_floor: find_floor 결과 (행 1 = 바닥 법선 n(위), t[1] = d, 바닥: n·p + d = 0, VGGT 단위).
    """
    info = {"method": "charuco", "square_mm": spec.square_m * 1000, "marker_mm": spec.marker_m * 1000,
            "board_size_measured": spec.measured}
    ids, X = _board_corners_vggt(paths, metas, extr, intr, depth, spec, cfg, info)
    info["corners_used"] = len(ids)
    if len(ids) < cfg["charuco_min_corners"]:
        info["fail"] = f"사용 가능한 코너 {len(ids)} < {cfg['charuco_min_corners']}" if ids or info.get("corners_seen") \
            else "보드 미검출"
        return None, info

    obj = spec.make_board().getChessboardCorners()[np.asarray(ids)]   # 보드 좌표 (m)
    s, Rb, tb = umeyama_3d(obj, X)            # X ≈ s Rb obj + tb  (보드 m → VGGT 단위)
    res = (s * obj @ Rb.T + tb - X) / s       # 미터
    rms_mm = float(np.sqrt((res ** 2).sum(1).mean()) * 1000)
    bz = Rb[:, 2]
    out_of_plane_mm = float(np.sqrt(np.mean((res @ bz) ** 2)) * 1000)   # 휨/구김 정도
    info.update(scale_units_per_m=s, rms_mm=rms_mm, out_of_plane_rms_mm=out_of_plane_mm)
    if rms_mm > cfg["charuco_max_rms_mm"]:
        info["fail"] = f"보드 정합 잔차 {rms_mm:.1f}mm > {cfg['charuco_max_rms_mm']}mm"
        return None, info

    n, d = T_floor.R[1].copy(), float(T_floor.t[1])     # 바닥 법선(위), 바닥: n·p + d = 0
    c = s * Rb @ spec.center_m + tb                      # 보드 중심 (VGGT)
    h_units = float(n @ c + d)
    o = c - h_units * n                                  # 바닥에 내린 점 = 월드 원점
    bx = Rb[:, 0]
    x = bx - (bx @ n) * n
    if np.linalg.norm(x) < 0.5:
        info["fail"] = f"보드 +X가 거의 수직 (|투영|={np.linalg.norm(x):.2f}) — 보드를 세로(인쇄 방향 그대로)로 붙였는지 확인"
        return None, info
    x /= np.linalg.norm(x)
    z = np.cross(x, n)
    R = np.stack([x, n, z])                              # 행 = 월드 X, Y, Z (VGGT 기준), det=+1
    T = Sim3(1.0 / s, R, -(1.0 / s) * R @ o)             # X_w = (1/s) R (X_v - o)

    front = -bz                                          # 보드 앞면 방향 (방 안쪽)
    cams_w = T.apply(camera_centers(extr))
    info.update(
        board_center_height_m=h_units / s,
        board_x_tilt_from_floor_deg=float(np.rad2deg(np.arcsin(np.clip(abs(bx @ n), 0, 1)))),
        board_normal_vs_floor_deg=float(np.rad2deg(np.arccos(np.clip(abs(bz @ n), 0, 1)))),  # 벽 부착이면 ≈90
        z_dot_board_front=float(z @ front),
        cameras_on_plus_z_frac=float(np.mean(cams_w[:, 2] > 0)),
    )
    info["z_into_room"] = bool(info["cameras_on_plus_z_frac"] > 0.5 and
                               (info["z_dot_board_front"] > 0.5 or info["board_normal_vs_floor_deg"] < 45))
    return T, info


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
