"""3DGS(gsplat) 학습 시점 PSNR/SSIM (envs/gsplat 파이썬으로 실행, run_3dgs.py 가 부름).

  ${ENVS_ROOT}/gsplat/.venv/bin/python cv/recon/gsplat_eval_train.py <colmap 폴더> <ckpt.pt> <출력 json> [--every 8]

평가 시점(8장마다 1장) PSNR 이 낮을 때, 모델이 학습 사진을 잘 재현하는지(학습 PSNR 높음 → 포즈 오차·시점 부족 문제)
아예 못 맞추는지(학습 PSNR 도 낮음)를 가르기 위한 것. 포즈 최적화를 켠 모델은 학습 시점에 보정된 포즈로 렌더한다.
트레이너와 같은 Parser(월드 정규화 끔, factor 1)와 같은 rasterization 설정(classic, SH 3)을 쓴다.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ENVS_ROOT = Path(os.environ.get("ENVS_ROOT", "/storage/AI/cv_project/envs"))
sys.path.insert(0, str(ENVS_ROOT / "gsplat" / "gsplat" / "examples"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("data")
    ap.add_argument("ckpt")
    ap.add_argument("out")
    ap.add_argument("--every", type=int, default=8)
    a = ap.parse_args()
    import torch
    from datasets.colmap import Dataset, Parser
    from fused_ssim import fused_ssim
    from gsplat import rasterization
    from utils import CameraOptModule

    dev = "cuda"
    parser = Parser(data_dir=a.data, factor=1, normalize=False, test_every=8)
    train = Dataset(parser, split="train")
    ck = torch.load(a.ckpt, map_location=dev)
    sp = ck["splats"]
    colors = torch.cat([sp["sh0"], sp["shN"]], 1)
    pose = None
    if "pose_adjust" in ck:
        pose = CameraOptModule(len(train)).to(dev)
        pose.load_state_dict(ck["pose_adjust"])
    psnrs, ssims = [], []
    with torch.no_grad():
        for i in range(0, len(train), a.every):
            d = train[i]
            c2w = d["camtoworld"][None].to(dev)
            if pose is not None:
                c2w = pose(c2w, torch.tensor([d["image_id"]], device=dev))
            gt = d["image"][None].to(dev) / 255.0
            H, W = gt.shape[1:3]
            img, _, _ = rasterization(means=sp["means"], quats=sp["quats"], scales=torch.exp(sp["scales"]),
                                      opacities=torch.sigmoid(sp["opacities"]), colors=colors,
                                      viewmats=torch.linalg.inv(c2w), Ks=d["K"][None].to(dev), width=W, height=H,
                                      sh_degree=3, rasterize_mode="classic")
            img = img.clamp(0, 1)
            mse = torch.mean((img - gt) ** 2)
            psnrs.append(float(-10 * torch.log10(mse)))
            ssims.append(float(fused_ssim(img.permute(0, 3, 1, 2), gt.permute(0, 3, 1, 2), padding="valid")))
    res = {"train_views": len(psnrs), "psnr_train": round(sum(psnrs) / len(psnrs), 3),
           "ssim_train": round(sum(ssims) / len(ssims), 4), "pose_opt": pose is not None}
    Path(a.out).write_text(json.dumps(res, indent=1))
    print(json.dumps(res))


if __name__ == "__main__":
    main()
