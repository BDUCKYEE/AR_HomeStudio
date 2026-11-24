# cv 세션 진행 기록 (AI 컴퓨터)

> 이 파일은 cv 세션만 수정합니다. unity 세션은 읽기만 합니다.

## 현재 상태

- 마지막 갱신: 2026-11-25 01:15
- 단계: **메시 고도화 2차 비교 완료** (기존 파이프라인 + 잡음 규칙, SpatialLM+RANSAC 하이브리드, 3DGS 포즈 최적화 끔/켬 — 아래 "2차" 표). 카메라 측량(캘리브레이션)은 cam2 케이스가 오면(약 2026-11-30) 진행
- 최신 메시: `room_latest.glb` = `room_20261124_myroom2-charuco.glb` (`source: real`, `charuco`), 153,757 삼각형, 보드 중심 높이 **0.9046m**. 입력 `scans/20261124` 158장 중 120장(균등 추림), 전체 72초
  - 검증 전 항목 PASS. 벽 기준 방 크기(proxy_fit) 2.60×3.29m, 높이 2.37m (실측 2.5×3.3 대비 +4%/−0.3%). validate 의 백분위 범위는 3.34×2.88m 로 나오는데 벽 밖 점(문 등) 때문
  - ChArUco: 20시점, 코너 24/24, 재투영 2.1px, 정합 잔차 5.0mm(이전 2.3), 휨 4.2mm, 보드 법선-바닥 88.1°, `z_into_room: true`
  - **보드를 옮겼으므로 월드 좌표계가 바뀜** (이전 20261110 메시·실험 결과와 좌표가 다름). 벽이 월드 축에서 약 4° 돌아가 보임 (보드 +X 가 벽과 완전히 나란하지 않음, 규약상 문제 없음)
- 고정 카메라: 4대 모두 MJPG 1280×720 29fps 동시 캡처 OK. **4대 모두 옆으로 달려 있음**(반시계 90° 돌리면 바로 섬). 이름 ↔ 포트 `cv/config/cameras.yaml`: 지금은 cam2 = `0e:00.3-2`만 확정, cam1/3/4 는 다음 세션
  - 초점(가운데 1/3 라플라시안 분산, 마지막 값): `0b:00.0-5` 1100 / `0b:00.0-7` 330 / `0f:00.0-1` 300 / cam2 `0e:00.3-2` 상(像)이 안 맺힘(먼지만 또렷 → 렌즈가 거의 빠짐, 원인 = 케이스 나사 파손)

## READY

- READY: **하이브리드 프록시** `experiments/hybrid/<메시>/proxy_hybrid.json` (+ `.glb`, `preview.png`, `box_compare.md`) / `python -m cv.recon.run_hybrid [메시] [--seeds 8]` / 두 방 모두 RANSAC 상자를 하나도 빠뜨리지 않음, 규약 검사 통과 (단 `method: "hybrid"` 는 interfaces.md 갱신 전, 아래 사용자 확인)
- READY: **3DGS (gsplat)** `experiments/3dgs/room_20261124_myroom2-charuco/` (`model_{noposeopt,poseopt}`, `3dgs_metrics.json`, 영상) / `python -m cv.recon.run_3dgs [메시]` (GPU 0, 변형당 약 18분), 둘러보기 영상 `gsplat_render_tour.py`, 학습 시점 평가 `gsplat_eval_train.py`. 환경 `bash cv/recon/envs/setup_gsplat.sh` (Python 3.10, gsplat 1.5.3 wheel)
- READY: **카메라 미리보기 서버** (초점·각도 맞춤) / `python -m cv.capture.preview_server --host <Tailscale/LAN IP> --port 8091 --rotate ccw` → 다른 컴퓨터 브라우저 `http://<IP>:8091` /
  4대를 한 영상으로(돌린 보기 1줄), 카메라별 크게 보기(`/cam/<n>`), 3분할 격자·중앙 십자, 초점 수치·최고값 막대, 렌즈 가림 감지(이름 매핑용), `/snap` 4대 사진 저장(`${SHARED_DIR}/captures/aim_<시각>/`), USB 뽑았다 꽂아도 자동 재연결·새 카메라 추가. IP 는 실행 인자로만 (코드·커밋에 없음)
- READY: **새 방 메시** `room_latest.glb` = `room_20261124_myroom2-charuco.glb` (위 현재 상태), 프록시 `experiments/proxy-ransac/room_20261124_myroom2-charuco/`

- READY: **메시 개선 실험** / 결과 `${SHARED_DIR}/meshes/experiments/<방법>/<메시 이름>/`, 비교표 `experiments/compare_<메시 이름>.md` (아래 표) /
  `python -m cv.recon.proxy_fit` · `smooth_mesh` · `run_2dgs` · `run_spatiallm` · `compare_experiments` (인자 없으면 `room_latest.json`의 메시, 새 방도 같은 명령 한 줄). 예제 침실로도 재실행 확인
- READY: **방 프록시** `proxy.json` (interfaces.md 2-1절) / `experiments/proxy-ransac/room_20261110_myroom-charuco/{proxy.json, proxy.glb, preview.png}` /
  벽 4 + 바닥 + 천장, 가구 상자 18개, 방 2.55×3.27m(실측 2.5×3.3, +2%/−1%) 높이 2.37m. 저장 전 규약 검사(`check_proxy`) 통과. 같은 입력이면 같은 결과(시드 고정 RANSAC)
- READY: SpatialLM 프록시 `experiments/spatiallm/room_20261110_myroom-charuco/proxy.json` (점구름 입력, 시드 0: 벽 4, 문 1, 창 2, 상자 11 — bed, desk, bookcase 등 종류 포함) + 시드/입력별 변형
- READY: 2DGS / SpatialLM 전용 환경 `/storage/AI/cv_project/envs/{2dgs,spatiallm}/.venv` (메인 .venv 무변경) / `bash cv/recon/envs/setup_2dgs.sh`, `setup_spatiallm.sh` (sudo 불필요: 시스템 nvcc 12.4 + gcc-13, flash-attn 미리 빌드 wheel)
- READY: **손에 드는 ChArUco 보드** / `${SHARED_DIR}/charuco/charuco_A3_3x4_95mm_DICT_4X4_50_id17.pdf` (A3 실측, 100mm 자·보드 정보 표기, 인쇄 내용이 가장자리에서 6mm 이상 안쪽), 설정 `cv/config/charuco_handheld.yaml` /
  3×4칸, 칸 95mm, 마커 76mm, `DICT_4X4_50` 17~22번. 검출 `cv.calib.charuco.detect_boards()`가 마커 번호로 벽 보드(0~16)와 구분 → 한 장면 합성 시험(`handheld_range --mix-test`) 벽 24/24, 손 6/6, 섞임 0, 코너 오차 평균 0.30px. 생성 이미지 자체 검출 6/6, 칸 간격 2280.00px(기대 2280)

- READY: **실제 방 메시** / `${SHARED_DIR}/meshes/room_latest.glb` (= `room_20261110_myroom-charuco.glb`) + `room_latest.json` / 입력 `scans/20261110` 82장 중 세로 81장(가로 1장 제외), VGGT 17초 11.4GB, 전체 50초. ChArUco: 20시점에서 코너 24/24 삼각측량, 재투영 평균 1.8px, 보드 정합 잔차 2.3mm, 휨 2.2mm, 보드 중심 높이 0.895m, +Z 방 안쪽 확인. validate 전 항목 PASS: 바닥 1백분위 y −0.009m, 높이 2.37m, **수평 범위 3.35×2.60m (실측 3.3×2.5 대비 +2%/+4%, 스케일은 보드만으로 정했으므로 독립 확인)**. 바닥 덮임 53% → 1,629칸 메움

- READY: ChArUco 보드 A4 인쇄본 / `${SHARED_DIR}/charuco/charuco_A4_5x7_35mm_DICT_4X4_50.{pdf,png}`, 파라미터 `cv/config/charuco.yaml` / 생성 이미지 자체 검출 코너 24/24, 칸 간격 840.00px(기대 840), PDF 페이지 210.00×297.00mm
- READY: cv 가상환경 / `/storage/AI/cv_project/.venv` (`source cv/env.sh`, 캐시는 `/storage/AI/cv_project/.cache`) / `python -m cv.recon.check_env` → torch 2.3.1+cu121, CUDA OK, GPU 2장(RTX 3090 24GB ×2), numpy 1.26.4, Open3D 0.20.0(CUDA 빌드), OpenCV 4.10(cv2.aruco ChArUco OK), trimesh 5.2.0, VGGT import + 가중치 로드 OK. 추가 설치: trimesh, python-dotenv, vggt(-e, --no-deps). 기존 패키지 변경 없음
- READY: VGGT GPU 0 추론 벤치마크 / `python -m cv.recon.bench_vggt` / 아래 표
- READY: 방 메시 파이프라인 / `python -m cv.recon.build_room <이미지 폴더> --desc <설명>`, 검사 `python -m cv.recon.validate_mesh` / 예제 침실 8장 끝까지 9초. 검사: 형식·정점 색·삼각형 수·미터 단위·바닥 y≈0(1백분위 −0.004m)·높이 PASS, 방 크기 WARN(4.85×3.06m, 예제 방이라 당연). trimesh로도 정상 로드(COLOR_0 확인). 법선 98%가 카메라 쪽(방 안쪽)
- READY: ChArUco 스케일 보정 / `python -m cv.recon.test_charuco_scale` (합성 5시점) / 스케일 오차 0.43%, 회전 0.007°, 원점 0.12mm → 통과
- READY: 새 월드 좌표계 (interfaces.md 1절, 벽 보드) / `cv/recon/scale.py` `charuco_world` / 합성 시험(A3 보드를 벽에 뒤로 3°·면 안 2° 기울여 부착, 5시점): 스케일 오차 0.31%, 회전 0.012°, 원점 1.5mm, 보드 중심 높이 1.2537m(참 1.25), +Z 방 안쪽 확인 → 통과
- READY: 바닥 메우기 / `build_room --fill-floor auto|on|off` (`recon.yaml` `floor_fill`) / 예제 침실: 바닥 덮임 11% → 5,351칸(5cm) 채움, 법선 100% +Y, validate 바닥 표면 비율 9% → 49%
- READY: A3 보드 검출 거리 / `python -m cv.calib.charuco_range` / 아래 표
- READY (임시 메시): `${SHARED_DIR}/meshes/room_latest.glb` + `room_latest.json` / 예제 침실 (unity 쪽 glTFast 로드 시험용) / validate 통과(방 크기 WARN)

### 메시 고도화 비교 2차 (2026-11-25): 지난번 방(20261110) vs 이번 방(20261124, 잡다한 물건 치움, 보드 새 위치)

`python -m cv.recon.compare_experiments <메시>` 전체 표: `${SHARED_DIR}/meshes/experiments/compare_<메시>.md`. 두 방은 보드 위치가 달라 좌표계가 서로 다름.

| 방법 | 지표 | 20261110 (지난번) | 20261124 (이번) |
|---|---|---|---|
| 1. 원본 TSDF | 삼각형 / 벽 평면도 RMS / 국소 거칠기 / 벽 덮임 | 153,258 / 30.6mm / 13.6mm / 66% | 153,757 / 29.2mm / 16.2mm / 56% |
| 1. + 스무딩 `t30-s50k` | 삼각형 / 국소 거칠기 / 벽 덮임 | 5만 / 12.8mm / 66% | 5만 / 15.2mm / 55% |
| 1. + 평면·상자 `proxy.json` (RANSAC) | 방 크기·높이 / 상자 (벽 앞 판 제거) | 2.55×3.27m, 2.37m / 12개 (−6) | 2.60×3.29m, 2.37m / 10개 (−5) |
| 2. 하이브리드 `proxy_hybrid.json` | 시드별 SpatialLM 상자 수 (8시드) | 11~17 | **9~14** |
| | 투표 통과 / 그중 가구 / RANSAC 에서 보탬 / 최종 상자 | 14 / 8 / 6 / 20 | 11 / 6 / 5 / 16 |
| | 가구 상자의 RANSAC 대응 3D IoU 평균 | 0.54 | 0.40 |
| | 종류 | bed, desk, bookcase×2, cupboard, chair, computer, 그림·커튼·에어컨 | bed, desk, bookcase×3, computer, carpet, 그림·커튼 |
| | 시간 (SpatialLM 8회 포함) | 88초 | 87초 |
| 3. 3DGS (gsplat, 30k) 포즈 최적화 끔 | 학습 / PSNR 평가·학습 시점 / SSIM / LPIPS / 떠다님 | (2DGS 만 해 봄: 48.9분, 벽 덮임 54%) | 17.3분 / 15.38·25.87 / 0.599 / 0.616 / 31.1% |
| 3. 3DGS 포즈 최적화 켬 | 〃 | – | 18.5분 / **15.75·26.81** / **0.607** / **0.592** / **29.8%** |

- **1. 기존 파이프라인**: 새 방은 벽 덮임이 56%로 지난번(66%)보다 낮고 국소 거칠기도 큼 (사진 158장 중 VGGT 상한 120장만 사용). 스무딩은 두 방 모두 거칠기만 약 6% 줄이고 벽 휨·구멍은 그대로.
  새 잡음 규칙(벽 법선 방향 두께 ≤ 0.22m 이고 벽에서 0.15m 안인 판, 8cm 보다 얇은 상자 제거)으로 보드 벽 앞 0.85×2.28×0.20m 판 등 5~6개가 빠짐 (`proxy-ransac/<메시>/report.json` 의 `boxes_removed`)
- **2. 하이브리드**: 물건을 치운 효과로 시드별 SpatialLM 상자 수가 줄고(11~17 → 9~14) 투표 통과 상자도 정리됨. 하지만 RANSAC 과의 IoU 는 0.54 → 0.40 으로 낮아짐
  (이번 방은 RANSAC 이 책장 둘을 한 상자(0.35×1.71×1.95m)로 묶고, 하이브리드는 bookcase 3개로 나눔 → 상자 단위로는 하이브리드가 실제에 더 가까워 보임).
  점구름 맞춤에서 옆 가구 점이 섞이면 상자가 부풀어서(침대가 2.03×1.16m) RANSAC 상자로 옆 가구 점을 갈라내고 크기를 SpatialLM + 25cm 로 제한함 → 침대 1.95×0.94×0.95m (RANSAC IoU 0.42 → 0.56). 문·창은 시드 절반 이상에서 나온 것이 없어 0개.
  상자별 표: `experiments/hybrid/<메시>/box_compare.md`
- **3. 3DGS**: 학습 시점 PSNR 26~27 인데 평가 시점 15~16 → **약 10dB 차이 = 새 시점 일반화 실패**. 원인은 VGGT 포즈 오차와 근접 사진 부족(평가 그림에서 바닥·물건 근접 사진이 크게 어긋남). 포즈 최적화는 모든 지표에서 조금 낫지만(평가 +0.4dB, 학습 +0.9dB, 떠다님 −1.3%p, 시간 +7%) 차이를 메우지 못함.
  방 안 가시 가우시안의 약 30%가 TSDF 표면에서 10cm 넘게 떠 있음 (TSDF 에도 구멍이 있어 절대값보다 두 변형의 상대 비교로 봄).
  영상: `3dgs/<메시>/3dgs_tour_compare.mp4` (학습 카메라 촬영 순서대로 16초 둘러보기, 왼쪽 끔/오른쪽 켬, 둘 다 VGGT 포즈 경로라 켬 쪽에 조금 불리), `3dgs_compare.mp4`(트레이너 기본 궤적 3.6초, RGB+깊이), 평가 시점 그림 `3dgs_compare.png`
- **소요 시간 참고** (120장, 1600×1200, RTX 3090): VGGT 포즈 25초 + 3DGS 학습 17~19분 ≈ 18분. COLMAP SfM 으로 포즈를 구하면 5~20분 더 들고, 흰 벽에서는 매칭 부족으로 일부만 등록될 위험이 큼 (지난번 BA 시도에서 발산)

### 메시 개선 실험 비교 (2026-11-23, `room_20261110_myroom-charuco`, 실측 2.5×3.3m)

`python -m cv.recon.compare_experiments` 출력. 미리보기 경로는 `${SHARED_DIR}` 기준.
벽 평면도: 메시 = proxy-ransac 벽 평면 ±6cm 안 표면의 RMS / 20cm 타일 잔차(국소 거칠기), 프록시 = 입력 점이 그 벽 ±10cm 안에서 떨어진 RMS.
구멍: 메시 = 벽 5cm 칸 중 표면 있는 비율 / 열린 경계 길이, 프록시 = 평면이라 구멍 없음(괄호는 입력 점 덮임).

| 방법 | 시간 | 삼각형/상자 | 방 크기 | 벽 평면도 | 구멍 | 미리보기 |
|---|---|---|---|---|---|---|
| 원본 TSDF (기준) | - | 153,258 | - | 30.6mm / 13.6mm | 덮임 66% / 경계 225m | `meshes/experiments/smooth/room_20261110_myroom-charuco/smooth_orig.png` |
| smooth t10 | 1s | 153,258 | - | 30.4mm / 13.07mm | 덮임 66% / 경계 225m | `meshes/experiments/smooth/room_20261110_myroom-charuco/smooth_t10.png` |
| smooth t30 | 1s | 153,258 | - | 30.4mm / 12.85mm | 덮임 66% / 경계 225m | `meshes/experiments/smooth/room_20261110_myroom-charuco/smooth_t30.png` |
| smooth t100 | 3s | 153,258 | - | 30.5mm / 12.75mm | 덮임 66% / 경계 225m | `meshes/experiments/smooth/room_20261110_myroom-charuco/smooth_t100.png` |
| smooth t30-s50k | 2s | 49,999 | - | 30.4mm / 12.81mm | 덮임 66% / 경계 223m | `meshes/experiments/smooth/room_20261110_myroom-charuco/smooth_t30-s50k.png` |
| smooth t30-s20k | 2s | 19,999 | - | 30.4mm / 12.6mm | 덮임 66% / 경계 208m | `meshes/experiments/smooth/room_20261110_myroom-charuco/smooth_t30-s20k.png` |
| 2DGS noba (가우시안 1,756,450) | 48.9분 | 150,000 | - | 33.5mm / 16.19mm | 덮임 54% / 경계 686m | `meshes/experiments/2dgs/room_20261110_myroom-charuco/2dgs_noba.png` |
| 평면+상자 (RANSAC) | 3s | 벽 4, 상자 18 | 2.55×3.27m, 높이 2.37m | 평면 (점 44mm) | 없음 (점 덮임 73%) | `meshes/experiments/proxy-ransac/room_20261110_myroom-charuco/preview.png` |
| SpatialLM points s0 | 6s | 벽 4, 상자 11, 문/창 3 | 2.45×3.25m, 높이 2.28m | 평면 (점 50mm) | 없음 (점 덮임 76%) | `meshes/experiments/spatiallm/room_20261110_myroom-charuco/proxy.png` |
| SpatialLM mesh s0 | 5s | 벽 4, 상자 11, 문/창 2 | 2.40×3.17m, 높이 2.48m | 평면 (점 54mm) | 없음 (점 덮임 72%) | `meshes/experiments/spatiallm/room_20261110_myroom-charuco/proxy_mesh_s0.png` |
| SpatialLM mesh s1 | 4s | 벽 4, 상자 8, 문/창 2 | 2.45×3.23m, 높이 2.38m | 평면 (점 49mm) | 없음 (점 덮임 73%) | `meshes/experiments/spatiallm/room_20261110_myroom-charuco/proxy_mesh_s1.png` |
| SpatialLM mesh s2 | 4s | 벽 4, 상자 9, 문/창 1 | 2.52×3.30m, 높이 2.38m | 평면 (점 56mm) | 없음 (점 덮임 51%) | `meshes/experiments/spatiallm/room_20261110_myroom-charuco/proxy_mesh_s2.png` |
| SpatialLM points s1 | 6s | 벽 4, 상자 14 | 2.48×3.23m, 높이 2.30m | 평면 (점 47mm) | 없음 (점 덮임 75%) | `meshes/experiments/spatiallm/room_20261110_myroom-charuco/proxy_points_s1.png` |
| SpatialLM points s2 | 6s | 벽 4, 상자 15 | 2.48×3.23m, 높이 2.28m | 평면 (점 48mm) | 없음 (점 덮임 74%) | `meshes/experiments/spatiallm/room_20261110_myroom-charuco/proxy_points_s2.png` |

- **평면+상자 (RANSAC)**: 3초, 방 크기 +2%/−1%, 높이 2.37m. 벽에 구멍이 없고 삼각형 수백 개라 충돌체·가림용으로 가장 실용적. 가구 상자는 위에서 본 높이 지도(2.5D)로 나눔 (VGGT 점 잡음 때문에 3D DBSCAN 은 방 전체를 한 덩어리로 묶었음). 볼록한 방 가정
- **Taubin 스무딩**: 국소 거칠기 13.6 → 12.8mm(t30), 벽 전체 휨(30mm)은 그대로. 경계 정점을 고정해야 함 (Open3D 기본 Taubin 은 바닥 메우기 조각·구멍 가장자리를 오그라뜨림: 열린 경계 524m → 177m). 2만 삼각형까지 줄여도 지표 변화 없음 → Unity 충돌체용으로 `t30-s50k`/`s20k` 추천
- **2DGS**: 학습 46.8분(GPU 0, 30k 반복, 가우시안 176만) + 메시 15초. 색은 좋으나 방 안에 떠다니는 조각이 많고 벽 덮임 54%(원본 66%), 거칠기 16mm 로 **원본 TSDF 보다 나쁨**. 원인: VGGT 포즈 오차(1600px 기준 재투영 4.6px). BA 는 흰 벽 SIFT 매칭 부족으로 발산해 기각(점 3,122개, 정렬 배율 0.73, 카메라 이동 평균 20cm·최대 1.8m) → 포즈를 먼저 개선해야 의미 있음
- **SpatialLM 1.1 (Qwen-0.5B)**: 추론 5~6초(GPU 1, 1.7GB, 모델 로드 4초). 벽 4개는 시드와 무관하게 안정(방 2.45~2.48×3.23~3.25m), 높이 2.28~2.30m 로 RANSAC(2.37m)보다 낮음. 가구 종류(bed, desk, bookcase, computer, curtain 등)를 주는 게 장점이나 시드마다 상자 11~15개로 달라지고, 메시 표면 샘플을 넣으면 `tub`(욕조) 오분류가 섞임 → 점구름 입력이 나음. 벽 아래 끝이 y=0.06m (모델의 2.5cm 양자화·최솟값 이동 영향, `stats.floor_y_m`)

### 손 보드 후보 검출 거리 (합성, `python -m cv.calib.handheld_range`, 전체 표 `${SHARED_DIR}/charuco/handheld_range.md`)

천장 모서리 카메라(높이 2.3m, OV9281 1280×800 모노, 저대비·흐림·잡음) → 가슴 높이(1.2m)에 세워 든 A3 보드. 값 = yaw 0/30/45/60° 별 검출 코너 비율.
검출 설정 = 작은 마커용 매개변수 + 2배 확대 (OpenCV 기본 설정이면 70° 렌즈 3m 에서 67~83% 로 떨어짐).

| 보드 (A3) | 코너 | 렌즈 수평 70° 2.5m | 70° 3.0m | 70° 3.5m | 렌즈 수평 90° 2.0m | 90° 2.5m |
|---|---:|---|---|---|---|---|
| **3×4, 칸 95mm (채택)** | 6 | 100/100/100/46% | 100/100/100/0% | 100/100/46/0% | 100/100/83/4% | 100/46/25/0% |
| 3×4, 칸 90mm | 6 | 100/100/100/29% | 100/100/96/0% | 100/83/21/0% | 100/100/83/0% | 67/17/0/0% |
| 3×5, 칸 76mm | 8 | 100/100/81/0% | 88/75/3/0% | 50/9/0/0% | 100/47/9/0% | 16/0/0/0% |
| 4×5, 칸 70mm | 12 | 100/92/69/0% | 79/38/2/0% | 10/4/0/0% | 62/21/4/0% | 0% |
| 5×7, 칸 50mm (벽 보드와 같음) | 24 | 0% | 0% | 0% | 0% | 0% |

→ A3 에서는 칸을 최대로 키운 3×4(95mm)가 유일하게 방 가운데(약 2.3m)~맞은편(3.5m)까지 닿음 (70° 렌즈, 보드를 카메라 쪽으로 45° 이내로 향할 때). 90° 렌즈면 2m 정도까지.

### A3 보드(칸 50mm) 검출 거리 (합성, 벽 부착, 값 = 검출 코너/24, 방위 4개)

폰 4000×3000 f=3000px: 정면 3.5m까지 전부, 30° 3.0m, 45° 3.0m, 60° 2.5m (3.0m부터 일부/실패), 4.0m 전부 실패.
1080p 웹캠(수평 화각 78° 가정): 정면/30° 2.5m까지 대부분(18~24), 45° 2.0m, 60° 1.5m, 3.0m 전부 실패.
→ A4 35mm(폰 1.6m)보다 약 2배. 실제 사진은 흐림/조명 때문에 이보다 짧을 수 있음.

### VGGT-1B 이미지 수별 메모리/시간 (2026-11-09, GPU 0 RTX 3090, bf16, 카메라+깊이 헤드만)

입력 518×350 (VGGT 예제 kitchen 25장을 반복해 N장 구성). 모델 가중치 상주 4.31 GB 포함. 시간은 GPU 전송~포즈 변환까지 (2회 중 최소).
폰 4:3 사진은 518×392로 들어가 토큰이 약 12% 더 많으므로 수치가 조금 늘어납니다.

| 이미지 수 | 시간 (s) | 최대 할당 (GB) | 최대 예약 (GB) |
|---:|---:|---:|---:|
| 1 | 0.11 | 6.44 | 6.84 |
| 2 | 0.18 | 6.58 | 7.51 |
| 4 | 0.33 | 6.93 | 8.31 |
| 8 | 0.65 | 7.83 | 10.30 |
| 16 | 1.46 | 8.08 | 10.63 |
| 24 | 2.45 | 8.33 | 11.16 |
| 32 | 3.59 | 8.58 | 10.50 |
| 48 | 6.44 | 9.09 | 11.56 |
| 64 | 9.97 | 9.80 | 11.60 |
| 80 | 14.45 | 10.74 | 13.50 |
| 100 | 20.93 | 11.93 | 14.54 |
| 128 | 31.90 | 13.59 | 15.58 |
| 160 | 47.37 | 15.49 | 19.08 |
| 200 | 71.43 | 17.86 | 20.48 |

→ 방 촬영은 40~100장 권장 (100장 ≈ 21초, 15GB). 200장까지 24GB에 들어감.

## 첫 시연 체크리스트 (11/10 21:00)

- [x] 가상환경, VGGT 설치 및 샘플 이미지로 추론 확인
- [x] 신뢰도 필터 → TSDF/Poisson 메시
- [x] 바닥 평면 정렬
- [x] ChArUco 보드 기준 스케일 보정 (합성 시험 통과, 실제 사진 미검증)
- [x] 메시 간소화 (수십만 삼각형 이하)
- [x] `.glb` 내보내기 (정점 색 포함) → `SHARED_DIR/meshes/room_latest.glb` (현재 예제 방)
- [ ] 실제 방 사진으로 재실행

## 상대 세션에 요청

- **(unity, 2026-11-24) `room_latest` 교체 + 월드 좌표계 변경**: 벽 보드를 새 위치로 옮겨 `room_20261124_myroom2-charuco.glb`로 교체했습니다 (보드 중심 높이 0.8954 → **0.9046m**, 원점·축이 새 보드 기준). 이전 메시 기준으로 맞춘 값(시작 카메라 위치 등)이 있으면 다시 확인해 주세요. `experiments/` 의 2DGS·스무딩·SpatialLM 결과는 아직 이전 메시(이전 좌표) 기준이고, 새 메시는 proxy-ransac 만 만들었습니다 → unity 의 "가장 최근 파일" 규칙으로 키 3 은 새 방 프록시를, 2·4·5 는 이전 방 결과를 읽게 되니 섞어서 비교하지 마세요
- (unity, 선택) 메시 개선 실험 결과가 `${SHARED_DIR}/meshes/experiments/` 에 있습니다. `room_latest`는 바꾸지 않았습니다. 특히 `proxy-ransac/room_20261110_myroom-charuco/proxy.glb`(벽 구멍 없는 평면+상자, 같은 월드 좌표)는 지금 보조 바닥 대신/함께 충돌체로 시험해볼 만합니다. 형식은 interfaces.md 2-1절 (`proxy.json`: 평면·상자·문창, Unity 변환은 glTFast 규칙 한 곳에서). 시험 결과를 status-unity.md 에 적어주시면 어느 것을 최신본으로 올릴지 정하는 데 씁니다
- (unity, 2026-11-24 확인) status-unity 의 "가장 최근 파일" 규칙에 맞춰, 방법별 가장 최근 파일이 대표 결과가 되게 했습니다: 3 → `proxy-ransac/room_20261110_myroom-charuco/proxy.json`, 5 → `spatiallm/room_20261110_myroom-charuco/proxy.json`(점구름 입력, 시드 0), 2 → `smooth/…/smooth_t30-s50k.glb`(추천), 4 → `2dgs/…/2dgs_noba.glb`. 같은 폴더에 `report.json`, `raw_*.json`, 시드별 `proxy_*_s*.json` 도 있으니 가능하면 **파일 이름이 정확히 `proxy.json`인 것**을 고르도록 바꿔 주시면 안전합니다 (예제 침실 결과는 `shared/archive/experiments/`로 옮김)
- (unity) interfaces.md 2-1절 `proxy.json`은 요청하신 형식과 거의 같습니다 (`normal`+`d`+`polygon`, 상자 `center`/`size`/`yaw_deg`, +Y 회전). 다른 점: 평면 종류가 `label`이 아니라 **`type`**(`floor`/`ceiling`/`wall`)이고, 바닥·천장도 `planes` 안에 들어 있습니다(최상위 `floor`/`walls` 없음). 법선은 이미 방 안쪽입니다. SpatialLM 결과에도 바닥(벽 아래 끝 높이, y≈0.06m)·천장 평면을 넣었습니다
- (unity 요청 반영) `room_latest.json`에 `source`(`"real"`=사용자 방 사진 / `"sample"`=예제), `scale_method`(`charuco`/`room-size`/`camera-height`/`factor`), `triangles`, `created_at` 넣음. `room_latest.glb`/`.json`은 임시 파일에 쓴 뒤 `os.replace`로 교체
- (unity) `room_latest.glb`는 지금 VGGT 예제 침실(사용자 방 아님)입니다. glTFast 로드/`MeshCollider` 시험용으로 쓰고, 실제 방 메시가 올라오면 같은 이름으로 교체됩니다. `room_latest.json`의 `source_images`, `created_at`으로 구분할 수 있습니다.
- (unity) 메시 형식: 단일 메시, `POSITION`/`NORMAL`/`COLOR_0`(float RGB, **선형 색공간**, glTF 규약), uint32 인덱스, 머티리얼 1개(흰색, metallic 0, roughness 1, `doubleSided: true`). 정점 색 셰이더는 COLOR_0를 선형 값으로 그대로 쓰면 됩니다 (sRGB 디코드 하지 않음).
- (unity) 좌표: glTF(오른손, +Y 위, 미터), 바닥 y=0. ChArUco 사용 시 원점 = 보드 중심, 아니면 바닥 범위 중심. 벽이 X/Z축에 맞게 정렬돼 있습니다.

## 사용자 확인 필요

- **interfaces.md 갱신 확인 요청 (공유 파일이라 고치지 않음)**: 2절 실험 방법 이름에 `hybrid`, `3dgs` 추가, 2-1절 `method`에 `hybrid`(파일 이름 `proxy_hybrid.json`, `confidence` = 투표 비율 = 표 수 / 시드 수) 추가. 확인해 주시면 반영하고 변경 기록에 남기겠습니다. 상자에는 규약 밖 참고 필드(`votes`, `label_votes`, `labels_seen`, `refit`, `note`)도 들어 있습니다
- 3DGS 를 더 밀어볼지: 평가 시점 품질의 걸림돌은 포즈 정확도와 근접 사진 수 (사진 158장 전부 쓰기, 평가 시점 포즈 보정, 깊이 손실 등이 후보)
- cam1/cam3/cam4 ↔ 포트 지정 (`0b:00.0-5`, `0b:00.0-7`, `0f:00.0-1` 중): cam2 재장착 때 렌즈를 cam1→cam4 순서로 3초씩 가리면 기록
- 새 방 메시로 실험(스무딩/SpatialLM/2DGS)도 다시 돌릴지
- 메시 실험 중 `room_latest`로 올릴 것이 있는지 (추천: 충돌체는 `proxy.glb` 또는 `smooth_t30-s50k.glb`, 표시용은 원본 유지). 2DGS 는 포즈 개선 전에는 비추천
- OV9281 렌즈 화각 (수평 70° 대 90° 이상): 손 보드 검출 거리가 크게 달라짐. 렌즈 사양 또는 실제 캘리브레이션 후 확인
- 손 보드 인쇄 후 실측: `python -m cv.calib.make_charuco --config charuco_handheld.yaml --set-measured <칸 mm>` (폼보드에 붙여 평평하게)
- 카메라 MJPG 모드가 1280×720 / 640×400 등으로 보고됨 (사양 1280×800). 캡처 작업 때 전체 해상도 모드 확인 필요
- 저장소 루트의 `202611231101.txt`(사용자 메모로 보임)는 커밋하지 않고 그대로 둠
- CLAUDE.md 5절, PROJECT_BRIEF.md에는 아직 "월드 원점은 (바닥의) ChArUco 보드 중심"으로 남아 있음 → 새 정의(보드 중심의 바닥 투영)로 맞출지 확인 필요 (공유 파일이라 수정 안 함)
- `.env`의 `VGGT_WEIGHTS`가 비어 있음. 현재 가중치는 홈 캐시 `~/.cache/huggingface/hub/models--facebook--VGGT-1B/snapshots/<hash>/model.safetensors`에 있어 테스트 때는 명령줄에서 지정함

## 알려진 한계

- 2DGS/SpatialLM 라이선스: 2DGS = Inria/MPII Gaussian-Splatting 라이선스(비상업 연구용), SpatialLM1.1 = 모델은 Qwen2.5 기반 Apache-2.0 이지만 Sonata 점구름 인코더 가중치가 CC-BY-NC-4.0(비상업), Llama 변형은 Llama 3.2 라이선스. 공개·상업 사용 전 재확인 필요
- 2DGS: VGGT 포즈만으로는 표면이 흐림. COLMAP BA 는 흰 벽에서 매칭이 적어 발산(자동 기각 기준: 배율 ±5%, 카메라 이동 평균 5cm, 회전 3°, BA 후 점 5,000개). 포즈 개선(더 많은 겹침 촬영, 다른 특징점/매칭) 후 재시도 필요
- proxy-ransac: 바닥 다각형 = 경계 벽 반평면의 교집합 → 볼록한 방만. 가구 상자는 2.5D 라 책상 아래 같은 빈 공간도 채움(아래가 0.8m 미만이면 바닥까지 내림)
- SpatialLM: 생성 모델이라 시드마다 결과가 다름(`--seeds`로 여러 번), 실내 중국식 아파트 데이터로 학습되어 종류 오분류 있음
- 미리보기(Open3D 오프스크린, Vulkan)는 큰 지오메트리 직후나 GPU 가 바쁠 때 빈 프레임을 낼 수 있어 0 이 아닐 때까지 다시 그림
- **VGGT에 세로 사진을 그대로 넣으면 fx/fy를 틀리게 예측** (실측: fx 262 / fy 346, EXIF 참값 344 → 보드 재투영 오차 최대 45px). 이제 전부 세로면 반시계 90° 돌려 넣음(`load_images(rotate_portrait=True)`): fx≈fy≈344, 재투영 중앙 1.8px. 바닥 RANSAC의 중력 힌트도 회전에 맞춰 카메라 +x 사용
- 가로/세로가 섞이면 다수 방향만 사용 (`--keep-mixed-orientation`으로 끌 수 있음, 그 경우 정사각 패딩)

- Open3D 0.20(현재 venv)의 `ScalableTSDFVolume`/`t.VoxelBlockGrid`가 빈 메시를 냄(합성 평면으로도 재현) → `UniformTSDFVolume`(정육면체 격자, 최대 400³) 사용. 방 크기에서는 문제 없음
- ChArUco 스케일: 합성 시험에서 −0.3~0.4% 치우침(3.3m에 약 1cm). 코너 검출 단계에서 발생, 원인 미확정
- 벽 보드가 휘어 있으면(폼보드 없이 부착) 정합 잔차/휨이 커짐 → `room_latest.json` `scale.rms_mm`, `scale.out_of_plane_rms_mm`로 확인. 15mm 넘으면 ChArUco 실패 처리 후 대체 방법
- 고정 카메라(OV9281 1MP, 천장 모서리 3~4m)에는 A3 보드도 작을 수 있음 → 1주차 캘리브레이션 때 시험 필요
- 바닥 메우기는 방 범위를 점구름 1~99 백분위 직사각형으로 잡으므로, 문 밖(복도)이 많이 찍히면 방 밖까지 메울 수 있음
- 예제 이미지에는 보드가 없어 실제 파이프라인 안의 ChArUco 경로는 사용자 사진에서 처음 검증됨

## 규약 변경

- **2026-11-23 interfaces.md 2절 실험 산출물 규칙 + 2-1절 방 프록시(`proxy.json`) 추가 (사용자 요청)**: 실험 결과는 `${SHARED_DIR}/meshes/experiments/<방법>/<메시 이름>/`, `room_latest`는 건드리지 않음. `proxy.json` = 평면(바닥/천장/벽, 법선은 방 안쪽, `n·p+d=0`, 다각형은 방 안에서 반시계) + 상자(center/size/yaw, glTF 쿼터니언) + 문/창. 좌표는 기존 월드 그대로, Unity 는 glTFast 규칙(`x→−x`, 쿼터니언 `(x,−y,−z,w)`)으로 한 곳에서만
- **2026-11-10 월드 좌표계 정의 변경 (사용자 확인, interfaces.md 1절)**: ChArUco 보드를 바닥 → 벽(A3, 칸 50mm)으로 옮김. +Y = 바닥 RANSAC 법선(바닥 y=0), 원점 = 보드 중심을 바닥에 내린 점, +X = 보드 +X의 바닥 투영, +Z = X×Y(방 안쪽). `room_latest.json`에 `board_center_height_m` 추가. unity 쪽 축 처리는 그대로(glTFast 자동 변환만)

## 작업 기록

| 시각 | 내용 |
|---|---|
| 2026-11-25 01:15 | 메시 고도화 2차: RANSAC 프록시에 벽 앞 얇은 판 잡음 규칙(두 방 5~6개 제거), SpatialLM 8시드 투표 + 점구름 맞춤 하이브리드(`proxy_hybrid.json`, RANSAC 상자별 비교표), 3DGS(gsplat) 포즈 최적화 끔/켬 (평가 PSNR 15.4/15.8, 학습 시점 25.9/26.8), 두 방 나란히 비교. gsplat 환경, COLMAP bin 출력 추가 |
| 2026-11-25 00:10 | 벽 보드 새 위치로 `scans/20261124` 158장 → 메시 재생성(120장), 검증 통과 후 room_latest 교체. 카메라 미리보기 서버(Tailscale, 4대 한 화면, 초점 수치, 자동 재연결) 작성, 초점·각도 맞춤 시작. cam2(`0e:00.3-2`) 케이스 초점 나사 파손 → 케이스 재주문, 약 5일 뒤 재개 |
| 2026-11-24 00:20 | 메시 개선 실험 4종 + 비교표, interfaces.md proxy.json 정의, 손 ChArUco 보드(3×4 95mm, 17~22번) PDF·두 보드 구분 검출, 2DGS/SpatialLM 별도 환경. 사용자 수정(가상환경 경로 이동, CLAUDE.md 규칙) 커밋 |
| 2026-11-14 18:00 | 고정 카메라 4대: 1대가 안 뜨던 원인 = 연장 케이블 불량(꽂아도 커널 로그 없음, 직결 시 정상) → 교체 후 4대 인식. 4대 동시 MJPG 1280×720 30.2fps, 오류 없음. 4대 시리얼 모두 SN0001 → by-path 로 구분, Bus 1 에 2대(포트 5·7)가 같은 컨트롤러 공유 |
| 2026-11-09 | 상태 파일 생성 |
| 2026-11-09 17:45 | ChArUco 5×7, DICT_4X4_50, 칸 35mm/마커 26mm, A4 PDF/PNG 생성 (`python -m cv.calib.make_charuco`) |
| 2026-11-09 18:05 | 환경 확인(check_env) 통과, trimesh/python-dotenv/vggt 설치, VGGT N=1~200 메모리/시간 측정 |
| 2026-11-10 11:35 | 사용자 사진(scans/20261110)으로 실제 방 메시 생성 → room_latest. 세로 사진 회전 입력, 코너별 재투영 이상치 제거(4px) 추가 |
| 2026-11-10 01:55 | 벽 A3 보드 반영(charuco.yaml 50/37mm 실측), 새 월드 좌표계(charuco_world, 3D 정합) + 합성 시험, 바닥 메우기, A3 검출 거리 시험, interfaces.md 갱신. VGGT 가중치 → `/storage/AI/cache/huggingface`(sha256 확인), `.env` VGGT_WEIGHTS 설정, HF_HOME(cv/env.sh) 변경, `.env.example` IP 되돌림, 이전 시험 메시 → `shared/archive/` |
| 2026-11-09 18:25 | unity 요청 반영: room_latest.json에 source/scale_method 추가, 예제 메시 재생성 (`room_20261109_example-bedroom-180624.glb`) |
| 2026-11-09 18:20 | cv/recon 파이프라인(build_room, validate_mesh, glb, scale, geometry) 완성. 바닥 RANSAC을 수평면 점만으로 바꿔 침대 윗면을 바닥으로 잡던 문제 수정. 예제 침실로 room_latest 생성 |
