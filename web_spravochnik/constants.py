from __future__ import annotations

import os
from pathlib import Path
from threading import Lock

# Корневой каталог модуля и пути к данным
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
SHARED_DATA_DIR = ROOT.parent / "data"
WEB_SECRET_FILE = SHARED_DATA_DIR / "web_secret.txt"
LEGACY_WEB_SECRET_FILE = DATA_DIR / "web_secret.txt"
DB_FILE = ROOT.parent / "base" / "common_database.db"
WEB_USERS_DB = ROOT.parent / "base" / "web_users.db"

# Настройки префикса и авторизации
APP_PREFIX = "/spravochnik"
APP_VERSION = "web-spravochnik-3.0"
SESSION_COOKIE = "rtps_session"
SESSION_TTL_SECONDS = 7 * 24 * 60 * 60

# Блокировка базы данных
DB_LOCK = Lock()

# URL-адреса для внешней маршрутизации
MAIN_LOGIN_URL = os.environ.get("MAIN_LOGIN_URL", "/login")
MAIN_SITE_URL = os.environ.get("MAIN_SITE_URL", "http://yrtps.ru")

# Список месяцев для норм времени
MONTHS = [
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]

# Кэш секретного ключа
_SECRET_CACHE = {"mtime": 0.0, "secret": "opYbo6NB8pb7dChYQkmHEvUH6K4hAHjuzi2qEYOC024"}


def get_web_secret() -> str:
    """Получение актуального секретного ключа с авто-перечитыванием."""
    try:
        if WEB_SECRET_FILE.exists():
            mtime = WEB_SECRET_FILE.stat().st_mtime
            if mtime != _SECRET_CACHE["mtime"]:
                _SECRET_CACHE["mtime"] = mtime
                _SECRET_CACHE["secret"] = WEB_SECRET_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return _SECRET_CACHE["secret"]


def get_legacy_web_secret() -> str:
    """Получение устаревшего секретного ключа для обратной совместимости старых сессий."""
    try:
        if LEGACY_WEB_SECRET_FILE.exists():
            return LEGACY_WEB_SECRET_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return ""


def text(value) -> str:
    """Безопасное приведение значения к строке."""
    if value is None:
        return ""
    return str(value)
