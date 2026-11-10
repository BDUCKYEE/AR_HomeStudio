# AR_HomeStudio
**휴대폰으로 방을 3D화 하고 Unity와 몇 대의 카메라를 통해 가상 물체와 상호작용 하는 XR 환경 만들기**

핸드폰 사진으로 방을 3D 메시로 복원하고, 방 모서리에 고정한 글로벌 셔터 카메라 4대로 몸과 손 관절을 실시간 3D로 추적합니다. 추적한 관절로 Unity 디지털 트윈 속 가상 물체와 상호작용하고, 그 결과를 메인 웹캠 화면 위에 AR로 합성합니다.

> 상태: 개발 중. 첫 시연은 2026-11-10 21:00입니다. 자세한 기획은 [PROJECT_BRIEF.md](PROJECT_BRIEF.md)에 있습니다.

## 시스템 개요

```
[핸드폰 사진 또는 영상] ──► VGGT ──► 깊이/포즈 ──► Open3D (TSDF/Poisson) ──► 방 메시 (.glb)
                                                                   │
[고정 카메라 4대] ──► YOLO26-pose (몸) ──► 손목 크롭 ──► 손 키포인트   │
        │                                                          ▼
        └──► 타임스탬프 동기화 ──► 다시점 삼각측량 ──► 필터 ──► UDP ──► Unity 디지털 트윈
                                                                   │  (물리, 상호작용)
[메인 웹캠] ───────────────────────────────────────────────────────►│
                                                                   ▼
                                                     메인 웹캠 화면 위 AR 합성
```

| 단계 | 내용 | 담당 |
|---|---|---|
| 정적 방 복원 | VGGT로 Point Cloud/깊이 추정 → Open3D 메시 → 바닥 정렬, ChArUco 스케일 보정 → `.glb` | `cv/` |
| 관절 추적 | OV9281 4대 + YOLO26-pose (몸 17점) + 손 모델 (21점) → 삼각측량 → 필터 | `cv/` |
| 디지털 트윈 | Unity 6.3 LTS (URP)에서 방 메시와 실시간 관절로 물리 상호작용 | `unity/` |
| AR 합성 | 웹캠과 같은 내부/외부 파라미터의 Unity 카메라, 방 메시로 depth-only 가림 처리 | `unity/` |

## 저장소 구조

```
.
├─ README.md
├─ CLAUDE.md               # 두 Claude Code 세션 공통 지침
├─ PROJECT_BRIEF.md        # 기획 문서
├─ LICENSE                 # AGPL-3.0
├─ .env.example            # 환경 변수 목록 (실제 .env는 커밋하지 않음)
├─ docs/
│  ├─ interfaces.md        # 공통 규약: 좌표계, 메시 형식, UDP 메시지
│  ├─ status-cv.md         # AI 컴퓨터 세션 진행 기록
│  └─ status-unity.md      # 메인 컴퓨터 세션 진행 기록
├─ cv/                     # Python 코드 (AI 컴퓨터, Ubuntu)
└─ unity/AR_HomeStudioo/   # Unity 프로젝트 (메인 컴퓨터, Windows)
```

## 하드웨어

| 구분 | 구성 |
|---|---|
| AI 컴퓨터 | Ryzen 9 7950X, RTX 3090 ×2, RAM 128GB, Ubuntu 26.04 (헤드리스) |
| 메인 컴퓨터 | Ryzen 7 5800X, Radeon RX 9070 XT 16GB, RAM 32GB, Windows 11 |
| 고정 카메라 | OV9281 USB UVC ×4 (1280×800, 모노크롬, 글로벌 셔터) |
| 메인 웹캠 | 메인 컴퓨터에 연결 |
| 네트워크 | 1Gbps 스위치로 두 컴퓨터 직접 연결 |

## 시작하기

### 공통

```bash
git clone https://github.com/BDUCKYEE/AR_HomeStudio.git
cd AR_HomeStudio
cp .env.example .env   # 각 컴퓨터에서 값 입력
```

### AI 컴퓨터 (`cv/`)

```bash
cd cv
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

자세한 내용은 [cv/README.md](cv/README.md)를 참고하십시오.

### 메인 컴퓨터 (`unity/`)

1. Unity Hub에서 **Add project from disk** → `unity/AR_HomeStudioo` 선택
2. 에디터 버전: **Unity 6000.3.28f1** (6.3 LTS), 렌더 파이프라인: URP
3. 방 메시는 공유 폴더(`SHARED_DIR/meshes/room_latest.glb`)에서 glTFast로 불러옵니다.

## 공통 규약 요약

- 단위는 미터, 월드 원점은 바닥에 고정한 ChArUco 보드 중심, 바닥 높이 0
- 방 메시는 glTF 규약(오른손, Y 위)의 `.glb`. Unity 축 변환은 glTFast가 맡습니다.
- 관절 데이터는 UDP + JSON, 한 패킷에 한 프레임

전체 규약은 [docs/interfaces.md](docs/interfaces.md)에 있습니다.

## 데이터 정책

- 방 사진, 메시, 녹화 영상은 git에 커밋하지 않고 AI 컴퓨터의 Samba 공유 폴더에 둡니다.
- IP, 경로, 토큰 같은 값은 `.env`에만 둡니다.

## 라이선스

[AGPL-3.0](LICENSE) (Ultralytics YOLO 사용에 따름)
