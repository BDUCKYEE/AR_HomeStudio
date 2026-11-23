"""ChArUco 보드 정의 로드와 두 보드 구분 검출.

보드 (모두 DICT_4X4_50, 마커 번호 범위가 겹치지 않음):
  wall      cv/config/charuco.yaml           벽 A3 보드, 마커 0~16번 (월드 좌표계 기준, interfaces.md 1절)
  handheld  cv/config/charuco_handheld.yaml  손에 드는 A3 보드, 마커 17번부터

보드 좌표계(OpenCV): 원점 = 인쇄물 보드 영역의 왼쪽 위 모서리, +X = 오른쪽(가로 칸 방향),
+Y = 아래(세로 칸 방향), +Z = 보드 면 안쪽(오른손). 단위 미터.
코너 번호(charuco id)는 보드마다 0부터 시작하므로, 두 보드를 함께 쓸 때는 detect_boards() 처럼 보드 이름과 같이 다룬다.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from cv.common.config import load_yaml


@dataclass
class CharucoSpec:
    dictionary: str
    squares_x: int
    squares_y: int
    square_m: float           # 실측값 우선, 없으면 설계값
    marker_m: float
    measured: bool            # 실측값을 사용 중인지
    legacy_pattern: bool
    raw: dict
    first_marker_id: int = 0  # 이 보드의 첫 ArUco 마커 번호 (보드 마커 = first ~ first + n_markers - 1)
    name: str = "wall"

    @property
    def n_markers(self) -> int:
        return (self.squares_x * self.squares_y) // 2

    @property
    def marker_ids(self) -> np.ndarray:
        return np.arange(self.first_marker_id, self.first_marker_id + self.n_markers)

    @property
    def n_corners(self) -> int:
        return (self.squares_x - 1) * (self.squares_y - 1)

    @property
    def board_size_m(self) -> tuple[float, float]:
        return self.squares_x * self.square_m, self.squares_y * self.square_m

    @property
    def center_m(self) -> np.ndarray:
        """보드 좌표계에서 보드 중심 (월드 원점)."""
        w, h = self.board_size_m
        return np.array([w / 2, h / 2, 0.0])

    def make_board(self) -> cv2.aruco.CharucoBoard:
        d = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, self.dictionary))
        board = cv2.aruco.CharucoBoard((self.squares_x, self.squares_y), self.square_m, self.marker_m, d,
                                       self.marker_ids.astype(np.int32))
        board.setLegacyPattern(self.legacy_pattern)
        return board

    @property
    def detector_cfg(self) -> dict:
        """설정 파일 detector: 절. tuned=작은/먼 마커용 매개변수, upscale=검출 전 확대 배율 (손 보드)."""
        return self.raw.get("detector") or {}

    def make_detector(self) -> cv2.aruco.CharucoDetector:
        """이 보드의 마커 번호만 쓰는 검출기 (다른 보드의 마커는 코너 보간에 쓰이지 않음)."""
        return cv2.aruco.CharucoDetector(self.make_board(), cv2.aruco.CharucoParameters(),
                                         _detector_params(bool(self.detector_cfg.get("tuned", False))))

    def detect(self, gray: np.ndarray):
        """코너 검출 (설정의 upscale 반영). 반환 (corners (N,2) 원본 픽셀, ids (N,)) 또는 (None, None)."""
        up = float(self.detector_cfg.get("upscale", 1))
        img = cv2.resize(gray, None, fx=up, fy=up, interpolation=cv2.INTER_CUBIC) if up != 1 else gray
        cc, ci, _, _ = self.make_detector().detectBoard(img)
        if ci is None:
            return None, None
        return cc.reshape(-1, 2) / up + (0.5 / up - 0.5 if up != 1 else 0.0), ci.ravel()


def _detector_params(tuned: bool = False) -> cv2.aruco.DetectorParameters:
    """tuned=True: 멀리 있는 작은 마커용 (합성 시험에서 3×4 95mm 보드 3m 검출률 14% → 75%, handheld_range.py)."""
    params = cv2.aruco.DetectorParameters()
    params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    if tuned:
        params.minMarkerPerimeterRate = 0.01
        params.adaptiveThreshWinSizeMin = 3
        params.adaptiveThreshWinSizeMax = 43
        params.adaptiveThreshWinSizeStep = 4
        params.polygonalApproxAccuracyRate = 0.06
        params.perspectiveRemovePixelPerCell = 8
        params.perspectiveRemoveIgnoredMarginPerCell = 0.25
        params.errorCorrectionRate = 0.8
        params.minCornerDistanceRate = 0.02
    return params


BOARD_CONFIGS = {"wall": "charuco.yaml", "handheld": "charuco_handheld.yaml"}


def load_boards(names=("wall", "handheld")) -> dict[str, CharucoSpec]:
    """여러 보드 로드. 사전이 같은데 마커 번호 범위가 겹치면 오류 (구분 불가)."""
    specs = {n: load_charuco(BOARD_CONFIGS[n]) for n in names}
    items = list(specs.values())
    for i, a in enumerate(items):
        for b in items[i + 1:]:
            if a.dictionary == b.dictionary and set(a.marker_ids) & set(b.marker_ids):
                raise ValueError(f"보드 {a.name}, {b.name} 의 마커 번호가 겹칩니다: "
                                 f"{a.marker_ids.min()}~{a.marker_ids.max()} / {b.marker_ids.min()}~{b.marker_ids.max()}")
    return specs


def detect_boards(gray: np.ndarray, specs: dict[str, CharucoSpec], min_corners: int = 4) -> dict[str, dict]:
    """한 이미지에서 여러 보드를 구분해 검출. ArUco 마커는 사전별로 한 번만 찾고, 번호 범위로 보드에 나눈 뒤
    보드마다 ChArUco 코너를 보간한다.

    반환 {보드 이름: {"corners": (N,2) 픽셀, "ids": (N,) 보드 안 코너 번호, "markers": (M,) 마커 번호}}
    (코너 min_corners 개 미만인 보드는 빠짐)
    """
    out = {}
    by_dict: dict[str, list[CharucoSpec]] = {}
    for s in specs.values():
        by_dict.setdefault(s.dictionary, []).append(s)
    for dname, group in by_dict.items():
        d = cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, dname))
        # 같은 사전의 보드 중 가장 너그러운 설정(손 보드: tuned + 2배 확대)으로 마커를 한 번만 찾는다
        tuned = any(bool(s.detector_cfg.get("tuned", False)) for s in group)
        up = max(float(s.detector_cfg.get("upscale", 1)) for s in group)
        img = cv2.resize(gray, None, fx=up, fy=up, interpolation=cv2.INTER_CUBIC) if up != 1 else gray
        mc, mid, _ = cv2.aruco.ArucoDetector(d, _detector_params(tuned)).detectMarkers(img)
        if mid is None:
            continue
        mid = mid.ravel()
        for s in group:
            keep = np.isin(mid, s.marker_ids)       # 번호 범위로 보드 구분
            if keep.sum() == 0:
                continue
            sel_c = tuple(c for c, k in zip(mc, keep) if k)
            sel_i = mid[keep].reshape(-1, 1).astype(np.int32)
            det = cv2.aruco.CharucoDetector(s.make_board(), cv2.aruco.CharucoParameters(), _detector_params(tuned))
            cc, ci, _, _ = det.detectBoard(img, markerCorners=sel_c, markerIds=sel_i)
            if ci is None or len(ci) < min_corners:
                continue
            uv = cc.reshape(-1, 2) / up + (0.5 / up - 0.5 if up != 1 else 0.0)   # 확대 픽셀 → 원본 픽셀
            out[s.name] = {"corners": uv, "ids": ci.ravel(), "markers": mid[keep]}
    return out


def load_charuco(name: str = "charuco.yaml") -> CharucoSpec:
    c = load_yaml(name)
    meas = c.get("measured") or {}
    des = c["design"]
    sq = meas.get("square_length_mm")
    mk = meas.get("marker_length_mm")
    measured = sq is not None
    if sq is None:
        sq = des["square_length_mm"]
    if mk is None:
        # 마커만 실측하지 않았으면 설계 비율로 같이 스케일
        mk = des["marker_length_mm"] * sq / des["square_length_mm"]
    return CharucoSpec(
        dictionary=c["dictionary"],
        squares_x=int(c["squares_x"]),
        squares_y=int(c["squares_y"]),
        square_m=float(sq) / 1000.0,
        marker_m=float(mk) / 1000.0,
        measured=measured,
        legacy_pattern=bool(c.get("legacy_pattern", False)),
        raw=c,
        first_marker_id=int(c.get("first_marker_id", 0)),
        name=str(c.get("name", "wall")),
    )
