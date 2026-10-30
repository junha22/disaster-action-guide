"""Load API keys and settings from backend/.env (see backend/.env.example).

- Values already set in the process environment win (systemd, PowerShell $env:, tests).
- KIROTHON_ENV_FILE picks another file; an empty value turns loading off (tests do this).
- The file is never deployed or committed (.gitignore, scripts/deploy.ps1, ops/deploy.py).
"""
import logging
import os
from pathlib import Path

DEFAULT_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
log = logging.getLogger(__name__)


def load_env_file() -> Path | None:
    raw = os.environ.get("KIROTHON_ENV_FILE")
    if raw is not None and not raw.strip():
        return None
    path = Path(raw) if raw else DEFAULT_ENV_FILE
    if not path.is_file():
        return None
    try:
        from dotenv import load_dotenv  # pinned in requirements.lock (uvicorn[standard])
    except ImportError:
        log.warning(".env 파일을 읽지 못했습니다: python-dotenv 없음")
        return None
    load_dotenv(path, override=False, encoding="utf-8")
    return path
