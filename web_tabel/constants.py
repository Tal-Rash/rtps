from __future__ import annotations

import os
from pathlib import Path
from threading import Lock

# Корневые каталоги и пути
ROOT = Path(__file__).resolve().parent
SHARED_DATA_DIR = ROOT.parent / "data"
WEB_SECRET_FILE = SHARED_DATA_DIR / "web_secret.txt"
DB_FILE = ROOT.parent / "base" / "common_database.db"
COMMON_DB_FILE = DB_FILE
WEB_USERS_DB = ROOT.parent / "base" / "web_users.db"

# Настройки авторизации и сессий
SESSION_COOKIE = "rtps_session"
APP_PREFIX = "/tabel"
APP_VERSION = "web-tabel-1.58"
DB_LOCK = Lock()

# Адрес страницы входа (по умолчанию относительный URL для работы по HTTPS)
MAIN_LOGIN_URL = os.environ.get("MAIN_LOGIN_URL", "/login")

# Названия месяцев на русском языке
MONTH_NAMES = [
    "",
    "Январь",
    "Февраль",
    "Март",
    "Апрель",
    "Май",
    "Июнь",
    "Июль",
    "Август",
    "Сентябрь",
    "Октябрь",
    "Ноябрь",
    "Декабрь",
]


def load_web_secret() -> str:
    """Загрузка секретного ключа веб-сессий из общего файла."""
    if WEB_SECRET_FILE.exists():
        return WEB_SECRET_FILE.read_text(encoding="utf-8").strip()
    return "opYbo6NB8pb7dChYQkmHEvUH6K4hAHjuzi2qEYOC024"


WEB_SECRET = load_web_secret()
