#!/usr/bin/env bash
# 3DGS(gsplat) 전용 uv 환경. 메인 .venv 와 분리 (CLAUDE.md)
#   사용: bash cv/recon/envs/setup_gsplat.sh
#   결과: ${ENVS_ROOT}/gsplat/.venv (Python 3.10), 예제 트레이너 소스 ${ENVS_ROOT}/gsplat/gsplat (v1.5.3)
# gsplat 은 torch2.4+cu124 미리 빌드 wheel 사용 (cp310 만 제공). fused-ssim 만 소스 빌드 (시스템 nvcc 12.4 + gcc-13, sudo 불필요)
set -euo pipefail
ENVS_ROOT="${ENVS_ROOT:-/storage/AI/cv_project/envs}"
ROOT="$ENVS_ROOT/gsplat"
REPO="$ROOT/gsplat"
TAG="${GSPLAT_TAG:-v1.5.3}"
export UV_CACHE_DIR="${UV_CACHE_DIR:-/storage/AI/cv_project/.cache/uv}"
export UV_LINK_MODE=copy
mkdir -p "$ROOT"
[ -d "$REPO/.git" ] || git clone --depth 1 --branch "$TAG" https://github.com/nerfstudio-project/gsplat.git "$REPO"
echo "gsplat source: $(git -C "$REPO" describe --tags) $(git -C "$REPO" rev-parse HEAD)"
[ -x "$ROOT/.venv/bin/python" ] || uv venv --python 3.10 "$ROOT/.venv"
PY="$ROOT/.venv/bin/python"
uv pip install --python "$PY" "torch==2.4.1" "torchvision==0.19.1" --index-url https://download.pytorch.org/whl/cu124
uv pip install --python "$PY" "gsplat==${TAG#v}" --index-url https://docs.gsplat.studio/whl/pt24cu124 --extra-index-url https://pypi.org/simple
# examples/requirements.txt (simple_trainer.py) — numpy<2 고정
uv pip install --python "$PY" "numpy<2" viser nerfview "imageio[ffmpeg]" scikit-learn tqdm "torchmetrics[image]" \
  opencv-python-headless "tyro>=0.8.8" Pillow tensorboard tensorly pyyaml matplotlib plyfile splines setuptools wheel ninja \
  "pycolmap @ git+https://github.com/rmbrualla/pycolmap@cc7ea4b7301720ac29287dbe450952511b32125e"
export CC=gcc-13 CXX=g++-13 CUDAHOSTCXX=g++-13 CUDA_HOME="${CUDA_HOME:-/usr}" TORCH_CUDA_ARCH_LIST="${TORCH_CUDA_ARCH_LIST:-8.6}" MAX_JOBS=16
"$PY" -c "import fused_ssim" 2>/dev/null || uv pip install --python "$PY" --no-build-isolation \
  "fused-ssim @ git+https://github.com/rahul-goel/fused-ssim@328dc9836f513d00c4b5bc38fe30478b4435cbb5"
"$PY" - <<'EOF'
import numpy, torch, gsplat, fused_ssim, pycolmap, torchmetrics
from gsplat import rasterization
m = torch.zeros(1, 3, device="cuda")
print("OK numpy", numpy.__version__, "torch", torch.__version__, "gsplat", gsplat.__version__, "cuda", torch.cuda.is_available())
EOF
