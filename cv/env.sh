# cv 세션 공통 환경. 사용: source cv/env.sh
# 캐시와 가상환경은 모두 /storage 쪽에 둔다 (홈 디렉토리에 쓰지 않음).
_CV_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export CV_VENV="${CV_VENV:-/storage/AI/test/.venv}"
export CACHE_ROOT="${CACHE_ROOT:-/storage/AI/test/.cache}"
export UV_CACHE_DIR="$CACHE_ROOT/uv"
export UV_LINK_MODE=copy
export HF_HOME="$CACHE_ROOT/huggingface"
export TORCH_HOME="$CACHE_ROOT/torch"
export XDG_CACHE_HOME="$CACHE_ROOT/xdg"
export MPLCONFIGDIR="$CACHE_ROOT/matplotlib"
export PYTHONPYCACHEPREFIX="$CACHE_ROOT/pycache"
export PYTHONPATH="$_CV_ROOT/..${PYTHONPATH:+:$PYTHONPATH}"
# shellcheck disable=SC1091
source "$CV_VENV/bin/activate"
