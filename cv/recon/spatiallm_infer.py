"""SpatialLM 추론 (envs/spatiallm 의 파이썬으로 실행, GPU 1). 보통은 run_spatiallm.py 가 호출한다.

  ${ENVS_ROOT}/spatiallm/.venv/bin/python cv/recon/spatiallm_infer.py <입력 z-up ply> <출력 json> \
      [--model manycore-research/SpatialLM1.1-Qwen-0.5B] [--detect-type all] [--seed 0]

입력 좌표: SpatialLM 규약 (z 위, 벽이 x/y 축에 정렬, 미터). 출력 json 도 같은 z-up 좌표다 (변환은 run_spatiallm.py 에서).
SpatialLM 저장소의 inference.py 와 같은 순서: 복셀 정리(cleanup_pcd) → GridSample → generate → 원래 위치로 이동.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
import time
from pathlib import Path

ENVS_ROOT = Path(os.environ.get("ENVS_ROOT", "/storage/AI/cv_project/envs"))
REPO = ENVS_ROOT / "spatiallm" / "SpatialLM"
sys.path.insert(0, str(REPO))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("ply")
    ap.add_argument("out")
    ap.add_argument("--model", default="manycore-research/SpatialLM1.1-Qwen-0.5B")
    ap.add_argument("--detect-type", default="all", choices=["all", "arch", "object"])
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    import numpy as np
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    sys.argv = [sys.argv[0]]                       # inference.py 의 argparse 와 충돌 방지
    import inference as sl                         # 저장소 inference.py (preprocess_point_cloud, generate_layout)
    from spatiallm import Layout
    from spatiallm.pcd import cleanup_pcd, get_points_and_colors, load_o3d_pcd

    t0 = time.time()
    tok = AutoTokenizer.from_pretrained(a.model)
    model = AutoModelForCausalLM.from_pretrained(a.model, torch_dtype=torch.bfloat16)
    model.to("cuda")
    model.set_point_backbone_dtype(torch.float32)
    model.eval()
    t1 = time.time()
    num_bins = model.config.point_config["num_bins"]
    grid = Layout.get_grid_size(num_bins)
    pcd = cleanup_pcd(load_o3d_pcd(a.ply), voxel_size=grid)
    pts, cols = get_points_and_colors(pcd)
    min_extent = np.min(pts, axis=0)
    inp = sl.preprocess_point_cloud(pts, cols, grid, num_bins)
    layout = sl.generate_layout(model, inp, tok, str(REPO / "code_template.txt"), seed=a.seed, detect_type=a.detect_type)
    layout.translate(min_extent)
    t2 = time.time()
    res = {
        "model": a.model, "detect_type": a.detect_type, "seed": a.seed, "grid_size_m": grid, "num_bins": num_bins,
        "points_after_cleanup": int(len(pts)), "time_load_s": round(t1 - t0, 2), "time_infer_s": round(t2 - t1, 2),
        "gpu_peak_gb": round(torch.cuda.max_memory_allocated() / 1024 ** 3, 2),
        "language": layout.to_language_string(),
        "walls": [dataclasses.asdict(w) for w in layout.walls],
        "doors": [dataclasses.asdict(d) for d in layout.doors],
        "windows": [dataclasses.asdict(w) for w in layout.windows],
        "bboxes": [dataclasses.asdict(b) for b in layout.bboxes],
    }
    Path(a.out).write_text(json.dumps(res, indent=1, default=float))
    print(f"walls {len(res['walls'])}, doors {len(res['doors'])}, windows {len(res['windows'])}, boxes {len(res['bboxes'])}, "
          f"load {res['time_load_s']}s, infer {res['time_infer_s']}s, peak {res['gpu_peak_gb']}GB", flush=True)


if __name__ == "__main__":
    main()
