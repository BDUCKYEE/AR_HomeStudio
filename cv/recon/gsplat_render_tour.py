"""3DGS(gsplat) 방 둘러보기 영상: 학습 카메라를 촬영 순서(파일 이름 순)대로 부드럽게 이어 렌더 (envs/gsplat, GPU 0).

  ${ENVS_ROOT}/gsplat/.venv/bin/python cv/recon/gsplat_render_tour.py <colmap 폴더> <출력 mp4> <ckpt1.pt> [<ckpt2.pt> ...] \
      [--labels 끔 켬] [--steps 4] [--scale 0.5]

체크포인트를 여러 개 주면 같은 경로를 나란히 렌더한다 (포즈 최적화 끔/켬 비교). 경로는 VGGT 포즈(보정 전)를 쓴다.
카메라 사이 = 위치 선형 보간 + 회전 구면 보간, 카메라당 --steps 프레임. 세로 사진이라 화면은 원본 방향(가로)으로 렌더.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ENVS_ROOT = Path(os.environ.get("ENVS_ROOT", "/storage/AI/cv_project/envs"))
sys.path.insert(0, str(ENVS_ROOT / "gsplat" / "gsplat" / "examples"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("data")
    ap.add_argument("out")
    ap.add_argument("ckpts", nargs="+")
    ap.add_argument("--labels", nargs="+")
    ap.add_argument("--steps", type=int, default=4)
    ap.add_argument("--scale", type=float, default=0.5)
    a = ap.parse_args()
    import cv2
    import imageio.v2 as iio
    import numpy as np
    import torch
    from datasets.colmap import Parser
    from gsplat import rasterization
    from scipy.spatial.transform import Rotation, Slerp

    dev = "cuda"
    parser = Parser(data_dir=a.data, factor=1, normalize=False, test_every=8)
    order = np.argsort(parser.image_names)
    C2W = parser.camtoworlds[order]
    K0 = parser.Ks_dict[parser.camera_ids[order[0]]].copy()
    W0, H0 = parser.imsize_dict[parser.camera_ids[order[0]]]
    W, H = int(W0 * a.scale) // 2 * 2, int(H0 * a.scale) // 2 * 2
    K = K0.copy()
    K[:2] *= a.scale
    # 경로: 이웃 카메라 사이를 steps 프레임으로
    path = []
    for i in range(len(C2W) - 1):
        r = Rotation.from_matrix([C2W[i][:3, :3], C2W[i + 1][:3, :3]])
        sl = Slerp([0, 1], r)
        for t in np.linspace(0, 1, a.steps, endpoint=False):
            M = np.eye(4)
            M[:3, :3] = sl([t]).as_matrix()[0]
            M[:3, 3] = (1 - t) * C2W[i][:3, 3] + t * C2W[i + 1][:3, 3]
            path.append(M)
    # 영상이 너무 덜컹거리지 않게 위치를 이동 평균으로 살짝 다듬음
    P = np.array([m[:3, 3] for m in path])
    k = 5
    Ps = np.array([P[max(0, j - k):j + k + 1].mean(0) for j in range(len(P))])
    for m, p in zip(path, Ps):
        m[:3, 3] = p
    models = []
    for ck in a.ckpts:
        sp = torch.load(ck, map_location=dev)["splats"]
        models.append((sp, torch.cat([sp["sh0"], sp["shN"]], 1)))
    labels = a.labels or [Path(c).parent.parent.name for c in a.ckpts]
    Kt = torch.tensor(K, dtype=torch.float32, device=dev)[None]
    w = iio.get_writer(a.out, fps=30, codec="libx264", quality=7, macro_block_size=2)
    with torch.no_grad():
        for M in path:
            vm = torch.linalg.inv(torch.tensor(M, dtype=torch.float32, device=dev))[None]
            tiles = []
            for (sp, col), lab in zip(models, labels):
                img, _, _ = rasterization(means=sp["means"], quats=sp["quats"], scales=torch.exp(sp["scales"]),
                                          opacities=torch.sigmoid(sp["opacities"]), colors=col, viewmats=vm, Ks=Kt,
                                          width=W, height=H, sh_degree=3, rasterize_mode="classic")
                t = (img[0].clamp(0, 1).cpu().numpy() * 255).astype(np.uint8).copy()
                cv2.putText(t, lab, (10, 32), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 0), 2)
                tiles.append(t)
            w.append_data(np.hstack(tiles))
    w.close()
    print(f"{a.out}: {len(path)} 프레임 ({len(path) / 30:.1f}s), {W * len(models)}×{H}")


if __name__ == "__main__":
    main()
