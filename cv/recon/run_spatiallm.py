"""4. SpatialLM 레이아웃 → proxy.json (interfaces.md 2-1절, method = "spatiallm")

사용 (메인 .venv, 추론은 envs/spatiallm 을 하위 프로세스로 부름, GPU 1):
  python -m cv.recon.run_spatiallm                              # room_latest.json 이 가리키는 메시의 점구름
  python -m cv.recon.run_spatiallm room_20261110_myroom-charuco --input mesh   # TSDF 메시 표면 샘플을 입력으로
  python -m cv.recon.run_spatiallm --seeds 0 1 2                # 시드별 결과 (생성 모델이라 실행마다 다름)

환경 준비 (한 번): bash cv/recon/envs/setup_spatiallm.sh. 모델은 HF_HOME(cv/env.sh) 아래로 내려받는다.

입력 형식 (SpatialLM README / EXAMPLE.md): z 축이 위, 벽이 x/y 축에 정렬(ScanNet 규약), 미터 단위.
  우리 월드(glTF, +Y 위, 미터, 벽이 X/Z 에 정렬)를 X축 +90° 회전으로 한 번만 바꾼다:
    z-up = (x, −z, y)        ← 이 파일의 to_zup()
    월드 = (x', z', −y')      ← 이 파일의 from_zup()   (det=+1, 오른손 유지)
  밀도: SpatialLM 이 grid_size(= 32m / num_bins) 로 복셀 정리하므로 그보다 촘촘하면 된다 (points.ply 50만 점 ≈ 1~2cm).
출력: ${SHARED_DIR}/meshes/experiments/spatiallm/<이름>/{input_zup.ply, raw_<입력>_s<시드>.json, proxy[_...].json, proxy.glb, preview.png}

라이선스 (2026-11-23 확인, SpatialLM README): SpatialLM1.1-Qwen-0.5B 는 Qwen2.5(Apache-2.0) 파생, SpatialLM1.1 의
Sonata 점구름 인코더 가중치는 CC-BY-NC-4.0 (비상업), 코드(Pointcept 기반)는 Apache-2.0. Llama 변형은 Llama 3.2 라이선스.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import time
from pathlib import Path

import cv2
import numpy as np
import open3d as o3d

from cv.recon import experiments as ex
from cv.recon.glb import srgb_to_linear
from cv.recon.proxy_fit import _orient_poly, _poly_area, proxy_preview, proxy_to_mesh

ENVS_ROOT = Path(os.environ.get("ENVS_ROOT", "/storage/AI/cv_project/envs"))
ENV_PY = ENVS_ROOT / "spatiallm" / ".venv" / "bin" / "python"
HERE = Path(__file__).resolve().parent
M = np.array([[1.0, 0, 0], [0, 0, -1.0], [0, 1.0, 0]])      # 월드(glTF, Y 위) → z-up (SpatialLM)
Y = np.array([0, 1.0, 0])


def to_zup(P: np.ndarray) -> np.ndarray:
    return P @ M.T


def from_zup(P) -> np.ndarray:
    return np.asarray(P, float) @ M


def layout_to_proxy(raw: dict, cams: np.ndarray) -> dict:
    """SpatialLM 출력(z-up) → proxy dict (월드). 벽 법선은 카메라 쪽(방 안)을 향하게."""
    walls = []
    for w in raw["walls"]:
        A, B = from_zup([w["ax"], w["ay"], w["az"]]), from_zup([w["bx"], w["by"], w["bz"]])
        walls.append(dict(id=w["id"], A=A, B=B, h=float(w["height"]), t=float(w["thickness"])))
    inside = np.median(cams, 0)
    planes, fl_y, ce_y = [], 0.0, None
    if walls:
        fl_y = float(np.median([w["A"][1] for w in walls]))
        ce_y = fl_y + float(np.median([w["h"] for w in walls]))
    for k, w in enumerate(walls):
        A, B = w["A"].copy(), w["B"].copy()
        u = B - A
        n = np.cross(Y, u)
        n[1] = 0
        n /= max(np.linalg.norm(n), 1e-9)
        if n @ (inside - A) < 0:
            n = -n
        quad = np.array([A, B, B + Y * w["h"], A + Y * w["h"]])
        w["n"], w["pid"] = n, f"wall_{k}"
        planes.append(dict(id=w["pid"], type="wall", normal=n.round(5).tolist(), d=round(float(-n @ A), 5),
                           polygon=_orient_poly(quad, n).round(4).tolist(), area_m2=round(_poly_area(quad), 3),
                           rms_m=None, coverage=None))
    # 바닥/천장 = 벽 끝점의 볼록 껍질 (벽이 3개 미만이면 생략)
    footprint = []
    if len(walls) >= 3:
        xz = np.array([p[[0, 2]] for w in walls for p in (w["A"], w["B"])], np.float32)
        hull = cv2.convexHull(xz).reshape(-1, 2).astype(float)
        footprint = hull
        fpoly = np.c_[hull[:, 0], np.full(len(hull), fl_y), hull[:, 1]]
        cpoly = np.c_[hull[:, 0], np.full(len(hull), ce_y), hull[:, 1]]
        fpoly = _orient_poly(fpoly, Y)
        footprint = fpoly[:, [0, 2]]
        planes.insert(0, dict(id="ceiling", type="ceiling", normal=[0, -1.0, 0], d=round(ce_y, 5),
                              polygon=_orient_poly(cpoly, -Y).round(4).tolist(), area_m2=round(_poly_area(cpoly), 3),
                              rms_m=None, coverage=None))
        planes.insert(0, dict(id="floor", type="floor", normal=[0, 1.0, 0], d=round(-fl_y, 5),
                              polygon=fpoly.round(4).tolist(), area_m2=round(_poly_area(fpoly), 3), rms_m=None, coverage=None))
    byid = {w["id"]: w for w in walls}
    openings = []
    for kind in ("doors", "windows"):
        for j, o in enumerate(raw[kind]):
            w = byid.get(o["wall_id"])
            c = from_zup([o["position_x"], o["position_y"], o["position_z"]])
            if w is None:
                continue
            u = (w["B"] - w["A"]) / np.linalg.norm(w["B"] - w["A"])
            hw, hh = o["width"] / 2, o["height"] / 2
            quad = np.array([c - u * hw - Y * hh, c + u * hw - Y * hh, c + u * hw + Y * hh, c - u * hw + Y * hh])
            openings.append(dict(id=f"{kind[:-1]}_{j}", type=kind[:-1], wall=w["pid"],
                                 polygon=_orient_poly(quad, w["n"]).round(4).tolist()))
    boxes = []
    for j, b in enumerate(raw["bboxes"]):
        c = from_zup([b["position_x"], b["position_y"], b["position_z"]])
        th = float(b["angle_z"])                      # z-up 의 z 축 회전 = 월드 +Y 축 회전 (같은 각)
        th = (th + np.pi) % (2 * np.pi) - np.pi
        size = [float(b["scale_x"]), float(b["scale_z"]), float(b["scale_y"])]   # 상자 축 (x, z위, y) → (X, Y, Z)
        boxes.append(dict(id=f"box_{j}", label=b["class_name"], center=c.round(4).tolist(), size=np.round(size, 4).tolist(),
                          yaw_deg=round(float(np.degrees(th)), 2),
                          rotation_xyzw=[0.0, round(float(np.sin(th / 2)), 6), 0.0, round(float(np.cos(th / 2)), 6)],
                          confidence=None, points=None))
    size_m = [0.0, 0.0]
    if len(footprint):
        u0 = walls[0]["B"] - walls[0]["A"]
        yaw = np.arctan2(u0[2], u0[0])
        e1, e2 = np.array([np.cos(yaw), np.sin(yaw)]), np.array([-np.sin(yaw), np.cos(yaw)])
        size_m = sorted([float(np.ptp(footprint @ e1)), float(np.ptp(footprint @ e2))])
    return {
        "format": "roomar-proxy", "version": 1, "method": "spatiallm",
        "created_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "coordinate_system": "glTF world: right-handed, +Y up, meters, floor y=0",
        "room": {"height_m": None if ce_y is None else round(ce_y - fl_y, 4),
                 "footprint": np.round(footprint, 4).tolist() if len(footprint) else [], "size_m": [round(s, 4) for s in size_m]},
        "planes": planes, "boxes": boxes, "openings": openings,
        "stats": {"floor_y_m": round(fl_y, 4)},   # 모델이 본 바닥 높이 (우리 바닥 y=0 과의 차이, 2.5cm 양자화 영향)
    }


def wall_fit(proxy: dict, P: np.ndarray) -> dict:
    """입력 점이 모델 벽에 얼마나 붙는지 (참고용, proxy 필드가 아니라 stats 에 기록)."""
    ws = [ex.plane_stats(P, pl, band=0.10) for pl in proxy["planes"] if pl["type"] == "wall"]
    rms = [w["rms_m"] for w in ws if w["rms_m"] is not None]
    return {"wall_rms_mm_vs_points": round(float(np.mean(rms)) * 1000, 1) if rms else None,
            "wall_coverage_vs_points": round(float(np.mean([w["coverage"] for w in ws])), 3) if ws else None}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", nargs="?")
    ap.add_argument("--input", choices=["points", "mesh"], default="points",
                    help="points: recon_debug/points.ply (VGGT 점) / mesh: TSDF 메시 표면 샘플 (덜 시끄러움)")
    ap.add_argument("--model", default="manycore-research/SpatialLM1.1-Qwen-0.5B")
    ap.add_argument("--seeds", type=int, nargs="+", default=[0])
    a = ap.parse_args()
    if not ENV_PY.exists():
        raise SystemExit(f"SpatialLM 환경이 없습니다: {ENV_PY}. bash cv/recon/envs/setup_spatiallm.sh 를 먼저 실행하세요.")
    src = ex.resolve_source(a.target)
    out = ex.out_dir("spatiallm", src)
    if a.input == "points":
        P, C = ex.load_points(src)
    else:
        V, F, Cl = ex.load_mesh(src.mesh)
        P, _, Cl = ex.sample_surface(V, F, Cl, 500_000)
        C = ex.linear_to_srgb(Cl)
    ply = out / f"input_zup_{a.input}.ply"
    pc = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(to_zup(P)))
    pc.colors = o3d.utility.Vector3dVector(np.clip(C, 0, 1))
    o3d.io.write_point_cloud(str(ply), pc)
    cams = ex.camera_centers_world(src)
    ref = ex.reference_proxy(src)
    env = dict(os.environ, CUDA_VISIBLE_DEVICES="1")          # SpatialLM 은 GPU 1 (사용자 지시)
    for seed in a.seeds:
        raw_p = out / f"raw_{a.input}_s{seed}.json"
        t0 = time.time()
        log = out / f"infer_{a.input}_s{seed}.log"
        with open(log, "w") as f:
            p = subprocess.run([str(ENV_PY), str(HERE / "spatiallm_infer.py"), str(ply), str(raw_p), "--model", a.model,
                                "--seed", str(seed)], stdout=f, stderr=subprocess.STDOUT, env=env)
        if p.returncode != 0:
            raise SystemExit(f"SpatialLM 실패. 로그 {log}\n" + "".join(open(log, errors="replace").readlines()[-25:]))
        raw = json.loads(raw_p.read_text())
        proxy = layout_to_proxy(raw, cams)
        proxy["source"] = src.meta.get("source")
        proxy["source_mesh"] = src.mesh.name
        proxy["stats"] = {**proxy["stats"], "input": a.input, "seed": seed, "model": a.model, "time_total_s": round(time.time() - t0, 1),
                          "time_load_s": raw["time_load_s"], "time_infer_s": raw["time_infer_s"],
                          "gpu_peak_gb": raw["gpu_peak_gb"], "grid_size_m": raw["grid_size_m"],
                          "labels": sorted({b["label"] for b in proxy["boxes"]}), **wall_fit(proxy, P)}
        if ref is not None:
            proxy["stats"]["ref_room_size_m"] = ref["room"]["size_m"]
            proxy["stats"]["ref_height_m"] = ref["room"]["height_m"]
        errs = ex.check_proxy(proxy, np.median(cams, 0))
        if errs:
            raise SystemExit("proxy.json 규약 위반: " + "; ".join(errs))
        name = "proxy" if (a.input == "points" and seed == a.seeds[0]) else f"proxy_{a.input}_s{seed}"
        ex.write_json(out / f"{name}.json", proxy)
        V, F, Cm, N = proxy_to_mesh(proxy)
        ex.safe_write_glb(out / f"{name}.glb", V, F, srgb_to_linear(Cm), N,
                          extras={"method": "spatiallm", "source_mesh": src.mesh.name,
                                  "coordinate_system": "glTF world: right-handed, +Y up, meters, floor y=0"})
        if proxy["planes"]:
            proxy_preview(out / f"{name}.png", proxy, P, C, cams, None)
        r = proxy["room"]
        ex.log(f"[{a.input} s{seed}] 벽 {sum(p['type'] == 'wall' for p in proxy['planes'])}, 문 "
               f"{sum(o['type'] == 'door' for o in proxy['openings'])}, 창 {sum(o['type'] == 'window' for o in proxy['openings'])}, "
               f"상자 {len(proxy['boxes'])} {proxy['stats']['labels']}, 방 {r['size_m']} 높이 {r['height_m']}, "
               f"추론 {raw['time_infer_s']}s (로드 {raw['time_load_s']}s, {raw['gpu_peak_gb']}GB) → {name}.json")
    if (out / "proxy.json").exists():
        (out / "proxy.json").touch()   # unity 는 경로에 spatiallm 이 든 가장 최근 .json 을 읽음 → 기본 결과를 마지막으로


if __name__ == "__main__":
    main()
