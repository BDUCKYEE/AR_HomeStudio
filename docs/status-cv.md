# cv 세션 진행 기록 (AI 컴퓨터)

> 이 파일은 cv 세션만 수정합니다. unity 세션은 읽기만 합니다.

## 현재 상태

- 마지막 갱신: 2026-11-09 18:05
- 단계: 환경 확인/VGGT 벤치마크 완료 → 방 메시 파이프라인(cv/recon) 작업 중
- 최신 메시: 없음

## READY

- READY: ChArUco 보드 A4 인쇄본 / `${SHARED_DIR}/charuco/charuco_A4_5x7_35mm_DICT_4X4_50.{pdf,png}`, 파라미터 `cv/config/charuco.yaml` / 생성 이미지 자체 검출 코너 24/24, 칸 간격 840.00px(기대 840), PDF 페이지 210.00×297.00mm
- READY: cv 가상환경 / `/storage/AI/test/.venv` (`source cv/env.sh`, 캐시는 `/storage/AI/test/.cache`) / `python -m cv.recon.check_env` → torch 2.3.1+cu121, CUDA OK, GPU 2장(RTX 3090 24GB ×2), numpy 1.26.4, Open3D 0.20.0(CUDA 빌드), OpenCV 4.10(cv2.aruco ChArUco OK), trimesh 5.2.0, VGGT import + 가중치 로드 OK. 추가 설치: trimesh, python-dotenv, vggt(-e, --no-deps). 기존 패키지 변경 없음
- READY: VGGT GPU 0 추론 벤치마크 / `python -m cv.recon.bench_vggt` / 아래 표

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
- [ ] 신뢰도 필터 → TSDF/Poisson 메시
- [ ] 바닥 평면 정렬
- [ ] ChArUco 보드 기준 스케일 보정
- [ ] 메시 간소화 (수십만 삼각형 이하)
- [ ] `.glb` 내보내기 (정점 색 포함) → `SHARED_DIR/meshes/room_latest.glb`
- [ ] 실제 방 사진으로 재실행

## 상대 세션에 요청

- (없음)

## 사용자 확인 필요

- `.env`의 `VGGT_WEIGHTS`가 비어 있음. 현재 가중치는 홈 캐시 `~/.cache/huggingface/hub/models--facebook--VGGT-1B/snapshots/<hash>/model.safetensors`에 있어 테스트 때는 명령줄에서 지정함

## 규약 변경

- (없음)

## 작업 기록

| 시각 | 내용 |
|---|---|
| 2026-11-09 | 상태 파일 생성 |
| 2026-11-09 17:45 | ChArUco 5×7, DICT_4X4_50, 칸 35mm/마커 26mm, A4 PDF/PNG 생성 (`python -m cv.calib.make_charuco`) |
| 2026-11-09 18:05 | 환경 확인(check_env) 통과, trimesh/python-dotenv/vggt 설치, VGGT N=1~200 메모리/시간 측정 |
