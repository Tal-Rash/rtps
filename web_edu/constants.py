from __future__ import annotations

import os
from pathlib import Path
from threading import Lock

# Корневой каталог модуля и пути к данным
ROOT = Path(__file__).resolve().parent
SHARED_DATA_DIR = ROOT.parent / "data"
WEB_SECRET_FILE = SHARED_DATA_DIR / "web_secret.txt"
DB_FILE = ROOT.parent / "base" / "common_database.db"
WEB_USERS_DB = ROOT.parent / "base" / "web_users.db"

# Настройки авторизации и сессий
SESSION_COOKIE = "rtps_session"
APP_PREFIX = "/edu"
APP_VERSION = "web-edu-3.1"
DB_LOCK = Lock()

# URL-адреса для перенаправления и навигации
MAIN_LOGIN_URL = os.environ.get("MAIN_LOGIN_URL", "/login")
MAIN_SITE_URL = os.environ.get("MAIN_SITE_URL", "http://yrtps.ru")

# Дефолтные колонки видов обучения (название, порядок сортировки, периодичность в месяцах)
DEFAULT_COLUMNS = [
    ("ПТМ", 0, 12),
    ("наряды-допуска\n(П 38-01-2019)", 1, 12),
    ("СИЗ", 2, 12),
    ("Высота", 3, 36),
    ("Стропальщик", 4, 24),
    ("Три шага", 5, 12),
]

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
