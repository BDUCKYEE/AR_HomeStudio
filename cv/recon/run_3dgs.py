"""3. 3DGS(gsplat) 시점 합성: VGGT 포즈 초기값, 포즈 최적화 켬/끔 두 가지 학습 → PSNR/SSIM/LPIPS, 떠다니는 조각, 렌더 영상

사용 (메인 .venv 에서 실행, 학습은 envs/gsplat 의 공식 예제 트레이너를 하위 프로세스로, GPU 0):
  python -m cv.recon.run_3dgs                       # room_latest.json 이 가리키는 메시, 포즈 최적화 끔/켬 둘 다
  python -m cv.recon.run_3dgs room_20261124_myroom2-charuco --variants noposeopt --steps 30000

환경 준비 (한 번): bash cv/recon/envs/setup_gsplat.sh

출력: ${SHARED_DIR}/meshes/experiments/3dgs/<이름>/
  colmap_vggt/              VGGT 포즈 COLMAP 모델(txt+bin) + 1600×1200 이미지 (export_colmap, 월드 좌표 그대로)
  model_<변형>/             gsplat 결과 (ckpts, ply, stats, renders = 평가 시점 GT|렌더, videos/traj_*.mp4)
  3dgs_<변형>.mp4           학습 시점 사이를 잇는 렌더 영상 (트레이너의 interp 궤적)
  3dgs_compare.mp4          두 변형을 나란히 (트레이너 기본 궤적, 왼쪽 끔 / 오른쪽 켬)
  3dgs_tour_compare.mp4     학습 카메라를 촬영 순서대로 잇는 둘러보기 (gsplat_render_tour.py, 약 16초)
  3dgs_compare.png          평가 시점 몇 장: 원본 | 포즈 최적화 끔 | 켬
  3dgs_metrics.json         변형별 PSNR/SSIM/LPIPS(평가 15장 = 8장마다 1장), 학습 시점 PSNR(gsplat_eval_train.py),
                            가우시안 수, 학습 시간, 떠다니는 조각

평가 주의: 포즈 최적화는 학습 시점 포즈만 고친다. 평가 시점은 VGGT 포즈 그대로 렌더하므로, 포즈 최적화가
학습 장면을 VGGT 좌표에서 조금 옮기면 평가 PSNR 이 오히려 떨어질 수 있다 (평가 시점 포즈 보정은 하지 않음).
떠다니는 조각: 불투명도 > 0.05 인 가우시안 중 방 안(프록시 바닥 다각형 범위 × 바닥~천장)에 있으면서
원본 TSDF 메시 표면에서 10cm 넘게 떨어진 것의 비율 (개수, 불투명도 가중). 방 밖(벽 너머) 비율은 따로.
TSDF 메시에도 구멍이 있어 절대값보다 두 변형의 상대 비교로 본다.
좌표: 월드 정규화(normalize_world_space)를 끄고 학습하므로 가우시안도 우리 월드(glTF, +Y 위, 미터) 그대로.
"""
from __future__ import annotations

import os

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")   # 3DGS 학습은 GPU 0 (사용자 지시)

import argparse  # noqa: E402
import glob  # noqa: E402
import json  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

from cv.recon import experiments as ex  # noqa: E402
from cv.recon.export_colmap import export  # noqa: E402

ENVS_ROOT = Path(os.environ.get("ENVS_ROOT", "/storage/AI/cv_project/envs"))
ENV_PY = ENVS_ROOT / "gsplat" / ".venv" / "bin" / "python"
EXAMPLES = ENVS_ROOT / "gsplat" / "gsplat" / "examples"
VARIANTS = {"noposeopt": ["--no-pose-opt"], "poseopt": ["--pose-opt"]}


def read_ply(path: Path) -> dict:
    """gsplat 이 내보낸 3DGS ply (binary_little_endian, float 속성) → {속성 이름: 배열}."""
    data = Path(path).read_bytes()
    end = data.index(b"end_header\n") + len(b"end_header\n")
    head = data[:end].decode()
    n = int([ln for ln in head.split("\n") if ln.startswith("element vertex")][0].split()[-1])
    props = [ln.split() for ln in head.split("\n") if ln.startswith("property")]
    types = {"float": "<f4", "double": "<f8", "uchar": "u1", "int": "<i4", "uint": "<u4"}
    dt = np.dtype([(p[2], types[p[1]]) for p in props])
    arr = np.frombuffer(data, dtype=dt, count=n, offset=end)
    return {k: np.asarray(arr[k]) for k in dt.names}


def floaters(ply: Path, src: ex.Source, proxy: dict | None) -> dict:
    import open3d as o3d

    g = read_ply(ply)
    X = np.stack([g["x"], g["y"], g["z"]], 1).astype(np.float64)
    alpha = 1 / (1 + np.exp(-g["opacity"].astype(np.float64)))
    vis = alpha > 0.05
    V, F, _ = ex.load_mesh(src.mesh)
    scene = o3d.t.geometry.RaycastingScene()
    scene.add_triangles(o3d.core.Tensor(V.astype(np.float32)), o3d.core.Tensor(F.astype(np.uint32)))
    d = scene.compute_distance(o3d.core.Tensor(X.astype(np.float32))).numpy()
    if proxy is not None:
        fp = np.asarray(proxy["room"]["footprint"])
        inside = ex._inside_poly2d_raster(X[:, [0, 2]], fp) & (X[:, 1] > -0.05) & (X[:, 1] < proxy["room"]["height_m"] + 0.05)
    else:
        lo, hi = np.percentile(V, 1, 0), np.percentile(V, 99, 0)
        inside = ((X > lo) & (X < hi)).all(1)
    fl = vis & inside & (d > 0.10)
    out = vis & ~inside
    return {"gaussians": int(len(X)), "visible": int(vis.sum()),
            "floater_frac": round(float(fl.sum() / max(vis.sum(), 1)), 4),
            "floater_frac_alpha": round(float(alpha[fl].sum() / max(alpha[vis].sum(), 1e-9)), 4),
            "outside_room_frac": round(float(out.sum() / max(vis.sum(), 1)), 4),
            "median_dist_to_mesh_mm": round(float(np.median(d[vis & inside])) * 1000, 1)}


def run_env(code: str, log: Path) -> None:
    """gsplat 환경 파이썬으로 짧은 스크립트 실행 (영상 합성 등, imageio-ffmpeg 사용)."""
    with open(log, "a") as f:
        subprocess.run([str(ENV_PY), "-c", code], stdout=f, stderr=subprocess.STDOUT, check=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", nargs="?")
    ap.add_argument("--variants", nargs="+", default=list(VARIANTS), choices=list(VARIANTS))
    ap.add_argument("--steps", type=int, default=30000)
    ap.add_argument("--reexport", action="store_true")
    a = ap.parse_args()
    if not ENV_PY.exists():
        raise SystemExit(f"gsplat 환경이 없습니다: {ENV_PY}. bash cv/recon/envs/setup_gsplat.sh 를 먼저 실행하세요.")
    src = ex.resolve_source(a.target)
    out = ex.out_dir("3dgs", src)
    data = out / "colmap_vggt"
    if a.reexport or not (data / "sparse" / "0" / "images.bin").exists():
        export(src, data)
    proxy = ex.reference_proxy(src)
    mpath = out / "3dgs_metrics.json"
    res = json.loads(mpath.read_text()) if mpath.exists() else {"source": src.stem, "variants": {}}
    last = a.steps - 1
    for v in a.variants:
        model = out / f"model_{v}"
        stats_f = model / "stats" / f"val_step{last:04d}.json"
        t_train = None
        if not stats_f.exists():
            cmd = [str(ENV_PY), "simple_trainer.py", "default", "--data-dir", str(data), "--data-factor", "1",
                   "--result-dir", str(model), "--no-normalize-world-space", "--disable-viewer", "--save-ply",
                   "--max-steps", str(a.steps), "--eval-steps", "7000", str(a.steps), "--save-steps", str(a.steps),
                   "--ply-steps", str(a.steps), "--test-every", "8", *VARIANTS[v]]
            ex.log(f"[{v}] 학습: {' '.join(cmd[1:])}")
            t0 = time.time()
            with open(out / f"train_{v}.log", "w") as f:
                p = subprocess.run(cmd, cwd=EXAMPLES, stdout=f, stderr=subprocess.STDOUT,
                                   env=dict(os.environ, CUDA_VISIBLE_DEVICES="0"))
            t_train = round(time.time() - t0, 1)
            if p.returncode != 0:
                tail = "".join(open(out / f"train_{v}.log", errors="replace").readlines()[-25:])
                raise SystemExit(f"[{v}] 학습 실패 ({t_train}s). 로그 {out / f'train_{v}.log'}\n{tail}")
        st = json.loads(stats_f.read_text())
        tr = sorted(glob.glob(str(model / "stats" / "train_step*_rank0.json")))
        trs = json.loads(Path(tr[-1]).read_text()) if tr else {}
        ply = sorted(glob.glob(str(model / "ply" / "*.ply")))[-1]
        te = model / "train_eval.json"
        if not te.exists():          # 학습 시점 PSNR (평가 시점과의 차이 = 일반화 실패 정도)
            ck = sorted(glob.glob(str(model / "ckpts" / "*.pt")))[-1]
            subprocess.run([str(ENV_PY), str(Path(__file__).with_name("gsplat_eval_train.py")), str(data), ck, str(te)],
                           check=True, env=dict(os.environ, CUDA_VISIBLE_DEVICES="0"), capture_output=True)
        tev = json.loads(te.read_text())
        prev = res["variants"].get(v, {})
        row = {"psnr": round(st["psnr"], 3), "ssim": round(st["ssim"], 4), "lpips": round(st["lpips"], 4),
               "psnr_train": tev["psnr_train"], "ssim_train": tev["ssim_train"],
               "num_gs": st.get("num_GS"), "train_time_s": t_train or prev.get("train_time_s") or round(trs.get("ellipse_time", 0), 1),
               "gpu_mem_gb": round(trs.get("mem", 0), 2), "render_s_per_image": round(st.get("ellipse_time", 0), 4),
               **floaters(Path(ply), src, proxy)}
        vids = sorted(glob.glob(str(model / "videos" / "traj_*.mp4")))
        if vids:
            dst = out / f"3dgs_{v}.mp4"
            dst.write_bytes(Path(vids[-1]).read_bytes())
            row["video"] = dst.name
        res["variants"][v] = row
        ex.log(f"[{v}] PSNR {row['psnr']} (학습 시점 {row['psnr_train']}) SSIM {row['ssim']} LPIPS {row['lpips']} 가우시안 {row['num_gs']:,} "
               f"떠다님 {row['floater_frac']:.1%} (불투명도 가중 {row['floater_frac_alpha']:.1%}) 방 밖 {row['outside_room_frac']:.1%} "
               f"학습 {row['train_time_s']}s")
        mpath.write_text(json.dumps(res, ensure_ascii=False, indent=1))

    vs = [v for v in VARIANTS if v in res["variants"]]
    if len(vs) == 2:
        m0, m1 = (out / f"model_{v}" for v in vs)
        code = f'''
import glob, imageio.v2 as iio, numpy as np, cv2
def lab(im, t):
    im = np.ascontiguousarray(im); cv2.putText(im, t, (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 0), 3); return im
# 평가 시점 비교 그림: 원본 | 끔 | 켬 (renders/val_step*_XXXX.png = GT|렌더 가로 이어붙임)
r0 = sorted(glob.glob("{m0}/renders/val_step{last}_*.png")); r1 = sorted(glob.glob("{m1}/renders/val_step{last}_*.png"))
rows = []
for f0, f1 in list(zip(r0, r1))[::max(1, len(r0) // 4)][:4]:
    a, b = iio.imread(f0)[..., :3], iio.imread(f1)[..., :3]; w = a.shape[1] // 2
    row = np.hstack([lab(a[:, :w], "GT"), lab(a[:, w:], "pose-opt OFF"), lab(b[:, w:], "pose-opt ON")])
    rows.append(cv2.resize(row, (row.shape[1] // 2, row.shape[0] // 2)))
iio.imwrite("{out}/3dgs_compare.png", np.vstack(rows))
# 궤적 영상 나란히
ra = iio.get_reader(sorted(glob.glob("{m0}/videos/traj_*.mp4"))[-1]); rb = iio.get_reader(sorted(glob.glob("{m1}/videos/traj_*.mp4"))[-1])
w = iio.get_writer("{out}/3dgs_compare.mp4", fps=30, codec="libx264", quality=7, macro_block_size=8)
for fa, fb in zip(ra, rb):
    fr = np.hstack([lab(fa, "pose-opt OFF"), lab(fb, "pose-opt ON")])
    w.append_data(cv2.resize(fr, ((fr.shape[1] // 2) // 8 * 8, (fr.shape[0] // 2) // 8 * 8)))
w.close()
print("ok")
'''
        run_env(code, out / "compare_media.log")
        res["compare_png"], res["compare_mp4"] = "3dgs_compare.png", "3dgs_compare.mp4"
        # 학습 카메라를 촬영 순서대로 잇는 16초 둘러보기 (왼쪽 끔 / 오른쪽 켬)
        tour = out / "3dgs_tour_compare.mp4"
        if not tour.exists():
            cks = [sorted(glob.glob(str(m / "ckpts" / "*.pt")))[-1] for m in (m0, m1)]
            with open(out / "compare_media.log", "a") as f:
                subprocess.run([str(ENV_PY), str(Path(__file__).with_name("gsplat_render_tour.py")), str(data), str(tour),
                                *cks, "--labels", "pose-opt OFF", "pose-opt ON"], stdout=f, stderr=subprocess.STDOUT,
                               check=True, env=dict(os.environ, CUDA_VISIBLE_DEVICES="0"))
        res["tour_mp4"] = tour.name
        mpath.write_text(json.dumps(res, ensure_ascii=False, indent=1))
    ex.log(f"완료 → {out}")


if __name__ == "__main__":
    main()
