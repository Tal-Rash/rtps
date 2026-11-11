from __future__ import annotations

import calendar
import datetime as dt
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

# Обеспечиваем доступность корня проекта для системных импортов
_ROOT = Path(__file__).resolve().parent
if str(_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_ROOT.parent))

from rtps_common import connect_sqlite

try:
    from .constants import DATA_DIR, DB_FILE, DB_LOCK, DEFAULT_CATEGORIES
except (ImportError, ValueError):
    from constants import DATA_DIR, DB_FILE, DB_LOCK, DEFAULT_CATEGORIES


@contextmanager
def conn_ctx() -> Generator[sqlite3.Connection, None, None]:
    """Безопасный контекстный менеджер SQLite соединения с оптимизированными настройками."""
    connection = connect_sqlite(DB_FILE)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA foreign_keys=ON")
        yield connection
    finally:
        connection.close()


def parse_date_safe(date_str: str) -> dt.date | None:
    """Безопасный разбор даты из форматов ДД.ММ.ГГГГ или ГГГГ-ММ-ДД."""
    s = str(date_str or "").strip()
    if not s:
        return None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def add_months_to_date(sourcedate: dt.date, months: int) -> dt.date:
    """Прибавление заданного числа месяцев к дате с корректным учетом конца месяца."""
    month = sourcedate.month - 1 + months
    year = sourcedate.year + month // 12
    month = month % 12 + 1
    day = min(sourcedate.day, calendar.monthrange(year, month)[1])
    return dt.date(year, month, day)


def calculate_next_test_date(last_date_str: str, periodicity_str: str) -> str:
    """Вычисляет дату следующего испытания на основе даты последнего испытания и периодичности в месяцах."""
    last_d = parse_date_safe(last_date_str)
    if not last_d:
        return ""
    try:
        p = int(str(periodicity_str or "12").strip())
        if p <= 0:
            p = 12
    except ValueError:
        p = 12
    next_d = add_months_to_date(last_d, p)
    return next_d.strftime("%d.%m.%Y")


def normalize_equipment_item(item: dict, idx: int = 0) -> dict:
    """Нормализация структуры одного объекта оборудования с валидацией полей."""
    name = str(item.get("name") or "").strip()
    inv_number = str(item.get("inv_number") or "").strip()
    category = str(item.get("category") or "").strip()
    if not category:
        category = "Прочее"

    test_type = str(item.get("test_type") or "").strip()
    periodicity = str(item.get("periodicity") or "12").strip()
    last_test_date = str(item.get("last_test_date") or "").strip()
    next_test_date = str(item.get("next_test_date") or "").strip()

    # Если следующая дата не заполнена, но есть дата последней проверки и периодичность — вычисляем
    if not next_test_date and last_test_date:
        next_test_date = calculate_next_test_date(last_test_date, periodicity)

    raw_repair = item.get("in_repair", 0)
    in_repair = 1 if raw_repair in (1, "1", True, "true", "True", "Да", "да", "В ремонте") else 0

    location = str(item.get("location") or "").strip()
    responsible = str(item.get("responsible") or "").strip()
    test_result = str(item.get("test_result") or "Годен").strip()
    protocol_num = str(item.get("protocol_num") or "").strip()
    notes = str(item.get("notes") or "").strip()
    updated_at = str(item.get("updated_at") or "").strip()
    sort_order = int(item.get("sort_order") or (idx + 1))

    return {
        "id": item.get("id"),
        "sort_order": sort_order,
        "category": category,
        "name": name,
        "inv_number": inv_number,
        "location": location,
        "responsible": responsible,
        "test_type": test_type,
        "periodicity": periodicity,
        "last_test_date": last_test_date,
        "next_test_date": next_test_date,
        "in_repair": in_repair,
        "test_result": test_result,
        "protocol_num": protocol_num,
        "notes": notes,
        "updated_at": updated_at,
    }


def init_db() -> None:
    """Инициализация таблиц базы данных оборудования и первичное наполнение демонстрационными записями."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with DB_LOCK, conn_ctx() as conn:
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS equipment (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    category TEXT NOT NULL DEFAULT 'Прочее',
                    name TEXT NOT NULL DEFAULT '',
                    inv_number TEXT NOT NULL DEFAULT '',
                    location TEXT NOT NULL DEFAULT '',
                    responsible TEXT NOT NULL DEFAULT '',
                    test_type TEXT NOT NULL DEFAULT '',
                    periodicity TEXT NOT NULL DEFAULT '12',
                    last_test_date TEXT NOT NULL DEFAULT '',
                    next_test_date TEXT NOT NULL DEFAULT '',
                    in_repair INTEGER NOT NULL DEFAULT 0,
                    test_result TEXT NOT NULL DEFAULT 'Годен',
                    protocol_num TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT ''
                )
                """
            )
            # Индексы для быстрой фильтрации и сортировки
            conn.execute("CREATE INDEX IF NOT EXISTS idx_equipment_sort ON equipment(sort_order, id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_equipment_cat ON equipment(category)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_equipment_repair ON equipment(in_repair)")

            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM equipment")
            row_count = int(cur.fetchone()[0] or 0)
            if row_count == 0:
                # Наполняем базу стандартными типовыми образцами оборудования депо РТПС
                now_str = dt.datetime.now().strftime("%d.%m.%Y %H:%M")
                initial_items = [
                    (
                        1, "Домкраты и гидрооборудование", "Домкрат гидравлический ДГ-50 (50 тн)", "Д-01",
                        "Участок РТПС (стойло 1)", "Мастер участка",
                        "Техническое освидетельствование (под нагрузкой)", "12",
                        "15.01.2026", "15.01.2027", 0, "Годен", "Акт № 12/исп",
                        "Грузоподъемность 50 тонн, проверен гидропресс", now_str
                    ),
                    (
                        2, "Домкраты и гидрооборудование", "Домкрат гидравлический ДГ-30 (30 тн)", "Д-02",
                        "Участок РТПС (стойло 2)", "Слесарь Бопхоев М. М.",
                        "Техническое освидетельствование (под нагрузкой)", "12",
                        "20.04.2026", "20.04.2027", 0, "Годен", "Акт № 45/исп",
                        "Грузоподъемность 30 тонн", now_str
                    ),
                    (
                        3, "Домкраты и гидрооборудование", "Домкрат реечный ДР-5 (5 тн)", "Д-05",
                        "Слесарное отделение", "Слесарь Тимин И. В.",
                        "Статическое испытание под нагрузкой", "12",
                        "10.12.2025", "10.12.2026", 0, "Годен", "Акт № 88/исп",
                        "Высота подъема 350 мм", now_str
                    ),
                    (
                        4, "Электроинструмент", "Угловая шлифмашина Bosch GWS 22-230", "Э-011",
                        "Слесарный верстак №2", "Слесарь Цюрко Г. В.",
                        "Проверка изоляции (мегомметром) и осмотр", "6",
                        "10.06.2026", "10.12.2026", 0, "Годен", "Протокол № 104",
                        "Сопротивление изоляции 4.5 МОм, круг 230 мм", now_str
                    ),
                    (
                        5, "Электроинструмент", "Перфоратор Makita HR2470", "Э-015",
                        "Инструментальная кладовая", "Кладовщик",
                        "Проверка изоляции (мегомметром) и осмотр", "6",
                        "15.05.2026", "15.11.2026", 0, "Годен", "Протокол № 92",
                        "Срок поверки наступает в текущем месяце", now_str
                    ),
                    (
                        6, "Электроинструмент", "Дрель ударная Интерскол ДУ-16/1050ЭР", "Э-024",
                        "Слесарный верстак №1", "Слесарь Бопхоев М. М.",
                        "Проверка изоляции (мегомметром) и осмотр", "6",
                        "05.02.2026", "05.08.2026", 0, "Годен", "Протокол № 18",
                        "Требуется периодическая проверка изоляции", now_str
                    ),
                    (
                        7, "Пневмоинструмент", "Гайковерт ударный пневматический 1/2\" JAI-1054", "П-004",
                        "Участок РТПС (стойло 1)", "Слесарь Цюрко Г. В.",
                        "Осмотр и проверка на холостом ходу", "6",
                        "18.06.2026", "18.12.2026", 0, "Годен", "Акт № 63",
                        "Рабочее давление 6.3 бар", now_str
                    ),
                    (
                        8, "Грузоподъемные механизмы и стропы", "Таль ручная шестеренная ТРШС-3.2", "ГПМ-01",
                        "Тележечное отделение", "Мастер участка",
                        "Техническое освидетельствование (под нагрузкой)", "12",
                        "25.03.2026", "25.03.2027", 0, "Годен", "Акт ТО-14",
                        "Грузоподъемность 3.2 тонны, цепь проверена", now_str
                    ),
                    (
                        9, "Грузоподъемные механизмы и стропы", "Строп канатный 4СК-5.0/2000", "СТР-03",
                        "Стойло 1", "Стропальщик",
                        "Периодический осмотр и статическое испытание", "6",
                        "12.04.2026", "12.10.2026", 0, "Годен", "Бирка № 44",
                        "Грузоподъемность 5 тонн", now_str
                    ),
                    (
                        10, "Лестницы и стремянки", "Стремянка алюминиевая 7 ступеней (2.0 м)", "Л-01",
                        "Участок РТПС", "Мастер участка",
                        "Статическое испытание ступеней под нагрузкой", "12",
                        "14.02.2026", "14.02.2027", 0, "Годен", "Бирка Л-01",
                        "Ступени испытаны грузом 120 кгс", now_str
                    ),
                    (
                        11, "Лестницы и стремянки", "Лестница приставная деревянная (3.0 м)", "Л-04",
                        "Склад запасных частей", "Кладовщик",
                        "Статическое испытание ступеней под нагрузкой", "6",
                        "01.03.2026", "01.09.2026", 0, "Годен", "Бирка Л-04",
                        "Испытание ступеней 120 кгс в течение 2 мин", now_str
                    ),
                    (
                        12, "Диэлектрические средства защиты", "Перчатки диэлектрические бесшовные", "СЗ-01",
                        "Шкаф средств защиты", "Ответственный за электрохозяйство",
                        "Испытание повышенным напряжением", "6",
                        "20.06.2026", "20.12.2026", 0, "Годен", "Штамп испытаний",
                        "Испытаны 6 кВ, ток утечки в норме", now_str
                    ),
                    (
                        13, "Диэлектрические средства защиты", "Боты диэлектрические резиновые", "СЗ-03",
                        "Шкаф средств защиты", "Ответственный за электрохозяйство",
                        "Испытание повышенным напряжением", "36",
                        "15.01.2025", "15.01.2028", 0, "Годен", "Штамп испытаний",
                        "Испытаны 15 кВ", now_str
                    ),
                    (
                        14, "Сварочное оборудование", "Сварочный выпрямитель ВД-306", "СВ-02",
                        "Сварочный пост", "Электросварщик",
                        "Проверка сопротивления изоляции", "6",
                        "10.05.2026", "10.11.2026", 1, "Требует ремонта", "Дефектная ведомость №3",
                        "В ремонте: замена силового кабеля и держателя", now_str
                    ),
                ]
                conn.executemany(
                    """
                    INSERT INTO equipment (
                        sort_order, category, name, inv_number, location, responsible,
                        test_type, periodicity, last_test_date, next_test_date,
                        in_repair, test_result, protocol_num, notes, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    initial_items,
                )


def load_equipment_from_db() -> list[dict]:
    """Загрузка полного списка оборудования из базы данных с упорядочиванием по sort_order."""
    with conn_ctx() as conn:
        rows = conn.execute(
            """
            SELECT id, sort_order, category, name, inv_number, location, responsible,
                   test_type, periodicity, last_test_date, next_test_date,
                   in_repair, test_result, protocol_num, notes, updated_at
            FROM equipment
            ORDER BY sort_order ASC, id ASC
            """
        ).fetchall()
        return [dict(r) for r in rows]


def save_equipment_to_db(items: list[dict]) -> None:
    """Атомарная перезапись списка оборудования в SQLite в транзакции."""
    normalized = [normalize_equipment_item(item, idx) for idx, item in enumerate(items)]
    now_str = dt.datetime.now().strftime("%d.%m.%Y %H:%M")

    with DB_LOCK, conn_ctx() as conn:
        with conn:
            conn.execute("DELETE FROM equipment")
            for idx, item in enumerate(normalized):
                conn.execute(
                    """
                    INSERT INTO equipment (
                        sort_order, category, name, inv_number, location, responsible,
                        test_type, periodicity, last_test_date, next_test_date,
                        in_repair, test_result, protocol_num, notes, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        idx + 1,
                        item["category"],
                        item["name"],
                        item["inv_number"],
                        item["location"],
                        item["responsible"],
                        item["test_type"],
                        item["periodicity"],
                        item["last_test_date"],
                        item["next_test_date"],
                        item["in_repair"],
                        item["test_result"],
                        item["protocol_num"],
                        item["notes"],
                        item["updated_at"] or now_str,
                    ),
                )
