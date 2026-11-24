# cv/ — AI 컴퓨터 Python 코드

방 복원(VGGT, Open3D), 카메라 캘리브레이션, 관절 추적(YOLO26-pose, 손 모델), 삼각측량, UDP 송신을 담당합니다.
이 폴더는 cv 세션만 수정합니다. 공통 규약은 [../docs/interfaces.md](../docs/interfaces.md)를 따릅니다.

## 환경

가상환경은 저장소 밖 `/storage/AI/cv_project/.venv` (uv, Python 3.12.14)를 씁니다. 캐시는 `/storage/AI/cv_project/.cache` (uv, torch 등), Hugging Face/VGGT 가중치는 `HF_HOME=/storage/AI/cache/huggingface`.

```bash
source cv/env.sh                               # venv 활성화 + 캐시 경로 + PYTHONPATH
uv pip install -c cv/constraints.txt <패키지>   # torch 2.3.1 / torchvision 0.18.1 / numpy<2 고정
python -m cv.recon.check_env                   # torch/CUDA/GPU, VGGT 가중치, Open3D, cv2.aruco 확인
```

환경 변수는 저장소 루트 `.env`에서 읽습니다 (`SHARED_DIR`, `VGGT_WEIGHTS` 등). `VGGT_WEIGHTS`는 `model.safetensors` 파일 또는 그 폴더.

## ChArUco 보드 (`cv/calib/`)

```bash
python -m cv.calib.make_charuco                     # charuco.yaml 대로 PDF/PNG 생성 (기존 파일은 --force 없이는 안 덮어씀)
python -m cv.calib.make_charuco --set-measured 50   # 인쇄물 실측 칸 크기(mm) → cv/config/charuco.yaml
python -m cv.calib.charuco_range                    # 현재 보드의 검출 거리 시험 (폰 / 1080p 웹캠, 합성)
```

- 현재 보드: A3, 5×7칸, 칸 50mm, 마커 37mm, `DICT_4X4_50`, **벽에 세로로 부착**. 월드 좌표계 정의는 `docs/interfaces.md` 1절.
- 실측: 가로 5칸 전체 폭 ÷ 5, 세로 7칸 전체 높이 ÷ 7을 재서 평균. 마커만 따로 쟀으면 `--marker-mm`.
- 검출 거리 (합성, 실제는 조금 짧음): 폰 12MP 정면 3.5m / 45° 이내 3.0m, 1080p 웹캠 2.0~2.5m. (예전 A4 35mm는 폰 1.6m)

### 손에 드는 보드 (`cv/config/charuco_handheld.yaml`)

```bash
python -m cv.calib.make_charuco --config charuco_handheld.yaml   # A3 PDF/PNG (…_id17.pdf)
python -m cv.calib.handheld_range [--save]                       # 칸 크기 후보별 검출 거리 (천장 모서리 OV9281, 합성)
python -m cv.calib.handheld_range --mix-test                     # 벽 보드 + 손 보드 한 장면에서 구분되는지 시험
```

- A3, 3×4칸, 칸 95mm, 마커 76mm, `DICT_4X4_50` **마커 17~22번** (벽 보드 0~16번과 겹치지 않음). 폼보드에 붙여 평평하게.
- 검출: `cv.calib.charuco.detect_boards(gray, load_boards())` → `{"wall": …, "handheld": …}`. 마커를 한 번 찾고 번호 범위로 보드를 나눈다.
  보드 하나만 쓸 때는 `spec.detect(gray)` (손 보드는 설정의 `detector:` 절대로 작은 마커용 매개변수 + 2배 확대 후 검출).
- 합성 검출 거리 (보드를 세워 든 채, 카메라 높이 2.3m → 가슴 높이 1.2m): 렌즈 수평 70°면 yaw 45° 이내 3.0m, 30° 이내 3.5m.
  수평 90°면 yaw 30° 이내 2.0m, 정면 2.5m. 넓은 렌즈에서 방 가운데를 쓰려면 보드를 카메라 쪽으로 기울여 들거나 더 큰 용지 필요.

## 방 메시 (`cv/recon/`)

```bash
python -m cv.recon.build_room ${SHARED_DIR}/scans/<폴더> --desc <설명> [--room-size 3.3 2.5 | --cam-height 1.4]
python -m cv.recon.validate_mesh [파일.glb]           # 기본: ${SHARED_DIR}/meshes/room_latest.glb
python -m cv.recon.test_charuco_scale                # ChArUco 스케일 보정 합성 시험
python -m cv.recon.bench_vggt --images <폴더>         # 이미지 수별 메모리/시간
```

순서: 이미지 → VGGT(GPU 0, 카메라+깊이) → 신뢰도/경계 필터 → 바닥 RANSAC(수평면 점만, 가장 낮은 평면) + 벽 방향 yaw 정렬
→ 월드/스케일(ChArUco 다시점 삼각측량 + 3D 정합: 원점 = 보드 중심의 바닥 투영, +X = 보드 +X의 바닥 투영
→ 실패 시 `--room-size` / `--cam-height` / `--scale-factor`) → TSDF(미터, 2cm 복셀)
→ 작은 조각 제거, quadric 간소화(15만 삼각형) → 바닥 메우기(`--fill-floor auto|on|off`, 바닥 덮임 80% 미만이면 빈 칸을 y≈0 평면으로)
→ `.glb`(COLOR_0 선형 float, glTF 좌표계).

출력: `${SHARED_DIR}/meshes/room_<YYYYMMDD>_<desc>.glb`, `room_latest.glb`, `room_latest.json`,
디버그 `${SHARED_DIR}/recon_debug/<이름>/` (points.ply, cameras.json, preview.png, report.json).
파라미터: `cv/config/recon.yaml`.

### 메시 개선 실험 (`cv/recon/`, 결과는 `${SHARED_DIR}/meshes/experiments/<방법>/<이름>/`)

`build_room`으로 메시를 만든 뒤, 같은 방에 대해 한 줄씩 실행합니다. 인자를 생략하면 `room_latest.json`이 가리키는 메시입니다.
`room_latest.*`는 절대 건드리지 않습니다.

```bash
python -m cv.recon.proxy_fit            # 1. 평면(바닥/천장/벽 RANSAC) + 가구 상자 → proxy.json (interfaces.md 2-1절), proxy.glb
python -m cv.recon.smooth_mesh          # 2. Taubin 스무딩(경계 고정) / 간소화 → smooth_*.glb
python -m cv.recon.run_2dgs             # 3. VGGT → COLMAP(+SIFT·BA 시도) → 2DGS 학습(GPU 0) → 메시 → 2dgs_*.glb
python -m cv.recon.run_spatiallm        # 4. SpatialLM 1.1 (GPU 1) → proxy.json   (--input mesh, --seeds 0 1 2)
python -m cv.recon.run_hybrid           # SpatialLM 8시드 투표 + 점구름 맞춤 → hybrid/<이름>/proxy_hybrid.json, RANSAC 과 상자별 비교표
python -m cv.recon.run_3dgs             # 3DGS(gsplat, GPU 0), 포즈 최적화 끔/켬 → PSNR/SSIM/LPIPS, 떠다니는 조각, 렌더 영상
python -m cv.recon.compare_experiments  # 방법별 비교표 → experiments/compare_<이름>.md
```

- 프록시(RANSAC)는 벽 앞 얇은 판(벽 법선 방향 두께 ≤ 0.22m, 벽에서 0.15m 안)과 8cm 보다 얇은 상자를 잡음으로 지우고 `report.json`에 이유를 남깁니다.
- 하이브리드: 벽·바닥·천장은 RANSAC 평면, 가구는 SpatialLM 투표(시드 절반 이상)로 종류를 정하고 점구름으로 다시 맞춤.
  옆 가구 점은 RANSAC 상자로 갈라내고, 크기는 SpatialLM 상자 + 25cm 까지만. 그림·커튼·카펫은 맞추지 않음. SpatialLM 이 놓친 RANSAC 상자는 `furniture`로 덧붙임.
- 3DGS: `envs/gsplat` (Python 3.10, gsplat 1.5.3 미리 빌드 wheel, 공식 `examples/simple_trainer.py`), `bash cv/recon/envs/setup_gsplat.sh`.
  월드 정규화를 꺼서 가우시안도 월드 좌표 그대로. COLMAP 입력은 `export_colmap`이 txt 와 bin 을 함께 씀 (gsplat 의 pycolmap 포크는 txt 를 못 읽음).

- 2DGS, SpatialLM은 각각 별도 uv 환경(`/storage/AI/cv_project/envs/{2dgs,spatiallm}`)에서 하위 프로세스로 돕니다.
  처음 한 번 `bash cv/recon/envs/setup_2dgs.sh`, `bash cv/recon/envs/setup_spatiallm.sh` (sudo 불필요, 시스템 nvcc 12.4 + gcc-13).
- 2DGS: `export_colmap`이 VGGT 포즈를 우리 월드 좌표 그대로 COLMAP 모델로 내보내므로 결과 메시도 같은 좌표입니다.
  BA는 결과가 정상(배율 ±5%, 카메라 이동 평균 5cm, 회전 3° 이내)일 때만 쓰고 아니면 VGGT 포즈로 학습합니다.
- SpatialLM 입력은 z-up이라 `(x, y, z) → (x, −z, y)`로 한 번 바꾸고 결과를 되돌립니다. 생성 모델이라 시드마다 결과가 다릅니다.
- 미리보기는 Open3D 오프스크린 렌더(헤드리스, Vulkan)입니다.
- 라이선스: 2DGS = Inria/MPII Gaussian-Splatting 라이선스(비상업 연구), SpatialLM1.1 = 모델 Apache-2.0(Qwen 기반)이나
  Sonata 인코더 가중치 CC-BY-NC-4.0(비상업). 공개/상업 사용 전 확인 필요.

### 촬영 요령 (폰)

- 방 전체를 40~100장, 사진 사이 겹침이 충분하게 (한 걸음씩 이동하며 벽을 따라 한 바퀴 + 방 중앙에서 한 바퀴).
- 바닥이 보이게 약간 아래를 향해. 가로/세로 방향은 한 가지로 통일.
- 벽의 ChArUco 보드가 **1~2.5m 거리에서 서로 다른 방향으로 4장 이상** 나오게 (보드와 주변 벽/바닥/가구가 같이 보이게).
- JPG로 저장 (HEIC 미지원).

## 데이터

입력 사진과 출력 메시는 git이 아닌 `SHARED_DIR` 아래에 둡니다.
