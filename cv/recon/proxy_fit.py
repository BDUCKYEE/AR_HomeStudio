"""1. 평면 + 상자 프록시: 바닥·천장·벽 평면(RANSAC) + 가구 덩어리 OBB → proxy.json (interfaces.md 2-1절)

사용 (메인 .venv, GPU 불필요):
  python -m cv.recon.proxy_fit                         # room_latest.json 이 가리키는 메시의 점구름
  python -m cv.recon.proxy_fit room_20261110_myroom-charuco

입력: ${SHARED_DIR}/recon_debug/<이름>/points.ply (build_room 출력, 월드 m), cameras.json
출력: ${SHARED_DIR}/meshes/experiments/proxy-ransac/<이름>/{proxy.json, proxy.glb, preview.png, report.json}
파라미터: cv/config/recon.yaml proxy 절

방법
- 바닥: |y|<10cm 이고 법선이 수직인 점에 RANSAC.  천장: 1.8m 위 수평면 점 중 가장 높은 층에 RANSAC (없으면 추정)
- 벽: 법선이 수평인 점에서 RANSAC 을 반복해 수직 평면 후보를 뽑고, 카메라 쪽을 안쪽으로 법선을 맞춘 뒤
  '벽 밖에 점이 거의 없는' 평면만 방 경계로 본다. 경계 벽들의 안쪽 반평면 교집합 = 바닥 다각형 (볼록 방 가정).
  벽 방향(±X, ±Z) 중 찾지 못한 쪽은 점구름 백분위로 추정한 벽을 넣고 estimated=true 로 표시
- 가구: 평면 띠(7cm)와 방 밖 점을 뺀 나머지를 DBSCAN 으로 묶고, 묶음마다 세운 OBB(yaw 만, 벽 방향 근처면 맞춤)

좌표: 입력/출력 모두 월드(glTF, 오른손, +Y 위, 미터, 바닥 y=0). 변환 없음.
"""
from __future__ import annotations

import argparse
import datetime as dt
import time

import cv2
import numpy as np
import open3d as o3d
from PIL import Image, ImageDraw

from cv.common.config import load_yaml
from cv.recon import experiments as ex
from cv.recon.glb import srgb_to_linear


# ---------------------------------------------------------------- 평면 도우미

def _ransac(P: np.ndarray, dist: float, iters: int = 1500, seed: int = 0):
    """평면 RANSAC (numpy, 시드 고정 → 같은 입력이면 같은 결과).

    Open3D segment_plane 은 시드를 줘도 멀티스레드라 실행마다 결과가 달라졌다(실측: 벽 4개/5개, 폭 2.52/2.59m).
    점이 많으면 최대 30,000개로 점수를 매기고, 마지막 인라이어는 전체 점에서 고른다.
    """
    rng = np.random.default_rng(seed)
    S = P if len(P) <= 30_000 else P[rng.choice(len(P), 30_000, replace=False)]
    best_n, best_d, best_cnt = None, 0.0, -1
    for _ in range(0, iters, 250):
        tri = S[rng.integers(0, len(S), (250, 3))]
        n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        k = np.linalg.norm(n, axis=1)
        ok = k > 1e-12
        n, tri = n[ok] / k[ok, None], tri[ok]
        d = -np.einsum("ij,ij->i", n, tri[:, 0])
        cnt = (np.abs(S @ n.T + d) < dist).sum(0)
        j = int(np.argmax(cnt))
        if cnt[j] > best_cnt:
            best_n, best_d, best_cnt = n[j], float(d[j]), int(cnt[j])
    inl = np.flatnonzero(np.abs(P @ best_n + best_d) < dist)
    return best_n, best_d, inl


def _refit(P: np.ndarray, n0: np.ndarray, vertical: bool = False):
    """인라이어로 평면 다시 맞춤 (PCA). vertical=True 면 법선의 y 를 0 으로."""
    c = P.mean(0)
    _, _, Vt = np.linalg.svd(P - c, full_matrices=False)
    n = Vt[-1]
    if vertical:
        n = np.array([n[0], 0.0, n[2]])
    n /= np.linalg.norm(n)
    if n @ n0 < 0:
        n = -n
    return n, float(-(n @ c))


def _orient_poly(poly: np.ndarray, n: np.ndarray) -> np.ndarray:
    """법선 쪽에서 볼 때 반시계가 되도록 (오른손 법칙 면적 벡터 · n > 0)."""
    area = np.zeros(3)
    for i in range(len(poly)):
        area += np.cross(poly[i], poly[(i + 1) % len(poly)])
    return poly if area @ n > 0 else poly[::-1]


def _poly_area(poly: np.ndarray) -> float:
    area = np.zeros(3)
    for i in range(len(poly)):
        area += np.cross(poly[i], poly[(i + 1) % len(poly)])
    return float(np.linalg.norm(area) / 2)


def _clip_halfplane(poly: list, a: np.ndarray, b: float) -> list:
    """Sutherland–Hodgman: a·p + b >= 0 쪽만 남김 (2D)."""
    out = []
    for i in range(len(poly)):
        p, q = np.asarray(poly[i]), np.asarray(poly[(i + 1) % len(poly)])
        fp, fq = a @ p + b, a @ q + b
        if fp >= 0:
            out.append(p)
        if (fp >= 0) != (fq >= 0):
            t = fp / (fp - fq)
            out.append(p + t * (q - p))
    return out


def _y_on(plane, x, z):
    n, d = plane
    return -(n[0] * x + n[2] * z + d) / n[1]


# ---------------------------------------------------------------- 맞춤

def fit_proxy(P: np.ndarray, C: np.ndarray, cams: np.ndarray, cfg: dict) -> tuple[dict, dict]:
    t0 = time.time()
    pc = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(P))
    pc.colors = o3d.utility.Vector3dVector(C)
    pc = pc.voxel_down_sample(cfg["voxel_m"])
    pc.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=cfg["normal_radius_m"], max_nn=40))
    D, N, DC = np.asarray(pc.points), np.asarray(pc.normals), np.asarray(pc.colors)
    dist = cfg["plane_dist_m"]
    dbg = {"points_in": len(P), "points_down": len(D)}

    # 바닥
    m = (np.abs(D[:, 1]) < 0.10) & (np.abs(N[:, 1]) > cfg["horizontal_min_ny"])
    n, d, inl = _ransac(D[m], dist)
    n, d = _refit(D[m][inl], np.array([0, 1.0, 0]))
    floor = dict(n=n, d=d, idx=np.flatnonzero(m)[inl])
    dbg["floor"] = {"normal": n.round(4).tolist(), "y_at_origin": round(-d / n[1], 4),
                    "tilt_deg": round(float(np.degrees(np.arccos(abs(n[1])))), 2), "inliers": len(inl)}

    # 천장
    up = (np.abs(N[:, 1]) > cfg["horizontal_min_ny"]) & (D[:, 1] > cfg["ceiling_min_height_m"])
    ceil = None
    if up.sum() >= cfg["wall_min_points"] // 2:
        ys = D[up, 1]
        top = up & (D[:, 1] > np.percentile(ys, 97) - 0.20)
        n, d, inl = _ransac(D[top], dist)
        if abs(n[1]) > 0.97 and len(inl) >= cfg["wall_min_points"] // 2:
            n, d = _refit(D[top][inl], np.array([0, -1.0, 0]))
            ceil = dict(n=n, d=d, idx=np.flatnonzero(top)[inl], estimated=False)
    if ceil is None:      # 천장이 거의 안 찍힘 → 점 높이 99.5 백분위의 수평면
        h = float(np.percentile(D[:, 1], 99.5))
        ceil = dict(n=np.array([0, -1.0, 0]), d=h, idx=np.zeros(0, int), estimated=True)
    height0 = float(_y_on((ceil["n"], ceil["d"]), 0, 0))
    dbg["ceiling"] = {"height_at_origin": round(height0, 4), "estimated": ceil["estimated"], "inliers": len(ceil["idx"])}

    # 벽 후보 (수직 평면)
    vm = (np.abs(N[:, 1]) < cfg["vertical_max_ny"]) & (D[:, 1] > 0.10) & (D[:, 1] < height0 - 0.10)
    rest = np.flatnonzero(vm)
    cands = []
    for k in range(cfg["max_planes"]):
        if len(rest) < cfg["wall_min_points"]:
            break
        n, d, inl = _ransac(D[rest], dist, seed=k)
        idx = rest[inl]
        rest = np.delete(rest, inl)
        if abs(n[1]) > 0.15 or len(idx) < cfg["wall_min_points"]:
            continue
        n, d = _refit(D[idx], n, vertical=True)
        if np.median(cams @ n + d) < 0:           # 법선을 카메라(방 안) 쪽으로
            n, d = -n, -d
        tang = np.cross([0, 1.0, 0], n)
        s = D[idx] @ tang
        span = float(np.percentile(s, 98) - np.percentile(s, 2))
        outside = float(np.mean(D @ n + d < -cfg["wall_outside_m"]))
        cands.append(dict(n=n, d=d, idx=idx, span=span, outside=outside,
                          boundary=outside <= cfg["wall_outside_frac"] and span >= cfg["wall_min_span_m"]))
    dbg["wall_candidates"] = [{"normal_xz": c["n"][[0, 2]].round(3).tolist(), "d": round(c["d"], 3),
                               "inliers": len(c["idx"]), "span_m": round(c["span"], 2),
                               "outside_frac": round(c["outside"], 4), "boundary": c["boundary"]} for c in cands]

    # 같은 벽 합치기 (VGGT 벽은 두께가 있어 평행 평면 2장으로 잡히기도 함) → 인라이어 합쳐 다시 맞춤
    walls = []
    bnd = sorted([c for c in cands if c["boundary"]], key=lambda c: -len(c["idx"]))
    big = len(bnd[0]["idx"]) if bnd else 0
    for c in bnd:
        for w in walls:
            if np.degrees(np.arccos(np.clip(c["n"] @ w["n"], -1, 1))) < cfg["wall_merge_deg"] and \
                    abs((c["d"] - w["d"])) < cfg["wall_merge_m"]:
                w["idx"] = np.concatenate([w["idx"], c["idx"]])
                w["n"], w["d"] = _refit(D[w["idx"]], w["n"], vertical=True)
                break
        else:
            # 새 벽은 가장 큰 벽 인라이어의 일정 비율 이상일 때만 (모서리 잡음이 비스듬한 작은 평면으로 잡히는 것 방지,
            # 실측: 벽 방향에서 8° 비스듬한 1,472점 평면이 모서리를 깎음)
            if len(c["idx"]) >= cfg["wall_min_rel_inliers"] * big:
                walls.append(dict(c, estimated=False))
            else:
                c["boundary"] = False

    # 찾지 못한 벽 방향(±X, ±Z, 벽 방향 기준)은 백분위로 추정
    yaw = 0.0
    if walls:
        ang = np.array([np.arctan2(w["n"][2], w["n"][0]) for w in walls])
        wgt = np.array([len(w["idx"]) for w in walls], float)
        yaw = float(np.angle(np.sum(wgt * np.exp(4j * ang))) / 4)
    inroom = D[(D[:, 1] > 0.1) & (D[:, 1] < height0 - 0.1)]
    for k in range(4):
        a = yaw + k * np.pi / 2
        nn = np.array([np.cos(a), 0, np.sin(a)])          # 안쪽 법선 후보
        if any(w["n"] @ nn > np.cos(np.radians(30)) for w in walls):
            continue
        off = float(np.percentile(inroom @ nn, 1))
        walls.append(dict(n=nn, d=-off, idx=np.zeros(0, int), span=0.0, outside=0.01, boundary=True, estimated=True))

    # 바닥 다각형 = 경계 벽 안쪽 반평면 교집합 (XZ)
    lo, hi = D[:, [0, 2]].min(0) - 2, D[:, [0, 2]].max(0) + 2
    poly = [np.array([lo[0], lo[1]]), np.array([hi[0], lo[1]]), np.array([hi[0], hi[1]]), np.array([lo[0], hi[1]])]
    for w in walls:
        poly = _clip_halfplane(poly, w["n"][[0, 2]], w["d"])
    poly = np.array(poly)
    # 바닥 다각형 변마다 어느 벽인지
    edges = []
    for i in range(len(poly)):
        a, b = poly[i], poly[(i + 1) % len(poly)]
        if np.linalg.norm(b - a) < 0.05:
            continue
        mid = (a + b) / 2
        w = min(walls, key=lambda w: abs(w["n"][[0, 2]] @ mid + w["d"]))
        edges.append((a, b, w))

    planes, colors = [], []
    fl = (floor["n"], floor["d"])
    cl = (ceil["n"], ceil["d"])
    fpoly = np.array([[x, _y_on(fl, x, z), z] for x, z in poly])
    cpoly = np.array([[x, _y_on(cl, x, z), z] for x, z in poly])
    fpoly = _orient_poly(fpoly, floor["n"])
    planes.append(dict(id="floor", type="floor", normal=floor["n"], d=floor["d"], polygon=fpoly))
    colors.append(DC[floor["idx"]].mean(0))
    planes.append(dict(id="ceiling", type="ceiling", normal=ceil["n"], d=ceil["d"],
                       polygon=_orient_poly(cpoly, ceil["n"]), estimated=ceil["estimated"]))
    colors.append(DC[ceil["idx"]].mean(0) if len(ceil["idx"]) else np.full(3, 0.8))
    for k, (a, b, w) in enumerate(edges):
        quad = np.array([[a[0], _y_on(fl, *a), a[1]], [b[0], _y_on(fl, *b), b[1]],
                         [b[0], _y_on(cl, *b), b[1]], [a[0], _y_on(cl, *a), a[1]]])
        planes.append(dict(id=f"wall_{k}", type="wall", normal=w["n"], d=w["d"],
                           polygon=_orient_poly(quad, w["n"]), estimated=w["estimated"]))
        colors.append(DC[w["idx"]].mean(0) if len(w["idx"]) else np.full(3, 0.75))
    for pl in planes:
        st = ex.plane_stats(P, dict(pl), band=cfg["furniture_band_m"])
        pl["area_m2"] = _poly_area(pl["polygon"])
        pl["rms_m"] = None if pl.get("estimated") or st["rms_m"] is None else st["rms_m"]
        pl["coverage"] = st["coverage"]

    # 가구: 평면 띠 밖·방 안 점 → 위에서 본 높이 지도(벽 방향 격자). 높이가 이어지는 칸끼리 묶어 상자로.
    # (VGGT 점은 잡음이 방 안을 연속으로 채워 3D DBSCAN 이 한 덩어리로 묶음 → 2.5D 가 더 안정적)
    band, cell = cfg["furniture_band_m"], cfg["furniture_cell_m"]
    keep = (P @ floor["n"] + floor["d"] > band) & (P @ ceil["n"] + ceil["d"] > band)
    for _, _, w in edges:
        keep &= P @ w["n"] + w["d"] > band
    Q, QC = P[keep], C[keep]
    e1 = np.array([np.cos(yaw), 0, np.sin(yaw)])           # 벽 법선 방향 격자 축
    e2 = np.array([-np.sin(yaw), 0, np.cos(yaw)])
    st = np.stack([Q @ e1, Q @ e2], 1)
    lo2 = st.min(0)
    ij = np.floor((st - lo2) / cell).astype(int)
    nx, nz = ij.max(0) + 1
    cid = ij[:, 1] * nx + ij[:, 0]
    order = np.argsort(cid, kind="stable")
    uniq, start, cnt = np.unique(cid[order], return_index=True, return_counts=True)
    top = np.full(nx * nz, np.nan)
    bot = np.full(nx * nz, np.nan)
    ys = Q[order, 1]
    for u, s0, c in zip(uniq, start, cnt):
        if c >= cfg["furniture_min_cell_points"]:
            top[u], bot[u] = np.percentile(ys[s0:s0 + c], [95, 5])
    occ = ~np.isnan(top).reshape(nz, nx)
    occ = cv2.morphologyEx(occ.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)).astype(bool)
    T, B = top.reshape(nz, nx), bot.reshape(nz, nx)
    lab = -np.ones((nz, nx), int)
    nlab = 0
    for r0, c0 in zip(*np.nonzero(occ)):
        if lab[r0, c0] >= 0:
            continue
        # 영역 확장: 이웃 칸 높이가 '영역 평균 높이'와 join_dh 안일 때만 잇는다
        # (이웃끼리만 비교하면 잡음 경사를 따라 침대-옷장처럼 높이가 다른 가구가 계속 이어짐)
        lab[r0, c0] = nlab
        stack, ssum, scnt = [(r0, c0)], T[r0, c0], 1
        while stack:
            r, c = stack.pop(0)
            for rr, cc in ((r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1)):
                if 0 <= rr < nz and 0 <= cc < nx and occ[rr, cc] and lab[rr, cc] < 0 \
                        and abs(T[rr, cc] - ssum / scnt) < cfg["furniture_join_dh_m"]:
                    lab[rr, cc] = nlab
                    stack.append((rr, cc))
                    ssum += T[rr, cc]
                    scnt += 1
        nlab += 1
    plab = lab.reshape(-1)[cid]
    boxes = []
    for k in range(nlab):
        rc = np.argwhere(lab == k)                               # (행=e2, 열=e1)
        if len(rc) * cell ** 2 < cfg["box_min_area_m2"]:
            continue
        cs = np.concatenate([rc[:, ::-1] + o for o in ((0, 0), (1, 0), (0, 1), (1, 1))]) * cell + lo2
        phi = np.radians(cv2.minAreaRect(cs.astype(np.float32))[2])
        rel = phi % (np.pi / 2)
        rel = rel - np.pi / 2 if rel > np.pi / 4 else rel
        if abs(np.degrees(rel)) < cfg["box_snap_deg"]:          # 벽 방향 근처면 벽 방향으로
            phi -= rel
        a3 = np.cos(phi) * e1 + np.sin(phi) * e2                 # 상자 한 축 (월드 XZ)
        th = float(np.arctan2(-a3[2], a3[0]))                    # yaw: 상자 +X = (cos θ, 0, −sin θ)
        th = (th + np.pi / 4) % (np.pi / 2) - np.pi / 4          # (−45°, 45°]
        ux = np.array([np.cos(th), 0, -np.sin(th)])
        uz = np.array([np.sin(th), 0, np.cos(th)])
        W3 = cs[:, :1] * e1 + cs[:, 1:] * e2
        su, sz = W3 @ ux, W3 @ uz
        hy = float(np.percentile(T[lab == k], 90))
        ly = float(np.percentile(B[lab == k], 10))
        if ly < cfg["box_floor_snap_m"]:
            ly = 0.0
        size = np.array([su.max() - su.min(), hy - ly, sz.max() - sz.min()])
        if size.max() < cfg["box_min_extent_m"] or min(size[0], size[2]) < cfg["box_min_thickness_m"] or size[1] <= 0:
            continue
        center = ux * (su.max() + su.min()) / 2 + uz * (sz.max() + sz.min()) / 2
        center[1] = (ly + hy) / 2
        pm = plab == k
        boxes.append(dict(center=center, size=size, yaw=th, points=int(pm.sum()), color=QC[pm].mean(0)))
    boxes.sort(key=lambda b: -np.prod(b["size"]))
    dbg["furniture"] = {"points": int(len(Q)), "cells_occupied": int(occ.sum()), "regions": nlab,
                        "boxes": len(boxes), "boxes_kept": min(len(boxes), cfg["max_boxes"])}
    boxes = boxes[: cfg["max_boxes"]]

    # 벽 방향 기준 방 크기
    u = np.array([np.cos(yaw), np.sin(yaw)])
    v = np.array([-np.sin(yaw), np.cos(yaw)])
    size_m = [float(np.ptp(poly @ u)), float(np.ptp(poly @ v))]
    fxz = fpoly[:, [0, 2]]
    proxy = {
        "format": "roomar-proxy", "version": 1, "method": "ransac-obb",
        "created_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "coordinate_system": "glTF world: right-handed, +Y up, meters, floor y=0",
        "room": {"height_m": round(height0 - float(_y_on(fl, 0, 0)), 4),
                 "footprint": fxz.round(4).tolist(), "size_m": [round(s, 4) for s in size_m]},
        "planes": [{"id": p["id"], "type": p["type"], "normal": np.round(p["normal"], 5).tolist(),
                    "d": round(float(p["d"]), 5), "polygon": np.round(p["polygon"], 4).tolist(),
                    "area_m2": round(p["area_m2"], 3),
                    "rms_m": None if p["rms_m"] is None else round(p["rms_m"], 4),
                    "coverage": round(p["coverage"], 3)} for p in planes],
        "boxes": [{"id": f"box_{i}", "label": "furniture", "center": np.round(b["center"], 4).tolist(),
                   "size": np.round(b["size"], 4).tolist(), "yaw_deg": round(float(np.degrees(b["yaw"])), 2),
                   "rotation_xyzw": [0.0, round(float(np.sin(b["yaw"] / 2)), 6), 0.0,
                                     round(float(np.cos(b["yaw"] / 2)), 6)],
                   "confidence": None, "points": int(b["points"])} for i, b in enumerate(boxes)],
        "openings": [],
        "stats": {"time_s": round(time.time() - t0, 2), "wall_yaw_deg": round(float(np.degrees(yaw)), 2),
                  "walls_estimated": [p["id"] for p in planes if p.get("estimated")],
                  "ceiling_estimated": bool(ceil["estimated"])},
    }
    colors += [b["color"] for b in boxes]
    return proxy, {"debug": dbg, "colors": colors}


# ---------------------------------------------------------------- proxy → 메시

def box_corners(center, size, yaw_deg):
    th = np.radians(yaw_deg)
    ux = np.array([np.cos(th), 0, -np.sin(th)])
    uy = np.array([0, 1.0, 0])
    uz = np.array([np.sin(th), 0, np.cos(th)])
    h = np.asarray(size) / 2
    return np.array([np.asarray(center) + sx * h[0] * ux + sy * h[1] * uy + sz * h[2] * uz
                     for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)])


def proxy_to_mesh(proxy: dict, colors: list | None = None):
    """평면 다각형(부채꼴 삼각형) + 상자(면마다 바깥 법선). 반환 V, F, C(sRGB 0~1), N (면별 정점 복제)."""
    V, F, C, N = [], [], [], []
    k = 0
    cols = colors or []

    def add_poly(poly, n, col):
        nonlocal k
        poly = np.asarray(poly)
        for i in range(1, len(poly) - 1):
            V.extend([poly[0], poly[i], poly[i + 1]])
            F.append([k, k + 1, k + 2])
            k += 3
            C.extend([col] * 3)
            N.extend([n] * 3)

    for i, pl in enumerate(proxy["planes"]):
        col = cols[i] if i < len(cols) else {"floor": (0.55, 0.5, 0.45), "ceiling": (0.9, 0.9, 0.9)}.get(pl["type"], (0.8, 0.8, 0.78))
        add_poly(pl["polygon"], np.asarray(pl["normal"]), np.asarray(col))
    nb = len(proxy["planes"])
    faces = [(0, 1, 3, 2, (-1, 0, 0)), (4, 6, 7, 5, (1, 0, 0)), (0, 4, 5, 1, (0, -1, 0)),
             (2, 3, 7, 6, (0, 1, 0)), (0, 2, 6, 4, (0, 0, -1)), (1, 5, 7, 3, (0, 0, 1))]
    for j, b in enumerate(proxy["boxes"]):
        cr = box_corners(b["center"], b["size"], b["yaw_deg"])
        th = np.radians(b["yaw_deg"])
        Ry = np.array([[np.cos(th), 0, np.sin(th)], [0, 1, 0], [-np.sin(th), 0, np.cos(th)]])
        col = np.asarray(cols[nb + j]) if nb + j < len(cols) else np.array([0.3, 0.6, 0.9])
        for a, b_, c, d, nl in faces:
            n = Ry @ np.asarray(nl, float)
            add_poly(_orient_poly(cr[[a, b_, c, d]], n), n, col)
    return np.array(V), np.array(F), np.array(C), np.array(N)


def proxy_preview(path, proxy, P, C, cams, colors) -> None:
    """위: 입력 점(천장 부근 제외) + 바닥 다각형(노랑) + 상자(하늘색). 방 안 두 시점: 프록시 음영/색, 입력 점."""
    import open3d as o3d

    rd = ex.Renderer.get()
    V, F, Cm, _ = proxy_to_mesh(proxy, colors)
    ceil_tris = sum(len(pl["polygon"]) - 2 for pl in proxy["planes"][:2] if pl["type"] == "ceiling")
    first = sum(len(pl["polygon"]) - 2 for pl in proxy["planes"][:1])          # floor 다음이 ceiling
    keep = np.ones(len(F), bool)
    keep[first:first + ceil_tris] = False                                       # 미리보기에서 천장 숨김
    lo, hi = np.percentile(P, 0.5, 0), np.percentile(P, 99.5, 0)
    h = proxy["room"]["height_m"]
    k = P[:, 1] < h - 0.3
    pc = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(P[k]))
    pc.colors = o3d.utility.Vector3dVector(C[k])
    frame, to_px = rd.top_frame(lo - 0.1, hi + 0.1)
    im = Image.fromarray(rd.render([(pc, "points")], ortho=frame))
    dr = ImageDraw.Draw(im)
    dr.polygon([to_px(x, z) for x, z in proxy["room"]["footprint"]], outline=(255, 255, 0))
    for b in proxy["boxes"]:
        cr = box_corners(b["center"], b["size"], b["yaw_deg"])[[0, 4, 5, 1]]
        dr.polygon([to_px(x, z) for x, _, z in cr], outline=(0, 220, 255))
        dr.text(to_px(b["center"][0], b["center"][2]), b["id"].split("_")[1], fill=(0, 255, 255))
    for c in cams:
        x, z = to_px(c[0], c[2])
        dr.ellipse([x - 3, z - 3, x + 3, z + 3], outline=(255, 60, 60))
    pc_all = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(P))
    pc_all.colors = o3d.utility.Vector3dVector(C)
    m_lit = rd.mesh(V, F[keep])
    m_col = rd.mesh(V, F[keep], Cm)
    panels = [("TOP input points + footprint(yellow) + boxes(cyan)", np.asarray(im))]
    views = ex.room_views(lo, hi)
    panels.append(("view1 proxy shaded (ceiling hidden)", rd.render([(m_lit, "lit")], *views[0])))
    panels.append(("view1 proxy color + input points", rd.render([(m_col, "unlit"), (pc_all, "points")], *views[0])))
    panels.append(("view1 input points", rd.render([(pc_all, "points")], *views[0])))
    panels.append(("view2 proxy shaded", rd.render([(m_lit, "lit")], *views[1])))
    panels.append(("view2 input points", rd.render([(pc_all, "points")], *views[1])))
    ex.compose_preview(path, panels, f"{proxy['method']}  planes {len(proxy['planes'])}, boxes {len(proxy['boxes'])}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", nargs="?", help="방 메시 이름 (기본: room_latest.json 의 file)")
    a = ap.parse_args()
    cfg = load_yaml("recon.yaml")["proxy"]
    src = ex.resolve_source(a.target)
    out = ex.out_dir("proxy-ransac", src)
    ex.log(f"대상 {src.stem} → {out}")
    P, C = ex.load_points(src)
    cams = ex.camera_centers_world(src)
    proxy, info = fit_proxy(P, C, cams, cfg)
    proxy["source"] = src.meta.get("source")
    proxy["source_mesh"] = src.mesh.name
    errs = ex.check_proxy(proxy, np.median(cams, 0))
    if errs:
        raise SystemExit("proxy.json 규약 위반: " + "; ".join(errs))
    ex.write_json(out / "proxy.json", proxy)
    V, F, Cs, N = proxy_to_mesh(proxy, info["colors"])
    ex.safe_write_glb(out / "proxy.glb", V, F, srgb_to_linear(Cs), N,
                      extras={"method": "proxy-ransac", "source_mesh": src.mesh.name,
                              "coordinate_system": "glTF world: right-handed, +Y up, meters, floor y=0"})
    proxy_preview(out / "preview.png", proxy, P, C, cams, info["colors"])
    ex.write_json(out / "report.json", {"source": src.stem, "params": cfg, **info["debug"], "stats": proxy["stats"]})
    r = proxy["room"]
    walls = [p for p in proxy["planes"] if p["type"] == "wall"]
    ex.log(f"방 {r['size_m'][0]:.2f}×{r['size_m'][1]:.2f}m, 높이 {r['height_m']:.2f}m, 벽 {len(walls)}개 "
           f"(추정 {proxy['stats']['walls_estimated']}), 상자 {len(proxy['boxes'])}개, {proxy['stats']['time_s']}s")
    for p in proxy["planes"]:
        ex.log(f"  {p['id']:8s} 넓이 {p['area_m2']:.2f}m²  rms {p['rms_m']}  덮임 {p['coverage']:.0%}")
    ex.log(f"완료 → {out}")


if __name__ == "__main__":
    main()
