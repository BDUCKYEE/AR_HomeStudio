# cv/ — AI 컴퓨터 Python 코드

방 복원(VGGT, Open3D), 카메라 캘리브레이션, 관절 추적(YOLO26-pose, 손 모델), 삼각측량, UDP 송신을 담당합니다.
이 폴더는 cv 세션만 수정합니다. 공통 규약은 [../docs/interfaces.md](../docs/interfaces.md)를 따릅니다.

## 환경

가상환경은 저장소 밖 `/storage/AI/test/.venv` (uv, Python 3.12.14)를 씁니다. 캐시는 `/storage/AI/test/.cache`.

```bash
source cv/env.sh                               # venv 활성화 + 캐시 경로 + PYTHONPATH
uv pip install -c cv/constraints.txt <패키지>   # torch 2.3.1 / torchvision 0.18.1 / numpy<2 고정
python -m cv.recon.check_env                   # torch/CUDA/GPU, VGGT 가중치, Open3D, cv2.aruco 확인
```

환경 변수는 저장소 루트 `.env`에서 읽습니다 (`SHARED_DIR`, `VGGT_WEIGHTS` 등). `VGGT_WEIGHTS`는 `model.safetensors` 파일 또는 그 폴더.

## ChArUco 보드 (`cv/calib/`)

```bash
python -m cv.calib.make_charuco                     # ${SHARED_DIR}/charuco/charuco_A4_5x7_35mm_DICT_4X4_50.{pdf,png}
python -m cv.calib.make_charuco --set-measured 34.8 # 인쇄물 실측 칸 크기(mm) → cv/config/charuco.yaml
```

- 5×7칸, 칸 35mm, 마커 26mm, `DICT_4X4_50`, A4 세로. PDF는 "실제 크기(100%)"로 인쇄.
- 실측: 가로 5칸 전체 폭 ÷ 5, 세로 7칸 전체 높이 ÷ 7을 재서 평균. 마커만 따로 쟀으면 `--marker-mm`.
- 폰 사진(12MP)에서 보드 검출은 카메라-보드 거리 약 1.6m까지 (합성 시험 기준). 2m 이상은 실패.

## 방 메시 (`cv/recon/`)

```bash
python -m cv.recon.build_room ${SHARED_DIR}/scans/<폴더> --desc <설명> [--room-size 3.3 2.5 | --cam-height 1.4]
python -m cv.recon.validate_mesh [파일.glb]           # 기본: ${SHARED_DIR}/meshes/room_latest.glb
python -m cv.recon.test_charuco_scale                # ChArUco 스케일 보정 합성 시험
python -m cv.recon.bench_vggt --images <폴더>         # 이미지 수별 메모리/시간
```

순서: 이미지 → VGGT(GPU 0, 카메라+깊이) → 신뢰도/경계 필터 → 바닥 RANSAC(수평면 점만, 가장 낮은 평면) + 벽 방향 yaw 정렬
→ 스케일(ChArUco 다시점 삼각측량 → 실패 시 `--room-size` / `--cam-height` / `--scale-factor`) → TSDF(미터, 2cm 복셀)
→ 작은 조각 제거, quadric 간소화(15만 삼각형) → `.glb`(COLOR_0 선형 float, glTF 좌표계).

출력: `${SHARED_DIR}/meshes/room_<YYYYMMDD>_<desc>.glb`, `room_latest.glb`, `room_latest.json`,
디버그 `${SHARED_DIR}/recon_debug/<이름>/` (points.ply, cameras.json, preview.png, report.json).
파라미터: `cv/config/recon.yaml`.

### 촬영 요령 (폰)

- 방 전체를 40~100장, 사진 사이 겹침이 충분하게 (한 걸음씩 이동하며 벽을 따라 한 바퀴 + 방 중앙에서 한 바퀴).
- 바닥이 보이게 약간 아래를 향해. 가로/세로 방향은 한 가지로 통일.
- ChArUco 보드는 바닥 위에 평평하게, **보드에서 1~1.5m 거리에서 서로 다른 방향으로 4장 이상** (보드와 주변 바닥/가구가 같이 보이게).
- JPG로 저장 (HEIC 미지원).

## 데이터

입력 사진과 출력 메시는 git이 아닌 `SHARED_DIR` 아래에 둡니다.
