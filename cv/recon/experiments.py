"""메시 개선 실험 공통 도구: 대상 선택, 출력 폴더, 메시 지표, 미리보기 (메인 .venv, scipy 없이 numpy/Open3D/OpenCV).

실험 스크립트 (모두 같은 형태로 한 줄 실행, 인자 없으면 room_latest.json 이 가리키는 메시):
  python -m cv.recon.proxy_fit   [대상]     # 1. 평면 + 상자 프록시 → proxy.json
  python -m cv.recon.smooth_mesh [대상]     # 2. Taubin 스무딩/간소화 → smooth_*.glb
  python -m cv.recon.run_2dgs    [대상]     # 3. VGGT → COLMAP(+BA) → 2DGS → glb   (envs/2dgs)
  python -m cv.recon.run_spatiallm [대상]   # 4. SpatialLM 레이아웃 → proxy.json   (envs/spatiallm)
  python -m cv.recon.compare_experiments [대상]   # 방법별 지표 표

[대상] = 방 메시 이름(room_<날짜>_<설명>), 그 .glb 경로, 또는 recon_debug/<이름> 폴더.
build_room 이 만든 recon_debug/<이름>/{points.ply, cameras.json} 를 함께 쓴다.

출력: ${SHARED_DIR}/meshes/experiments/<방법>/<이름>/  (room_latest.* 는 절대 쓰지 않음, interfaces.md 2절)
좌표: 입력/출력 모두 월드(glTF, 오른손, +Y 위, 미터, 바닥 y=0). 이 모듈은 좌표를 바꾸지 않는다.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from cv.common.config import shared_dir
from cv.recon.glb import read_glb, write_glb

METHODS = ("proxy-ransac", "smooth", "2dgs", "spatiallm")


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


@dataclass
class Source:
    stem: str        # room_20261110_myroom-charuco
    mesh: Path       # meshes/<stem>.glb (원본 TSDF 메시)
    meta: dict       # meshes/<stem>.json
    debug: Path      # recon_debug/<stem>

    @property
    def points(self) -> Path:
        return self.debug / "points.ply"

    @property
    def cameras(self) -> Path:
        return self.debug / "cameras.json"


def resolve_source(arg: str | None) -> Source:
    """인자 없음 → room_latest.json 의 file. 이름/.glb 경로/recon_debug 폴더 모두 허용."""
    meshes = shared_dir() / "meshes"
    if not arg:
        stem = Path(json.loads((meshes / "room_latest.json").read_text())["file"]).stem
    else:
        p = Path(arg)
        stem = p.stem if p.suffix == ".glb" else p.name
    if stem.startswith("room_latest"):
        raise SystemExit("room_latest 대신 실제 메시 이름(room_<날짜>_<설명>)을 지정하세요.")
    src = Source(stem, meshes / f"{stem}.glb", {}, shared_dir() / "recon_debug" / stem)
    if not src.mesh.is_file():
        raise SystemExit(f"메시가 없습니다: {src.mesh}")
    mj = meshes / f"{stem}.json"
    src.meta = json.loads(mj.read_text()) if mj.is_file() else {}
    for f in (src.points, src.cameras):
        if not f.is_file():
            raise SystemExit(f"{f} 가 없습니다. build_room 으로 이 메시를 다시 만들면 생깁니다.")
    return src


def out_dir(method: str, src: Source) -> Path:
    assert method in METHODS, method
    d = shared_dir() / "meshes" / "experiments" / method / src.stem
    d.mkdir(parents=True, exist_ok=True)
    return d


def safe_write_glb(path: Path, V, F, C_linear, N=None, extras=None) -> None:
    """실험 glb 저장. room_latest.* 와 meshes/ 바로 아래에는 쓰지 않는다."""
    path = Path(path)
    if path.name.startswith("room_latest") or "experiments" not in path.parts:
        raise RuntimeError(f"실험 결과는 experiments/ 아래에만 씁니다: {path}")
    write_glb(path, np.asarray(V, np.float64), np.asarray(F, np.int64), np.asarray(C_linear, np.float64),
              None if N is None else np.asarray(N, np.float64), extras=extras or {})


def load_points(src: Source) -> tuple[np.ndarray, np.ndarray]:
    import open3d as o3d

    pc = o3d.io.read_point_cloud(str(src.points))
    return np.asarray(pc.points), np.asarray(pc.colors)   # 색은 sRGB 0~1


def camera_centers_world(src: Source) -> np.ndarray:
    E = np.asarray(json.loads(src.cameras.read_text())["camera_from_world_4x4"])
    return -np.einsum("sji,sj->si", E[:, :3, :3], E[:, :3, 3])


def load_mesh(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    m = read_glb(path)
    return m["V"], m["F"], m["C"]                         # C: COLOR_0 (선형)


def linear_to_srgb(c: np.ndarray) -> np.ndarray:
    c = np.clip(c, 0, 1)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055)


def face_normals(V: np.ndarray, F: np.ndarray) -> np.ndarray:
    n = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    return n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)


def vertex_normals(V: np.ndarray, F: np.ndarray) -> np.ndarray:
    n = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])   # 면적 가중
    N = np.zeros_like(V)
    for k in range(3):
        np.add.at(N, F[:, k], n)
    return N / np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)


def sample_surface(V, F, C, n: int, seed: int = 0):
    """면적 비례 균일 표면 샘플 → (점, 면 법선, 색)."""
    a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    cr = np.cross(b - a, c - a)
    area = 0.5 * np.linalg.norm(cr, axis=1)
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(F), n, p=area / area.sum())
    r1, r2 = rng.random(n), rng.random(n)
    sq = np.sqrt(r1)
    w0, w1, w2 = (1 - sq), sq * (1 - r2), sq * r2
    P = w0[:, None] * a[idx] + w1[:, None] * b[idx] + w2[:, None] * c[idx]
    col = (w0[:, None] * C[F[idx, 0]] + w1[:, None] * C[F[idx, 1]] + w2[:, None] * C[F[idx, 2]])
    nrm = cr[idx] / np.maximum(np.linalg.norm(cr[idx], axis=1, keepdims=True), 1e-12)
    return P, nrm, col


def boundary_edges(F: np.ndarray) -> np.ndarray:
    """한 삼각형에만 속한 변 (열린 경계 = 구멍/가장자리). (M,2) 정점 인덱스."""
    e = np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    e = np.sort(e, axis=1)
    u, cnt = np.unique(e, axis=0, return_counts=True)
    return u[cnt == 1]


# ---------------------------------------------------------------- 지표

def _plane_frame(pl: dict):
    """평면 다각형의 2D 좌표계 (원점, u, v, 크기). 벽/바닥 공통."""
    poly = np.asarray(pl["polygon"], float)
    n = np.asarray(pl["normal"], float)
    u = poly[1] - poly[0]
    u -= (u @ n) * n
    u /= np.linalg.norm(u)
    v = np.cross(n, u)
    q = (poly - poly[0]) @ np.stack([u, v]).T
    return poly[0], u, v, q


def _inside_poly2d(pts: np.ndarray, poly: np.ndarray) -> np.ndarray:
    import cv2

    c = poly.astype(np.float32).reshape(-1, 1, 2)
    return np.array([cv2.pointPolygonTest(c, (float(x), float(y)), False) >= 0 for x, y in pts], bool) \
        if len(pts) < 2000 else _inside_poly2d_raster(pts, poly)


def _inside_poly2d_raster(pts: np.ndarray, poly: np.ndarray, res: float = 0.01) -> np.ndarray:
    import cv2

    lo = poly.min(0) - res
    hi = poly.max(0) + res
    W, H = np.ceil((hi - lo) / res).astype(int) + 1
    mask = np.zeros((H, W), np.uint8)
    cv2.fillPoly(mask, [np.round((poly - lo) / res).astype(np.int32)], 1)
    ij = np.floor((pts - lo) / res).astype(int)
    ok = (ij[:, 0] >= 0) & (ij[:, 0] < W) & (ij[:, 1] >= 0) & (ij[:, 1] < H)
    out = np.zeros(len(pts), bool)
    out[ok] = mask[ij[ok, 1], ij[ok, 0]] > 0
    return out


def plane_stats(P: np.ndarray, pl: dict, band: float = 0.06, cell: float = 0.05) -> dict:
    """점 P 중 평면 다각형 안·띠(|거리|<band) 안의 점으로 평면도 RMS 와 덮임 비율(칸 단위) 계산."""
    n = np.asarray(pl["normal"], float)
    dist = P @ n + pl["d"]
    near = np.abs(dist) < band
    o, u, v, q = _plane_frame(pl)
    R = P[near] - o
    uv = np.stack([R @ u, R @ v], 1)
    inside = _inside_poly2d_raster(uv, q)
    d_in = dist[near][inside]
    lo, hi = q.min(0), q.max(0)
    nu, nv = np.maximum(np.ceil((hi - lo) / cell).astype(int), 1)
    grid = np.zeros((nv, nu), bool)
    ij = np.clip(np.floor((uv[inside] - lo) / cell).astype(int), 0, [nu - 1, nv - 1])
    grid[ij[:, 1], ij[:, 0]] = True
    # 다각형 안 칸만 분모로 (벽은 직사각형이라 전부, 바닥은 다각형)
    cu = lo[0] + (np.arange(nu) + 0.5) * cell
    cv_ = lo[1] + (np.arange(nv) + 0.5) * cell
    cc = np.stack(np.meshgrid(cu, cv_), -1).reshape(-1, 2)
    inpoly = _inside_poly2d_raster(cc, q).reshape(nv, nu)
    cov = float((grid & inpoly).sum() / max(inpoly.sum(), 1))
    rms = float(np.sqrt(np.mean(d_in ** 2))) if len(d_in) else None
    # 국소 거칠기: tile×tile 칸마다 평면(거리 = a·u + b·v + c)을 맞춘 잔차 RMS. 벽 전체 휨(저주파)은 빼고
    # 잔 울퉁불퉁함만 본다 (스무딩 효과는 여기서 보임)
    tile = 0.20
    uvi = uv[inside]
    res = []
    if len(uvi):
        key = np.floor(uvi / tile).astype(int)
        kid = key[:, 0] * 100000 + key[:, 1]
        order = np.argsort(kid)
        _, st, ct = np.unique(kid[order], return_index=True, return_counts=True)
        for s0, c in zip(st, ct):
            if c < 30:
                continue
            o_ = order[s0:s0 + c]
            A = np.c_[uvi[o_], np.ones(c)]
            coef, *_ = np.linalg.lstsq(A, d_in[o_], rcond=None)
            res.append(d_in[o_] - A @ coef)
    local = float(np.sqrt(np.mean(np.concatenate(res) ** 2))) if res else None
    return {"rms_m": rms, "coverage": cov, "points": int(len(d_in)), "local_rms_m": local}


def check_proxy(proxy: dict, inside: np.ndarray | None = None) -> list[str]:
    """proxy.json 이 interfaces.md 2-1절을 지키는지 검사. 문제 목록 반환 (빈 목록 = 통과).
    inside: 방 안의 한 점 (카메라 중심 중앙값 등). 주면 벽/바닥/천장 법선이 그쪽을 향하는지도 본다."""
    errs = []
    if proxy.get("format") != "roomar-proxy" or proxy.get("version") != 1:
        errs.append("format/version")
    for pl in proxy["planes"]:
        n = np.asarray(pl["normal"], float)
        poly = np.asarray(pl["polygon"], float)
        if abs(np.linalg.norm(n) - 1) > 1e-3:
            errs.append(f"{pl['id']}: 법선이 단위 벡터가 아님")
        if len(poly) >= 3 and np.abs(poly @ n + pl["d"]).max() > 0.01:
            errs.append(f"{pl['id']}: 꼭짓점이 평면 위에 없음 ({np.abs(poly @ n + pl['d']).max():.3f}m)")
        area = sum(np.cross(poly[i], poly[(i + 1) % len(poly)]) for i in range(len(poly)))
        if area @ n <= 0:
            errs.append(f"{pl['id']}: 다각형이 법선 쪽에서 반시계가 아님")
        if inside is not None and np.asarray(inside) @ n + pl["d"] <= 0:
            errs.append(f"{pl['id']}: 법선이 방 안쪽을 향하지 않음")
    for b in proxy["boxes"]:
        th = np.radians(b["yaw_deg"])
        q = np.array([0, np.sin(th / 2), 0, np.cos(th / 2)])
        if min(np.abs(q - b["rotation_xyzw"]).max(), np.abs(q + b["rotation_xyzw"]).max()) > 1e-4:
            errs.append(f"{b['id']}: rotation_xyzw 와 yaw_deg 불일치")
        if min(b["size"]) <= 0:
            errs.append(f"{b['id']}: 크기 ≤ 0")
    return errs


def reference_proxy(src: Source) -> dict | None:
    p = shared_dir() / "meshes" / "experiments" / "proxy-ransac" / src.stem / "proxy.json"
    return json.loads(p.read_text()) if p.is_file() else None


def mesh_metrics(V: np.ndarray, F: np.ndarray, proxy: dict | None, n_samples: int = 2_000_000) -> dict:
    """메시 비교 지표. proxy(평면 기준)가 있으면 벽마다 평면도(RMS)와 덮임 비율(구멍)을 잰다.

    - wall_rms_mm: 벽 평면 ±6cm 띠 안 표면 샘플의 평면 거리 RMS 평균 (작을수록 평평, 벽 전체 휨 포함)
    - wall_local_rms_mm: 같은 점을 20cm 타일별 평면에 맞춘 잔차 RMS 평균 (잔 울퉁불퉁함, 스무딩 효과)
    - wall_coverage: 벽 직사각형 5cm 칸 중 표면이 있는 칸 비율 평균 (1 = 구멍 없음)
    - boundary_m: 열린 경계 변 길이 합 (구멍 둘레 + 메시 가장자리)
    """
    be = boundary_edges(F)
    out = {"triangles": int(len(F)), "vertices": int(len(V)),
           "boundary_m": float(np.linalg.norm(V[be[:, 0]] - V[be[:, 1]], axis=1).sum()) if len(be) else 0.0}
    if proxy is None:
        return out
    P, _, _ = sample_surface(V, F, np.zeros_like(V), n_samples)
    walls = []
    for pl in proxy["planes"]:
        st = plane_stats(P, pl)
        st["id"] = pl["id"]
        if pl["type"] == "wall":
            walls.append(st)
        else:
            out[f"{pl['type']}_rms_mm"] = None if st["rms_m"] is None else round(st["rms_m"] * 1000, 1)
            out[f"{pl['type']}_coverage"] = round(st["coverage"], 3)
    rms = [w["rms_m"] for w in walls if w["rms_m"] is not None]
    out["wall_rms_mm"] = round(float(np.mean(rms)) * 1000, 1) if rms else None
    loc = [w["local_rms_m"] for w in walls if w["local_rms_m"] is not None]
    out["wall_local_rms_mm"] = round(float(np.mean(loc)) * 1000, 2) if loc else None
    out["wall_coverage"] = round(float(np.mean([w["coverage"] for w in walls])), 3) if walls else None
    out["walls"] = [{"id": w["id"], "rms_mm": None if w["rms_m"] is None else round(w["rms_m"] * 1000, 1),
                     "coverage": round(w["coverage"], 3)} for w in walls]
    return out


# ---------------------------------------------------------------- 미리보기 (헤드리스, 점 z-버퍼)

def _look_at(eye, target, up=(0, 1, 0)):
    """월드(glTF) → OpenCV 카메라 회전 (x 오른쪽, y 아래, z 앞)."""
    f = np.asarray(target, float) - eye
    f /= np.linalg.norm(f)
    r = np.cross(f, up)
    r /= np.linalg.norm(r)
    d = np.cross(f, r)          # 아래
    return np.stack([r, d, f])


def render_points(P, col, eye, target, W=640, H=480, fov_deg=75.0, bg=(25, 25, 30), splat=1):
    """원근 점 렌더 (가까운 점이 남음). col: 0~1 RGB (표시용 sRGB)."""
    R = _look_at(np.asarray(eye, float), target)
    X = (P - eye) @ R.T
    ok = X[:, 2] > 0.05
    X, c = X[ok], col[ok]
    f = 0.5 * W / np.tan(np.deg2rad(fov_deg) / 2)
    u = (f * X[:, 0] / X[:, 2] + W / 2).astype(int)
    v = (f * X[:, 1] / X[:, 2] + H / 2).astype(int)
    img = np.empty((H, W, 3), np.uint8)
    img[:] = bg
    zb = np.full((H, W), np.inf)
    o = np.argsort(-X[:, 2])                    # 먼 점부터 → 가까운 점이 덮음
    cc = (np.clip(c, 0, 1) * 255).astype(np.uint8)
    for du in range(splat):
        for dv in range(splat):
            uu, vv = u[o] + du, v[o] + dv
            m = (uu >= 0) & (uu < W) & (vv >= 0) & (vv < H)
            img[vv[m], uu[m]] = cc[o][m]
            zb[vv[m], uu[m]] = X[o, 2][m]
    return img


def shade(nrm: np.ndarray, base: np.ndarray | None = None) -> np.ndarray:
    """법선 음영 (빛 방향 고정, 양면). 매끈함/울퉁불퉁함이 잘 보이게."""
    L = np.array([0.35, 0.8, 0.5])
    L /= np.linalg.norm(L)
    s = 0.25 + 0.75 * np.abs(nrm @ L)
    b = np.full((len(nrm), 3), 0.85) if base is None else base
    return b * s[:, None]


def room_views(bbox_lo, bbox_hi):
    """방 안 위쪽 두 모서리에서 반대편 아래 중심을 보는 시점 2개."""
    lo, hi = np.asarray(bbox_lo, float), np.asarray(bbox_hi, float)
    c = (lo + hi) / 2
    hgt = hi[1]
    inset = 0.12 * (hi - lo)
    e1 = np.array([lo[0] + inset[0], 0.85 * hgt, lo[2] + inset[2]])
    e2 = np.array([hi[0] - inset[0], 0.85 * hgt, hi[2] - inset[2]])
    t = np.array([c[0], 0.35 * hgt, c[2]])
    return [(e1, t + (t - e1) * 0.2), (e2, t + (t - e2) * 0.2)]


def top_view(P, col, lo, hi, px=110, cut_y=None, bg=(25, 25, 30)):
    """위에서 본 직교 투영 (X 오른쪽, +Z 아래). cut_y 위 점은 잘라냄 (천장 제거)."""
    if cut_y is not None:
        k = P[:, 1] < cut_y
        P, col = P[k], col[k]
    w, d = (np.asarray(hi)[[0, 2]] - np.asarray(lo)[[0, 2]]) * px
    w, d = int(w) + 1, int(d) + 1
    img = np.empty((d, w, 3), np.uint8)
    img[:] = bg
    u = ((P[:, 0] - lo[0]) * px).astype(int).clip(0, w - 1)
    v = ((P[:, 2] - lo[2]) * px).astype(int).clip(0, d - 1)
    o = np.argsort(P[:, 1])
    img[v[o], u[o]] = (np.clip(col[o], 0, 1) * 255).astype(np.uint8)
    return img


def compose_preview(path: Path, panels: list[tuple[str, np.ndarray]], title: str, ncol: int = 2) -> None:
    """패널(제목, 이미지) 을 격자로 붙여 저장."""
    Wc = max(p.shape[1] for _, p in panels)
    Hc = max(p.shape[0] for _, p in panels)
    nrow = (len(panels) + ncol - 1) // ncol
    im = Image.new("RGB", (Wc * ncol, (Hc + 18) * nrow + 22), (12, 12, 12))
    dr = ImageDraw.Draw(im)
    dr.text((4, 4), title, fill=(255, 255, 0))
    for k, (name, p) in enumerate(panels):
        x, y = (k % ncol) * Wc, 22 + (k // ncol) * (Hc + 18)
        im.paste(Image.fromarray(p), (x, y + 16))
        dr.text((x + 4, y + 2), name, fill=(200, 200, 200))
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    im.save(path)


class Renderer:
    """Open3D 오프스크린 렌더러 (헤드리스, Vulkan). 프로세스당 하나만 만들어 재사용한다."""

    _inst = None

    def __init__(self, W: int = 640, H: int = 480):
        import open3d as o3d

        self.o3d = o3d
        self.W, self.H = W, H
        self.r = o3d.visualization.rendering.OffscreenRenderer(W, H)
        self.r.scene.set_background([0.10, 0.10, 0.12, 1.0])
        self.r.scene.scene.set_sun_light([-0.35, -0.8, -0.5], [1.0, 1.0, 1.0], 90000)
        self.r.scene.scene.enable_sun_light(True)

    @classmethod
    def get(cls) -> "Renderer":
        if cls._inst is None:
            cls._inst = Renderer()
        return cls._inst

    def mesh(self, V, F, C_srgb=None, two_sided: bool = True):
        """두 면 모두 보이게 뒤집은 삼각형을 덧붙인 Open3D 메시 (메시 법선 방향이 제각각이어도 보이게)."""
        o3d = self.o3d
        V, F = np.asarray(V, float), np.asarray(F, int)
        if two_sided:
            nV = len(V)
            V = np.concatenate([V, V])
            F = np.concatenate([F, F[:, ::-1] + nV])
            if C_srgb is not None:
                C_srgb = np.concatenate([C_srgb, C_srgb])
        m = o3d.geometry.TriangleMesh(o3d.utility.Vector3dVector(V), o3d.utility.Vector3iVector(F))
        if C_srgb is not None:
            m.vertex_colors = o3d.utility.Vector3dVector(np.clip(C_srgb, 0, 1))
        m.compute_vertex_normals()
        return m

    def render(self, geoms, eye=None, target=None, fov_v: float = 62.0, ortho=None) -> np.ndarray:
        """geoms: [(geometry, 'lit'|'unlit'|'points')]. ortho=(center, half_x, half_z) 면 위에서 내려다본 직교."""
        o3d = self.o3d
        R = o3d.visualization.rendering
        sc = self.r.scene
        sc.clear_geometry()
        for i, (g, mode) in enumerate(geoms):
            mat = R.MaterialRecord()
            if mode == "lit":
                mat.shader = "defaultLit"
                mat.base_color = [0.82, 0.82, 0.80, 1.0]
            else:
                mat.shader = "defaultUnlit"
                if mode == "points":
                    mat.point_size = 2.0
            sc.add_geometry(f"g{i}", g, mat)
        if ortho is not None:
            c, hx, hz = ortho
            cam = sc.camera
            cam.set_projection(R.Camera.Projection.Ortho, -hx, hx, -hz, hz, 0.05, 50.0)
            # 위에서 아래로, 화면 위쪽 = −Z → 화면 오른쪽 = +X, 아래쪽 = +Z
            cam.look_at(np.asarray(c, float), np.asarray(c, float) + [0, 20.0, 0], [0, 0, -1.0])
        else:
            self.r.setup_camera(fov_v, np.asarray(target, float), np.asarray(eye, float), [0, 1.0, 0])
        # 큰 지오메트리를 올린 직후나 GPU 가 바쁠 때(2DGS 학습 중) 프레임이 완전히 0(배경색도 아님)으로 나오는
        # 경우가 있다(실측: 점 15만~50만 개, 메시 17만 정점). 0 이 아닐 때까지 조금 기다리며 다시 그린다
        img = np.zeros(1)
        for k in range(20):
            img = np.asarray(self.r.render_to_image())
            if img.max() > 0:
                break
            time.sleep(0.05 * (k + 1))
        if img.max() == 0:
            log("경고: 미리보기 렌더가 빈 화면입니다 (GPU 사용 중일 수 있음)")
        return img[:, :, :3].copy()

    def top_frame(self, lo, hi):
        """직교 위 시점 범위 (화면 비율 유지). 반환 (center, hx, hz), 월드→픽셀 함수."""
        c = (np.asarray(lo) + np.asarray(hi)) / 2
        hx, hz = (hi[0] - lo[0]) / 2, (hi[2] - lo[2]) / 2
        asp = self.W / self.H
        if hx / hz < asp:
            hx = hz * asp
        else:
            hz = hx / asp

        def to_px(x, z):
            return (x - (c[0] - hx)) / (2 * hx) * self.W, (z - (c[2] - hz)) / (2 * hz) * self.H

        return (c, hx, hz), to_px


def mesh_preview(path: Path, V, F, C_linear, title: str, bbox=None, cams=None, extra_note: str = "") -> None:
    """메시 미리보기 (Open3D 렌더): 위에서 본 색/음영 (천장 부근 잘라냄) + 방 안 두 시점 (음영 / 색)."""
    rd = Renderer.get()
    V, F = np.asarray(V), np.asarray(F)
    col = linear_to_srgb(np.asarray(C_linear))
    if bbox is None:
        P, _, _ = sample_surface(V, F, np.zeros_like(V), 300_000)
        lo, hi = np.percentile(P, 0.5, 0), np.percentile(P, 99.5, 0)
    else:
        lo, hi = map(np.asarray, bbox)
    cut = F[(V[F, 1] < hi[1] - 0.30).all(1)]                 # 위 시점: 천장 부근 삼각형 제거
    frame, to_px = rd.top_frame(lo - 0.1, hi + 0.1)
    top_c = rd.render([(rd.mesh(V, cut, col), "unlit")], ortho=frame)
    top_s = rd.render([(rd.mesh(V, cut), "lit")], ortho=frame)
    if cams is not None:
        pim = Image.fromarray(top_c)
        dr = ImageDraw.Draw(pim)
        for c in cams:
            x, z = to_px(c[0], c[2])
            dr.ellipse([x - 3, z - 3, x + 3, z + 3], outline=(255, 60, 60))
        top_c = np.asarray(pim)
    panels = [("TOP color (ceiling cut, X right, +Z down)", top_c), ("TOP shaded", top_s)]
    m_lit, m_col = rd.mesh(V, F), rd.mesh(V, F, col)
    for k, (eye, tgt) in enumerate(room_views(lo, hi)):
        panels.append((f"view{k + 1} shaded", rd.render([(m_lit, "lit")], eye, tgt)))
        panels.append((f"view{k + 1} color", rd.render([(m_col, "unlit")], eye, tgt)))
    compose_preview(path, panels, f"{title}  tris {len(F):,} {extra_note}")


def write_json(path: Path, obj) -> None:
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=1, default=_json_default), encoding="utf-8")


def _json_default(o):
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, Path):
        return str(o)
    raise TypeError(type(o))
