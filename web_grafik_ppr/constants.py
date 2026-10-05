from __future__ import annotations

import os
from pathlib import Path

# Константы и конфигурация для модуля График ППР
APP_VERSION = "web-gpp-1.18"

# Месяцы на русском языке
MONTHS_RU = [
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]

# Нормативы для тепловозов и тяговых агрегатов
TEM_NORM_ROWS = ["ТО2", "ТО3", "ТР1", "ТР2", "ТР3", "СР", "КР"]
AGR_NORM_ROWS = ["ТО", "ТР", "КР"]

# Коды колонок для долгосрочного графика ремонта
REPAIR_SCHEDULE_COLUMN_CODES = [
    "ТР1", "ТР2", "ТР1", "ТР3", "ТР1", "ТР2", "ТР1", "СР",
    "ТР1", "ТР2", "ТР1", "ТР3", "ТР1", "ТР2", "ТР1", "КР",
]

# Имена файлов шаблонов Excel
REPORT_TEMPLATE_NAME = "Отчет_шаблон.xlsx"
TU28_TEMPLATE_NAME = "ТУ-28_шаблон.xlsx"
ACT_TEMPLATE_NAME = "Акт_шаблон.xlsx"

MONTH_DAY_LIMIT_FOR_REPORT = 25

# Коэффициенты пересчета ремонтов
TEP_REPORT_FACTORS = {"ТО2": 1, "ТО3": 2, "ТР1": 5, "ТР2": 10, "ТР3": 15}
AGR_REPORT_FACTORS = {"ТО": 1, "ТР": 5}
TEP_HOUR_FACTORS = {"ТО2": 1, "ТО3": 2, "ТР1": 5, "ТР2": 10, "ТР3": 15}
AGR_HOUR_FACTORS = {"ТО": 1, "ТР": 5}
TU28_REPAIR_CODES = {"ТО3", "ТР1", "ТР2", "ТР3", "СР", "КР"}

# Нерабочие праздничные дни
FIXED_HOLIDAYS = {
    (1, 1), (1, 2), (1, 3), (1, 4), (1, 5), (1, 6), (1, 7), (1, 8),
    (2, 23), (3, 8), (5, 1), (5, 9), (6, 12), (11, 4),
}

# Переносы праздничных дней по годам
TRANSFER_HOLIDAYS_BY_YEAR = {
    2025: {(5, 2), (5, 8), (6, 13), (11, 3), (12, 31)},
}

# Пути к директориям и базам данных
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DB_FILE = DATA_DIR / "grafik_ppr_web.db"
SHARED_DATA_DIR = ROOT.parent / "data"
WEB_SECRET_FILE = SHARED_DATA_DIR / "web_secret.txt"
SOURCE_DB = ROOT.parent / "base" / "common_database.db"
SOURCE_DIR = ROOT.parent / "src" / "График ППР"

# Настройки авторизации и сессий
SESSION_COOKIE = "rtps_session"
SESSION_TTL_SECONDS = 7 * 24 * 60 * 60
MAIN_LOGIN_URL = os.environ.get("MAIN_LOGIN_URL", "http://yrtps.ru/login")
APP_PREFIX = "/grafik-ppr"
AUTH_ENABLED = True
