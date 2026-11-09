"""A4 실측 크기 ChArUco 보드 PDF/PNG 생성, 인쇄 후 실측값 반영.

사용:
  python -m cv.calib.make_charuco                     # ${SHARED_DIR}/charuco/ 에 PDF, PNG 생성 + 자체 검출 검증
  python -m cv.calib.make_charuco --set-measured 34.8 # 실측 칸 크기(mm)를 charuco.yaml에 기록
  python -m cv.calib.make_charuco --set-measured 34.8 --marker-mm 25.9
  python -m cv.calib.make_charuco --clear-measured    # 실측값 제거 (설계값 사용)
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from cv.calib.charuco import load_charuco
from cv.common.config import CONFIG_DIR, load_yaml, shared_dir


def _text(img, s, org, scale=2.2, thick=5):
    cv2.putText(img, s, org, cv2.FONT_HERSHEY_SIMPLEX, scale, 0, thick, cv2.LINE_AA)


def render_page() -> tuple[np.ndarray, dict]:
    c = load_yaml("charuco.yaml")
    des, page = c["design"], c["page"]
    ppm = int(page["px_per_mm"])
    sq_mm, mk_mm = float(des["square_length_mm"]), float(des["marker_length_mm"])
    sq_px = sq_mm * ppm
    if abs(sq_px - round(sq_px)) > 1e-9 or abs(mk_mm * ppm - round(mk_mm * ppm)) > 1e-9:
        raise ValueError("칸/마커 크기 × px_per_mm 이 정수여야 합니다 (픽셀 정렬).")
    sq_px = int(round(sq_px))
    W, H = int(round(page["width_mm"] * ppm)), int(round(page["height_mm"] * ppm))
    nx, ny = int(c["squares_x"]), int(c["squares_y"])
    bw, bh = nx * sq_px, ny * sq_px
    if bw > W - 10 * ppm or bh > H - 30 * ppm:
        raise ValueError("보드가 페이지 여백(좌우 5mm, 상하 15mm) 안에 들어가지 않습니다.")

    d = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, c["dictionary"]))
    board = cv2.aruco.CharucoBoard((nx, ny), sq_mm, mk_mm, d)
    board.setLegacyPattern(bool(c.get("legacy_pattern", False)))
    # marginSize=0 이면 칸 = 정확히 bw/nx px. 마커는 칸 안에서 OpenCV가 비율대로 배치
    board_img = board.generateImage((bw, bh), marginSize=0, borderBits=1)

    pageimg = np.full((H, W), 255, np.uint8)
    x0, y0 = (W - bw) // 2, (H - bh) // 2
    pageimg[y0:y0 + bh, x0:x0 + bw] = board_img

    # 머리글
    _text(pageimg, f"ChArUco {nx}x{ny}  {c['dictionary']}  square {sq_mm:.1f} mm  marker {mk_mm:.1f} mm",
          (x0, y0 - 9 * ppm), 2.0, 4)
    _text(pageimg, "PRINT AT 100% / ACTUAL SIZE (no fit-to-page). Keep flat, do not move after calibration.",
          (x0, y0 - 4 * ppm), 1.5, 3)
    # 보드 축 표시 (OpenCV 보드 좌표계: 원점 = 보드 왼쪽 위, +X 오른쪽, +Y 아래)
    _text(pageimg, "O", (x0 - 5 * ppm, y0 - 1 * ppm), 1.6, 4)
    _text(pageimg, "+X ->", (x0 + bw - 18 * ppm, y0 - 1 * ppm), 1.6, 4)
    _text(pageimg, "+Y", (x0 - 7 * ppm, y0 + bh - 2 * ppm), 1.6, 4)

    # 아래 여백: 100mm 자 (인쇄 배율 확인용)
    ry = y0 + bh + 12 * ppm
    rx = x0
    cv2.line(pageimg, (rx, ry), (rx + 100 * ppm, ry), 0, 4)
    for mm in range(0, 101):
        L = 5 * ppm if mm % 10 == 0 else (3 * ppm if mm % 5 == 0 else int(1.5 * ppm))
        x = rx + mm * ppm
        cv2.line(pageimg, (x, ry), (x, ry - L), 0, 3 if mm % 10 == 0 else 2)
    _text(pageimg, "0", (rx - 1 * ppm, ry + 5 * ppm), 1.3, 3)
    _text(pageimg, "100 mm", (rx + 96 * ppm, ry + 5 * ppm), 1.3, 3)
    _text(pageimg, f"board {nx * sq_mm:.0f} x {ny * sq_mm:.0f} mm", (rx + 110 * ppm, ry), 1.5, 3)

    meta = dict(ppm=ppm, sq_px=sq_px, nx=nx, ny=ny, x0=x0, y0=y0, W=W, H=H, sq_mm=sq_mm, mk_mm=mk_mm,
                dictionary=c["dictionary"])
    return pageimg, meta


def self_check(img: np.ndarray, meta: dict) -> str:
    """생성 이미지를 축소해 다시 검출 → 코너 수와 칸 간격 확인."""
    spec = load_charuco()
    det = spec.make_detector()
    s = 0.25
    small = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    ch_corners, ch_ids, _, _ = det.detectBoard(small)
    n_exp = (meta["nx"] - 1) * (meta["ny"] - 1)
    n = 0 if ch_ids is None else len(ch_ids)
    if n != n_exp:
        raise RuntimeError(f"자체 검출 실패: 코너 {n}/{n_exp}")
    pts = ch_corners.reshape(-1, 2) / s
    ids = ch_ids.ravel()
    # 같은 행의 인접 코너 간격 = 칸 크기(px)
    per_row = meta["nx"] - 1
    d = [np.linalg.norm(pts[ids == i + 1][0] - pts[ids == i][0])
         for i in range(n_exp - 1) if (i + 1) % per_row != 0]
    return f"코너 {n}/{n_exp} 검출, 칸 간격 {np.mean(d):.2f}px (기대 {meta['sq_px']}px)"


def save(img: np.ndarray, meta: dict) -> tuple[Path, Path]:
    out = shared_dir() / "charuco"
    out.mkdir(parents=True, exist_ok=True)
    stem = f"charuco_A4_{meta['nx']}x{meta['ny']}_{meta['sq_mm']:g}mm_{meta['dictionary']}"
    dpi = meta["ppm"] * 25.4  # 24 px/mm = 609.6 dpi → 페이지 = 정확히 A4
    pil = Image.fromarray(img).convert("1", dither=Image.Dither.NONE)
    png = out / f"{stem}.png"
    pdf = out / f"{stem}.pdf"
    pil.save(png, dpi=(dpi, dpi))
    pil.save(pdf, resolution=dpi)
    return png, pdf


def pdf_page_mm(pdf: Path) -> tuple[float, float]:
    m = re.search(rb"/MediaBox\s*\[\s*0\s+0\s+([\d.]+)\s+([\d.]+)\s*\]", pdf.read_bytes())
    return float(m.group(1)) / 72 * 25.4, float(m.group(2)) / 72 * 25.4


def set_measured(square_mm: float | None, marker_mm: float | None) -> None:
    path = CONFIG_DIR / "charuco.yaml"
    txt = path.read_text(encoding="utf-8")
    blk = re.search(r"(?ms)^measured:\n(.*?)(?=^\S|\Z)", txt)
    if not blk:
        raise RuntimeError("charuco.yaml 에 measured: 블록이 없습니다.")
    body = blk.group(1)
    fmt = lambda v: "null" if v is None else f"{v:g}"  # noqa: E731
    body = re.sub(r"(square_length_mm:\s*)\S+", lambda m: m.group(1) + fmt(square_mm), body, count=1)
    body = re.sub(r"(marker_length_mm:\s*)\S+", lambda m: m.group(1) + fmt(marker_mm), body, count=1)
    path.write_text(txt[:blk.start(1)] + body + txt[blk.end(1):], encoding="utf-8")
    spec = load_charuco()
    print(f"charuco.yaml 갱신: 칸 {spec.square_m * 1000:g} mm, 마커 {spec.marker_m * 1000:.3g} mm "
          f"(실측 사용={spec.measured})")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--set-measured", type=float, metavar="MM", help="인쇄물 실측 칸 크기 (mm)")
    ap.add_argument("--marker-mm", type=float, help="인쇄물 실측 마커 크기 (mm). 생략 시 설계 비율로 계산")
    ap.add_argument("--clear-measured", action="store_true")
    a = ap.parse_args()
    if a.clear_measured:
        set_measured(None, None)
        return
    if a.set_measured is not None:
        if not 20 <= a.set_measured <= 60:
            raise SystemExit("칸 크기는 mm 단위로 입력합니다 (예: 34.8).")
        set_measured(a.set_measured, a.marker_mm)
        return
    img, meta = render_page()
    print(self_check(img, meta))
    png, pdf = save(img, meta)
    w, h = pdf_page_mm(pdf)
    print(f"PNG: {png}  ({meta['W']}x{meta['H']}px, {meta['ppm'] * 25.4:.1f} dpi)")
    print(f"PDF: {pdf}  (페이지 {w:.2f} x {h:.2f} mm)")


if __name__ == "__main__":
    main()
