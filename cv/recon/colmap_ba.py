"""VGGT 포즈로 만든 COLMAP 모델에 SIFT 매칭 → 알려진 포즈 삼각측량 → 번들 조정(BA) → 원래 월드로 재정렬.

envs/2dgs 의 pycolmap(3.10, CPU)으로 실행한다 (메인 .venv 에는 pycolmap 이 없음). numpy + pycolmap 만 쓰는 독립 스크립트.
보통은 run_2dgs.py 가 호출한다:
  ${ENVS_ROOT}/2dgs/.venv/bin/python cv/recon/colmap_ba.py <colmap_vggt 폴더> <출력 폴더>

좌표: 입력 모델의 world = 우리 월드(glTF, +Y 위, 미터). BA 는 게이지(위치·회전·스케일)가 자유라 조금 움직이므로,
끝에 BA 후 카메라 중심을 BA 전 중심에 상사변환(Umeyama)으로 맞춰 우리 월드로 되돌린다 (바닥 y=0, 미터 유지).
출력: <출력>/sparse/0/*.bin, <출력>/images → 입력 images 심볼릭 링크, <출력>/ba_report.json
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

import numpy as np
import pycolmap


def umeyama(src: np.ndarray, dst: np.ndarray):
    ms, md = src.mean(0), dst.mean(0)
    a, b = src - ms, dst - md
    U, S, Vt = np.linalg.svd(b.T @ a / len(src))
    D = np.diag([1.0, 1.0, np.sign(np.linalg.det(U @ Vt))])
    R = U @ D @ Vt
    s = float(np.trace(np.diag(S) @ D) / (a ** 2).sum(1).mean())
    return s, R, md - s * R @ ms


def centers(rec) -> dict:
    return {im.name: np.asarray(im.projection_center()) for im in rec.images.values()}


def main(src_dir: Path, out_dir: Path) -> None:
    t0 = time.time()
    rep: dict = {}
    out_dir.mkdir(parents=True, exist_ok=True)
    work = out_dir / "work"
    work.mkdir(exist_ok=True)
    db = work / "database.db"
    if db.exists():
        db.unlink()
    img_dir = src_dir / "images"
    ref = pycolmap.Reconstruction()
    ref.read_text(str(src_dir / "sparse" / "0"))
    name2ref = {im.name: im for im in ref.images.values()}

    # 1) SIFT 추출 (이미지마다 PINHOLE 카메라) + 전체 쌍 매칭 (81장이면 CPU 로 수 분)
    sift = pycolmap.SiftExtractionOptions()
    sift.max_num_features = 8192
    pycolmap.extract_features(str(db), str(img_dir), camera_mode=pycolmap.CameraMode.PER_IMAGE,
                              camera_model="PINHOLE", sift_options=sift, device=pycolmap.Device.cpu)
    t1 = time.time()
    pycolmap.match_exhaustive(str(db), device=pycolmap.Device.cpu)
    t2 = time.time()
    rep["time_extract_s"], rep["time_match_s"] = round(t1 - t0, 1), round(t2 - t1, 1)

    # 2) DB 카메라를 VGGT 내부 파라미터로 바꾸고, VGGT 포즈로 재구성 만들기 (DB 의 image_id/camera_id 를 따름)
    d = pycolmap.Database(str(db))
    rec = pycolmap.Reconstruction()
    for im in d.read_all_images():
        r = name2ref[im.name]
        cam = d.read_camera(im.camera_id)
        cam.params = ref.cameras[r.camera_id].params
        d.update_camera(cam)
        rec.add_camera(cam)
        new = pycolmap.Image(name=im.name, camera_id=im.camera_id, image_id=im.image_id,
                             cam_from_world=r.cam_from_world)
        rec.add_image(new)
        rec.register_image(im.image_id)
    d.close()
    rep["verified_pairs"] = None

    # 3) 알려진 포즈 삼각측량. VGGT 포즈 오차(1600px 기준 수 px)를 고려해 처음엔 허용 오차를 넓게
    opts = pycolmap.IncrementalPipelineOptions()
    opts.triangulation.create_max_angle_error = 4.0
    opts.triangulation.continue_max_angle_error = 4.0
    opts.triangulation.merge_max_reproj_error = 12.0
    opts.triangulation.complete_max_reproj_error = 12.0
    opts.mapper.filter_max_reproj_error = 12.0
    rec = pycolmap.triangulate_points(rec, str(db), str(img_dir), str(work), clear_points=True, options=opts)
    rep["before_ba"] = {"points3D": rec.num_points3D(), "mean_reproj_px": round(rec.compute_mean_reprojection_error(), 3),
                        "mean_track_length": round(rec.compute_mean_track_length(), 2)}
    before = centers(rec)
    before_R = {im.name: np.asarray(im.cam_from_world.rotation.matrix()) for im in rec.images.values()}
    before_f = {im.name: np.asarray(rec.cameras[im.camera_id].params[:2]) for im in rec.images.values()}

    # 4) BA (포즈 + 초점거리), 큰 오차 점 거르고 한 번 더
    ba = pycolmap.BundleAdjustmentOptions()
    ba.refine_focal_length = True
    ba.refine_principal_point = False
    ba.refine_extra_params = False
    ba.loss_function_type = pycolmap.LossFunctionType.CAUCHY
    ba.loss_function_scale = 2.0
    pycolmap.bundle_adjustment(rec, ba)
    for thr in (6.0, 3.0):
        bad = [pid for pid, p in rec.points3D.items() if p.error > thr]
        for pid in bad:
            rec.delete_point3D(pid)
        pycolmap.bundle_adjustment(rec, ba)
    rep["after_ba"] = {"points3D": rec.num_points3D(), "mean_reproj_px": round(rec.compute_mean_reprojection_error(), 3),
                       "mean_track_length": round(rec.compute_mean_track_length(), 2)}

    # 5) 우리 월드로 재정렬: BA 후 카메라 중심 → BA 전 중심 (상사변환)
    after = centers(rec)
    names = sorted(after)
    s, R, t = umeyama(np.array([after[n] for n in names]), np.array([before[n] for n in names]))
    rec.transform(pycolmap.Sim3d(s, pycolmap.Rotation3d(R), t))
    aligned = centers(rec)
    dpos = np.array([np.linalg.norm(aligned[n] - before[n]) for n in names])
    drot = []
    dfoc = []
    for im in rec.images.values():
        Ra = np.asarray(im.cam_from_world.rotation.matrix())
        cosang = (np.trace(Ra @ before_R[im.name].T) - 1) / 2
        drot.append(np.degrees(np.arccos(np.clip(cosang, -1, 1))))
        f = np.asarray(rec.cameras[im.camera_id].params[:2])
        dfoc.append(float(np.mean(f / before_f[im.name] - 1)))
    rep["align_to_vggt_world"] = {"scale": s, "rotation_deg": float(np.degrees(np.arccos(np.clip((np.trace(R) - 1) / 2, -1, 1)))),
                                  "translation_m": float(np.linalg.norm(t))}
    rep["pose_change"] = {"pos_mean_cm": round(float(dpos.mean() * 100), 2), "pos_max_cm": round(float(dpos.max() * 100), 2),
                          "rot_mean_deg": round(float(np.mean(drot)), 3), "rot_max_deg": round(float(np.max(drot)), 3),
                          "focal_change_mean_pct": round(float(np.mean(dfoc) * 100), 2)}
    sp = out_dir / "sparse" / "0"
    if sp.exists():
        shutil.rmtree(sp)
    sp.mkdir(parents=True)
    rec.write_binary(str(sp))
    link = out_dir / "images"
    if not link.exists():
        link.symlink_to(img_dir.resolve())
    rep["time_total_s"] = round(time.time() - t0, 1)
    (out_dir / "ba_report.json").write_text(json.dumps(rep, indent=1))
    print(json.dumps(rep, indent=1), flush=True)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(Path(sys.argv[1]), Path(sys.argv[2]))
