"""바닥 메우기: 바닥 평면(월드 y=0) 위, 방 범위 안에서 메시 바닥이 비어 있는 격자 칸에 평면 사각형을 채운다.

좌표: 입력/출력 모두 월드(glTF, +Y 위, 미터, 바닥 y=0). 방 범위는 벽 방향(맨해튼 yaw)으로 회전한 좌표에서
점구름 백분위 직사각형으로 잡고, 결과 사각형은 다시 월드로 돌려놓는다 (Y축 회전이므로 법선 +Y 유지).
"""
from __future__ import annotations

import numpy as np

from cv.recon.geometry import manhattan_yaw, rot_y
from cv.recon.validate_mesh import sample_surface


def fill_floor(V, F, C, N, pts, cols, cfg: dict, mode: str = "auto"):
    """V,F,C(sRGB 0~1),N: 메시. pts/cols: 신뢰도 필터 후 월드 점과 색. 반환 (V,F,C,N,info)."""
    info = {"mode": mode, "applied": False}
    if mode == "off":
        return V, F, C, N, info
    cell, band = cfg["cell_m"], cfg["floor_band_m"]
    inroom = pts[(pts[:, 1] > -0.05) & (pts[:, 1] < 2.5)]
    yaw = manhattan_yaw(inroom, unit=1.0)
    Ry = rot_y(-yaw)                                   # 월드 → 벽 정렬 좌표 (Y축 회전)
    pr = inroom @ Ry.T
    p = cfg["region_percentile"]
    lo, hi = np.percentile(pr[:, [0, 2]], [p, 100 - p], axis=0)
    nx, nz = np.ceil((hi - lo) / cell).astype(int)
    info.update(yaw_deg=float(np.rad2deg(yaw)), region_size_m=(hi - lo).round(3).tolist(), cells=int(nx * nz))

    def to_cell(q):
        ij = np.floor((q[:, [0, 2]] - lo) / cell).astype(int)
        ok = (ij[:, 0] >= 0) & (ij[:, 0] < nx) & (ij[:, 1] >= 0) & (ij[:, 1] < nz)
        return ij[ok, 0] * nz + ij[ok, 1], ok

    # 기존 바닥 삼각형(세 정점 모두 |y| < band)이 덮는 칸
    occ = np.zeros(nx * nz, bool)
    ftri = F[(np.abs(V[F][:, :, 1]) < band).all(1)]
    if len(ftri):
        a, b, c = V[ftri[:, 0]], V[ftri[:, 1]], V[ftri[:, 2]]
        area = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1).sum()
        S = sample_surface(V, ftri, int(min(2_000_000, max(10_000, area / cell ** 2 * 8))))
        idx, _ = to_cell(S @ Ry.T)
        occ[idx] = True
    cov = float(occ.mean())
    info["coverage_before"] = cov
    if mode == "auto" and cov >= cfg["auto_coverage"]:
        return V, F, C, N, info

    # 칸별 색: 그 칸의 바닥 점 평균, 없으면 바닥 점 전체 중앙값
    fl = np.abs(pts[:, 1]) < band
    gcol = np.median(cols[fl], 0) if fl.sum() > 100 else np.array([0.5, 0.5, 0.5])
    idx, ok = to_cell(pts[fl] @ Ry.T)
    csum = np.zeros((nx * nz, 3))
    np.add.at(csum, idx, cols[fl][ok])
    cnt = np.bincount(idx, minlength=nx * nz)
    ccol = np.where(cnt[:, None] > 3, csum / np.maximum(cnt, 1)[:, None], gcol)

    empty = np.flatnonzero(~occ)
    i, j = empty // nz, empty % nz
    x0, z0 = lo[0] + i * cell, lo[1] + j * cell
    x1, z1 = x0 + cell, z0 + cell
    y = np.full_like(x0, cfg["y_offset_m"])
    # 사각형 정점 a=(x0,z0) b=(x0,z1) c=(x1,z1) d=(x1,z0); 삼각형 (a,b,c),(a,c,d) → 법선 +Y (위에서 반시계)
    q = np.stack([np.stack([x0, y, z0], 1), np.stack([x0, y, z1], 1),
                  np.stack([x1, y, z1], 1), np.stack([x1, y, z0], 1)], 1).reshape(-1, 3)
    qv = q @ Ry                                        # 벽 정렬 좌표 → 월드 (Ry^T 적용)
    base = len(V) + 4 * np.arange(len(empty))
    qf = np.concatenate([np.stack([base, base + 1, base + 2], 1), np.stack([base, base + 2, base + 3], 1)])
    qc = np.repeat(ccol[empty], 4, 0)
    qn = np.tile([0.0, 1.0, 0.0], (len(qv), 1))
    info.update(applied=True, cells_filled=int(len(empty)), triangles_added=int(len(qf)))
    return (np.vstack([V, qv]), np.vstack([F, qf]), np.vstack([C, qc]), np.vstack([N, qn]), info)
