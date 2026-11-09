"""cv 환경 확인: torch/CUDA/GPU, VGGT import + 가중치 로드, Open3D, OpenCV(aruco), trimesh.

사용: source cv/env.sh && python -m cv.recon.check_env
"""
from __future__ import annotations

import importlib


def main() -> None:
    ok = True
    import numpy as np
    import torch

    print(f"python numpy {np.__version__}, torch {torch.__version__} (CUDA {torch.version.cuda})")
    print(f"torch.cuda.is_available() = {torch.cuda.is_available()}, device_count = {torch.cuda.device_count()}")
    for i in range(torch.cuda.device_count()):
        p = torch.cuda.get_device_properties(i)
        print(f"  cuda:{i} {p.name} {p.total_memory / 1024**3:.1f} GB, cc {p.major}.{p.minor}")
    if not torch.cuda.is_available():
        ok = False

    for mod in ["open3d", "cv2", "trimesh", "yaml", "dotenv", "vggt"]:
        try:
            m = importlib.import_module(mod)
            print(f"import {mod}: OK {getattr(m, '__version__', '')}")
        except Exception as e:  # noqa: BLE001
            ok = False
            print(f"import {mod}: FAIL {e}")
    import cv2

    has = all(hasattr(cv2.aruco, n) for n in ["CharucoBoard", "CharucoDetector", "getPredefinedDictionary"])
    print(f"cv2.aruco ChArUco API: {'OK' if has else 'FAIL'}")
    ok &= has

    import open3d as o3d

    print(f"open3d CUDA build: {o3d.core.cuda.is_available()}")

    from cv.recon.vggt_infer import load_model, resolve_weights

    w = resolve_weights()
    m = load_model(device="cuda:0")
    n = sum(p.numel() for p in m.parameters())
    print(f"VGGT weights {w} → 로드 OK ({n / 1e9:.2f}B params, track/point head 제외)")
    print("ALL OK" if ok else "SOME CHECKS FAILED")


if __name__ == "__main__":
    main()
