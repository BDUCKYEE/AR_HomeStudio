# 공통 규약 (interfaces)

> 상태: 초안 (2026-11-09), 월드 좌표계 정의 갱신 (2026-11-10). cv 세션과 unity 세션이 함께 따르는 규약입니다. 수정은 사용자 확인 후에만 하고, 아래 변경 기록에 남깁니다.

## 1. 좌표계와 단위

| 항목 | 규약 |
|---|---|
| 단위 | 미터 (m) |
| 월드 원점 | **벽에 붙인 ChArUco 보드의 중심을 바닥 평면에 수직으로 내린 점** |
| 바닥 | 높이 0 (바닥 평면 = 방 메시 점구름의 RANSAC 평면) |
| 월드 좌표계 | **glTF 규약**: 오른손 좌표계, +Y 위 |
| 시간 | 초 (float), AI 컴퓨터 기준 단조 시계 |

### 월드 축 정의

| 축 | 정의 |
|---|---|
| +Y (위) | 바닥 평면(RANSAC)의 법선, 방 안쪽(카메라 쪽)을 향함 |
| +X | 보드 +X(인쇄물 가로 방향, 보드를 정자세로 봤을 때 오른쪽)를 바닥 평면에 투영한 방향. 보드가 살짝 기울어도 수평으로 보정됨 |
| +Z | X × Y (오른손). 보드를 정자세로 벽에 붙였으면 벽에서 방 안쪽을 향함 (cv가 매번 확인해 `room_latest.json`에 기록) |
| 스케일 | 보드 칸 크기 (`cv/config/charuco.yaml`의 실측값) |

- 보드: A3, 5×7칸, 칸 50mm, 마커 37mm, `DICT_4X4_50`, 벽에 세로(인쇄 방향 그대로)로 부착 (2026-11-10~). 보드 좌표계(OpenCV)는 원점이 보드 왼쪽 위 모서리, +X 오른쪽, +Y 아래, +Z 보드 안쪽(벽 쪽)입니다.
- 보드 중심의 바닥 위 높이는 `room_latest.json`의 `board_center_height_m`에 기록합니다. 고정 카메라나 웹캠이 보드로 자세를 구할 때 이 높이와 위 축 정의로 월드 좌표를 맞춥니다.
- ChArUco 보드는 고정 카메라 외부 파라미터 캘리브레이션이 끝날 때까지 절대 옮기지 않습니다. 보드를 옮기거나 다시 붙이면 월드 좌표계가 바뀌므로 방 메시도 다시 만듭니다.

### 좌표 변환 책임

```
OpenCV 카메라 좌표계 (x 오른쪽, y 아래, z 앞)
        │  cv 쪽에서 한 번만 변환
        ▼
월드 좌표계 = glTF 규약 (오른손, Y 위, 미터)   ← .glb 파일, UDP 메시지 모두 이 좌표계
        │  unity 쪽에서 한 번만 변환 (glTFast가 메시에 대해 자동 수행: X축 반전)
        ▼
Unity 좌표계 (왼손, Y 위, 미터)
```

- cv 쪽은 Unity 좌표계를 고려해 축을 뒤집지 않습니다.
- unity 쪽은 메시에 대해 별도 변환을 하지 않습니다(glTFast가 처리). UDP 관절 좌표는 glTFast와 같은 규칙(`x → -x`)으로 수신부 한 곳에서만 변환합니다.
- 이중 변환에 주의합니다.

## 2. 방 메시

| 항목 | 규약 |
|---|---|
| 형식 | `.glb` (glTF 2.0 바이너리), 정점 색(`COLOR_0`) 포함 |
| 좌표계 | 위 월드 좌표계, 미터 |
| 위치 | `${SHARED_DIR}/meshes/` |
| 파일명 | `room_<YYYYMMDD>_<설명>.glb` (예: `room_20261110_poisson-d9.glb`) |
| 최신본 | `room_latest.glb`로 복사 |
| 삼각형 수 | Unity `MeshCollider`를 위해 수십만 개 이하로 간소화 |

- 메시 파일은 git에 커밋하지 않습니다.
- `room_latest.glb`와 `room_latest.json`은 임시 파일에 쓴 뒤 rename으로 교체합니다.
- `COLOR_0`은 glTF 규약대로 선형 색공간 값입니다 (float RGB).
- 바닥이 부족하면 cv가 바닥 평면(y≈0) 위 방 범위 안의 빈 칸을 평면 사각형으로 메울 수 있습니다 (`floor_fill`).

### `room_latest.json` 주요 필드

| 필드 | 설명 |
|---|---|
| `file` | 실제 메시 파일명 (`room_<YYYYMMDD>_<설명>.glb`) |
| `source` | `"real"` (사용자 방 사진) / `"sample"` (예제 이미지) |
| `scale_method` | `charuco` / `room-size` / `camera-height` / `factor` (charuco 외에는 원점이 바닥 범위 중심) |
| `board_center_height_m` | 바닥에서 보드 중심까지 높이 (m), charuco가 아니면 `null` |
| `created_at`, `triangles`, `bbox` | 생성 시각(ISO 8601), 삼각형 수, 바운딩 박스 (min/max/size, m) |
| `scale` | 스케일 보정 상세 (charuco: 코너 수, 정합 잔차 `rms_mm`, 휨 `out_of_plane_rms_mm`, `z_into_room` 등) |
| `floor_fill` | 바닥 메우기 적용 여부와 채운 칸 수 |
- 새 메시를 올리면 `docs/status-cv.md`에 파일명, 삼각형 수, 스케일 보정 방법을 적습니다.

## 3. 실시간 관절 데이터 (2주차부터 사용, 초안)

| 항목 | 규약 |
|---|---|
| 전송 | UDP, AI 컴퓨터 → 메인 컴퓨터 |
| 주소 | 메인 컴퓨터 LAN IP, 포트 `${UDP_PORT}` |
| 형식 | UTF-8 JSON, 한 패킷에 한 프레임 |
| 좌표 | 월드 좌표계 (glTF 규약, 미터) |

### 메시지 필드

| 필드 | 타입 | 설명 |
|---|---|---|
| `t` | float | AI 컴퓨터 기준 타임스탬프 (초) |
| `body` | `[[x, y, z, conf] × 17]` 또는 `null` | COCO 17점 순서 |
| `hands.left` | `[[x, y, z, conf] × 21]` 또는 `null` | 손 21점, 미검출 시 `null` |
| `hands.right` | `[[x, y, z, conf] × 21]` 또는 `null` | 손 21점, 미검출 시 `null` |

예시:

```json
{
  "t": 12345.678,
  "body": [[0.12, 1.65, -0.40, 0.98], "... 17개"],
  "hands": {
    "left": null,
    "right": [[0.30, 1.10, -0.25, 0.91], "... 21개"]
  }
}
```

### 관절 순서

- 몸 (COCO 17): 0 nose, 1 left_eye, 2 right_eye, 3 left_ear, 4 right_ear, 5 left_shoulder, 6 right_shoulder, 7 left_elbow, 8 right_elbow, 9 left_wrist, 10 right_wrist, 11 left_hip, 12 right_hip, 13 left_knee, 14 right_knee, 15 left_ankle, 16 right_ankle
- 손 (21): 0 wrist, 1–4 thumb, 5–8 index, 9–12 middle, 13–16 ring, 17–20 pinky (각 손가락 MCP → TIP 순)
- 개별 관절이 추정되지 않으면 해당 점은 `conf = 0`으로 보냅니다.

### 미정 사항

- 프레임 번호(`seq`) 필드 추가 여부, 패킷 손실 처리
- 두 컴퓨터 시계 차이 보정 방법 (지연 보정, 4주차)
- 패킷 크기가 커질 경우 바이너리 형식 전환 여부

## 4. 카메라 캘리브레이션 (예정)

- 형식, 저장 위치는 1주차 내부 파라미터 캘리브레이션 때 정합니다. → **미정**
- 후보: `${SHARED_DIR}/calib/cam<N>.json` (`K`, `dist`, `R`, `t`, 해상도), 메인 웹캠 포함

## 변경 기록

| 날짜 | 변경 | 작성 |
|---|---|---|
| 2026-11-09 | 초안 작성 (PROJECT_BRIEF.md 공통 규약 기준) | - |
| 2026-11-10 | 월드 좌표계 정의 변경 (사용자 확인): 보드를 바닥 → 벽(A3)으로 옮김. +Y = 바닥 RANSAC 법선, 원점 = 보드 중심의 바닥 투영, +X = 보드 +X의 바닥 투영, +Z = X×Y. `room_latest.json` 필드(`source`, `scale_method`, `board_center_height_m` 등)와 `COLOR_0` 선형 색공간, 바닥 메우기 명시 | cv |
