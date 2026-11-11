from __future__ import annotations

import os
from pathlib import Path
from threading import Lock

# Корневой каталог модуля и пути к данным
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DB_FILE = DATA_DIR / "equipment.db"
SHARED_DATA_DIR = ROOT.parent / "data"
WEB_USERS_DB = ROOT.parent / "base" / "web_users.db"
WEB_SECRET_FILE = SHARED_DATA_DIR / "web_secret.txt"

# Настройки авторизации и сессий
SESSION_COOKIE = "rtps_session"
APP_PREFIX = "/equipment"
APP_VERSION = "web-equipment-1.01"
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


# Предустановленные категории оборудования
DEFAULT_CATEGORIES = [
    "Домкраты и гидрооборудование",
    "Электроинструмент",
    "Пневмоинструмент",
    "Грузоподъемные механизмы и стропы",
    "Слесарный инструмент",
    "Лестницы и стремянки",
    "Диэлектрические средства защиты",
    "Сварочное оборудование",
    "Прочее",
]

# Стандартные виды проверок и испытаний
DEFAULT_TEST_TYPES = [
    "Техническое освидетельствование (под нагрузкой)",
    "Испытание статической нагрузкой",
    "Проверка изоляции и осмотр",
    "Периодический осмотр и испытание",
    "Поверка / калибровка",
    "Осмотр и проверка на холостом ходу",
]

