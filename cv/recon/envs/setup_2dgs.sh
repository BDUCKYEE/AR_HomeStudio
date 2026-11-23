#!/usr/bin/env bash
# 2DGS(2D Gaussian Splatting) 전용 uv 환경. 메인 .venv 와 분리 (CLAUDE.md, 메인 venv 는 건드리지 않음)
#   사용: bash cv/recon/envs/setup_2dgs.sh            (이미 있으면 빠진 것만 설치)
#   결과: ${ENVS_ROOT}/2dgs/.venv, 소스 ${ENVS_ROOT}/2dgs/2d-gaussian-splatting
# sudo 불필요. 시스템 nvcc 12.4 + gcc-13 으로 CUDA 확장(diff-surfel-rasterization, simple-knn)을 빌드한다.
# (Ubuntu 기본 gcc 15 는 CUDA 12.4 가 지원하지 않으므로 gcc-13 을 명시)
set -euo pipefail
ENVS_ROOT="${ENVS_ROOT:-/storage/AI/cv_project/envs}"
ROOT="$ENVS_ROOT/2dgs"
REPO="$ROOT/2d-gaussian-splatting"
REPO_URL="https://github.com/hbb1/2d-gaussian-splatting.git"
REPO_COMMIT="${REPO_COMMIT:-}"          # 비우면 기본 브랜치 최신. 재현 시 status-cv.md 에 적힌 커밋 지정
export UV_CACHE_DIR="${UV_CACHE_DIR:-/storage/AI/cv_project/.cache/uv}"
export UV_LINK_MODE=copy

mkdir -p "$ROOT"
if [ ! -d "$REPO/.git" ]; then
  git clone --recursive "$REPO_URL" "$REPO"
fi
if [ -n "$REPO_COMMIT" ]; then
  git -C "$REPO" checkout "$REPO_COMMIT" && git -C "$REPO" submodule update --init --recursive
fi
echo "2DGS commit: $(git -C "$REPO" rev-parse HEAD)"

if [ ! -x "$ROOT/.venv/bin/python" ]; then
  uv venv --python 3.11 "$ROOT/.venv"
fi
PY="$ROOT/.venv/bin/python"
# torch 는 시스템 nvcc(12.4)와 맞춰 cu124 빌드
uv pip install --python "$PY" "torch==2.4.1" "torchvision==0.19.1" --index-url https://download.pytorch.org/whl/cu124
uv pip install --python "$PY" "numpy<2" plyfile tqdm opencv-python-headless "open3d==0.18.0" trimesh \
  mediapy lpips scikit-image pillow pyyaml setuptools wheel ninja "pycolmap==3.10.0"

export CC=gcc-13 CXX=g++-13 CUDAHOSTCXX=g++-13
export CUDA_HOME="${CUDA_HOME:-/usr}"
export TORCH_CUDA_ARCH_LIST="${TORCH_CUDA_ARCH_LIST:-8.6}"   # RTX 3090
export MAX_JOBS="${MAX_JOBS:-16}"
# gcc 13+ 에서는 <cstdint> 가 간접 포함되지 않아 uint32_t 미정의 오류 → 헤더에 한 줄 추가 (이미 있으면 건너뜀)
H="$REPO/submodules/diff-surfel-rasterization/cuda_rasterizer/rasterizer_impl.h"
grep -q '#include <cstdint>' "$H" || sed -i '0,/#include/s//#include <cstdint>\n#include/' "$H"
K="$REPO/submodules/simple-knn/simple_knn.cu"                       # 같은 이유로 FLT_MAX 미정의
grep -q '#include <cfloat>' "$K" || sed -i '0,/#include/s//#include <cfloat>\n#include/' "$K"
for sub in diff-surfel-rasterization simple-knn; do
  uv pip install --python "$PY" --no-build-isolation "$REPO/submodules/$sub"
done
"$PY" - <<'EOF'
import numpy, torch, diff_surfel_rasterization, simple_knn._C, pycolmap, open3d
print("OK numpy", numpy.__version__, "torch", torch.__version__, "cuda", torch.cuda.is_available(),
      "pycolmap", pycolmap.__version__, "open3d", open3d.__version__)
EOF
