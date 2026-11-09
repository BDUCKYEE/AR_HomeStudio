# cv 세션 진행 기록 (AI 컴퓨터)

> 이 파일은 cv 세션만 수정합니다. unity 세션은 읽기만 합니다.

## 현재 상태

- 마지막 갱신: 2026-11-09 18:20
- 단계: 방 메시 파이프라인 완료(예제 이미지로 끝까지 검증). 사용자 방 사진(`${SHARED_DIR}/scans/`) 대기 중
- 최신 메시: `room_latest.glb` = **VGGT 예제 침실 8장 (사용자 방 아님, 임시)**. 105,360 삼각형, 스케일 = 촬영 높이 1.4m 가정

## READY

- READY: ChArUco 보드 A4 인쇄본 / `${SHARED_DIR}/charuco/charuco_A4_5x7_35mm_DICT_4X4_50.{pdf,png}`, 파라미터 `cv/config/charuco.yaml` / 생성 이미지 자체 검출 코너 24/24, 칸 간격 840.00px(기대 840), PDF 페이지 210.00×297.00mm
- READY: cv 가상환경 / `/storage/AI/test/.venv` (`source cv/env.sh`, 캐시는 `/storage/AI/test/.cache`) / `python -m cv.recon.check_env` → torch 2.3.1+cu121, CUDA OK, GPU 2장(RTX 3090 24GB ×2), numpy 1.26.4, Open3D 0.20.0(CUDA 빌드), OpenCV 4.10(cv2.aruco ChArUco OK), trimesh 5.2.0, VGGT import + 가중치 로드 OK. 추가 설치: trimesh, python-dotenv, vggt(-e, --no-deps). 기존 패키지 변경 없음
- READY: VGGT GPU 0 추론 벤치마크 / `python -m cv.recon.bench_vggt` / 아래 표
- READY: 방 메시 파이프라인 / `python -m cv.recon.build_room <이미지 폴더> --desc <설명>`, 검사 `python -m cv.recon.validate_mesh` / 예제 침실 8장 끝까지 9초. 검사: 형식·정점 색·삼각형 수·미터 단위·바닥 y≈0(1백분위 −0.004m)·높이 PASS, 방 크기 WARN(4.85×3.06m, 예제 방이라 당연). trimesh로도 정상 로드(COLOR_0 확인). 법선 98%가 카메라 쪽(방 안쪽)
- READY: ChArUco 스케일 보정 / `python -m cv.recon.test_charuco_scale` (합성 5시점) / 스케일 오차 0.43%, 회전 0.007°, 원점 0.12mm → 통과
- READY (임시 메시): `${SHARED_DIR}/meshes/room_latest.glb` + `room_latest.json` / 예제 침실 (unity 쪽 glTFast 로드 시험용) / validate 통과(방 크기 WARN)

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

- (unity) `room_latest.glb`는 지금 VGGT 예제 침실(사용자 방 아님)입니다. glTFast 로드/`MeshCollider` 시험용으로 쓰고, 실제 방 메시가 올라오면 같은 이름으로 교체됩니다. `room_latest.json`의 `source_images`, `created_at`으로 구분할 수 있습니다.
- (unity) 메시 형식: 단일 메시, `POSITION`/`NORMAL`/`COLOR_0`(float RGB, **선형 색공간**, glTF 규약), uint32 인덱스, 머티리얼 1개(흰색, metallic 0, roughness 1, `doubleSided: true`). 정점 색 셰이더는 COLOR_0를 선형 값으로 그대로 쓰면 됩니다 (sRGB 디코드 하지 않음).
- (unity) 좌표: glTF(오른손, +Y 위, 미터), 바닥 y=0. ChArUco 사용 시 원점 = 보드 중심, 아니면 바닥 범위 중심. 벽이 X/Z축에 맞게 정렬돼 있습니다.

## 사용자 확인 필요

- ChArUco 보드 → 월드 축 대응 제안 (interfaces.md에서 "미정"): 보드가 바닥에 앞면이 위로 놓였을 때 월드 +X = 보드 +X(인쇄물 가로, 오른쪽), 월드 +Y = 위, 월드 +Z = 보드 +Y(인쇄물 아래쪽 방향), 원점 = 보드 중심. 현재 `cv/recon/scale.py`가 이 대응을 씀. 확정되면 interfaces.md에 기록 필요
- 로컬 `.env.example`에 실제 LAN IP가 들어간 미커밋 변경이 있음 → 커밋하지 않음 (cv 세션은 손대지 않음)
- `.env`의 `VGGT_WEIGHTS`가 비어 있음. 현재 가중치는 홈 캐시 `~/.cache/huggingface/hub/models--facebook--VGGT-1B/snapshots/<hash>/model.safetensors`에 있어 테스트 때는 명령줄에서 지정함

## 알려진 한계

- Open3D 0.20(현재 venv)의 `ScalableTSDFVolume`/`t.VoxelBlockGrid`가 빈 메시를 냄(합성 평면으로도 재현) → `UniformTSDFVolume`(정육면체 격자, 최대 400³) 사용. 방 크기에서는 문제 없음
- ChArUco 스케일: 합성 시험에서 −0.43% 치우침(3.3m에 약 1.4cm). 코너 검출 단계에서 발생, 원인 미확정
- ChArUco 검출 거리: 12MP 폰 기준 보드에서 1.6m 이내 (2m부터 실패). 고정 카메라(OV9281, 1MP, 천장 모서리 3~4m) 캘리브레이션에는 A4 보드가 너무 작을 가능성 큼 → 1주차 캘리브레이션 때 A3 이상 또는 큰 칸으로 별도 보드 검토
- 예제 이미지에는 보드가 없어 실제 파이프라인 안의 ChArUco 경로는 사용자 사진에서 처음 검증됨

## 규약 변경

- (없음)

## 작업 기록

| 시각 | 내용 |
|---|---|
| 2026-11-09 | 상태 파일 생성 |
| 2026-11-09 17:45 | ChArUco 5×7, DICT_4X4_50, 칸 35mm/마커 26mm, A4 PDF/PNG 생성 (`python -m cv.calib.make_charuco`) |
| 2026-11-09 18:05 | 환경 확인(check_env) 통과, trimesh/python-dotenv/vggt 설치, VGGT N=1~200 메모리/시간 측정 |
| 2026-11-09 18:20 | cv/recon 파이프라인(build_room, validate_mesh, glb, scale, geometry) 완성. 바닥 RANSAC을 수평면 점만으로 바꿔 침대 윗면을 바닥으로 잡던 문제 수정. 예제 침실로 room_latest 생성 |
