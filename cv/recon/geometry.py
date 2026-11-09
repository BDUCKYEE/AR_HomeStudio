"""기하 유틸: 상사변환, 바닥 RANSAC, 맨해튼 yaw, 삼각측량, Umeyama.

좌표계 표기
- VGGT 월드: 첫 카메라의 OpenCV 카메라 좌표계 (x 오른쪽, y 아래, z 앞), 단위 임의
- 월드(glTF): 오른손, +Y 위, 미터, 바닥 y=0 (docs/interfaces.md)
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import open3d as o3d


@dataclass
class Sim3:
    """X' = s * R @ X + t  (R은 det=+1 회전)."""
    s: float = 1.0
    R: np.ndarray = field(default_factory=lambda: np.eye(3))
    t: np.ndarray = field(default_factory=lambda: np.zeros(3))

    def apply(self, X: np.ndarray) -> np.ndarray:
        return self.s * X @ self.R.T + self.t

    def then(self, other: "Sim3") -> "Sim3":
        """self 다음에 other 적용."""
        return Sim3(other.s * self.s, other.R @ self.R, other.s * other.R @ self.t + other.t)

    def to_dict(self) -> dict:
        return {"s": float(self.s), "R": self.R.tolist(), "t": self.t.tolist()}


def camera_centers(extr: np.ndarray) -> np.ndarray:
    """extr (S,3,4) camera-from-world → 카메라 중심 (S,3) = -R^T t."""
    R, t = extr[:, :, :3], extr[:, :, 3]
    return -np.einsum("sji,sj->si", R, t)


def extrinsic_after(extr: np.ndarray, T: Sim3) -> np.ndarray:
    """VGGT camera-from-world (S,3,4) → 변환된 월드 기준 4x4 camera-from-world (카메라 축은 OpenCV, 단위는 T.s 배).

    X_c' = s X_c = R_c R^T (X_w - t) + s t_c
    """
    out = np.tile(np.eye(4), (len(extr), 1, 1))
    for i, E in enumerate(extr):
        Rc, tc = E[:, :3], E[:, 3]
        Rn = Rc @ T.R.T
        out[i, :3, :3] = Rn
        out[i, :3, 3] = T.s * tc - Rn @ T.t
    return out


def rot_y(alpha: float) -> np.ndarray:
    """XZ 평면에서 atan2(z, x) 각을 alpha 만큼 증가시키는 Y축 회전 (det=+1)."""
    c, s = np.cos(alpha), np.sin(alpha)
    return np.array([[c, 0, -s], [0, 1, 0], [s, 0, c]])


@dataclass
class FloorResult:
    T: Sim3            # VGGT 월드 → 바닥 정렬 (+Y = 바닥 법선 위, 바닥 y=0), 스케일 1
    method: str        # "ransac" | "lowest-points"
    inlier_frac: float
    tilt_deg: float    # 바닥 법선과 카메라 평균 아래 방향(반대) 사이 각
    candidates: list


def find_floor(P: np.ndarray, extr: np.ndarray, cfg: dict, unit: float, seed: int = 0) -> FloorResult:
    """바닥 평면 RANSAC.

    P: VGGT 월드 점 (N,3). unit: 장면 단위(중앙값 깊이). 카메라 y축(아래)의 평균을 중력 방향 힌트로 쓴다.
    수평면 점(법선 기준)만 모아 평면을 반복 추출하고, 후보 = 법선이 아래 방향과 max_tilt 이내 &
    인라이어 비율(수평면 점 대비) ≥ min_inlier_frac & 카메라들이 평면 위쪽. 그중 가장 낮은 평면(침대/책상 위 제외).
    """
    rng = np.random.default_rng(seed)
    if len(P) > 200_000:
        P = P[rng.choice(len(P), 200_000, replace=False)]
    C = camera_centers(extr)
    down = extr[:, 1, :3].mean(0)      # 카메라 +y(아래)의 월드 방향 = R의 2번째 행
    down /= np.linalg.norm(down)
    cos_tilt = np.cos(np.deg2rad(cfg["max_tilt_deg"]))
    # 수평면 점만 RANSAC (벽이 반복 선택되는 것 방지): 법선이 아래 방향과 max_tilt 이내
    pcd_all = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(P))
    pcd_all.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=0.04 * unit, max_nn=30))
    horiz = np.abs(np.asarray(pcd_all.normals) @ down) > cos_tilt
    Ph = P[horiz]
    rest = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(Ph))
    N = len(Ph)
    cands = []
    for _ in range(cfg["max_planes"]):
        if len(rest.points) < 500:
            break
        o3d.utility.random.seed(int(rng.integers(1 << 30)))
        (a, b, c, d), inl = rest.segment_plane(cfg["ransac_dist_rel"] * unit, 3, 2000)
        n = np.array([a, b, c])
        nn = np.linalg.norm(n)
        n, d = n / nn, d / nn
        side = C @ n + d
        if np.median(side) < 0:          # 법선을 카메라 쪽(위)으로
            n, d, side = -n, -d, -side
        frac = len(inl) / max(N, 1)
        is_floor = (n @ down) < -cos_tilt and frac >= cfg["min_inlier_frac"] and np.mean(side > 0) > 0.9
        cands.append(dict(n=n, d=float(d), frac=frac, cam_height=float(np.median(side)), floor_like=bool(is_floor)))
        rest = rest.select_by_index(inl, invert=True)

    floors = [c for c in cands if c["floor_like"]]
    if floors:
        best = max(floors, key=lambda c: c["cam_height"])        # 가장 낮은(카메라에서 먼) 수평면
        n, d, frac, method = best["n"], best["d"], best["frac"], "ransac"
    else:
        n = -down
        h = P @ n
        d = -float(np.percentile(h, 2))
        frac, method = 0.0, "lowest-points"
    # 회전: 행 = 새 축 (X, Y=n, Z=X×Y). X는 첫 카메라 x축을 바닥에 투영
    x0 = extr[0, 0, :3] - (extr[0, 0, :3] @ n) * n
    x0 /= np.linalg.norm(x0)
    z0 = np.cross(x0, n)
    R = np.stack([x0, n, z0])
    T = Sim3(1.0, R, np.array([0.0, d, 0.0]))   # y' = n·p + d
    tilt = float(np.rad2deg(np.arccos(np.clip(-(n @ down), -1, 1))))
    for c in cands:
        c["n"] = c["n"].tolist()
    return FloorResult(T, method, frac, tilt, cands)


def manhattan_yaw(P: np.ndarray, unit: float, seed: int = 0) -> float:
    """바닥 정렬된 점 (+Y 위)에서 벽 법선의 지배 방향 각(라디안, [-pi/4, pi/4))."""
    rng = np.random.default_rng(seed)
    if len(P) > 150_000:
        P = P[rng.choice(len(P), 150_000, replace=False)]
    pcd = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(P))
    pcd.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=0.05 * unit, max_nn=30))
    n = np.asarray(pcd.normals)
    wall = np.abs(n[:, 1]) < 0.3
    if wall.sum() < 500:
        return 0.0
    ang = np.arctan2(n[wall, 2], n[wall, 0])
    w = np.hypot(n[wall, 0], n[wall, 2])
    m = np.angle(np.sum(w * np.exp(4j * ang)))
    return float(m / 4)


def umeyama_2d(src: np.ndarray, dst: np.ndarray) -> tuple[float, np.ndarray, np.ndarray]:
    """dst ≈ s R src + t (2D, 반사 없음). 반환 s, R(2x2), t."""
    ms, md = src.mean(0), dst.mean(0)
    a, b = src - ms, dst - md
    H = b.T @ a / len(src)
    U, S, Vt = np.linalg.svd(H)
    D = np.diag([1.0, np.sign(np.linalg.det(U @ Vt))])
    R = U @ D @ Vt
    s = float(np.trace(np.diag(S) @ D) / (a ** 2).sum(1).mean())
    return s, R, md - s * R @ ms


def triangulate(Ps: list[np.ndarray], uvs: list[np.ndarray]) -> np.ndarray:
    """DLT 다시점 삼각측량. Ps: 3x4 투영행렬들, uvs: 픽셀 (2,)."""
    A = []
    for P, (u, v) in zip(Ps, uvs):
        A.append(u * P[2] - P[0])
        A.append(v * P[2] - P[1])
    _, _, Vt = np.linalg.svd(np.asarray(A))
    X = Vt[-1]
    return X[:3] / X[3]


def umeyama_3d(src: np.ndarray, dst: np.ndarray) -> tuple[float, np.ndarray, np.ndarray]:
    """dst ≈ s R src + t (3D 상사, 반사 없음). 반환 s, R(3x3), t."""
    ms, md = src.mean(0), dst.mean(0)
    a, b = src - ms, dst - md
    H = b.T @ a / len(src)
    U, S, Vt = np.linalg.svd(H)
    D = np.diag([1.0, 1.0, np.sign(np.linalg.det(U @ Vt))])
    R = U @ D @ Vt
    s = float(np.trace(np.diag(S) @ D) / (a ** 2).sum(1).mean())
    return s, R, md - s * R @ ms
