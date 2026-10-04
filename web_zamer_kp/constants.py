from __future__ import annotations

import os
from pathlib import Path
from threading import Lock

# Корневой каталог модуля и пути к общим ресурсам
ROOT = Path(__file__).resolve().parent
SHARED_DATA_DIR = ROOT.parent / "data"
LEGACY_WEB_SECRET_FILE = ROOT / "data" / "web_secret.txt"
WEB_SECRET_FILE = SHARED_DATA_DIR / "web_secret.txt"
ACCESS_STATE_FILE = SHARED_DATA_DIR / "web_access.json"
DB_FILE = ROOT.parent / "base" / "common_database.db"

# Настройки авторизации и сессий
SESSION_COOKIE = "rtps_session"
SESSION_TTL_SECONDS = 7 * 24 * 60 * 60
APP_PREFIX = "/zamer-kp"
APP_VERSION = "web-zkp-2.27"
DB_LOCK = Lock()
MAIN_LOGIN_URL = os.environ.get("MAIN_LOGIN_URL", "http://yrtps.ru/login")

# Параметры бланка замера колесных пар
INPUT_ROWS = 12
INPUT_DATA_COLS = 10

# Варианты видов ремонта по сериям локомотивов
DEFAULT_REPAIR_OPTIONS = {
    "tem": ["", "ТО2", "ТО3", "ТО4", "ТР1", "ТР2", "ТР3", "СР", "КР"],
    "pe": ["", "ТО", "ТР", "СР", "КР"],
}

# Нормативные значения предельного износа
DEFAULT_NORMS = [
    ("max_prokat", "Прокат", "больше или равно", "6", "7"),
    ("min_greben", "Толщина гребня", "меньше или равно", "26", "25"),
    ("min_krut", "Крутизна гребня", "меньше или равно", "7", "6"),
    ("min_bandage_thickness", "Толщина бандажа", "меньше или равно", "", ""),
    ("max_diameter_diff", "Наибольшая разница диаметров бандажей в комплекте, мм", "больше или равно", "", ""),
    ("prokat_6_count", "Число КП с прокатом 6 мм и более", "больше или равно", "", ""),
]

# Заголовки таблицы архива при экспорте в Excel
ARCHIVE_EXCEL_HEADERS = [
    "Дата замера",
    "Локомотив",
    "Вид ремонта",
    "Серия",
    "Секция",
    "Номер КП",
    "Прокат лев",
    "Прокат прав",
    "Толщина гребня лев",
    "Толщина гребня прав",
    "Крутизна гребня лев",
    "Крутизна гребня прав",
    "Толщина бандажа лев",
    "Толщина бандажа прав",
    "Диаметр бандажа лев",
    "Диаметр бандажа прав",
]

# Метрики для анализа трендов износа колесных пар
WEAR_TREND_METRICS = [
    {
        "key": "prokat",
        "label": "Прокат",
        "columns": (2, 3),
        "aggregate": "max",
        "worse_when": "higher",
    },
    {
        "key": "greben",
        "label": "Гребень",
        "columns": (4, 5),
        "aggregate": "min",
        "worse_when": "lower",
    },
    {
        "key": "krut",
        "label": "Крутизна",
        "columns": (6, 7),
        "aggregate": "min",
        "worse_when": "lower",
    },
    {
        "key": "bandage_thickness",
        "label": "Бандаж",
        "columns": (8, 9),
        "aggregate": "min",
        "worse_when": "lower",
    },
    {
        "key": "diameter",
        "label": "Диаметр",
        "columns": (10, 11),
        "aggregate": "side",
        "worse_when": "lower",
    },
]


def load_web_secret() -> str:
    """Загрузка общего секретного ключа для подписи cookies сессий."""
    if WEB_SECRET_FILE.exists():
        return WEB_SECRET_FILE.read_text(encoding="utf-8").strip()
    return "opYbo6NB8pb7dChYQkmHEvUH6K4hAHjuzi2qEYOC024"


WEB_SECRET = load_web_secret()
LEGACY_WEB_SECRET = ""
