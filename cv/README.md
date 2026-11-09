# cv/ — AI 컴퓨터 Python 코드

방 복원(VGGT, Open3D), 카메라 캘리브레이션, 관절 추적(YOLO26-pose, 손 모델), 삼각측량, UDP 송신을 담당합니다.
이 폴더는 cv 세션만 수정합니다. 공통 규약은 [../docs/interfaces.md](../docs/interfaces.md)를 따릅니다.

## 환경 설정

```bash
cd cv
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

환경 변수는 저장소 루트의 `.env`에서 읽습니다 (`SHARED_DIR`, `UDP_PORT`, `VGGT_WEIGHTS` 등).

## 예정 구조

```
cv/
├─ recon/      # VGGT 추론 → Open3D 메시 → 바닥 정렬, 스케일 보정 → .glb
├─ calib/      # ChArUco 내부/외부 파라미터 캘리브레이션
├─ tracking/   # 카메라 캡처, YOLO26-pose, 손 키포인트, 삼각측량, 필터
├─ net/        # UDP 송신
└─ common/     # 좌표 변환, 설정 로드
```

## 데이터

입력 사진과 출력 메시는 git이 아닌 `SHARED_DIR` 아래에 둡니다.
