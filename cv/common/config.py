"""공통 설정 로드: 저장소 루트 .env, cv/config/*.yaml."""
from __future__ import annotations

import os
from pathlib import Path

import yaml

CV_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = CV_ROOT.parent
CONFIG_DIR = CV_ROOT / "config"

_env_loaded = False


def load_env() -> None:
    """저장소 루트 .env를 읽는다. 이미 설정된 환경 변수가 우선한다."""
    global _env_loaded
    if _env_loaded:
        return
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env", override=False)
    _env_loaded = True


def env(name: str, required: bool = True) -> str | None:
    load_env()
    val = os.environ.get(name, "").strip()
    if not val:
        if required:
            raise RuntimeError(f"환경 변수 {name}가 비어 있습니다. 저장소 루트 .env에 값을 채워주세요.")
        return None
    return val


def shared_dir() -> Path:
    p = Path(env("SHARED_DIR"))
    if not p.is_dir():
        raise RuntimeError(f"SHARED_DIR={p} 폴더가 없습니다.")
    return p


def load_yaml(name: str) -> dict:
    with open(CONFIG_DIR / name, encoding="utf-8") as f:
        return yaml.safe_load(f)
