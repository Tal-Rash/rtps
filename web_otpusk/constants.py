from __future__ import annotations

import os
from pathlib import Path
from threading import Lock

# Корневой каталог модуля и пути к файлам данных
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
SHARED_DATA_DIR = ROOT.parent / "data"
WEB_SECRET_FILE = SHARED_DATA_DIR / "web_secret.txt"
DB_FILE = ROOT.parent / "base" / "common_database.db"
WEB_USERS_DB = ROOT.parent / "base" / "web_users.db"

# Настройки префикса и сессий
APP_PREFIX = "/otpusk"
APP_VERSION = "web-otpusk-3.0"
SESSION_COOKIE = "rtps_session"
SESSION_TTL_SECONDS = 7 * 24 * 60 * 60

# Блокировка базы данных для безопасного параллельного доступа
DB_LOCK = Lock()

# URL-адреса для маршрутизации
MAIN_LOGIN_URL = os.environ.get("MAIN_LOGIN_URL", "/login")
MAIN_SITE_URL = os.environ.get("MAIN_SITE_URL", "http://yrtps.ru")

# Дефолтный список праздничных дней по месяцам (ст. 112 ТК РФ)
DEFAULT_HOLIDAYS = [
    {"month": 0, "name": "Январь", "totalDays": 31, "dates": "1, 2, 3, 4, 5, 6, 7, 8"},
    {"month": 1, "name": "Февраль", "totalDays": 28, "dates": ""},
    {"month": 2, "name": "Март", "totalDays": 31, "dates": "8"},
    {"month": 3, "name": "Апрель", "totalDays": 30, "dates": ""},
    {"month": 4, "name": "Май", "totalDays": 31, "dates": "1, 9"},
    {"month": 5, "name": "Июнь", "totalDays": 30, "dates": "12"},
    {"month": 6, "name": "Июль", "totalDays": 31, "dates": ""},
    {"month": 7, "name": "Август", "totalDays": 31, "dates": ""},
    {"month": 8, "name": "Сентябрь", "totalDays": 30, "dates": ""},
    {"month": 9, "name": "Октябрь", "totalDays": 31, "dates": ""},
    {"month": 10, "name": "Ноябрь", "totalDays": 30, "dates": "4"},
    {"month": 11, "name": "Декабрь", "totalDays": 31, "dates": ""}
]

# Кэш секретного ключа для быстрой проверки сессий
_SECRET_CACHE = {"mtime": 0.0, "secret": "opYbo6NB8pb7dChYQkmHEvUH6K4hAHjuzi2qEYOC024"}


def get_web_secret() -> str:
    """Получение секретного ключа подписи сессий с кэшированием."""
    try:
        if WEB_SECRET_FILE.exists():
            mtime = WEB_SECRET_FILE.stat().st_mtime
            if mtime != _SECRET_CACHE["mtime"]:
                _SECRET_CACHE["mtime"] = mtime
                _SECRET_CACHE["secret"] = WEB_SECRET_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return _SECRET_CACHE["secret"]
