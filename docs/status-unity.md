# unity 세션 진행 기록 (메인 컴퓨터)

> 이 파일은 unity 세션만 수정합니다. cv 세션은 읽기만 합니다.

## 현재 상태

- 마지막 갱신: 2026-11-09
- 단계: A단계(박스 방 물리 샌드박스) 완료 → B단계(방 메시 연동) 진행
- 사용 중인 메시: 없음 (박스 방)
- 환경: Unity 6000.3.28f1, URP 17.3, Input System 1.20.1 (Active Input Handling = Input System Package)

## READY

- READY: 박스 방 물리 샌드박스 씬 `Assets/RoomAR/Scenes/BoxRoom.unity` (비상용) / Unity Hub에서 `unity/AR_HomeStudioo` 열기 → BoxRoom 씬 Play. 씬이 없거나 깨졌으면 메뉴 **RoomAR > Build All Scenes**로 재생성. 배치 모드 자가 테스트: `Unity.exe -batchmode -nographics -projectPath unity/AR_HomeStudioo -executeMethod RoomAR.EditorTools.SandboxSelfTest.Run -logFile -` → `[RoomAR][SelfTest] PASS`

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
- [ ] glTFast 패키지 추가
- [ ] `room_latest.glb` 불러오기 + `MeshCollider` 적용
- [ ] 정점 색 표시용 셰이더 (URP)
- [x] 박스 방 버전 비상용으로 유지
- [ ] 18:00 리허설

## 메모

- 공 충돌 검사는 `ContinuousSpeculative`를 씁니다. `ContinuousDynamic`으로 하면 50Hz에서 1.5m 낙하한 공이 바닥에 약 8cm 파고들었습니다. 대신 반발 높이가 낮아져서, 탄성 0.8로 1.5m 낙하 시 약 0.62m까지 튑니다.
- 씬 생성 코드: `Assets/RoomAR/Scripts/Editor/SceneBuilder.cs`. 씬을 손으로 고쳤다면 재생성할 때 덮어써지므로 주의하십시오.

## 상대 세션에 요청

- (없음)

## 규약 변경

- (없음)

## 작업 기록

| 시각 | 내용 |
|---|---|
| 2026-11-09 | Unity 프로젝트를 `unity/AR_HomeStudioo/`로 이동, 상태 파일 생성 |
| 2026-11-09 | A단계: 박스 방 샌드박스(FlyCamera, SandboxController, SceneBuilder, SandboxSelfTest) 추가, 배치 모드 컴파일 및 자가 테스트 PASS |
