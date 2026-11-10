# unity 세션 진행 기록 (메인 컴퓨터)

> 이 파일은 unity 세션만 수정합니다. cv 세션은 읽기만 합니다.

## 현재 상태

- 마지막 갱신: 2026-11-10 11:45
- 단계: **실제 방 메시 검증 완료** (종합 WARN, 크기·바닥·보드 모두 OK) → 에디터에서 시연 확인 단계
- 사용 중인 메시: `room_20261110_myroom-charuco.glb` (`source: real`, `charuco`, 보드 중심 높이 0.8954m). 보조 바닥(y=0)은 계속 켬 (X쪽 벽 구멍 대비)
- 환경: Unity 6000.3.28f1, URP 17.3, Input System 1.20.1 (Active Input Handling = Input System Package)

## READY

- READY: 박스 방 물리 샌드박스 씬 `Assets/RoomAR/Scenes/BoxRoom.unity` (비상용) / Unity Hub에서 `unity/AR_HomeStudioo` 열기 → BoxRoom 씬 Play. 씬이 없거나 깨졌으면 메뉴 **RoomAR > Build All Scenes**로 재생성. 배치 모드 자가 테스트: `Unity.exe -batchmode -nographics -projectPath unity/AR_HomeStudioo -executeMethod RoomAR.EditorTools.SandboxSelfTest.Run -logFile -` → `[RoomAR][SelfTest] PASS`

- READY: 방 메시 런타임 로더 + 정점 색 셰이더 + 검증기 (메시 없이 준비 완료) / `RoomMesh.unity` 씬 Play → `SHARED_DIR/meshes/room_latest.glb` 자동 로드, **L** 다시 불러오기, **V** 메시 표시 토글. 검증: 메뉴 **RoomAR > Validate room_latest.glb** 또는 배치 `-executeMethod RoomAR.EditorTools.RoomMeshValidator.ValidateBatch [-roomGlb <path>]` (`-quit` 없이 실행, 보고서 `unity/AR_HomeStudioo/Logs/room_mesh_validation.md`). 합성 glb(3.3×2.5×2.4m, 정점 색)로 배치 검증 OK, 반 크기 + `source: sample_images` json → 크기 WARN/종료 0, json 없음 → 크기 FAIL/종료 1 확인

- READY: cv `room_latest.glb`(예제 메시) 실행 중 로드 + MeshCollider + 정점 색 + 보조 바닥 / `RoomMesh.unity` Play → 화면 왼쪽 위에 메시 정보 표시, Space로 공 → 메시 위에서 튐. **F** 보조 바닥 토글. 배치 테스트: `-executeMethod RoomAR.EditorTools.RoomMeshLoaderSelfTest.RunBatch` (`-quit` 없이) → `PASS` (81개 낙하 중 바닥 뚫림 0, 벽 구멍 탈출 4)

- READY: 벽 ChArUco 보드 위치 표시 / `room_latest.json`에 `board_center_height_m`가 있으면 `RoomMesh` 씬에서 메시 로드 시 자동 생성 (**B** 토글, 화면 안내에 보드 높이 표시). 얇은 사각형: 종이 A3 297×420mm(흰색) + 패턴 `squares_x × squares_y × square_mm`(기본 5×7×50mm, 검정), 보드 +X 빨간 막대, 보드 중심→바닥 원점 노란 수직선, 바닥 원점 십자(파랑 = +Z 방 안쪽). 충돌체 없음. 배치 테스트: `RoomMeshLoaderSelfTest.RunBatch -roomGlb <합성 벽 원점 glb>` → 종이 중심 (0.000, 1.250, 0.004) = 기대 (0, h, 0) → PASS. 보드 정보가 없는 현재 예제 메시에서는 "보드: 위치 정보 없음 (scale_method=camera-height)"으로 표시

- READY: 실제 방 메시 + 보드 표시 / `RoomMesh.unity` Play → `room_20261110_myroom-charuco.glb` 자동 로드, 보드는 벽 (0, 0.895, 0)에 표시. 배치: 검증기 종합 WARN(종료 0), `RoomMeshLoaderSelfTest` PASS (81개 낙하 중 바닥 뚫림 0, X쪽 벽 구멍으로 탈출 2, 보드 종이 중심 (0.000, 0.895, 0.004))

### 실제 방 메시 검증 결과 (2026-11-10 11:32, 배치 모드)

- glb: `room_20261110_myroom-charuco.glb` (사진 81장, `scale_method: charuco`, 보드 20장에서 코너 24/24, rms 2.27mm, `z_into_room: true`)
- 로딩 0.77s, 메시 1개, 정점 85,243

| 결과 | 항목 | 값 |
|---|---|---|
| OK | 삼각형 수 | 153,258 |
| OK | 정점 색 | COLOR_0 있음 |
| OK | MeshCollider | 1개 |
| OK | 수평 긴 변 | 3.50 m (Z 방향, 보드 벽 → 맞은편 벽; 실측 3.3 대비 +6%) |
| OK | 수평 짧은 변 | 2.73 m (X 방향; 실측 2.5 대비 +9%) |
| OK | 높이 | 2.44 m (실측 2.4) |
| OK | 바운딩 박스 (Unity) | min (-1.48, -0.05, -0.01) / max (1.25, 2.39, 3.49) |
| OK | 바닥 높이 | p1 -0.009 m, p5 -0.003 m, min -0.051 m |
| OK | 보드 중심 높이 | 0.895 m |
| OK | 원점 위치 (벽 보드) | x 범위에 0 포함, 메시 −Z 끝 z = −0.01 m (보드 벽) |
| OK | 보드 벽면 Raycast | 보드 앞 0.5m → −Z 광선이 z = 0.012 m에서 벽에 맞음 |
| OK | 바닥 Raycast | 79/81 (98%) |
| WARN | 공 낙하 (메시 단독) | 79개 중 3개 탈출 (보조 바닥 없이) |

**종합: WARN** — 메시만 썼을 때 공 일부가 벽 구멍으로 나가는 것만 경고입니다. 보조 바닥을 켜면 바닥을 뚫는 공은 0개이고, 2개가 ±X 벽 구멍(x ≈ −2.2 / +1.95 지점으로 나감)으로 방 밖에 나갔습니다.
- 교차 확인: cv json bbox(glTF) x [−1.25, 1.48] → Unity x [−1.48, 1.25] (X 반전), z [−0.01, 3.49]는 그대로입니다. 좌표 규약대로입니다.
- 참고: 방의 긴 변(3.5m)이 보드 벽에 수직인 Z 방향입니다. 박스 방(BoxRoom, X 3.3 × Z 2.5)과는 축 배치가 다릅니다 (박스 방은 비상용이라 그대로 둠).

### 새 좌표계 반영 (interfaces.md 2026-11-10)

- 원점 = 벽 보드 중심의 바닥 투영, +Y = 바닥 법선, +Z = 벽 → 방 안쪽. glTF 월드에서 보드 중심은 (0, h, 0)이고 보드 면은 XY 평면입니다.
- Unity 변환은 glTFast와 같이 x → −x만 합니다. 보드 중심과 +Z는 그대로이고, 보드 +X(인쇄물 오른쪽)는 Unity −X입니다. 빨간 막대가 화면에서 보드 오른쪽에 보이면 정상입니다 (방 안쪽에서 보드를 바라볼 때).
- 로더와 보조 바닥은 바꾸지 않았습니다 (바닥 y=0, +Y 위 규약 동일).
- 검증기: 보드 높이가 있으면 "원점이 메시 범위 안" 대신 다음을 검사합니다.
  - 보드 높이가 0.2m ~ min(2.3m, 메시 높이) 범위인지
  - 메시 x 범위에 0이 들어가고, 메시 −Z 끝이 z≈0(±0.3m)인지 (보드가 붙은 벽)
  - 보드 앞 0.5m에서 −Z로 쏜 Raycast가 |z| < 0.1m에서 벽 메시에 맞는지
  - json의 `z_into_room=false`이면 경고
  - 합성 벽 원점 메시(+`source: real`, `charuco`, h=1.25)로 모두 OK 확인
- 현재 예제 메시 재검증 (11:35): 바닥 메우기 덕분에 바닥 Raycast 9% → 98%, 메시만으로 공 낙하는 FAIL → WARN (79개 중 6개가 벽 구멍으로 탈출). 크기는 WARN(예제). 종합 WARN

### room_latest.glb 검증 결과 (2026-11-09 18:12, 배치 모드)

- glb: `Z:\meshes\room_latest.glb` = `room_20261109_example-bedroom-180624.glb` (json `source: sample` → 크기 검사는 경고만)
- 로딩 0.66s, 메시 1개, 정점 57,142

| 결과 | 항목 | 값 |
|---|---|---|
| OK | 삼각형 수 | 105,195 |
| OK | 정점 색 | COLOR_0 있음 |
| OK | MeshCollider | 1개 |
| WARN | 수평 긴 변 | 5.05 m (기대 3.3 ±15%) |
| WARN | 수평 짧은 변 | 3.20 m (기대 2.5 ±15%) |
| WARN | 높이 | 1.99 m (기대 2.4 ±15%) |
| OK | 바운딩 박스 (Unity) | min (-1.54, -0.03, -2.58) / max (1.66, 1.96, 2.48) |
| OK | 바닥 높이 | p1 -0.005 m, p5 0.004 m, min -0.027 m, \|y\|<3cm 정점 8.1% |
| OK | 원점 위치 | 월드 원점(XZ)이 메시 범위 안 |
| WARN | 바닥 Raycast | 9×9 격자 중 7/81(9%)만 y≈0 바닥에 맞음. 뒷면 포함해도 7/81 → 법선 문제가 아닌 **바닥 누락** |
| FAIL | 공 낙하 (메시 단독) | 바닥이 맞은 7지점 중 5개가 빠짐 (굴러서 바닥/벽 구멍으로) |

**종합: FAIL (메시 단독).** 크기 경고는 예제 이미지라 예상된 결과입니다. 바닥/벽 누락 때문에 메시만으로는 공이 빠집니다.
→ Unity 쪽 대응: `RoomMeshLoader`가 y=0에 보이지 않는 보조 바닥(메시 범위 + 0.5m)을 기본으로 켭니다. 켠 상태에서는 81개 낙하 중 바닥 뚫림 0개였고, 4개는 −Z 쪽과 +X 쪽 벽 구멍으로 방 밖으로 나갔다가 보조 바닥 끝에서 떨어졌습니다 (y < −5에서 자동 제거).
- 교차 확인: cv json의 bbox(glTF) x [-1.66, 1.54] → Unity x [-1.54, 1.66]으로 X 반전, 바닥 1백분위(cv -0.004 / unity -0.005)가 일치합니다. 좌표 규약대로 동작합니다.

### 방 메시 연동 구성 (B단계)

- glTFast `com.unity.cloud.gltfast` 6.20.0. 메시는 실행 중 바이트로 읽어 로드(`RoomMeshIO.LoadAsync`), 모든 MeshFilter에 `MeshCollider` 부착 (glTFast 메시는 readable 유지).
- L 키 재로드는 새 메시 로딩이 성공해야 기존 메시를 교체합니다. cv가 파일을 쓰는 도중 눌러도 기존 메시가 유지됩니다.
- `SHARED_DIR`은 저장소 루트 `.env`에서 읽습니다 (메인 컴퓨터: `Z:\` = `\\<AI컴퓨터>\AR_HomeStudio`). `.env`는 L 키마다 다시 읽습니다.
- 셰이더 `RoomAR/VertexColor` (`Assets/RoomAR/Shaders/VertexColor.shader`, 머티리얼 `Materials/RoomVertexColor.mat`): COLOR_0을 그대로 출력(Unlit). `_Shade`(기본 0.35)로 메인 라이트 음영과 그림자를 섞어 공 그림자가 보이게 합니다. 양면 렌더(Cull Off). DepthOnly 패스가 있어 이후 AR 가림 처리에 재사용할 수 있습니다.
- 좌표: glTFast가 glTF → Unity 변환(X축 반전)을 자동으로 합니다. 합성 메시로 확인한 결과 glb x ∈ [-0.83, 1.60] → Unity x ∈ [-1.60, 0.83]입니다. Unity 쪽에서 추가로 축을 바꾸지 않습니다.

### 검증 기준 (`RoomMeshValidator`)

| 항목 | 기준 |
|---|---|
| 삼각형 수 | 0 또는 > 1,000,000 FAIL, > 500,000 WARN |
| 수평 긴 변 / 짧은 변 / 높이 | 3.3 / 2.5 / 2.4 m ±15%, 벗어나면 FAIL (예제 이미지 메시면 WARN) |
| 바닥 높이 | 정점 y 1% 분위수 \|p1\| ≤ 0.05 m, 아니면 FAIL |
| 정점 색 | 없으면 WARN |
| 원점 위치 | 월드 원점(XZ)이 메시 범위 밖이면 WARN |

### 박스 방 조작법

| 입력 | 동작 |
|---|---|
| WASD / Q·E / Shift | 이동 / 하강·상승 / 가속 |
| 마우스 오른쪽 드래그 | 시점 회전 |
| Space | 카메라 앞에 공 생성 (지름 0.2m, 0.3kg) |
| 왼쪽 클릭 | 커서 위치로 Raycast → 맞은 Rigidbody에 `AddForceAtPosition` (충격량 2 N·s) |
| `[` / `]` | 공 탄성(PhysicsMaterial.bounciness) −/+ 0.1 |
| C / R | 공 모두 제거 / 씬 초기화 |
| L / V / F / B | (RoomMesh 씬) 메시 다시 불러오기 / 메시 표시 토글 / 보조 바닥 토글 / 보드 표시 토글 |

### 박스 방 구성

- 안쪽 치수 X 3.3m × Z 2.5m × 높이 2.4m, 바닥 중심이 원점(바닥 y=0). 실제 ChArUco 원점과는 아직 맞추지 않았습니다.
- 가구 자리표시자(책상, 침대, 선반 박스)는 실제 배치와 무관합니다.
- 공 탄성 기본값은 `Assets/RoomAR/Physics/BallPhysics.asset`(0.8, bounceCombine=Maximum)입니다. 실행 중 `[`/`]`로 바꾼 값은 복제본에만 반영되고 에셋은 바뀌지 않습니다.

## 첫 시연 체크리스트 (11/10 21:00)

- [x] 실측 크기(3.3m × 2.5m × 2.4m) 박스 방 씬
- [x] 공 생성, 마우스 클릭으로 힘 가하기
- [x] 플라이 카메라 (Input System)
- [x] glTFast 패키지 추가 (6.20.0)
- [x] `room_latest.glb` 불러오기 + `MeshCollider` 적용 (코드 완료, 실제 메시 대기)
- [x] 정점 색 표시용 셰이더 (URP)
- [x] 실제 `room_latest.glb` 검증 결과 기록 (예제 메시)
- [x] 실제 방 사진 메시(`source: real`)로 재검증 (11:32, 종합 WARN)
- [ ] 에디터 Play로 조작/표시 확인 (사용자)
- [x] 박스 방 버전 비상용으로 유지
- [ ] 18:00 리허설

## 메모

- 공 충돌 검사는 `ContinuousSpeculative`를 씁니다. `ContinuousDynamic`으로 하면 50Hz에서 1.5m 낙하한 공이 바닥에 약 8cm 파고들었습니다. 대신 반발 높이가 낮아져서, 탄성 0.8로 1.5m 낙하 시 약 0.62m까지 튑니다.
- 씬 생성 코드: `Assets/RoomAR/Scripts/Editor/SceneBuilder.cs`. 씬을 손으로 고쳤다면 재생성할 때 덮어써지므로 주의하십시오.

## 상대 세션에 요청

- ~~`room_latest.json`에 `source` 필드~~ → 반영 확인 (18:06 `"source": "sample"`). Unity는 `source`가 `real`이 아니면 예제 메시로 봅니다.
- **바닥/벽 누락**: 예제 메시는 바닥 Raycast 9%만 맞음 (위 검증 표). 실제 방 촬영 때 바닥을 충분히 찍도록 촬영 가이드에 넣어 주시고, 가능하면 Poisson 밀도 trimming이 바닥을 깎지 않는지 확인 부탁드립니다. Unity는 보조 바닥으로 버팁니다.
- 가능하면 json에 `triangles`, `scale_method`(ChArUco/추정), 생성 시각도 넣어 주십시오. 검증 보고서에 함께 기록하겠습니다.
- `room_latest.glb`는 임시 이름으로 쓴 뒤 rename으로 교체해 주십시오. Unity가 L 키로 다시 불러올 때 쓰다 만 파일을 읽지 않게 하기 위해서입니다. 쓰다 만 파일을 읽더라도 Unity는 기존 메시를 유지합니다.

## 규약 변경

- (없음)

## 작업 기록

| 시각 | 내용 |
|---|---|
| 2026-11-09 | Unity 프로젝트를 `unity/AR_HomeStudioo/`로 이동, 상태 파일 생성 |
| 2026-11-09 | A단계: 박스 방 샌드박스(FlyCamera, SandboxController, SceneBuilder, SandboxSelfTest) 추가, 배치 모드 컴파일 및 자가 테스트 PASS |
| 2026-11-09 18:00 | git pull → status-cv "최신 메시: 없음", `Z:\meshes` 없음 → B단계 중 메시 없이 가능한 부분 진행 |
| 2026-11-09 18:00 | B단계 코드: glTFast 6.20.0, EnvConfig/RoomMeshIO/RoomMeshLoader, VertexColor 셰이더, RoomMesh 씬, RoomMeshValidator. 합성 glb로 배치 검증 통과. `room_latest.json` 대기 시작 |
| 2026-11-09 18:05 | `room_latest.json` 생성 감지 → 예제 bedroom 메시 검증. 바닥 누락 발견 → 보조 바닥(F 토글), 바닥 Raycast/공 낙하 검사, RoomMeshLoaderSelfTest 추가. `source` 필드 우선 판단 |
| 2026-11-10 11:40 | interfaces.md 새 좌표계(벽 보드) 확인. BoardMarker(보드 위치 표시, B 토글), json 파싱(`RoomMeshInfo`), 검증기 보드 검사 추가. 합성 벽 원점 메시로 배치 테스트 PASS. 실제 방 메시(`source: real`) 대기 시작 |
| 2026-11-10 11:45 | 11:31 `source: real` 감지 → `room_20261110_myroom-charuco.glb` 배치 검증 WARN(크기·바닥·보드 OK), 로더 테스트 PASS, 보드 (0, 0.895, 0) 표시 확인 |
