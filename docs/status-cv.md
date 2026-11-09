# cv 세션 진행 기록 (AI 컴퓨터)

> 이 파일은 cv 세션만 수정합니다. unity 세션은 읽기만 합니다.

## 현재 상태

- 마지막 갱신: 2026-11-09 17:45
- 단계: ChArUco 보드 생성 완료 → VGGT 환경 확인 중
- 최신 메시: 없음

## READY

- READY: ChArUco 보드 A4 인쇄본 / `${SHARED_DIR}/charuco/charuco_A4_5x7_35mm_DICT_4X4_50.{pdf,png}`, 파라미터 `cv/config/charuco.yaml` / 생성 이미지 자체 검출 코너 24/24, 칸 간격 840.00px(기대 840), PDF 페이지 210.00×297.00mm

## 첫 시연 체크리스트 (11/10 21:00)

- [ ] 가상환경, VGGT 설치 및 샘플 이미지로 추론 확인
- [ ] 신뢰도 필터 → TSDF/Poisson 메시
- [ ] 바닥 평면 정렬
- [ ] ChArUco 보드 기준 스케일 보정
- [ ] 메시 간소화 (수십만 삼각형 이하)
- [ ] `.glb` 내보내기 (정점 색 포함) → `SHARED_DIR/meshes/room_latest.glb`
- [ ] 실제 방 사진으로 재실행

## 상대 세션에 요청

- (없음)

## 규약 변경

- (없음)

## 작업 기록

| 시각 | 내용 |
|---|---|
| 2026-11-09 | 상태 파일 생성 |
| 2026-11-09 17:45 | ChArUco 5×7, DICT_4X4_50, 칸 35mm/마커 26mm, A4 PDF/PNG 생성 (`python -m cv.calib.make_charuco`) |
