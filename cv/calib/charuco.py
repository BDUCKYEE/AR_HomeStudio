"""ChArUco 보드 정의 로드 (cv/config/charuco.yaml).

보드 좌표계(OpenCV): 원점 = 인쇄물 보드 영역의 왼쪽 위 모서리, +X = 오른쪽(가로 칸 방향),
+Y = 아래(세로 칸 방향), +Z = 보드 면 안쪽(오른손). 단위 미터.
월드 좌표계(glTF)와의 축 대응은 interfaces.md에서 확정한다 (현재 미정).
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
        board = cv2.aruco.CharucoBoard((self.squares_x, self.squares_y), self.square_m, self.marker_m, d)
        board.setLegacyPattern(self.legacy_pattern)
        return board

    def make_detector(self) -> cv2.aruco.CharucoDetector:
        params = cv2.aruco.DetectorParameters()
        params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
        return cv2.aruco.CharucoDetector(self.make_board(), cv2.aruco.CharucoParameters(), params)


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
    )
