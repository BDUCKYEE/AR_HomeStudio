"""방 메시(.glb)가 docs/interfaces.md 규약을 지키는지 검사.

사용:
  python -m cv.recon.validate_mesh                      # ${SHARED_DIR}/meshes/room_latest.glb
  python -m cv.recon.validate_mesh path/to/room.glb --expect-size 3.3 2.5 --tol 0.25
  python -m cv.recon.validate_mesh room.glb --no-size-check

검사 항목 (FAIL 이 하나라도 있으면 종료 코드 1):
  형식      glTF 2.0 바이너리, 노드 변환 없음, 좌표 유한값
  정점 색   COLOR_0 존재, 단색이 아님
  삼각형 수 1,000 이상, 상한(recon.yaml mesh.max_triangles) 이하
  미터 단위 전체 크기 0.5~15m (mm/cm 단위나 스케일 미보정이면 벗어남)
  바닥 y≈0  표면 샘플 1백분위 높이가 0 근처, 바닥 근처(|y|<5cm)에 표면이 충분히 있음
  높이      최고점 1.5~3.5m (부족하면 WARN: 천장/윗벽 미복원)
  방 크기   수평 범위(1~99 백분위)가 기대 크기(기본 3.3×2.5m) ±tol 이내 (2×tol까지 WARN)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

from cv.common.config import load_yaml, shared_dir
from cv.recon.glb import read_glb

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"


def sample_surface(V: np.ndarray, F: np.ndarray, n: int = 200_000, seed: int = 0) -> np.ndarray:
    """면적 비례 균일 표면 샘플 (간소화로 정점 밀도가 불균일해도 통계가 치우치지 않게)."""
    a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    area = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
    if area.sum() <= 0:
        return V
    rng = np.random.default_rng(seed)
    idx = rng.choice(len(F), n, p=area / area.sum())
    r1, r2 = rng.random(n), rng.random(n)
    sq = np.sqrt(r1)
    return (1 - sq)[:, None] * a[idx] + (sq * (1 - r2))[:, None] * b[idx] + (sq * r2)[:, None] * c[idx]


def validate(path: Path, expect_size=(3.3, 2.5), tol=0.25, size_check=True, max_tris=None) -> tuple[bool, list, dict]:
    rcfg = load_yaml("recon.yaml")
    max_tris = max_tris or rcfg["mesh"]["max_triangles"]
    out: list[tuple[str, str, str]] = []

    def rep(level, name, msg):
        out.append((level, name, msg))

    m = read_glb(path)
    V, F, C = m["V"], m["F"], m["C"]
    rep(PASS, "형식", f"glTF {m['gltf']['asset'].get('version')}, 정점 {len(V):,}, 삼각형 {len(F):,}")
    if m["node_transform"]:
        rep(WARN, "노드 변환", "노드에 matrix/TRS가 있음 (정점 좌표만 검사함)")
    if not np.isfinite(V).all():
        rep(FAIL, "좌표", "NaN/Inf 정점")
        return False, out, {}
    if F.max() >= len(V):
        rep(FAIL, "인덱스", "정점 범위를 벗어난 인덱스")
        return False, out, {}

    # 정점 색
    if not m["has_color"]:
        rep(FAIL, "정점 색", "COLOR_0 없음")
    elif C.std(0).max() < 0.01:
        rep(FAIL, "정점 색", f"COLOR_0이 단색 (std {C.std(0).max():.4f})")
    else:
        rep(PASS, "정점 색", f"COLOR_0 있음, 평균 {np.round(C.mean(0), 3).tolist()}")

    # 삼각형 수
    nt = len(F)
    rep(FAIL if nt > max_tris or nt < 1000 else PASS, "삼각형 수", f"{nt:,} (상한 {max_tris:,})")

    S = sample_surface(V, F)
    bb_min, bb_max = V.min(0), V.max(0)
    size = bb_max - bb_min
    stats = {"bbox_min": bb_min.tolist(), "bbox_max": bb_max.tolist(), "bbox_size": size.tolist()}

    # 미터 단위
    big = float(size.max())
    rep(PASS if 0.5 <= big <= 15 else FAIL, "미터 단위", f"바운딩 박스 {np.round(size, 2).tolist()} m")

    # 바닥 y≈0
    p1 = float(np.percentile(S[:, 1], 1))
    near = float(np.mean(np.abs(S[:, 1]) < 0.05))
    stats.update(floor_p1_y=p1, floor_band_frac=near)
    lvl = PASS if -0.08 <= p1 <= 0.05 else (WARN if -0.2 <= p1 <= 0.15 else FAIL)
    rep(lvl, "바닥 y≈0", f"표면 1백분위 y = {p1:+.3f} m")
    rep(PASS if near >= 0.05 else WARN, "바닥 표면", f"|y|<5cm 표면 비율 {near:.1%}")

    # 높이
    top = float(np.percentile(S[:, 1], 99.5))
    stats["top_y"] = top
    rep(PASS if 1.5 <= top <= 3.5 else WARN, "높이", f"표면 99.5백분위 y = {top:.2f} m")

    # 방 크기
    lo, hi = np.percentile(S[:, [0, 2]], [1, 99], axis=0)
    ext = hi - lo
    stats["extent_xz_p1_p99"] = ext.tolist()
    if size_check:
        got = np.sort(ext)[::-1]
        exp = np.sort(np.asarray(expect_size, float))[::-1]
        err = np.abs(got / exp - 1)
        lvl = PASS if err.max() <= tol else (WARN if err.max() <= 2 * tol else FAIL)
        rep(lvl, "방 크기", f"수평 범위 {got[0]:.2f}×{got[1]:.2f} m (기대 {exp[0]}×{exp[1]} ±{tol:.0%}, "
                         f"오차 {err[0]:+.0%}/{err[1]:+.0%})")
    else:
        rep(PASS, "방 크기", f"검사 생략, 수평 범위 {ext[0]:.2f}×{ext[1]:.2f} m")

    ok = not any(lv == FAIL for lv, _, _ in out)
    return ok, out, stats


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("glb", nargs="?", type=Path)
    rc = load_yaml("recon.yaml")["room"]
    ap.add_argument("--expect-size", type=float, nargs=2, default=rc["expected_size_m"], metavar=("W", "D"))
    ap.add_argument("--tol", type=float, default=rc["size_tolerance"])
    ap.add_argument("--no-size-check", action="store_true")
    ap.add_argument("--max-triangles", type=int)
    a = ap.parse_args()
    path = a.glb or shared_dir() / "meshes" / "room_latest.glb"
    ok, rows, _ = validate(path, a.expect_size, a.tol, not a.no_size_check, a.max_triangles)
    print(f"검사: {path}")
    for lv, name, msg in rows:
        print(f"  [{lv}] {name}: {msg}")
    print("결과:", "통과" if ok else "실패")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
