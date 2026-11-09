"""VGGT 이미지 수별 GPU 메모리/시간 측정.

사용: CUDA_VISIBLE_DEVICES=0 python -m cv.recon.bench_vggt --images <폴더> --counts 1 2 4 8 16 24 32 48 64
이미지가 부족하면 반복해서 채운다 (메모리/시간은 이미지 수와 해상도에만 의존).
"""
from __future__ import annotations

import argparse
from pathlib import Path

import torch

from cv.recon.vggt_infer import list_images, load_images, load_model, run


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", required=True, type=Path)
    ap.add_argument("--counts", type=int, nargs="+", default=[1, 2, 4, 8, 16, 24, 32, 48, 64, 80, 100])
    ap.add_argument("--repeat", type=int, default=2, help="N별 반복 횟수 (최소 시간 기록)")
    a = ap.parse_args()

    paths = list_images(a.images)
    model = load_model(device="cuda:0")
    base = torch.cuda.memory_allocated() / 1024**3
    allimgs = load_images(paths)
    print(f"모델 가중치 상주 메모리 {base:.2f} GB, 입력 {tuple(allimgs.shape[1:])}, 원본 {len(paths)}장")
    run(model, allimgs[:2])  # warmup
    print("| 이미지 수 | 시간 (s) | 최대 할당 (GB) | 최대 예약 (GB) |")
    print("|---:|---:|---:|---:|")
    for n in a.counts:
        idx = [i % len(paths) for i in range(n)]
        imgs = allimgs[idx]
        try:
            rs = [run(model, imgs) for _ in range(a.repeat)]
        except torch.cuda.OutOfMemoryError:
            print(f"| {n} | OOM | - | - |")
            torch.cuda.empty_cache()
            break
        t = min(r["time_s"] for r in rs)
        print(f"| {n} | {t:.2f} | {max(r['peak_alloc_gb'] for r in rs):.2f} | "
              f"{max(r['peak_reserved_gb'] for r in rs):.2f} |", flush=True)


if __name__ == "__main__":
    main()
