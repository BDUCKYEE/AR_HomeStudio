"""2. Taubin 스무딩 / 간소화: 원본 TSDF 메시를 여러 강도로 다듬어 smooth_*.glb 로 저장하고 지표를 잰다.

사용 (메인 .venv, GPU 불필요):
  python -m cv.recon.smooth_mesh                          # room_latest.json 이 가리키는 메시
  python -m cv.recon.smooth_mesh room_20261110_myroom-charuco
  python -m cv.recon.smooth_mesh --variants t10 t30 t100 t30-s50k

변형 이름: t<반복> = Taubin 반복 수 (λ=0.5, μ=−0.53, 부피 거의 유지, 열린 경계 정점 고정), -s<N>k = quadric 간소화 목표 삼각형 N천 개.
"orig" 는 원본 그대로 (기준선 지표).

출력: ${SHARED_DIR}/meshes/experiments/smooth/<이름>/{smooth_<변형>.glb, smooth_<변형>.png, metrics.json}
지표(벽 평면도, 벽 덮임)는 proxy-ransac 결과의 평면을 기준으로 잰다 → 먼저 proxy_fit 을 돌린다 (없으면 자동 실행).
좌표: 월드(glTF, +Y 위, 미터) 그대로. 정점 위치만 바뀌고 좌표계는 바뀌지 않는다.
"""
from __future__ import annotations

import argparse
import re
import time

import numpy as np
import open3d as o3d

from cv.recon import experiments as ex

DEFAULT_VARIANTS = ["orig", "t10", "t30", "t100", "t30-s50k", "t30-s20k"]


def taubin(V: np.ndarray, F: np.ndarray, iters: int, lam: float = 0.5, mu: float = -0.53) -> np.ndarray:
    """Taubin 스무딩 (균일 라플라시안). 열린 경계 정점은 고정한다.

    Open3D filter_smooth_taubin 은 경계도 움직여서, 바닥 메우기 사각형처럼 떨어진 조각과 구멍 가장자리가
    오그라든다(실측: 열린 경계 길이 524m → 177m, 바닥에 틈이 생김). 그래서 직접 구현.
    """
    E = np.unique(np.sort(np.concatenate([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]]), axis=1), axis=0)
    deg = np.bincount(E.ravel(), minlength=len(V)).astype(float)
    pinned = np.zeros(len(V), bool)
    pinned[ex.boundary_edges(F).ravel()] = True
    pinned |= deg == 0
    V = V.copy()
    for _ in range(iters):
        for f in (lam, mu):
            S = np.zeros_like(V)
            np.add.at(S, E[:, 0], V[E[:, 1]])
            np.add.at(S, E[:, 1], V[E[:, 0]])
            L = S / np.maximum(deg, 1)[:, None] - V
            L[pinned] = 0
            V += f * L
    return V


def apply_variant(V, F, C, name: str):
    m = o3d.geometry.TriangleMesh(o3d.utility.Vector3dVector(V), o3d.utility.Vector3iVector(F))
    m.vertex_colors = o3d.utility.Vector3dVector(C)
    m.remove_duplicated_vertices()                       # 같은 위치 정점 합침 (이음매가 경계로 잡히지 않게)
    t = re.search(r"t(\d+)", name)
    s = re.search(r"s(\d+)k", name)
    if t:
        Vs = taubin(np.asarray(m.vertices), np.asarray(m.triangles), int(t.group(1)))
        m.vertices = o3d.utility.Vector3dVector(Vs)
    if s:
        m = m.simplify_quadric_decimation(int(s.group(1)) * 1000, boundary_weight=10.0)
        m.remove_degenerate_triangles()
        m.remove_unreferenced_vertices()
    m.compute_vertex_normals()
    return (np.asarray(m.vertices), np.asarray(m.triangles), np.asarray(m.vertex_colors),
            np.asarray(m.vertex_normals))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", nargs="?", help="방 메시 이름 (기본: room_latest.json 의 file)")
    ap.add_argument("--variants", nargs="+", default=DEFAULT_VARIANTS)
    a = ap.parse_args()
    src = ex.resolve_source(a.target)
    out = ex.out_dir("smooth", src)
    proxy = ex.reference_proxy(src)
    if proxy is None:
        ex.log("기준 프록시가 없어 proxy_fit 을 먼저 실행합니다.")
        import subprocess
        import sys

        subprocess.run([sys.executable, "-m", "cv.recon.proxy_fit", src.stem], check=True)
        proxy = ex.reference_proxy(src)
    V0, F0, C0 = ex.load_mesh(src.mesh)
    Vr, *_ = apply_variant(V0, F0, C0, "orig")            # 이동량 비교 기준 (중복 정점 합친 원본)
    cams = ex.camera_centers_world(src)
    bbox = (np.percentile(V0, 0.5, 0), np.percentile(V0, 99.5, 0))
    rows = {}
    for name in a.variants:
        t0 = time.time()
        V, F, C, N = apply_variant(V0, F0, C0, name)
        dt = time.time() - t0
        mt = ex.mesh_metrics(V, F, proxy)
        mt["time_s"] = round(dt, 2)
        # 부피 변화 확인: 정점 평균 이동량 (간소화가 없을 때만 1:1 대응)
        if not re.search(r"s\d+k", name):
            mt["mean_shift_mm"] = round(float(np.linalg.norm(V - Vr, axis=1).mean()) * 1000, 2)
        glb = out / f"smooth_{name}.glb"
        ex.safe_write_glb(glb, V, F, C, N, extras={"method": "smooth", "variant": name, "source_mesh": src.mesh.name,
                                                   "coordinate_system": "glTF world: right-handed, +Y up, meters, floor y=0"})
        ex.mesh_preview(out / f"smooth_{name}.png", V, F, C, f"smooth {name}", bbox=bbox, cams=cams)
        mt["glb"] = glb.name
        mt["preview"] = f"smooth_{name}.png"
        rows[name] = mt
        ex.log(f"{name:10s} 삼각형 {mt['triangles']:>7,}  벽 rms {mt['wall_rms_mm']}mm  국소 {mt['wall_local_rms_mm']}mm  벽 덮임 {mt['wall_coverage']}  "
               f"열린 경계 {mt['boundary_m']:.1f}m  {dt:.1f}s")
    ex.write_json(out / "metrics.json", {"source": src.stem, "reference_proxy": "proxy-ransac", "variants": rows})
    ex.log(f"완료 → {out}")


if __name__ == "__main__":
    main()
