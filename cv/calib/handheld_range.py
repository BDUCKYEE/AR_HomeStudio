"""손에 드는 A3 ChArUco 보드 후보 비교 (합성): 천장 모서리 고정 카메라에서 방 가운데까지 검출 거리.

장면 (실험실 좌표, 미터, +Y 위): 카메라 = 방 모서리 천장 (0, 2.3, 0), 방 가운데 쪽을 봄.
보드 = 사람이 가슴 높이(1.2m)에 세로로 세워 들고, 카메라 쪽을 향한 방향에서 yaw 만큼 돌림 + 면 안 기울기 ±8°.
거리 = 카메라에서 보드 중심까지 3D 거리. 방 3.3×2.5m 의 가운데는 약 2.3m, 맞은편 모서리 쪽은 약 3.5~4m.
카메라: OV9281 1280×800 모노, 렌즈 화각 가정 2가지 (수평 70° f≈914px, 수평 90° f=640px).
화질: 저대비(흰 220/검정 35), 초점 흐림 σ=1.0px, 잡음 σ=4.

값 = 4번(yaw ±, 기울기 ±) 렌더 중 검출 코너 수 평균 / 전체 코너, 괄호 = 코너 4개 이상 검출된 비율.
사용: python -m cv.calib.handheld_range [--quick]  (결과를 표로 출력, --save 면 ${SHARED_DIR}/charuco/handheld_range.md)
      python -m cv.calib.handheld_range --mix-test   # 벽 보드와 손 보드를 한 장면에 두고 서로 섞이지 않는지 확인
"""
from __future__ import annotations

import argparse
import tempfile

import cv2
import numpy as np

from cv.calib.charuco import CharucoSpec, detect_boards, load_boards
from cv.common.config import shared_dir
from cv.recon.test_charuco_scale import look_at, render_views

# (이름, 가로 칸, 세로 칸, 칸 mm, 마커 mm) — A3 (297×420) 에서 좌우 여백 ≥5mm, 위아래에 머리글/자 공간
# 마커 = 칸 × 0.8 이하 (OpenCV 권장 여백). 3x4_95 가 A3 에 들어가는 가장 큰 칸
CANDIDATES = [
    ("3x4_95", 3, 4, 95, 76),     # 추천 (charuco_handheld.yaml)
    ("3x4_90", 3, 4, 90, 72),
    ("3x5_76", 3, 5, 76, 60),
    ("4x5_70", 4, 5, 70, 56),
    ("4x6_60", 4, 6, 60, 48),
    ("5x7_50", 5, 7, 50, 37),     # 벽 보드와 같은 칸 크기 (기준)
]
LENSES = {"hfov70": 640 / np.tan(np.deg2rad(35)), "hfov90": 640.0}
CAM = np.array([0.0, 2.3, 0.0])
ROOM_CENTER = np.array([1.25, 1.0, 1.65])
BOARD_H = 1.2


def spec_of(nx, ny, sq, mk, first=17, tuned=True) -> CharucoSpec:
    det = {"tuned": True, "upscale": 2} if tuned else {}
    return CharucoSpec("DICT_4X4_50", nx, ny, sq / 1000, mk / 1000, False, False, {"detector": det}, first, "cand")


def board_pose(spec: CharucoSpec, center: np.ndarray, yaw_deg: float, roll_deg: float):
    """세로로 든 보드: 앞면이 카메라 방향(수평)에서 yaw 만큼 돈 방향. 열 = 보드 X, Y, Z 의 실험실 방향."""
    f = CAM - center
    f[1] = 0
    f /= np.linalg.norm(f)
    c, s = np.cos(np.deg2rad(yaw_deg)), np.sin(np.deg2rad(yaw_deg))
    f = np.array([c * f[0] + s * f[2], 0, -s * f[0] + c * f[2]])
    Zb = -f                                  # 보드 +Z = 보드 안쪽 (앞면 반대)
    Yb = np.array([0, -1.0, 0])              # 보드 +Y = 아래
    Xb = np.cross(Yb, Zb)
    Rb = np.stack([Xb, Yb, Zb], 1)
    Rb = Rb @ cv2.Rodrigues(np.array([0, 0, np.deg2rad(roll_deg)]))[0]
    return Rb, center - Rb @ spec.center_m


class _NoNoise:
    def normal(self, loc, scale, size):
        return np.zeros(size)


def render_scene(specs_poses, E, K, rng, blur=1.0, noise=4.0):
    """보드 여러 개를 한 이미지에 합성 (render_views 를 보드별로 부르고 어두운 쪽을 취함)."""
    W, H = int(K[0, 2] * 2), int(K[1, 2] * 2)
    img = np.full((H, W), 150, np.float32)
    with tempfile.TemporaryDirectory() as td:
        for spec, Rb, tb in specs_poses:
            # 보드별 렌더는 잡음 없이 (배경 잡음이 앞서 그린 보드를 덮지 않게), 잡음은 합성 뒤 한 번만
            p = render_views(spec, Rb, tb, E[None], K, _NoNoise(), td)[0]
            one = cv2.imread(str(p), 0).astype(np.float32)
            mask = np.abs(one - 150) > 0.5
            img[mask] = one[mask]
    img = 35 + img * (220 - 35) / 255                       # 저대비 (모노 센서, 실내 조명)
    img = cv2.GaussianBlur(img, (0, 0), blur)
    img = np.clip(img + rng.normal(0, noise, img.shape), 0, 255).astype(np.uint8)
    return img


def run_table(dists, yaws, quick=False, tuned=True):
    rng = np.random.default_rng(0)
    rows = []
    for lens, f in LENSES.items():
        K = np.array([[f, 0, 640], [0, f, 400], [0, 0, 1]])
        E = look_at(CAM, ROOM_CENTER)
        for name, nx, ny, sq, mk in CANDIDATES:
            spec = spec_of(nx, ny, sq, mk, tuned=tuned)
            cells = []
            for d in dists:
                dh = np.sqrt(max(d ** 2 - (CAM[1] - BOARD_H) ** 2, 0.01))
                hdir = (ROOM_CENTER - CAM)
                hdir[1] = 0
                hdir /= np.linalg.norm(hdir)
                center = np.array([CAM[0], BOARD_H, CAM[2]]) + hdir * dh
                for yaw in yaws:
                    cnt = []
                    for sgn, roll in ((1, 8), (-1, -8)) if quick else ((1, 8), (-1, 8), (1, -8), (-1, -8)):
                        Rb, tb = board_pose(spec, center, sgn * yaw, roll)
                        img = render_scene([(spec, Rb, tb)], E, K, rng)
                        _, ids = spec.detect(img)          # 실제 검출 경로 (tuned + 확대)
                        cnt.append(0 if ids is None else len(ids))
                    cells.append((d, yaw, float(np.mean(cnt)) / spec.n_corners, float(np.mean(np.array(cnt) >= 4))))
            rows.append((lens, name, spec, cells))
            print(f"  {lens} {name} 완료", flush=True)
    return rows


def to_markdown(rows, dists, yaws) -> str:
    out = []
    for lens in LENSES:
        out.append(f"\n#### 렌즈 {lens} (f = {LENSES[lens]:.0f}px, 1280×800)\n")
        out.append("| 보드 | 코너 | " + " | ".join(f"{d:g}m" for d in dists) + " |")
        out.append("|---|---:|" + "---|" * len(dists))
        for ln, name, spec, cells in rows:
            if ln != lens:
                continue
            line = [f"{name} (칸 {spec.square_m * 1000:g}mm)", str(spec.n_corners)]
            for d in dists:
                cs = [c for c in cells if c[0] == d]
                line.append(" / ".join(f"{c[2]:.0%}({c[3]:.0%})" for c in cs))
            out.append("| " + " | ".join(line) + " |")
    out.append(f"\n칸 값 = yaw {', '.join(f'{y:g}°' for y in yaws)} 순서로 '평균 검출 코너 비율(코너 ≥4 검출 비율)'")
    return "\n".join(out)


def mix_test() -> None:
    """벽 보드(0~16번)와 손 보드(17번~)를 한 장면에 두고 검출이 서로 섞이지 않는지 확인."""
    specs = load_boards()
    wall, hand = specs["wall"], specs["handheld"]
    K = np.array([[1000.0, 0, 640], [0, 1000.0, 400], [0, 0, 1]])
    cam = np.array([0.4, 1.3, 1.6])
    E = look_at(cam, np.array([0.4, 1.1, 0.0]))
    base = np.array([[1, 0, 0], [0, -1, 0], [0, 0, -1]], float)
    tw = np.array([0.0, 1.1, 0.0]) - base @ wall.center_m
    Rh = base @ cv2.Rodrigues(np.array([0, np.deg2rad(15), 0]))[0]
    th = np.array([0.75, 1.1, 0.3]) - Rh @ hand.center_m
    img = render_scene([(wall, base, tw), (hand, Rh, th)], E, K, np.random.default_rng(1), blur=0.6, noise=2)
    res = detect_boards(img, specs)
    ok = True
    for nm, s in specs.items():
        r = res.get(nm)
        n = 0 if r is None else len(r["ids"])
        mk = [] if r is None else sorted(set(r["markers"].tolist()))
        bad = [m for m in mk if m not in set(s.marker_ids.tolist())]
        print(f"  {nm}: 코너 {n}/{s.n_corners}, 마커 {mk}, 다른 보드 마커 {bad}")
        ok &= n == s.n_corners and not bad
        # 보드별 검출기 단독 사용 시에도 다른 보드 마커를 쓰지 않는지
        _, ci = s.detect(img)
        n2 = 0 if ci is None else len(ci)
        print(f"    단독 검출기: 코너 {n2}/{s.n_corners}")
        ok &= n2 == s.n_corners
    # 코너 위치 확인: 손 보드 코너를 투영 위치와 비교
    r = res["handheld"]
    obj = hand.make_board().getChessboardCorners()[r["ids"]]
    Xc = (E[:, :3] @ (Rh @ obj.T + th[:, None]) + E[:, 3:]).T
    uv = (K @ Xc.T).T
    uv = uv[:, :2] / uv[:, 2:]
    err = np.linalg.norm(uv - r["corners"], axis=1)
    print(f"  손 보드 코너 위치 오차 평균 {err.mean():.2f}px, 최대 {err.max():.2f}px")
    ok &= err.max() < 1.5
    print("결과:", "통과" if ok else "실패")
    if not ok:
        raise SystemExit(1)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dists", type=float, nargs="+", default=[1.5, 2.0, 2.5, 3.0, 3.5, 4.0])
    ap.add_argument("--yaws", type=float, nargs="+", default=[0, 30, 45, 60])
    ap.add_argument("--quick", action="store_true", help="조건당 렌더 2장 (기본 4장)")
    ap.add_argument("--save", action="store_true")
    ap.add_argument("--mix-test", action="store_true")
    ap.add_argument("--default-detector", action="store_true", help="OpenCV 기본 검출 설정으로 (비교용)")
    a = ap.parse_args()
    if a.mix_test:
        mix_test()
        return
    rows = run_table(a.dists, a.yaws, a.quick, tuned=not a.default_detector)
    md = to_markdown(rows, a.dists, a.yaws)
    md += "\n검출 설정: " + ("OpenCV 기본" if a.default_detector else "tuned + 2배 확대 (charuco_handheld.yaml detector 절)")
    print(md)
    if a.save:
        p = shared_dir() / "charuco" / "handheld_range.md"
        p.write_text("# 손 보드 후보 검출 거리 (합성)\n\n" + (__doc__ or "") + "\n" + md + "\n", encoding="utf-8")
        print(f"저장: {p}")


if __name__ == "__main__":
    main()
