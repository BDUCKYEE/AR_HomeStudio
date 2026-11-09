# unity 세션 진행 기록 (메인 컴퓨터)

> 이 파일은 unity 세션만 수정합니다. cv 세션은 읽기만 합니다.

## 현재 상태

- 마지막 갱신: 2026-11-09
- 단계: A단계 완료, B단계 코드(로더/셰이더/검증) 완료 → cv의 `room_latest.glb` 대기 중
- 사용 중인 메시: 없음 (박스 방). 합성 테스트 메시로만 검증함
- 환경: Unity 6000.3.28f1, URP 17.3, Input System 1.20.1 (Active Input Handling = Input System Package)

## READY

- READY: 박스 방 물리 샌드박스 씬 `Assets/RoomAR/Scenes/BoxRoom.unity` (비상용) / Unity Hub에서 `unity/AR_HomeStudioo` 열기 → BoxRoom 씬 Play. 씬이 없거나 깨졌으면 메뉴 **RoomAR > Build All Scenes**로 재생성. 배치 모드 자가 테스트: `Unity.exe -batchmode -nographics -projectPath unity/AR_HomeStudioo -executeMethod RoomAR.EditorTools.SandboxSelfTest.Run -logFile -` → `[RoomAR][SelfTest] PASS`

- READY: 방 메시 런타임 로더 + 정점 색 셰이더 + 검증기 (메시 없이 준비 완료) / `RoomMesh.unity` 씬 Play → `SHARED_DIR/meshes/room_latest.glb` 자동 로드, **L** 다시 불러오기, **V** 메시 표시 토글. 검증: 메뉴 **RoomAR > Validate room_latest.glb** 또는 배치 `-executeMethod RoomAR.EditorTools.RoomMeshValidator.ValidateBatch [-roomGlb <path>]` (`-quit` 없이 실행, 보고서 `unity/AR_HomeStudioo/Logs/room_mesh_validation.md`). 합성 glb(3.3×2.5×2.4m, 정점 색)로 배치 검증 OK, 반 크기 + `source: sample_images` json → 크기 WARN/종료 0, json 없음 → 크기 FAIL/종료 1 확인

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
- [ ] 실제 `room_latest.glb` 검증 결과 기록
- [x] 박스 방 버전 비상용으로 유지
- [ ] 18:00 리허설

## 메모

- 공 충돌 검사는 `ContinuousSpeculative`를 씁니다. `ContinuousDynamic`으로 하면 50Hz에서 1.5m 낙하한 공이 바닥에 약 8cm 파고들었습니다. 대신 반발 높이가 낮아져서, 탄성 0.8로 1.5m 낙하 시 약 0.62m까지 튑니다.
- 씬 생성 코드: `Assets/RoomAR/Scripts/Editor/SceneBuilder.cs`. 씬을 손으로 고쳤다면 재생성할 때 덮어써지므로 주의하십시오.

## 상대 세션에 요청

- **cv → `room_latest.json`에 입력 출처 필드를 넣어 주십시오.** 예: `"source": "sample"` (예제 이미지) / `"source": "real"` (실제 방 사진). 지금은 스키마가 정해지지 않아서, json의 문자열 값에 `example`/`sample`/`예제`/`샘플`/`demo`가 있거나 이름에 그 단어가 들어간 키가 `true`이면 예제 메시로 판단합니다. 예제 메시이면 Unity 검증기가 크기 검사를 경고만 냅니다.
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
