"""2. SpatialLM + RANSAC 하이브리드 프록시 → proxy_hybrid.json (interfaces.md 2-1절, method = "hybrid")

SpatialLM 으로 가구 종류와 대략 위치를 잡고(시드 여러 번 → 투표), 실제 점구름에 맞춰 상자 크기·방향을 다시 맞춘다.
벽·바닥·천장은 RANSAC 프록시(proxy_fit) 평면을 그대로 쓴다. RANSAC 단독 프록시와 상자별 비교표도 만든다.

사용 (메인 .venv, SpatialLM 추론은 envs/spatiallm 하위 프로세스, GPU 1):
  python -m cv.recon.run_hybrid                                   # room_latest.json 이 가리키는 메시
  python -m cv.recon.run_hybrid room_20261124_myroom2-charuco --seeds 8

순서
  1) SpatialLM 시드 N번 (점구름 입력, z-up 변환은 run_spatiallm 과 같음)
  2) 투표: 위에서 본 바닥 사각형 IoU ≥ 0.3 이거나 중심 거리 < 0.35m 인 상자를 같은 가구로 묶고, N/2 이상 시드에서
     나온 묶음만 남김. 종류 = 다수결, 초기 상자 = 중심·크기 중앙값, 방향 = 180° 주기 평균
  3) 점구름 맞춤: 평면 띠(proxy_fit 과 같은 7cm) 밖, 초기 상자를 15cm·20% 넓힌 범위 안의 점(여러 상자에 걸치면
     중심이 가까운 상자로)을 모아 방향(최소 사각형, 벽 방향 12° 안이면 벽 방향), 크기(2~98 백분위), 높이(98 백분위),
     아래(0.8m 미만이면 바닥까지)를 다시 맞춤. 벽에 붙는 납작한 물건(그림·커튼·에어컨 등)이나 점이 모자라면 SpatialLM 상자 그대로
  4) 문·창도 같은 방식으로 투표해 가장 가까운 RANSAC 벽 위 사각형으로
  5) SpatialLM 이 놓친 가구: 어떤 하이브리드 상자와도 겹치지 않는 RANSAC 상자는 종류 'furniture' 로 덧붙임 (votes=0)
출력: ${SHARED_DIR}/meshes/experiments/hybrid/<이름>/{proxy_hybrid.json, proxy_hybrid.glb, preview.png,
      box_compare.md, box_compare.json, raw_s<시드>.json, report.json}
좌표: 월드(glTF, +Y 위, 미터). SpatialLM 입출력만 z-up 으로 한 번 바꿨다 되돌린다 (run_spatiallm.to_zup/from_zup).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import time
from pathlib import Path

import cv2
import numpy as np
import open3d as o3d

from cv.common.config import load_yaml
from cv.recon import experiments as ex
from cv.recon.glb import srgb_to_linear
from cv.recon.proxy_fit import _orient_poly, box_corners, proxy_preview, proxy_to_mesh
from cv.recon.run_spatiallm import ENV_PY, HERE, layout_to_proxy, to_zup

WALL_ITEMS = {"painting", "curtain", "wall_decoration", "air_conditioner", "mirror", "range_hood", "wall_cabinet", "tv",
              "screen"}
FLAT_ITEMS = {"carpet"}     # 바닥에 깔린 납작한 것: 점구름 맞춤을 하면 위에 놓인 물건까지 잡혀 두꺼워짐 (실측 0.27m)


def foot(b) -> np.ndarray:
    """상자 바닥 사각형 (XZ, 4×2)."""
    return box_corners(b["center"], b["size"], b["yaw_deg"])[[0, 4, 5, 1]][:, [0, 2]]


def iou3d(a, b) -> float:
    pa, pb = foot(a).astype(np.float32), foot(b).astype(np.float32)
    inter, _ = cv2.intersectConvexConvex(pa, pb)
    ya = (a["center"][1] - a["size"][1] / 2, a["center"][1] + a["size"][1] / 2)
    yb = (b["center"][1] - b["size"][1] / 2, b["center"][1] + b["size"][1] / 2)
    yo = max(0.0, min(ya[1], yb[1]) - max(ya[0], yb[0]))
    vi = inter * yo
    va, vb = np.prod(a["size"]), np.prod(b["size"])
    return float(vi / max(va + vb - vi, 1e-9))


def iou_xz(a, b) -> float:
    pa, pb = foot(a).astype(np.float32), foot(b).astype(np.float32)
    inter, _ = cv2.intersectConvexConvex(pa, pb)
    return float(inter / max(cv2.contourArea(pa) + cv2.contourArea(pb) - inter, 1e-9))


def vote(boxes_per_seed: list[list[dict]], n_seeds: int, min_votes: int) -> list[dict]:
    """시드별 상자 목록 → 묶음(같은 가구). 묶음 = {members: [(seed, box)], votes, label, ...}"""
    clusters = []
    for s, boxes in enumerate(boxes_per_seed):
        for b in sorted(boxes, key=lambda b: -np.prod(b["size"])):
            best, best_score = None, 0.0
            for c in clusters:
                if s in {m[0] for m in c["members"]}:
                    continue                                  # 한 시드는 한 묶음에 한 상자
                ref = c["members"][0][1]
                sc = iou_xz(b, ref)
                dist = np.linalg.norm(np.subtract(b["center"], ref["center"])[[0, 2]])
                if (sc >= 0.3 or dist < 0.35) and sc + (0.35 - dist) > best_score:
                    best, best_score = c, sc + (0.35 - dist)
            if best is None:
                clusters.append({"members": [(s, b)]})
            else:
                best["members"].append((s, b))
    out = []
    for c in clusters:
        votes = len({m[0] for m in c["members"]})
        if votes < min_votes:
            continue
        bs = [m[1] for m in c["members"]]
        labels = [b["label"] for b in bs]
        lab = max(set(labels), key=labels.count)
        th = np.radians([b["yaw_deg"] for b in bs]) * 2               # 180° 주기 평균
        yaw = np.degrees(np.angle(np.exp(1j * th).mean()) / 2)
        out.append({"label": lab, "label_votes": labels.count(lab), "labels": sorted(set(labels)), "votes": votes,
                    "center": np.median([b["center"] for b in bs], 0), "size": np.median([b["size"] for b in bs], 0),
                    "yaw_deg": float(yaw)})
    return sorted(out, key=lambda c: (-c["votes"], -np.prod(c["size"])))


def refit(clusters, P, proxy, cfg, wall_yaw) -> tuple[list, list]:
    """초기 상자를 점구름에 다시 맞춤. 반환 (상자 목록, 상자별 메모)."""
    band = cfg["furniture_band_m"]
    keep = np.ones(len(P), bool)
    for pl in proxy["planes"]:
        keep &= P @ np.asarray(pl["normal"]) + pl["d"] > band
    Q = P[keep]
    # 점마다 가장 가까운(정규화 거리) 초기 상자 하나에만 배정
    regions = []
    for c in clusters:
        th = np.radians(c["yaw_deg"])
        ux, uz = np.array([np.cos(th), 0, -np.sin(th)]), np.array([np.sin(th), 0, np.cos(th)])
        half = np.asarray(c["size"]) / 2 * 1.1 + 0.08     # 넓게 잡으면 옆 가구까지 삼킴 (실측: 침대가 2.02×1.16m 로 부풂)
        rel = Q - c["center"]
        u, z, y = rel @ ux, rel @ uz, Q[:, 1]
        inside = (np.abs(u) <= half[0]) & (np.abs(z) <= half[2]) & (y <= c["center"][1] + half[1]) & (y > -0.05)
        nd = np.hypot(u / max(half[0], 1e-3), z / max(half[2], 1e-3))
        regions.append((inside, nd))
    nd_all = np.stack([np.where(r[0], r[1], np.inf) for r in regions]) if regions else np.zeros((0, len(Q)))
    owner = np.argmin(nd_all, 0) if len(regions) else np.zeros(len(Q), int)
    has = np.isfinite(nd_all.min(0)) if len(regions) else np.zeros(len(Q), bool)
    boxes, notes = [], []
    for k, c in enumerate(clusters):
        sel = has & (owner == k)
        # 옆 가구 점 빼기: 중심이 초기 상자 바닥 사각형 밖에 있는 RANSAC 상자 안의 점은 다른 가구로 본다
        # (실측: 침대 끝의 키 큰 물건 점이 섞여 침대가 2.03×1.12m 로 커짐)
        f0 = foot(c)
        for r in proxy.get("boxes", []):
            if ex._inside_poly2d_raster(np.asarray([r["center"]])[:, [0, 2]], f0)[0]:
                continue
            rin = ex._inside_poly2d_raster(Q[:, [0, 2]], foot(r)) & (Q[:, 1] <= r["center"][1] + r["size"][1] / 2)
            sel &= ~rin
        pts = Q[sel]
        note = {"points": int(len(pts)), "refit": False}
        if c["label"] in WALL_ITEMS:
            note["why"] = "벽에 붙는 납작한 물건 → SpatialLM 상자 그대로"
        elif c["label"] in FLAT_ITEMS:
            note["why"] = "바닥에 깔린 납작한 물건 → SpatialLM 상자 그대로"
        elif len(pts) < cfg["box_min_points_hybrid"]:
            note["why"] = f"점 {len(pts)}개 < {cfg['box_min_points_hybrid']} → SpatialLM 상자 그대로"
        if "why" in note:
            boxes.append({**c, "points": int(len(pts))})
            notes.append(note)
            continue
        rect = cv2.minAreaRect(pts[:, [0, 2]].astype(np.float32))
        phi = float(np.radians(rect[2]))
        a = np.array([np.cos(phi), np.sin(phi)])
        th = float(np.arctan2(-a[1], a[0]))
        rel = (th - wall_yaw) % (np.pi / 2)
        rel = rel - np.pi / 2 if rel > np.pi / 4 else rel
        if abs(np.degrees(rel)) < cfg["box_snap_deg"]:
            th -= rel
        th = (th + np.pi / 4) % (np.pi / 2) - np.pi / 4
        ux, uz = np.array([np.cos(th), 0, -np.sin(th)]), np.array([np.sin(th), 0, np.cos(th)])
        su, sz = pts @ ux, pts @ uz
        lu, hu = np.percentile(su, [2, 98])
        lz, hz = np.percentile(sz, [2, 98])
        ly, hy = np.percentile(pts[:, 1], [2, 98])
        hy = min(hy, c["center"][1] + c["size"][1] / 2 + 0.15)          # 위로는 초기 상자 + 15cm 까지
        if ly < cfg["box_floor_snap_m"]:
            ly = 0.0
        # 한 변이 초기 상자보다 25cm 넘게 커지지 않게 (가운데 기준으로 줄임). 초기 상자의 축과 새 축이 90° 돌면 변을 맞바꿔 비교
        rel90 = abs(((th - np.radians(c["yaw_deg"])) + np.pi / 2) % np.pi - np.pi / 2) > np.pi / 4
        lim_u, lim_z = (c["size"][2], c["size"][0]) if rel90 else (c["size"][0], c["size"][2])
        def clamp(lo, hi, lim):
            if hi - lo > lim + 0.25:
                mid = (lo + hi) / 2
                return mid - (lim + 0.25) / 2, mid + (lim + 0.25) / 2
            return lo, hi

        lu, hu = clamp(lu, hu, lim_u)
        lz, hz = clamp(lz, hz, lim_z)
        center = ux * (lu + hu) / 2 + uz * (lz + hz) / 2
        center[1] = (ly + hy) / 2
        boxes.append({**c, "center": center, "size": np.array([hu - lu, hy - ly, hz - lz]),
                      "yaw_deg": float(np.degrees(th)), "points": int(len(pts))})
        note.update(refit=True)
        notes.append(note)
    return boxes, notes


def vote_openings(props: list[dict], ransac: dict, min_votes: int) -> list[dict]:
    """시드별 문/창 → 투표 → 가장 가까운 RANSAC 벽 위 사각형."""
    items = []
    for s, p in enumerate(props):
        for o in p["openings"]:
            poly = np.asarray(o["polygon"])
            items.append((s, o["type"], poly.mean(0), np.linalg.norm(poly[1] - poly[0]), np.linalg.norm(poly[2] - poly[1])))
    clusters = []
    for s, t, c, w, h in items:
        for cl in clusters:
            if cl["type"] == t and np.linalg.norm(cl["c"][0] - c) < 0.4 and s not in cl["seeds"]:
                cl["c"].append(c), cl["w"].append(w), cl["h"].append(h), cl["seeds"].add(s)
                break
        else:
            clusters.append({"type": t, "c": [c], "w": [w], "h": [h], "seeds": {s}})
    walls = [pl for pl in ransac["planes"] if pl["type"] == "wall"]
    out, cnt = [], {"door": 0, "window": 0}
    for cl in clusters:
        if len(cl["seeds"]) < min_votes or not walls:
            continue
        c = np.median(cl["c"], 0)
        w = min(walls, key=lambda pl: abs(np.asarray(pl["normal"]) @ c + pl["d"]))
        n = np.asarray(w["normal"])
        c = c - (n @ c + w["d"]) * n                                   # 벽 평면 위로
        u = np.cross([0, 1.0, 0], n)
        u /= np.linalg.norm(u)
        hw, hh = np.median(cl["w"]) / 2, np.median(cl["h"]) / 2
        Y = np.array([0, 1.0, 0])
        quad = np.array([c - u * hw - Y * hh, c + u * hw - Y * hh, c + u * hw + Y * hh, c - u * hw + Y * hh])
        out.append({"id": f"{cl['type']}_{cnt[cl['type']]}", "type": cl["type"], "wall": w["id"],
                    "polygon": _orient_poly(quad, n).round(4).tolist(), "votes": len(cl["seeds"])})
        cnt[cl["type"]] += 1
    return out


def compare(hyb: dict, ran: dict) -> tuple[str, dict]:
    """상자별 비교: 하이브리드 상자마다 3D IoU 가 가장 큰 RANSAC 상자."""
    rows, used = [], set()
    for b in hyb["boxes"]:
        cand = [(iou3d(b, r), r) for r in ran["boxes"]]
        iou, r = max(cand, key=lambda x: x[0]) if cand else (0.0, None)
        if r is not None and iou > 0.05:
            used.add(r["id"])
            dc = float(np.linalg.norm(np.subtract(b["center"], r["center"])))
        else:
            r, dc = None, None
        rows.append({"hybrid": b["id"], "label": b["label"] + (" (RANSAC)" if b.get("votes") == 0 else ""),
                     "votes": b.get("votes"), "refit": b.get("refit"),
                     "size_h": np.round(b["size"], 2).tolist(), "ransac": r["id"] if r else None,
                     "size_r": np.round(r["size"], 2).tolist() if r else None, "iou3d": round(iou, 3) if r else 0.0,
                     "center_dist_m": None if dc is None else round(dc, 3)})
    unmatched = [{"ransac": r["id"], "size_r": np.round(r["size"], 2).tolist(),
                  "center": np.round(r["center"], 2).tolist()} for r in ran["boxes"] if r["id"] not in used]
    fmt = lambda v: "-" if v is None else "×".join(f"{x:.2f}" for x in v)   # noqa: E731
    md = ["| 하이브리드 | 종류 | 투표 | 맞춤 | 크기 W×H×D (m) | RANSAC | RANSAC 크기 | 3D IoU | 중심 거리 |",
          "|---|---|---:|---|---|---|---|---:|---:|"]
    for r in rows:
        md.append(f"| {r['hybrid']} | {r['label']} | {r['votes']} | {'예' if r['refit'] else '아니오'} | {fmt(r['size_h'])} | "
                  f"{r['ransac'] or '-'} | {fmt(r['size_r'])} | {r['iou3d']:.2f} | "
                  f"{'-' if r['center_dist_m'] is None else f'{r['center_dist_m']:.2f}m'} |")
    if unmatched:
        md.append("")
        md.append("RANSAC 에만 있는 상자: " + ", ".join(f"{u['ransac']} ({fmt(u['size_r'])}, 중심 {u['center']})" for u in unmatched))
    voted = [r for r in rows if r["votes"]]                      # SpatialLM 투표로 나온 상자 (RANSAC 에서 보탠 상자 제외)
    furn = [r for r in voted if r["label"] not in WALL_ITEMS | FLAT_ITEMS]
    ious = [r["iou3d"] for r in furn if r["ransac"]]
    summ = {"hybrid_boxes": len(rows), "voted": len(voted), "voted_furniture": len(furn),
            "added_from_ransac": len(rows) - len(voted), "ransac_boxes": len(ran["boxes"]),
            "furniture_matched": len(ious), "mean_iou_furniture": round(float(np.mean(ious)), 3) if ious else None,
            "ransac_only": len(unmatched)}
    return "\n".join(md), {"rows": rows, "ransac_only": unmatched, "summary": summ}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", nargs="?")
    ap.add_argument("--seeds", type=int, default=8)
    ap.add_argument("--min-votes", type=int, help="기본 = ceil(시드 수 / 2)")
    ap.add_argument("--model", default="manycore-research/SpatialLM1.1-Qwen-0.5B")
    a = ap.parse_args()
    cfg = load_yaml("recon.yaml")["proxy"]
    cfg.setdefault("box_min_points_hybrid", 300)
    src = ex.resolve_source(a.target)
    out = ex.out_dir("hybrid", src)
    ran = ex.reference_proxy(src)
    if ran is None:
        subprocess.run([os.sys.executable, "-m", "cv.recon.proxy_fit", src.stem], check=True)
        ran = ex.reference_proxy(src)
    P, C = ex.load_points(src)
    cams = ex.camera_centers_world(src)
    ply = out / "input_zup_points.ply"
    pc = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(to_zup(P)))
    pc.colors = o3d.utility.Vector3dVector(np.clip(C, 0, 1))
    o3d.io.write_point_cloud(str(ply), pc)
    t0 = time.time()
    props, t_infer, t_load = [], [], []
    for s in range(a.seeds):
        raw_p = out / f"raw_s{s}.json"
        if not raw_p.exists():
            with open(out / f"infer_s{s}.log", "w") as f:
                p = subprocess.run([str(ENV_PY), str(HERE / "spatiallm_infer.py"), str(ply), str(raw_p), "--model", a.model,
                                    "--seed", str(s)], stdout=f, stderr=subprocess.STDOUT,
                                   env=dict(os.environ, CUDA_VISIBLE_DEVICES="1"))
            if p.returncode != 0:
                raise SystemExit(f"SpatialLM 실패 (시드 {s}). 로그 {out / f'infer_s{s}.log'}")
        raw = json.loads(raw_p.read_text())
        t_infer.append(raw["time_infer_s"])
        t_load.append(raw["time_load_s"])
        props.append(layout_to_proxy(raw, cams))
    min_votes = a.min_votes or int(np.ceil(a.seeds / 2))
    clusters = vote([p["boxes"] for p in props], a.seeds, min_votes)
    walls = [pl for pl in ran["planes"] if pl["type"] == "wall"]
    wall_yaw = np.radians(ran["stats"].get("wall_yaw_deg", 0.0))
    boxes, notes = refit(clusters, P, ran, cfg, wall_yaw)
    hyb_boxes = []
    for i, (b, n) in enumerate(zip(boxes, notes)):
        th = np.radians(b["yaw_deg"])
        hyb_boxes.append({"id": f"box_{i}", "label": b["label"], "center": np.round(b["center"], 4).tolist(),
                          "size": np.round(b["size"], 4).tolist(), "yaw_deg": round(float(b["yaw_deg"]), 2),
                          "rotation_xyzw": [0.0, round(float(np.sin(th / 2)), 6), 0.0, round(float(np.cos(th / 2)), 6)],
                          "confidence": round(b["votes"] / a.seeds, 3), "points": b.get("points"),
                          "votes": b["votes"], "label_votes": b["label_votes"], "labels_seen": b["labels"],
                          "refit": n["refit"], **({"note": n["why"]} if "why" in n else {})})
    # SpatialLM 이 놓친 가구: 어떤 하이브리드 상자와도 겹치지 않는 RANSAC 상자를 종류 없이 덧붙임 (프록시 빈틈 방지)
    added = []
    for r in ran["boxes"]:
        # 3D IoU 0.2 미만이면 다른 가구 (침대 끝에 선 키 큰 물건처럼 바닥 사각형만 조금 겹치는 경우 포함).
        # 커튼·그림·카펫은 가구 자리를 덮지 않으므로 비교에서 뺀다
        if all(iou3d(r, h) < 0.2 for h in hyb_boxes if h["label"] not in WALL_ITEMS | FLAT_ITEMS):
            th = np.radians(r["yaw_deg"])
            added.append({"id": f"box_{len(hyb_boxes) + len(added)}", "label": "furniture", "center": r["center"],
                          "size": r["size"], "yaw_deg": r["yaw_deg"], "rotation_xyzw": r["rotation_xyzw"],
                          "confidence": None, "points": r["points"], "votes": 0, "refit": False,
                          "note": f"SpatialLM 미검출 → RANSAC {r['id']} 그대로"})
    hyb_boxes += added
    proxy = {"format": "roomar-proxy", "version": 1, "method": "hybrid",
             "created_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
             "source": src.meta.get("source"), "source_mesh": src.mesh.name,
             "coordinate_system": "glTF world: right-handed, +Y up, meters, floor y=0",
             "room": ran["room"], "planes": ran["planes"], "boxes": hyb_boxes,
             "openings": vote_openings(props, ran, min_votes),
             "stats": {"seeds": a.seeds, "min_votes": min_votes, "model": a.model,
                       # SpatialLM 시간은 시드별 원본 기록(모델 로드 + 추론)의 합 → 저장된 결과를 다시 써도 같은 값
                       "time_total_s": round(float(np.sum(t_infer) + np.sum(t_load)) + (time.time() - t0), 1),
                       "time_infer_s_each": round(float(np.mean(t_infer)), 2),
                       "boxes_per_seed": [len(p["boxes"]) for p in props], "clusters_kept": len(clusters),
                       "refit": int(sum(n["refit"] for n in notes)), "added_from_ransac": len(added),
                       "planes_from": "proxy-ransac",
                       "wall_yaw_deg": ran["stats"].get("wall_yaw_deg")}}
    errs = ex.check_proxy(proxy, np.median(cams, 0))
    if errs:
        raise SystemExit("proxy_hybrid.json 규약 위반: " + "; ".join(errs))
    ex.write_json(out / "report.json", {"clusters": clusters, "notes": notes})
    md, cmp_ = compare(proxy, ran)
    (out / "box_compare.md").write_text(f"# 상자별 비교: 하이브리드 vs RANSAC (`{src.stem}`)\n\n{md}\n", encoding="utf-8")
    ex.write_json(out / "box_compare.json", cmp_)
    proxy["stats"]["compare"] = cmp_["summary"]
    V, F, Cm, N = proxy_to_mesh(proxy)
    ex.safe_write_glb(out / "proxy_hybrid.glb", V, F, srgb_to_linear(Cm), N,
                      extras={"method": "hybrid", "source_mesh": src.mesh.name,
                              "coordinate_system": "glTF world: right-handed, +Y up, meters, floor y=0"})
    proxy_preview(out / "preview.png", proxy, P, C, cams, None)
    ex.write_json(out / "proxy_hybrid.json", proxy)          # 마지막에 써서 가장 최근 파일이 되게 (unity 규칙)
    ex.log(f"시드 {a.seeds}개 상자 수 {proxy['stats']['boxes_per_seed']} → 투표 통과 {len(clusters)}개 (≥{min_votes}표), "
           f"점구름 맞춤 {proxy['stats']['refit']}개, RANSAC 에서 보탠 상자 {len(added)}개, 문/창 {len(proxy['openings'])}개, {proxy['stats']['time_total_s']}s")
    ex.log(f"RANSAC 비교: {cmp_['summary']}")
    print(md)


if __name__ == "__main__":
    main()
