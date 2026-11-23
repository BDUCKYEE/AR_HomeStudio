"""VGGT 결과(build_room 의 recon_debug) → COLMAP 텍스트 모델 + 이미지. 2DGS 등 COLMAP 입력 도구용.

사용 (메인 .venv):
  python -m cv.recon.export_colmap [대상] [--width 1600] [--out <폴더>]
  기본 출력: ${SHARED_DIR}/meshes/experiments/2dgs/<이름>/colmap_vggt/{images/, sparse/0/*.txt}

좌표: COLMAP 의 world 는 우리 월드(glTF, +Y 위, 미터, 바닥 y=0)를 그대로 쓴다. COLMAP 카메라 규약(x 오른쪽,
y 아래, z 앞, camera-from-world)은 OpenCV 와 같으므로 cameras.json 의 camera_from_world_4x4 를 변환 없이 쓴다.
→ COLMAP/2DGS 산출물도 우리 월드 좌표 그대로 (축 변환 없음).

이미지 방향: build_room 이 세로 사진을 반시계 90° 돌려 VGGT 에 넣었으면(rot90) 같은 방향으로 저장한다.
내부 파라미터: VGGT 입력 해상도(예 518×392) 기준 K 를 축별로 출력 해상도에 맞게 늘린다 (PINHOLE, 이미지마다 카메라 1개).
points3D: recon_debug/points.ply (신뢰도 필터 후 VGGT 점, 미터) 를 최대 --max-points 개로 줄여 초기 점으로 넣는다.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

from cv.recon import experiments as ex


def rotmat_to_qvec(R: np.ndarray) -> np.ndarray:
    """회전행렬 → COLMAP 쿼터니언 (w, x, y, z)."""
    K = np.array([[R[0, 0] - R[1, 1] - R[2, 2], 0, 0, 0],
                  [R[1, 0] + R[0, 1], R[1, 1] - R[0, 0] - R[2, 2], 0, 0],
                  [R[2, 0] + R[0, 2], R[2, 1] + R[1, 2], R[2, 2] - R[0, 0] - R[1, 1], 0],
                  [R[2, 1] - R[1, 2], R[0, 2] - R[2, 0], R[1, 0] - R[0, 1], R[0, 0] + R[1, 1] + R[2, 2]]]) / 3.0
    w, V = np.linalg.eigh(K)
    q = V[[3, 0, 1, 2], np.argmax(w)]
    return -q if q[0] < 0 else q


def export(src: ex.Source, out: Path, width: int = 1600, max_points: int = 200_000) -> dict:
    from cv.recon.vggt_infer import open_rgb

    cams = json.loads(src.cameras.read_text())
    E = np.asarray(cams["camera_from_world_4x4"])
    Kv = np.asarray(cams["intrinsic_vggt_px"])
    vw, vh = cams["vggt_image_size_wh"]
    img_dir = Path(src.meta.get("source_images") or "")
    if not img_dir.is_dir():
        raise SystemExit(f"원본 이미지 폴더가 없습니다: {img_dir} (meshes/<이름>.json 의 source_images)")
    rot = vw > vh   # build_room: 세로 사진을 가로로 돌려 넣었으면 VGGT 입력이 가로
    (out / "images").mkdir(parents=True, exist_ok=True)
    (out / "sparse" / "0").mkdir(parents=True, exist_ok=True)
    cam_lines, img_lines = [], []
    size = None
    for i, name in enumerate(cams["images"]):
        im = open_rgb(img_dir / name, rot90=rot and _is_portrait(img_dir / name))
        H = round(width * im.height / im.width)
        size = (width, H)
        dst = out / "images" / (Path(name).stem + ".jpg")
        if not dst.exists():
            im.resize(size, Image.Resampling.LANCZOS).save(dst, quality=95)
        sx, sy = width / vw, H / vh
        fx, fy, cx, cy = Kv[i, 0, 0] * sx, Kv[i, 1, 1] * sy, Kv[i, 0, 2] * sx, Kv[i, 1, 2] * sy
        cam_lines.append(f"{i + 1} PINHOLE {width} {H} {fx:.6f} {fy:.6f} {cx:.6f} {cy:.6f}")
        q = rotmat_to_qvec(E[i, :3, :3])
        t = E[i, :3, 3]
        img_lines.append(f"{i + 1} {q[0]:.9f} {q[1]:.9f} {q[2]:.9f} {q[3]:.9f} {t[0]:.9f} {t[1]:.9f} {t[2]:.9f} {i + 1} {dst.name}")
        img_lines.append("")   # 2D 점 없음
    sp = out / "sparse" / "0"
    (sp / "cameras.txt").write_text("# Camera list: CAMERA_ID MODEL W H fx fy cx cy\n" + "\n".join(cam_lines) + "\n")
    (sp / "images.txt").write_text("# IMAGE_ID QW QX QY QZ TX TY TZ CAMERA_ID NAME\n" + "\n".join(img_lines) + "\n")
    P, C = ex.load_points(src)
    if len(P) > max_points:
        k = np.random.default_rng(0).choice(len(P), max_points, replace=False)
        P, C = P[k], C[k]
    rgb = (np.clip(C, 0, 1) * 255).round().astype(int)
    with open(sp / "points3D.txt", "w") as f:
        f.write("# POINT3D_ID X Y Z R G B ERROR TRACK[]\n")
        for j, (p, c) in enumerate(zip(P, rgb)):
            f.write(f"{j + 1} {p[0]:.5f} {p[1]:.5f} {p[2]:.5f} {c[0]} {c[1]} {c[2]} 0\n")
    info = {"images": len(cams["images"]), "size": size, "points3D": int(len(P)), "rot90": bool(rot), "dir": str(out)}
    (out / "export.json").write_text(json.dumps(info, indent=1))
    return info


def _is_portrait(p: Path) -> bool:
    from cv.recon.vggt_infer import oriented_size

    w, h = oriented_size(p)
    return w < h


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", nargs="?")
    ap.add_argument("--width", type=int, default=1600)
    ap.add_argument("--max-points", type=int, default=200_000)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    src = ex.resolve_source(a.target)
    out = a.out or ex.out_dir("2dgs", src) / "colmap_vggt"
    ex.log(f"내보내기 {src.stem} → {out}")
    ex.log(json.dumps(export(src, out, a.width, a.max_points), ensure_ascii=False))


if __name__ == "__main__":
    main()
