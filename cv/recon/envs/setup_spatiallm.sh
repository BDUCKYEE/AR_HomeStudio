#!/usr/bin/env bash
# SpatialLM 1.1 전용 uv 환경. 메인 .venv 와 분리 (CLAUDE.md)
#   사용: bash cv/recon/envs/setup_spatiallm.sh
#   결과: ${ENVS_ROOT}/spatiallm/.venv, 소스 ${ENVS_ROOT}/spatiallm/SpatialLM
# 공식 설치는 conda + poetry 이지만 여기서는 uv 로 pyproject 의존성을 그대로 설치한다. sudo 불필요.
# Sonata 인코더 의존성: flash-attn(미리 빌드된 wheel), torch-scatter(pyg wheel), spconv-cu120(wheel)
set -euo pipefail
ENVS_ROOT="${ENVS_ROOT:-/storage/AI/cv_project/envs}"
ROOT="$ENVS_ROOT/spatiallm"
REPO="$ROOT/SpatialLM"
REPO_COMMIT="${REPO_COMMIT:-}"
export UV_CACHE_DIR="${UV_CACHE_DIR:-/storage/AI/cv_project/.cache/uv}"
export UV_LINK_MODE=copy
mkdir -p "$ROOT"
[ -d "$REPO/.git" ] || git clone https://github.com/manycore-research/SpatialLM.git "$REPO"
[ -z "$REPO_COMMIT" ] || git -C "$REPO" checkout "$REPO_COMMIT"
echo "SpatialLM commit: $(git -C "$REPO" rev-parse HEAD)"
[ -x "$ROOT/.venv/bin/python" ] || uv venv --python 3.11 "$ROOT/.venv"
PY="$ROOT/.venv/bin/python"
uv pip install --python "$PY" "torch==2.4.1" "torchvision==0.19.1" --index-url https://download.pytorch.org/whl/cu124
uv pip install --python "$PY" "numpy<2" "transformers>=4.41.2,<=4.46.1" "tokenizers>=0.19.0,<0.20.4" "safetensors>=0.4.5" \
  pandas einops scipy scikit-learn toml "huggingface_hub>=0.25.0" shapely bbox terminaltables "open3d==0.18.0" addict \
  timm spconv-cu120 setuptools wheel ninja packaging psutil
uv pip install --python "$PY" torch-scatter -f https://data.pyg.org/whl/torch-2.4.0+cu124.html
# flash-attn: 소스 빌드는 오래 걸리므로 공식 릴리스의 미리 빌드된 wheel 사용 (torch2.4, cu12, cxx11abi=FALSE, cp311)
FA_WHL="https://github.com/Dao-AILab/flash-attention/releases/download/v2.7.4.post1/flash_attn-2.7.4.post1+cu12torch2.4cxx11abiFALSE-cp311-cp311-linux_x86_64.whl"
"$PY" -c "import flash_attn" 2>/dev/null || uv pip install --python "$PY" "$FA_WHL"
"$PY" - <<'EOF'
import numpy, torch, flash_attn, torch_scatter, spconv, transformers
print("OK numpy", numpy.__version__, "torch", torch.__version__, "cuda", torch.cuda.is_available(),
      "flash_attn", flash_attn.__version__, "transformers", transformers.__version__, "spconv", spconv.__version__)
EOF
