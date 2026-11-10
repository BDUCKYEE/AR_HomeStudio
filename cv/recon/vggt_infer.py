"""VGGT 추론 래퍼.

출력 좌표계: VGGT 월드 = 첫 번째 카메라의 OpenCV 카메라 좌표계 (x 오른쪽, y 아래, z 앞), 단위 임의(스케일 미정).
extrinsic 은 OpenCV 규약 camera-from-world [R|t] (S,3,4), intrinsic 은 전처리 이미지 픽셀 기준 (S,3,3).
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageOps

from cv.common.config import env

IMG_EXT = {".jpg", ".jpeg", ".png", ".JPG", ".JPEG", ".PNG", ".webp", ".heic", ".HEIC"}
VGGT_SIZE = 518
PATCH = 14


def list_images(folder: Path) -> list[Path]:
    return sorted(p for p in Path(folder).iterdir() if p.suffix in IMG_EXT)


def oriented_size(p: Path) -> tuple[int, int]:
    """EXIF 회전을 반영한 (가로, 세로), 픽셀 디코딩 없이."""
    im = Image.open(p)
    w, h = im.size
    return (h, w) if im.getexif().get(274) in (5, 6, 7, 8) else (w, h)


def majority_orientation(paths: list[Path]) -> tuple[list[Path], list[Path]]:
    """가로/세로가 섞이면 다수 방향만 남긴다 (섞이면 전부 정사각 패딩돼 해상도 손해). 반환 (남긴 것, 뺀 것)."""
    land = [oriented_size(p)[0] >= oriented_size(p)[1] for p in paths]
    keep_land = sum(land) * 2 >= len(land)
    keep = [p for p, l in zip(paths, land) if l == keep_land]
    return keep, [p for p, l in zip(paths, land) if l != keep_land]


def resolve_weights(weights: str | None = None) -> Path:
    w = Path(weights or env("VGGT_WEIGHTS"))
    if w.is_dir():
        w = w / "model.safetensors"
    if not w.is_file():
        raise FileNotFoundError(f"VGGT 가중치 파일이 없습니다: {w}")
    return w


def load_model(weights: str | None = None, device: str = "cuda"):
    """카메라 + 깊이 헤드만 로드 (track/point 헤드 제외 → 메모리 절약)."""
    from safetensors.torch import load_file
    from vggt.models.vggt import VGGT

    model = VGGT(enable_camera=True, enable_depth=True, enable_point=False, enable_track=False)
    sd = load_file(str(resolve_weights(weights)))
    missing, unexpected = model.load_state_dict(sd, strict=False)
    unexpected = [k for k in unexpected if not k.startswith(("track_head.", "point_head."))]
    if missing or unexpected:
        raise RuntimeError(f"가중치 키 불일치: missing={missing[:5]} unexpected={unexpected[:5]}")
    return model.to(device).eval()


def open_rgb(p: Path, rot90: bool = False) -> Image.Image:
    """EXIF 회전을 적용한 RGB 이미지 (폰 사진은 EXIF 회전 필수). rot90=True면 추가로 반시계 90° 회전
    (세로 사진 → 가로. 원래 아래(+v) 방향이 회전 후 카메라 +x(오른쪽)가 된다)."""
    im = Image.open(p)
    if im.format in ("HEIF", "HEIC") or Path(p).suffix.lower() == ".heic":
        raise RuntimeError(f"HEIC는 지원하지 않습니다. JPG로 변환해 주세요: {p}")
    im = ImageOps.exif_transpose(im)
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        im = Image.alpha_composite(bg, im)
    im = im.convert("RGB")
    return im.transpose(Image.Transpose.ROTATE_90) if rot90 else im


def load_images(paths: list[Path], return_meta: bool = False, rotate_portrait: bool = True):
    """EXIF 회전 적용, 비율 유지, 긴 변 518px, 짧은 변은 14의 배수. 방향이 섞이면 정사각 패딩.

    반환 (S,3,H,W) float [0,1]. return_meta=True면 이미지별 원본→전처리 픽셀 변환
    meta = {orig_wh, scale(sx,sy), offset(ox,oy), valid(x0,y0,x1,y1), rot90} 리스트도 반환: u' = u*sx + ox
    (u는 open_rgb(p, rot90) 이미지 기준 픽셀).

    rotate_portrait: 전부 세로 사진이면 가로로 돌려 넣는다. VGGT는 세로 입력에서 fov_w ≈ fov_h 로 예측해
    fx/fy가 크게 어긋나고(실측 fx 262 vs fy 346, 참값 344) 시점 간 재투영 오차가 수십 px이 됨.
    """
    rot = bool(rotate_portrait) and all(oriented_size(p)[0] < oriented_size(p)[1] for p in paths)
    ims = [open_rgb(p, rot) for p in paths]
    landscape = {im.width >= im.height for im in ims}
    out, metas = [], []
    if len(landscape) == 1:
        # 첫 장 기준 크기로 통일 (같은 폰이면 모두 같은 비율)
        w0, h0 = ims[0].size
        long_, short_ = max(w0, h0), min(w0, h0)
        s = max(PATCH, int(round(VGGT_SIZE * short_ / long_ / PATCH)) * PATCH)
        size = (VGGT_SIZE, s) if w0 >= h0 else (s, VGGT_SIZE)
        for im in ims:
            out.append(np.asarray(im.resize(size, Image.Resampling.BICUBIC)))
            metas.append(dict(orig_wh=im.size, scale=(size[0] / im.width, size[1] / im.height),
                              offset=(0.0, 0.0), valid=(0, 0, size[0], size[1]), rot90=rot))
    else:
        for im in ims:
            sc = VGGT_SIZE / max(im.size)
            nw, nh = round(im.width * sc), round(im.height * sc)
            ox, oy = (VGGT_SIZE - nw) // 2, (VGGT_SIZE - nh) // 2
            canvas = Image.new("RGB", (VGGT_SIZE, VGGT_SIZE), (255, 255, 255))
            canvas.paste(im.resize((nw, nh), Image.Resampling.BICUBIC), (ox, oy))
            out.append(np.asarray(canvas))
            metas.append(dict(orig_wh=im.size, scale=(nw / im.width, nh / im.height),
                              offset=(float(ox), float(oy)), valid=(ox, oy, ox + nw, oy + nh), rot90=rot))
    arr = np.stack(out).astype(np.float32) / 255.0
    t = torch.from_numpy(arr).permute(0, 3, 1, 2).contiguous()
    return (t, metas) if return_meta else t


@torch.no_grad()
def run(model, images: torch.Tensor, device: str = "cuda") -> dict:
    """images (S,3,H,W) [0,1] → numpy dict. timing/메모리 정보 포함."""
    from vggt.utils.pose_enc import pose_encoding_to_extri_intri

    dtype = torch.bfloat16 if torch.cuda.get_device_capability()[0] >= 8 else torch.float16
    torch.cuda.reset_peak_memory_stats(device)
    torch.cuda.synchronize(device)
    t0 = time.perf_counter()
    x = images.to(device)
    with torch.cuda.amp.autocast(dtype=dtype):
        pred = model(x)
    extr, intr = pose_encoding_to_extri_intri(pred["pose_enc"], x.shape[-2:])
    torch.cuda.synchronize(device)
    dt = time.perf_counter() - t0
    res = {
        "images": images.permute(0, 2, 3, 1).numpy(),                      # (S,H,W,3)
        "depth": pred["depth"][0, ..., 0].float().cpu().numpy(),           # (S,H,W)
        "depth_conf": pred["depth_conf"][0].float().cpu().numpy(),         # (S,H,W)
        "extrinsic": extr[0].float().cpu().numpy(),                        # (S,3,4) cam-from-world
        "intrinsic": intr[0].float().cpu().numpy(),                        # (S,3,3)
        "time_s": dt,
        "peak_alloc_gb": torch.cuda.max_memory_allocated(device) / 1024**3,
        "peak_reserved_gb": torch.cuda.max_memory_reserved(device) / 1024**3,
    }
    del pred, x
    torch.cuda.empty_cache()
    return res


def unproject(depth: np.ndarray, extr: np.ndarray, intr: np.ndarray) -> np.ndarray:
    """깊이 (H,W) → VGGT 월드 좌표 (H,W,3). OpenCV 카메라 → VGGT 월드(첫 카메라 OpenCV 좌표계)."""
    H, W = depth.shape
    u, v = np.meshgrid(np.arange(W, dtype=np.float32), np.arange(H, dtype=np.float32))
    fx, fy, cx, cy = intr[0, 0], intr[1, 1], intr[0, 2], intr[1, 2]
    pc = np.stack([(u - cx) / fx * depth, (v - cy) / fy * depth, depth], -1)
    R, t = extr[:, :3], extr[:, 3]
    return (pc - t) @ R  # R^T (pc - t)


