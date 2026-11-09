"""방 메시 파이프라인: 이미지 폴더 → VGGT → 신뢰도 필터 → 바닥 RANSAC 정렬 → 스케일 보정 → TSDF → 정리/간소화 → .glb

사용 (GPU 0):
  source cv/env.sh
  python -m cv.recon.build_room ${SHARED_DIR}/scans/<폴더> --desc myroom
  python -m cv.recon.build_room <폴더> --desc myroom --room-size 3.3 2.5     # ChArUco 실패 시 실측 방 크기로 대체
  python -m cv.recon.build_room <폴더> --desc test --cam-height 1.4         # 실패 시 촬영 높이(m)로 대체

출력 (${SHARED_DIR}/meshes/):
  room_<YYYYMMDD>_<desc>.glb, room_latest.glb, room_latest.json
디버그 (${SHARED_DIR}/recon_debug/<이름>/): points.ply, cameras.json, preview.png, report.json

순서 메모: 바닥 정렬과 스케일은 신뢰도 필터 후 점구름에서 먼저 추정하고, TSDF는 이미 미터 단위 월드 좌표에서 적분한다.
(TSDF→정렬→스케일과 결과는 같지만 복셀 크기, 깊이 상한을 미터로 지정할 수 있다.)

좌표: VGGT 월드(첫 카메라 OpenCV 좌표계) → [바닥 정렬 + 스케일, 이 파일에서 한 번] → 월드(glTF, +Y 위, 미터).
"""
from __future__ import annotations

import os

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")   # VGGT/Open3D는 GPU 0 (CLAUDE.md)

import argparse  # noqa: E402
import datetime as dt  # noqa: E402
import json  # noqa: E402
import shutil  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402
import open3d as o3d  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from cv.calib.charuco import load_charuco  # noqa: E402
from cv.common.config import load_yaml, shared_dir  # noqa: E402
from cv.recon import scale as sc  # noqa: E402
from cv.recon.geometry import Sim3, camera_centers, extrinsic_after, find_floor, manhattan_yaw, rot_y  # noqa: E402
from cv.recon.glb import srgb_to_linear, write_glb  # noqa: E402
from cv.recon.validate_mesh import validate  # noqa: E402


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def conf_masks(pred: dict, metas: list[dict], cfg: dict) -> np.ndarray:
    depth, conf = pred["depth"], pred["depth_conf"]
    S, H, W = depth.shape
    valid = np.zeros_like(depth, bool)
    for i, m in enumerate(metas):
        x0, y0, x1, y1 = m["valid"]
        valid[i, y0:y1, x0:x1] = True
    valid &= depth > 0
    thr = max(cfg["min_conf"], float(np.percentile(conf[valid], cfg["drop_percentile"])))
    mask = valid & (conf >= thr)
    gy, gx = np.gradient(depth, axis=(1, 2))
    rel = np.hypot(gx, gy) / np.maximum(depth, 1e-6)
    mask &= rel < cfg["max_rel_grad"]
    return mask, thr


def backproject(pred: dict, mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    from cv.recon.vggt_infer import unproject

    P, C = [], []
    for i in range(len(mask)):
        X = unproject(pred["depth"][i], pred["extrinsic"][i], pred["intrinsic"][i])
        P.append(X[mask[i]])
        C.append(pred["images"][i][mask[i]])
    return np.concatenate(P), np.concatenate(C)


def tsdf_mesh(pred: dict, mask: np.ndarray, E: np.ndarray, s: float, W_pts: np.ndarray, cfg: dict
              ) -> tuple[o3d.geometry.TriangleMesh, dict]:
    """UniformTSDFVolume 적분 (미터 월드).

    참고: 이 환경의 Open3D 0.20 에서는 ScalableTSDFVolume / t.VoxelBlockGrid 가 빈 메시를 내므로
    (합성 평면으로도 재현) 균일 격자를 쓴다. 범위 = 점구름 1~99 백분위 상자 + 여유, 정육면체.
    """
    lo, hi = np.percentile(W_pts, [1, 99], axis=0)
    lo, hi = lo - cfg["margin_m"], hi + cfg["margin_m"]
    length = float((hi - lo).max())
    res = int(np.ceil(length / cfg["voxel_m"]))
    if res > cfg["max_resolution"]:
        res = cfg["max_resolution"]
    vol = o3d.pipelines.integration.UniformTSDFVolume(
        length=length, resolution=res, sdf_trunc=cfg["trunc_m"],
        color_type=o3d.pipelines.integration.TSDFVolumeColorType.RGB8, origin=lo.astype(np.float64))
    S, H, W = pred["depth"].shape
    for i in range(S):
        d = np.where(mask[i], pred["depth"][i] * s, 0).astype(np.float32)  # 미터
        col = (pred["images"][i] * 255).clip(0, 255).astype(np.uint8)
        rgbd = o3d.geometry.RGBDImage.create_from_color_and_depth(
            o3d.geometry.Image(np.ascontiguousarray(col)), o3d.geometry.Image(d),
            depth_scale=1.0, depth_trunc=cfg["depth_max_m"], convert_rgb_to_intensity=False)
        K = pred["intrinsic"][i]
        intr = o3d.camera.PinholeCameraIntrinsic(int(W), int(H), float(K[0, 0]), float(K[1, 1]),
                                                 float(K[0, 2]), float(K[1, 2]))
        vol.integrate(rgbd, intr, E[i])   # E: 월드(glTF, m) → OpenCV 카메라
    return vol.extract_triangle_mesh(), {"tsdf_length_m": length, "tsdf_resolution": res,
                                         "tsdf_voxel_m": length / res, "tsdf_origin": lo.tolist()}


def clean_mesh(mesh: o3d.geometry.TriangleMesh, cfg: dict) -> tuple[o3d.geometry.TriangleMesh, dict]:
    info = {"tris_raw": len(mesh.triangles)}
    mesh.remove_degenerate_triangles()
    mesh.remove_duplicated_triangles()
    mesh.remove_duplicated_vertices()
    mesh.remove_non_manifold_edges()
    labels, counts, _ = mesh.cluster_connected_triangles()
    labels, counts = np.asarray(labels), np.asarray(counts)
    small = counts[labels] < cfg["min_component_tris"]
    mesh.remove_triangles_by_mask(small)
    mesh.remove_unreferenced_vertices()
    info["components_removed"] = int((counts < cfg["min_component_tris"]).sum())
    info["tris_clean"] = len(mesh.triangles)
    if len(mesh.triangles) > cfg["target_triangles"]:
        mesh = mesh.simplify_quadric_decimation(cfg["target_triangles"])
        mesh.remove_degenerate_triangles()
        mesh.remove_unreferenced_vertices()
    info["tris_final"] = len(mesh.triangles)
    mesh.compute_vertex_normals()
    return mesh, info


def preview(V: np.ndarray, Cs: np.ndarray, cams: np.ndarray, path: Path, title: str) -> None:
    """위에서 본 모습(XZ, 높은 점이 위)과 앞에서 본 모습(XY, 앞쪽 점이 위). 헤드리스 확인용."""
    px = 160  # px per m
    lo, hi = V.min(0) - 0.2, V.max(0) + 0.2
    w, h, d = ((hi - lo) * px).astype(int) + 1
    col = (Cs * 255).clip(0, 255).astype(np.uint8)

    def splat(ax_u, ax_v, key, H, flip_v):
        img = np.full((H, w, 3), 40, np.uint8)
        u = ((V[:, ax_u] - lo[ax_u]) * px).astype(int).clip(0, w - 1)
        v = ((V[:, ax_v] - lo[ax_v]) * px).astype(int).clip(0, H - 1)
        if flip_v:
            v = H - 1 - v
        o = np.argsort(key)   # 나중에 쓴 점이 남음
        img[v[o], u[o]] = col[o]
        return img

    top = splat(0, 2, V[:, 1], d, False)     # 행 방향 = +Z
    front = splat(0, 1, V[:, 2], h, True)    # 위 = +Y, +Z 쪽(앞) 점 우선
    im = Image.new("RGB", (w, d + h + 40), (20, 20, 20))
    im.paste(Image.fromarray(top), (0, 20))
    im.paste(Image.fromarray(front), (0, d + 40))
    dr = ImageDraw.Draw(im)
    dr.text((4, 4), f"{title}  TOP (X right, +Z down)", fill=(255, 255, 0))
    dr.text((4, d + 24), "FRONT (X right, +Y up)", fill=(255, 255, 0))
    for c in cams:
        x, z = (c[0] - lo[0]) * px, (c[2] - lo[2]) * px + 20
        dr.ellipse([x - 4, z - 4, x + 4, z + 4], outline=(255, 0, 0), width=2)
    ox, oz = -lo[0] * px, -lo[2] * px + 20
    dr.line([ox, oz, ox + px, oz], fill=(255, 0, 0), width=3)    # 원점에서 +X 1m
    dr.line([ox, oz, ox, oz + px], fill=(0, 128, 255), width=3)  # 원점에서 +Z 1m
    oy = d + 40 + (h - 1 + lo[1] * px)
    dr.line([0, oy, w, oy], fill=(0, 255, 0), width=1)            # y=0 바닥
    im.save(path)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("images", type=Path, help="이미지 폴더")
    ap.add_argument("--desc", default="vggt-tsdf", help="파일명 설명 (room_<날짜>_<desc>.glb)")
    ap.add_argument("--room-size", type=float, nargs=2, metavar=("W", "D"), help="ChArUco 실패 시: 실측 방 가로/세로 (m)")
    ap.add_argument("--cam-height", type=float, help="ChArUco 실패 시: 평균 촬영 높이 (m)")
    ap.add_argument("--scale-factor", type=float, help="ChArUco 실패 시: 직접 지정 배율")
    ap.add_argument("--no-charuco", action="store_true", help="ChArUco 검출 건너뜀")
    ap.add_argument("--no-latest", action="store_true", help="room_latest.* 갱신 안 함")
    ap.add_argument("--max-images", type=int)
    ap.add_argument("--expect-size", type=float, nargs=2, help="검증 시 기대 방 크기 (기본 recon.yaml)")
    ap.add_argument("--no-size-check", action="store_true")
    a = ap.parse_args()

    from cv.recon.vggt_infer import list_images, load_images, load_model, run

    cfg = load_yaml("recon.yaml")
    t_start = time.time()
    paths = list_images(a.images)
    if len(paths) < 2:
        raise SystemExit(f"이미지가 2장 미만입니다: {a.images}")
    mx = a.max_images or cfg["vggt"]["max_images"]
    if len(paths) > mx:
        paths = [paths[i] for i in np.linspace(0, len(paths) - 1, mx).round().astype(int)]
    log(f"이미지 {len(paths)}장: {a.images}")

    # 1) VGGT
    images, metas = load_images(paths, return_meta=True)
    model = load_model(device="cuda:0")
    pred = run(model, images, device="cuda:0")
    del model
    import torch

    torch.cuda.empty_cache()
    log(f"VGGT {tuple(images.shape)} {pred['time_s']:.1f}s, 최대 {pred['peak_alloc_gb']:.1f}GB")
    extr, intr = pred["extrinsic"], pred["intrinsic"]

    # 2) 신뢰도 필터
    mask, thr = conf_masks(pred, metas, cfg["conf_filter"])
    P, C = backproject(pred, mask)
    unit = float(np.median(pred["depth"][mask]))
    log(f"신뢰도 필터: conf ≥ {thr:.2f}, 남은 픽셀 {mask.mean():.0%}, 점 {len(P):,}, 중앙 깊이 {unit:.3f}")

    # 3) 바닥 RANSAC 정렬 (+ 맨해튼 yaw)
    floor = find_floor(P, extr, cfg["floor"], unit)
    T = floor.T
    Q = T.apply(P)
    yaw = manhattan_yaw(Q, unit)
    T = T.then(Sim3(1.0, rot_y(-yaw), np.zeros(3)))
    Q = T.apply(P)
    cam_y = T.apply(camera_centers(extr))[:, 1]
    log(f"바닥: {floor.method}, 인라이어 {floor.inlier_frac:.1%}, 카메라 아래 방향과 {floor.tilt_deg:.1f}°, "
        f"yaw {np.rad2deg(yaw):+.1f}°, 카메라 높이(단위) 중앙 {np.median(cam_y):.3f}")

    # 4) 스케일 보정: ChArUco → 방 크기 → 촬영 높이 → 배율
    tried = []
    S3 = None
    if not a.no_charuco:
        spec = load_charuco()
        S3, info = sc.charuco_scale(paths, metas, extr, intr, pred["depth"] * mask, T, spec, cfg["scale"])
        tried.append(info)
        log(f"ChArUco: {info}")
    if S3 is None and a.room_size:
        S3, info = sc.room_size_scale(Q, tuple(a.room_size))
        tried.append(info)
    if S3 is None and a.cam_height:
        S3, info = sc.cam_height_scale(Q, cam_y, a.cam_height)
        tried.append(info)
    if S3 is None and a.scale_factor:
        S3, info = sc.factor_scale(Q, a.scale_factor)
        tried.append(info)
    if S3 is None:
        raise SystemExit("스케일 보정 실패: ChArUco 미검출. --room-size W D, --cam-height H, --scale-factor 중 하나를 지정하세요.")
    scale_info = tried[-1]
    T = T.then(S3)
    log(f"스케일: {scale_info['method']} (배율 {T.s:.4f})")

    # 5) TSDF (미터 월드)
    E = extrinsic_after(extr, T)
    cams = T.apply(camera_centers(extr))
    W_pts = T.apply(P)
    mesh, tinfo = tsdf_mesh(pred, mask, E, T.s, W_pts, cfg["tsdf"])
    below = float(np.mean(W_pts[:, 1] < -0.05))
    if below > 0.02:
        log(f"경고: 바닥(y=0)보다 5cm 이상 아래 점 {below:.1%} — 바닥 평면 선택 확인 필요")
    log(f"TSDF 메시 삼각형 {len(mesh.triangles):,} {tinfo}")
    if len(mesh.triangles) == 0:
        raise SystemExit("TSDF 메시가 비었습니다.")

    # 6) 정리 + 간소화
    mesh, minfo = clean_mesh(mesh, cfg["mesh"])
    V = np.asarray(mesh.vertices)
    Nn = np.asarray(mesh.vertex_normals)
    Cs = np.asarray(mesh.vertex_colors)
    if len(Cs) != len(V):
        raise RuntimeError("간소화 후 정점 색이 사라졌습니다.")
    # 법선 방향 점검: 가장 가까운 카메라 쪽을 향하는 비율 (실내면 대부분 카메라 쪽)
    near_cam = cams[np.argmin(((V[:, None, :] - cams[None]) ** 2).sum(-1), axis=1)]
    minfo["normals_toward_camera"] = float(np.mean(((near_cam - V) * Nn).sum(1) > 0))
    log(f"정리/간소화: {minfo}")

    # 7) 내보내기
    out_dir = shared_dir() / "meshes"
    out_dir.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now().astimezone()
    stem = f"room_{now:%Y%m%d}_{a.desc}"
    glb = out_dir / f"{stem}.glb"
    if glb.exists():
        stem = f"{stem}-{now:%H%M%S}"
        glb = out_dir / f"{stem}.glb"
    extras = {"created_at": now.isoformat(timespec="seconds"), "scale_method": scale_info["method"],
              "coordinate_system": "glTF world: right-handed, +Y up, meters, floor y=0"}
    # glTF COLOR_0 는 선형 색공간 → 이미지 sRGB 를 선형으로 변환
    write_glb(glb, V, np.asarray(mesh.triangles), srgb_to_linear(Cs), Nn, extras=extras)

    vsize = cfg["room"]["expected_size_m"] if a.expect_size is None else a.expect_size
    ok, rows, vstats = validate(glb, vsize, cfg["room"]["size_tolerance"], not a.no_size_check)
    for lv, name, msg in rows:
        log(f"  [{lv}] {name}: {msg}")

    origin = ("ChArUco 보드 중심 (보드 +X→월드 +X, 보드 +Y→월드 +Z)" if scale_info["method"] == "charuco"
              else "바닥 범위(1~99 백분위) 중심, 축은 벽 방향(맨해튼) 정렬")
    meta = {
        "file": glb.name,
        "created_at": extras["created_at"],
        "source_images": str(a.images),
        "num_images": len(paths),
        "coordinate_system": extras["coordinate_system"],
        "origin": origin,
        "scale": {**{k: v for k, v in scale_info.items() if not isinstance(v, np.ndarray)}, "factor": T.s},
        "scale_attempts": tried,
        "triangles": int(len(mesh.triangles)),
        "vertices": int(len(V)),
        "bbox": {"min": V.min(0).round(4).tolist(), "max": V.max(0).round(4).tolist(),
                 "size": (V.max(0) - V.min(0)).round(4).tolist()},
        "validation": {"ok": ok, "checks": [f"[{lv}] {n}: {m}" for lv, n, m in rows]},
        "floor": {"method": floor.method, "inlier_frac": floor.inlier_frac, "tilt_deg": floor.tilt_deg},
        "vertex_color": "COLOR_0 float RGB, linear (sRGB→linear 변환)",
    }
    if not a.no_latest:
        tmp = out_dir / "room_latest.glb.tmp"
        shutil.copyfile(glb, tmp)
        os.replace(tmp, out_dir / "room_latest.glb")     # 원자적 교체 (Unity가 읽는 중 깨지지 않게)
        tmpj = out_dir / "room_latest.json.tmp"
        tmpj.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmpj, out_dir / "room_latest.json")
    (out_dir / f"{stem}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    # 디버그
    dbg = shared_dir() / "recon_debug" / stem
    dbg.mkdir(parents=True, exist_ok=True)
    keep = np.random.default_rng(0).choice(len(W_pts), min(len(W_pts), 500_000), replace=False)
    pc = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(W_pts[keep]))
    pc.colors = o3d.utility.Vector3dVector(C[keep])
    o3d.io.write_point_cloud(str(dbg / "points.ply"), pc)
    (dbg / "cameras.json").write_text(json.dumps({
        "images": [p.name for p in paths], "world_from_vggt": T.to_dict(),
        "camera_from_world_4x4": E.round(6).tolist(), "intrinsic_vggt_px": intr.round(4).tolist(),
        "vggt_image_size_wh": [images.shape[3], images.shape[2]]}, indent=1))
    (dbg / "report.json").write_text(json.dumps({**meta, "mesh_info": {**minfo, **tinfo}, "floor_candidates": floor.candidates,
                                                 "conf_threshold": thr, "vggt_time_s": pred["time_s"],
                                                 "vggt_peak_gb": pred["peak_alloc_gb"],
                                                 "validation_stats": vstats}, ensure_ascii=False, indent=1,
                                                default=float))
    preview(V, Cs, cams, dbg / "preview.png", stem)
    log(f"완료 {time.time() - t_start:.0f}s → {glb}  (검증 {'통과' if ok else '실패'}), 디버그 {dbg}")


if __name__ == "__main__":
    main()
