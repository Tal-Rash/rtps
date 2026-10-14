from __future__ import annotations

import os
from pathlib import Path
from threading import Lock

# Корневой каталог модуля и пути к данным
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DB_FILE = DATA_DIR / "alsn.db"
SHARED_DATA_DIR = ROOT.parent / "data"
WEB_USERS_DB = ROOT.parent / "base" / "web_users.db"
WEB_SECRET_FILE = SHARED_DATA_DIR / "web_secret.txt"

# Настройки авторизации и сессий
SESSION_COOKIE = "rtps_session"
APP_PREFIX = "/alsn"
APP_VERSION = "web-alsn-1.3"
DB_LOCK = Lock()

# URL-адреса для перенаправления и навигации
MAIN_LOGIN_URL = os.environ.get("MAIN_LOGIN_URL", "/login")
MAIN_SITE_URL = os.environ.get("MAIN_SITE_URL", "http://yrtps.ru")

# Внутренний кэш секретного ключа для подписи сессий
_SECRET_CACHE = {"mtime": 0.0, "secret": "opYbo6NB8pb7dChYQkmHEvUH6K4hAHjuzi2qEYOC024"}


def get_web_secret() -> str:
    """Получение секретного ключа с автоматическим перечитыванием при изменении файла."""
    try:
        if WEB_SECRET_FILE.exists():
            mtime = WEB_SECRET_FILE.stat().st_mtime
            if mtime != _SECRET_CACHE["mtime"]:
                _SECRET_CACHE["mtime"] = mtime
                _SECRET_CACHE["secret"] = WEB_SECRET_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return _SECRET_CACHE["secret"]
