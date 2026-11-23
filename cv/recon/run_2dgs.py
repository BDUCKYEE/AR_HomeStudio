"""3. 2DGS(2D Gaussian Splatting) 메시: VGGT → COLMAP 내보내기 → (SIFT+BA) → 2DGS 학습 → TSDF 메시 → glb

사용 (메인 .venv 에서 실행, 학습/BA 는 envs/2dgs 를 하위 프로세스로 부름, GPU 0):
  python -m cv.recon.run_2dgs                                  # room_latest.json 이 가리키는 메시, BA 포함
  python -m cv.recon.run_2dgs room_20261110_myroom-charuco --no-ba
  python -m cv.recon.run_2dgs --iterations 30000 --depth-ratio 1 --tag d1

환경 준비 (한 번): bash cv/recon/envs/setup_2dgs.sh

출력: ${SHARED_DIR}/meshes/experiments/2dgs/<이름>/
  colmap_vggt/        VGGT 포즈 COLMAP 모델 + 1600px 이미지 (export_colmap)
  colmap_ba/          SIFT 매칭 + 알려진 포즈 삼각측량 + BA 후 모델 (colmap_ba.py), ba_report.json
  model_<tag>/        2DGS 학습 결과 (point_cloud, train/ours_N/fuse_post.ply)
  2dgs_<tag>.glb/.png/.json   방 범위로 자르고 간소화한 메시, 미리보기, 지표·시간

좌표: COLMAP world = 우리 월드(glTF, +Y 위, 미터)를 그대로 쓰므로 2DGS 메시도 같은 좌표다 (축 변환 없음).
BA 는 끝에 카메라 중심을 원래 VGGT 중심에 상사변환으로 맞춰 월드를 유지한다.
"""
from __future__ import annotations

import os

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")   # 2DGS 학습은 GPU 0 (CLAUDE.md)

import argparse  # noqa: E402
import json  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402
import open3d as o3d  # noqa: E402

from cv.common.config import load_yaml  # noqa: E402
from cv.recon import experiments as ex  # noqa: E402
from cv.recon.export_colmap import export  # noqa: E402
from cv.recon.glb import srgb_to_linear  # noqa: E402

ENVS_ROOT = Path(os.environ.get("ENVS_ROOT", "/storage/AI/cv_project/envs"))
ENV_PY = ENVS_ROOT / "2dgs" / ".venv" / "bin" / "python"
REPO = ENVS_ROOT / "2dgs" / "2d-gaussian-splatting"
HERE = Path(__file__).resolve().parent


def run(cmd: list, log: Path, cwd: Path | None = None) -> float:
    ex.log("실행: " + " ".join(map(str, cmd)))
    t0 = time.time()
    env = dict(os.environ, CUDA_VISIBLE_DEVICES=os.environ.get("CUDA_VISIBLE_DEVICES", "0"))
    with open(log, "w") as f:
        p = subprocess.run([str(c) for c in cmd], cwd=cwd, stdout=f, stderr=subprocess.STDOUT, env=env)
    dt = time.time() - t0
    if p.returncode != 0:
        tail = "".join(open(log, errors="replace").readlines()[-30:])
        raise SystemExit(f"실패 (종료 코드 {p.returncode}, {dt:.0f}s). 로그 {log}\n{tail}")
    return dt


def crop_to_room(mesh: o3d.geometry.TriangleMesh, proxy: dict | None, V0: np.ndarray, margin: float = 0.25):
    """방 범위 밖(창밖, 떠다니는 조각) 삼각형 제거. 범위 = 프록시 바닥 다각형 bbox(없으면 원본 메시 bbox) + margin."""
    if proxy is not None:
        fp = np.asarray(proxy["room"]["footprint"])
        lo = np.array([fp[:, 0].min(), -0.10, fp[:, 1].min()]) - [margin, 0, margin]
        hi = np.array([fp[:, 0].max(), proxy["room"]["height_m"] + 0.10, fp[:, 1].max()]) + [margin, 0, margin]
    else:
        lo, hi = np.percentile(V0, 0.5, 0) - margin, np.percentile(V0, 99.5, 0) + margin
    box = o3d.geometry.AxisAlignedBoundingBox(lo, hi)
    return mesh.crop(box)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", nargs="?")
    ap.add_argument("--no-ba", action="store_true", help="BA 없이 VGGT 포즈 그대로 학습")
    ap.add_argument("--iterations", type=int, default=30000)
    ap.add_argument("--depth-ratio", type=float, default=0.0, help="2DGS: 0=평균 깊이(기본), 1=중앙 깊이")
    ap.add_argument("--lambda-dist", type=float, default=0.0)
    ap.add_argument("--lambda-normal", type=float, default=0.05)
    ap.add_argument("--voxel", type=float, default=0.01, help="메시 TSDF 복셀 (m)")
    ap.add_argument("--sdf-trunc", type=float, default=0.04)
    ap.add_argument("--depth-trunc", type=float, default=4.5, help="메시 TSDF 깊이 상한 (m, 방 대각선 정도)")
    ap.add_argument("--tag", help="결과 이름 (기본: ba / noba)")
    ap.add_argument("--reexport", action="store_true")
    a = ap.parse_args()
    if not ENV_PY.exists():
        raise SystemExit(f"2DGS 환경이 없습니다: {ENV_PY}. bash cv/recon/envs/setup_2dgs.sh 를 먼저 실행하세요.")
    src = ex.resolve_source(a.target)
    out = ex.out_dir("2dgs", src)
    tag = a.tag or ("noba" if a.no_ba else "ba")
    rep = {"source": src.stem, "tag": tag, "args": vars(a), "times_s": {}}
    try:
        rep["repo_commit"] = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True,
                                            text=True).stdout.strip()
    except OSError:
        pass

    # 1) COLMAP 내보내기
    cv_dir = out / "colmap_vggt"
    if a.reexport or not (cv_dir / "sparse" / "0" / "images.txt").exists():
        t0 = time.time()
        rep["export"] = export(src, cv_dir)
        rep["times_s"]["export"] = round(time.time() - t0, 1)
    data = cv_dir

    # 2) BA
    if not a.no_ba:
        ba_dir = out / "colmap_ba"
        if not (ba_dir / "sparse" / "0" / "images.bin").exists():
            rep["times_s"]["ba"] = round(run([ENV_PY, HERE / "colmap_ba.py", cv_dir, ba_dir], out / "colmap_ba.log"), 1)
        rep["ba"] = ba = json.loads((ba_dir / "ba_report.json").read_text())
        # BA 가 정상인지 판정: 흰 벽처럼 매칭이 적으면 게이지가 흘러 장면이 늘어나거나 카메라가 크게 움직인다
        # (실측 20261110 방: 점 3,122개, 정렬 배율 0.73, 위치 평균 20cm/최대 1.8m, 회전 최대 32° → 기각)
        pc_ = ba["pose_change"]
        ok = (abs(ba["align_to_vggt_world"]["scale"] - 1) < 0.05 and pc_["pos_mean_cm"] < 5
              and pc_["rot_max_deg"] < 3 and ba["after_ba"]["points3D"] >= 5000)
        rep["ba_accepted"] = bool(ok)
        if ok:
            data = ba_dir
        else:
            ex.log(f"BA 기각 (배율 {ba['align_to_vggt_world']['scale']:.3f}, 위치 평균 {pc_['pos_mean_cm']}cm, "
                   f"회전 최대 {pc_['rot_max_deg']}°, 점 {ba['after_ba']['points3D']}) → VGGT 포즈로 학습")
            if not a.tag:
                tag = "noba"

    rep["tag"] = tag            # BA 기각 시 noba 로 바뀐 이름을 기록
    # 3) 학습
    model = out / f"model_{tag}"
    ply = model / "point_cloud" / f"iteration_{a.iterations}" / "point_cloud.ply"
    if not ply.exists():
        rep["times_s"]["train"] = round(run(
            [ENV_PY, "train.py", "-s", data, "-m", model, "--iterations", a.iterations, "-r", "1",
             "--depth_ratio", a.depth_ratio, "--lambda_dist", a.lambda_dist, "--lambda_normal", a.lambda_normal,
             "--test_iterations", a.iterations, "--save_iterations", a.iterations, "--quiet",
             "--port", 6009 + int(time.time()) % 500],
            out / f"train_{tag}.log", cwd=REPO), 1)
    pc = o3d.io.read_point_cloud(str(ply))
    rep["gaussians"] = len(pc.points)

    # 4) 메시 추출 (렌더 깊이 TSDF, 2DGS 기본 방식)
    fuse = model / "train" / f"ours_{a.iterations}" / "fuse_post.ply"
    if not fuse.exists():
        rep["times_s"]["mesh"] = round(run(
            [ENV_PY, "render.py", "-m", model, "-s", data, "--skip_test", "--skip_train",
             "--depth_ratio", a.depth_ratio, "--voxel_size", a.voxel, "--sdf_trunc", a.sdf_trunc,
             "--depth_trunc", a.depth_trunc, "--num_cluster", 50],
            out / f"render_{tag}.log", cwd=REPO), 1)

    # 5) 정리: 방 범위로 자르기 → 간소화 → glb
    t0 = time.time()
    mesh = o3d.io.read_triangle_mesh(str(fuse))
    rep["tris_raw"] = len(mesh.triangles)
    proxy = ex.reference_proxy(src)
    V0, F0, _ = ex.load_mesh(src.mesh)
    mesh = crop_to_room(mesh, proxy, V0)
    mesh.remove_unreferenced_vertices()
    tgt = load_yaml("recon.yaml")["mesh"]["target_triangles"]
    if len(mesh.triangles) > tgt:
        mesh = mesh.simplify_quadric_decimation(tgt)
        mesh.remove_degenerate_triangles()
        mesh.remove_unreferenced_vertices()
    mesh.compute_vertex_normals()
    V, F = np.asarray(mesh.vertices), np.asarray(mesh.triangles)
    C = np.asarray(mesh.vertex_colors) if mesh.has_vertex_colors() else np.full_like(V, 0.7)
    glb = out / f"2dgs_{tag}.glb"
    ex.safe_write_glb(glb, V, F, srgb_to_linear(C), np.asarray(mesh.vertex_normals),
                      extras={"method": "2dgs", "variant": tag, "source_mesh": src.mesh.name,
                              "coordinate_system": "glTF world: right-handed, +Y up, meters, floor y=0"})
    rep["times_s"]["post"] = round(time.time() - t0, 1)
    rep["metrics"] = ex.mesh_metrics(V, F, proxy)
    bbox = (np.percentile(V0, 0.5, 0), np.percentile(V0, 99.5, 0))
    ex.mesh_preview(out / f"2dgs_{tag}.png", V, F, srgb_to_linear(C), f"2dgs {tag}", bbox=bbox,
                    cams=ex.camera_centers_world(src))
    rep["glb"], rep["preview"] = glb.name, f"2dgs_{tag}.png"
    ex.write_json(out / f"2dgs_{tag}.json", rep)
    m = rep["metrics"]
    ex.log(f"완료 {tag}: 가우시안 {rep['gaussians']:,}, 삼각형 {m['triangles']:,}, 벽 rms {m.get('wall_rms_mm')}mm, "
           f"국소 {m.get('wall_local_rms_mm')}mm, 벽 덮임 {m.get('wall_coverage')}, 시간 {rep['times_s']} → {glb}")


if __name__ == "__main__":
    main()
