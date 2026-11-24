"""고정 카메라 4대 미리보기 서버 (초점·각도 맞춤용). 헤드리스 AI 컴퓨터에서 돌리고 메인 컴퓨터 브라우저로 본다.

사용:
  python -m cv.capture.preview_server [--port 8090] [--host 127.0.0.1]
  → VS Code Remote-SSH 의 포트 전달(Ports 탭)로 메인 컴퓨터에서 http://localhost:<port> 열기
  python -m cv.capture.preview_server --host <이 컴퓨터의 Tailscale/LAN IP> --port 8091
  → 다른 컴퓨터 브라우저에서 http://<IP>:8091 (IP 는 코드에 적지 않고 실행할 때만 지정)

화면
  /            4대를 한 영상(2×2, 1920×1080)으로, 카메라 이름 = cv/config/cameras.yaml (없으면 USB 포트)
  /grid        4대를 따로따로 (640×360 스트림 4개)
  /cam/<n>     한 대 전체 해상도 + 큰 초점 수치 (초점 맞출 때)
  /snap        4대 전체 해상도 사진을 ${SHARED_DIR}/captures/aim_<시각>/ 에 저장
  /reset       초점 최고값 초기화
오버레이: 3분할 격자 + 중앙 십자(각도), 초점 = 가운데 1/3 영역 라플라시안 분산(클수록 선명, 노랑 = 지금까지 최고값),
         밝기 평균·포화 비율. 렌즈를 손으로 가리면 'COVERED' 로 바뀌고 표준 출력에 한 줄 남긴다 (카메라 이름 매핑용).

카메라 구분: 4대 모두 시리얼이 SN0001 로 같아 /dev/v4l/by-path (꽂은 USB 포트)로 구분한다.
캡처 모드: MJPG 1280×720 30fps (이 보드는 1280×800 모드가 없음).
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2
import numpy as np

from cv.common.config import CONFIG_DIR, shared_dir

W, H, FPS = 1280, 720, 30
ROTATE = None   # --rotate 로 지정 (cv2.ROTATE_*)


def port_of(path: str) -> str:
    """by-path 이름 → 짧은 포트 표기 (예: pci-0000:0f:00.0-usb-0:1:1.0-video-index0 → 0f:00.0-1)."""
    p = Path(path).name.replace("pci-0000:", "")
    pci, usb = p.split("-usb-")
    return f"{pci}-{usb.split(':')[1]}"


def load_names() -> dict[str, str]:
    f = CONFIG_DIR / "cameras.yaml"
    if not f.is_file():
        return {}
    import yaml

    cams = (yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("cameras") or {}
    return {v["port"]: k for k, v in cams.items() if isinstance(v, dict) and "port" in v}


class Cam:
    def __init__(self, path: str, name: str):
        self.path, self.port, self.name = path, port_of(path), name
        self.frame = None
        self.stamp = 0.0
        self.fps = 0.0
        self.focus = 0.0
        self.focus_max = 0.0
        self.mean = 0.0
        self.sat = 0.0
        self.covered = False
        self.lock = threading.Lock()
        self.cap = None
        self.open()
        threading.Thread(target=self.loop, daemon=True).start()

    def open(self):
        if self.cap is not None:
            self.cap.release()
        self.cap = cv2.VideoCapture(self.path, cv2.CAP_V4L2)
        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, W)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, H)
        self.cap.set(cv2.CAP_PROP_FPS, FPS)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    def loop(self):
        t_last, n, fails = time.time(), 0, 0
        while True:
            ok, f = self.cap.read() if self.cap is not None else (False, None)
            if not ok:
                fails += 1
                if fails == 10:
                    print(f"[{time.strftime('%H:%M:%S')}] 끊김 {self.port} ({self.name}) → 다시 여는 중", flush=True)
                if fails >= 10:          # USB 를 뺐다 꽂으면 같은 by-path 로 다시 연다
                    with self.lock:
                        self.frame, self.fps = None, 0.0
                    time.sleep(1.0)
                    if Path(self.path).exists():
                        self.open()
                        ok2, _ = self.cap.read()
                        if ok2:
                            print(f"[{time.strftime('%H:%M:%S')}] 다시 연결 {self.port} ({self.name})", flush=True)
                            fails = 0
                else:
                    time.sleep(0.05)
                continue
            fails = 0
            g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) if f.ndim == 3 else f
            h, w = g.shape
            roi = g[h // 3: 2 * h // 3, w // 3: 2 * w // 3]
            foc = float(cv2.Laplacian(roi, cv2.CV_64F).var())
            mean = float(g.mean())
            covered = mean < 25 and foc < 20
            with self.lock:
                self.frame, self.stamp = f, time.time()
                self.focus = 0.7 * self.focus + 0.3 * foc if self.focus else foc
                if not covered:
                    self.focus_max = max(self.focus_max, self.focus)
                self.mean, self.sat = mean, float((g >= 250).mean())
                if covered != self.covered:
                    print(f"[{time.strftime('%H:%M:%S')}] {'COVERED' if covered else 'UNCOVERED'} {self.port} ({self.name})", flush=True)
                self.covered = covered
            n += 1
            if time.time() - t_last >= 1.0:
                self.fps, n, t_last = n / (time.time() - t_last), 0, time.time()

    def render(self, size=None, big=False):
        with self.lock:
            f = None if self.frame is None else self.frame.copy()
            st = dict(focus=self.focus, mx=self.focus_max, mean=self.mean, sat=self.sat, fps=self.fps, cov=self.covered)
        if f is None:
            f = np.zeros((H, W, 3), np.uint8)
        if ROTATE is not None:                  # 카메라를 옆으로 달았을 때 보기용 회전 (저장 사진은 원본 방향)
            f = cv2.rotate(f, ROTATE)
        h, w = f.shape[:2]
        for k in (1, 2):                       # 3분할 격자
            cv2.line(f, (w * k // 3, 0), (w * k // 3, h), (90, 90, 90), 1)
            cv2.line(f, (0, h * k // 3), (w, h * k // 3), (90, 90, 90), 1)
        cv2.line(f, (w // 2 - 40, h // 2), (w // 2 + 40, h // 2), (0, 0, 255), 2)   # 중앙 십자
        cv2.line(f, (w // 2, h // 2 - 40), (w // 2, h // 2 + 40), (0, 0, 255), 2)
        cv2.rectangle(f, (w // 3, h // 3), (2 * w // 3, 2 * h // 3), (0, 200, 255), 1)   # 초점 측정 영역
        if size:
            f = cv2.resize(f, size, interpolation=cv2.INTER_AREA)
            h, w = f.shape[:2]
        s = 1.6 if big else 0.8
        lab = f"{self.name}  [{self.port}]  {st['fps']:.0f}fps"
        col = (0, 0, 255) if st["cov"] else (0, 255, 0)
        cv2.putText(f, lab + ("  COVERED" if st["cov"] else ""), (10, int(30 * s)), cv2.FONT_HERSHEY_SIMPLEX, s, col, 2)
        cv2.putText(f, f"focus {st['focus']:.0f}  (max {st['mx']:.0f})  bright {st['mean']:.0f}  sat {st['sat']:.1%}",
                    (10, int(62 * s)), cv2.FONT_HERSHEY_SIMPLEX, s * 0.8, (0, 255, 255), 2)
        # 초점 막대: 지금 / 최고값
        bw = w - 20
        r = 0 if st["mx"] <= 0 else min(st["focus"] / st["mx"], 1.0)
        cv2.rectangle(f, (10, h - 30), (10 + bw, h - 12), (60, 60, 60), -1)
        cv2.rectangle(f, (10, h - 30), (10 + int(bw * r), h - 12), (0, 220, 0) if r > 0.95 else (0, 160, 255), -1)
        return f


def page_mosaic(cams) -> bytes:
    links = " · ".join(f'<a href="/cam/{i}">{c.name if c.name != "?" else c.port} 크게</a>' for i, c in enumerate(cams))
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Camera aim</title>
<style>body{{background:#111;color:#ddd;font-family:sans-serif;margin:6px}} img{{width:100%;max-width:2000px}} a{{color:#8cf}}</style></head><body>
<div>{links} · <a href="/snap">사진 저장 (4대)</a> · <a href="/reset">초점 최고값 초기화</a></div>
<img src="/mosaic"></body></html>""".encode()


def mosaic(cams, cell=(960, 540)) -> np.ndarray:
    """4대를 한 장으로 (2×2, 칸 960×540 → 1920×1080). 세로로 돌려 보면 가로 1줄 (칸 480×854)."""
    if ROTATE in (cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_90_COUNTERCLOCKWISE):
        tiles = [c.render((480, 854)) for c in cams[:4]]
        return np.hstack(tiles + [np.zeros_like(tiles[0])] * (4 - len(tiles)))
    tiles = [c.render(cell) for c in cams[:4]]
    while len(tiles) < 4:
        tiles.append(np.zeros((cell[1], cell[0], 3), np.uint8))
    return np.vstack([np.hstack(tiles[:2]), np.hstack(tiles[2:4])])


def page_grid(cams) -> bytes:
    cells = "".join(f'<div><a href="/cam/{i}"><img src="/stream/{i}" width="640" height="360"></a></div>' for i in range(len(cams)))
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Camera aim</title>
<style>body{{background:#111;color:#ddd;font-family:sans-serif;margin:8px}} .g{{display:grid;grid-template-columns:640px 640px;gap:6px}}
a{{color:#8cf}}</style></head><body>
<div>클릭 = 한 대 크게 · <a href="/snap">사진 저장 (4대)</a> · <a href="/reset">초점 최고값 초기화</a></div>
<div class="g">{cells}</div></body></html>""".encode()


def page_single(i) -> bytes:
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>cam {i}</title>
<style>body{{background:#111;color:#ddd;font-family:sans-serif;margin:8px}} img{{max-width:100%}} a{{color:#8cf}}</style></head><body>
<div><a href="/">← 4대 보기</a> · <a href="/reset">초점 최고값 초기화</a></div><img src="/stream/{i}?full=1"></body></html>""".encode()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--rotate", choices=["none", "cw", "ccw", "180"], default="none",
                    help="보기 회전 (카메라를 옆으로 달았을 때). 저장 사진·캘리브레이션 입력은 원본 방향 그대로")
    a = ap.parse_args()
    global ROTATE
    ROTATE = {"none": None, "cw": cv2.ROTATE_90_CLOCKWISE, "ccw": cv2.ROTATE_90_COUNTERCLOCKWISE,
              "180": cv2.ROTATE_180}[a.rotate]
    names = load_names()
    paths = sorted(glob.glob("/dev/v4l/by-path/*-usb-*-video-index0"))
    paths = [p for p in paths if "usbv2" not in p]        # 같은 장치의 중복 링크 제외
    # 이름이 있는 카메라(cam1~4) 먼저, 이름 순
    cams = [Cam(p, names.get(port_of(p), "?")) for p in paths]
    cams.sort(key=lambda c: (c.name == "?", c.name, c.port))
    print(f"카메라 {len(cams)}대: " + ", ".join(f"{c.name}={c.port}" for c in cams), flush=True)

    def watch_new():
        """서버 시작 뒤 새로 꽂힌 카메라도 추가 (2초마다 by-path 확인)."""
        while True:
            time.sleep(2)
            known = {c.path for c in cams}
            for p in sorted(glob.glob("/dev/v4l/by-path/*-usb-*-video-index0")):
                if "usbv2" in p or p in known:
                    continue
                c = Cam(p, names.get(port_of(p), "?"))
                cams.append(c)
                cams.sort(key=lambda c: (c.name == "?", c.name, c.port))
                print(f"[{time.strftime('%H:%M:%S')}] 다시 연결 {c.port} ({c.name}) — 새 카메라 추가, 총 {len(cams)}대", flush=True)

    threading.Thread(target=watch_new, daemon=True).start()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, body: bytes, ctype="text/html; charset=utf-8"):
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/":
                return self.send(page_mosaic(cams))
            if path == "/grid":
                return self.send(page_grid(cams))
            if path == "/mosaic":
                self.send_response(200)
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                self.end_headers()
                try:
                    while True:
                        ok, jpg = cv2.imencode(".jpg", mosaic(cams), [cv2.IMWRITE_JPEG_QUALITY, 80])
                        self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                         + str(len(jpg)).encode() + b"\r\n\r\n" + jpg.tobytes() + b"\r\n")
                        time.sleep(1 / 15)
                except (BrokenPipeError, ConnectionResetError):
                    return
            if path.startswith("/cam/"):
                return self.send(page_single(int(path.split("/")[2])))
            if path == "/reset":
                for c in cams:
                    with c.lock:
                        c.focus_max = 0.0
                self.send_response(302)
                self.send_header("Location", "/")
                self.end_headers()
                return
            if path == "/stats":
                return self.send(json.dumps([dict(name=c.name, port=c.port, focus=c.focus, focus_max=c.focus_max,
                                                  mean=c.mean, sat=c.sat, fps=c.fps, covered=c.covered) for c in cams]).encode(),
                                 "application/json")
            if path == "/snap":
                d = shared_dir() / "captures" / f"aim_{dt.datetime.now():%Y%m%d_%H%M%S}"
                d.mkdir(parents=True, exist_ok=True)
                saved = []
                for c in cams:
                    with c.lock:
                        f = None if c.frame is None else c.frame.copy()
                    if f is not None:
                        fn = d / f"{c.name if c.name != '?' else c.port.replace(':', '_')}.png"
                        cv2.imwrite(str(fn), f)
                        saved.append(fn.name)
                print(f"[{time.strftime('%H:%M:%S')}] 저장 {d} {saved}", flush=True)
                return self.send(f"<meta charset=utf-8>저장: {d}<br>{saved}<br><a href='/'>돌아가기</a>".encode())
            if path.startswith("/stream/"):
                i = int(path.split("/")[2])
                full = "full=1" in self.path
                self.send_response(200)
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                self.end_headers()
                try:
                    while True:
                        img = cams[i].render(None if full else (640, 360), big=full)
                        ok, jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
                        self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                         + str(len(jpg)).encode() + b"\r\n\r\n" + jpg.tobytes() + b"\r\n")
                        time.sleep(1 / 15)
                except (BrokenPipeError, ConnectionResetError):
                    return
            self.send_error(404)

    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    print(f"미리보기: http://{a.host}:{a.port}  (Ctrl+C 로 종료)", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
