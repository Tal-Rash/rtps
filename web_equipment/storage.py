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


def calculate_next_jack_date(test_date_str: str) -> str:
    """
    Вычисляет дату следующего технического освидетельствования домкрата.
    По регламенту периодичность испытания домкратов составляет 1 раз в 12 месяцев (1 год).
    """
    d = parse_date_safe(test_date_str)
    if not d:
        return ""
    next_d = add_months_to_date(d, 12)
    return next_d.strftime("%d.%m.%Y")


def normalize_jack_item(item: dict, idx: int = 0) -> dict:
    """Нормализация структуры записи журнала домкратов по официальной форме."""
    name = str(item.get("name") or "").strip()
    inv_number = str(item.get("inv_number") or "").strip()
    capacity = str(item.get("capacity") or "").strip()
    prev_test_date = str(item.get("prev_test_date") or "").strip()
    test_reason = str(item.get("test_reason") or "очередное").strip()
    repair_info = str(item.get("repair_info") or "").strip()
    inspection_result = str(item.get("inspection_result") or "удовл.").strip()
    static_test_result = str(item.get("static_test_result") or "удовл.").strip()
    dynamic_test_result = str(item.get("dynamic_test_result") or "удовл.").strip()
    test_date = str(item.get("test_date") or "").strip()
    next_test_date = str(item.get("next_test_date") or "").strip()

    # Автоматический расчет следующего освидетельствования (через 1 год)
    if not next_test_date and test_date:
        next_test_date = calculate_next_jack_date(test_date)

    inspector = str(item.get("inspector") or "Шварчков С. А.").strip()
    raw_repair = item.get("in_repair", 0)
    in_repair = 1 if raw_repair in (1, "1", True, "true", "True", "Да", "да", "В ремонте") else 0
    notes = str(item.get("notes") or "").strip()
    updated_at = str(item.get("updated_at") or "").strip()
    sort_order = int(item.get("sort_order") or (idx + 1))

    return {
        "id": item.get("id"),
        "sort_order": sort_order,
        "name": name,
        "inv_number": inv_number,
        "capacity": capacity,
        "prev_test_date": prev_test_date,
        "test_reason": test_reason,
        "repair_info": repair_info,
        "inspection_result": inspection_result,
        "static_test_result": static_test_result,
        "dynamic_test_result": dynamic_test_result,
        "test_date": test_date,
        "next_test_date": next_test_date,
        "inspector": inspector,
        "in_repair": in_repair,
        "notes": notes,
        "updated_at": updated_at,
    }


def normalize_tool_item(item: dict, idx: int = 0) -> dict:
    """Нормализация структуры записи инструмента и прочего оборудования."""
    name = str(item.get("name") or "").strip()
    inv_number = str(item.get("inv_number") or "").strip()
    category = str(item.get("category") or "Электроинструмент").strip()
    location = str(item.get("location") or "Участок РТПС").strip()
    responsible = str(item.get("responsible") or "").strip()
    test_type = str(item.get("test_type") or "Проверка изоляции (мегомметром)").strip()
    periodicity = str(item.get("periodicity") or "6").strip()
    last_test_date = str(item.get("last_test_date") or "").strip()
    next_test_date = str(item.get("next_test_date") or "").strip()

    if not next_test_date and last_test_date:
        try:
            p = int(periodicity)
        except ValueError:
            p = 6
        last_d = parse_date_safe(last_test_date)
        if last_d:
            next_test_date = add_months_to_date(last_d, p).strftime("%d.%m.%Y")

    raw_repair = item.get("in_repair", 0)
    in_repair = 1 if raw_repair in (1, "1", True, "true", "True", "Да", "да", "В ремонте") else 0
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
    """Инициализация таблиц базы данных оборудования и первичное наполнение записями журнала домкратов."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with DB_LOCK, conn_ctx() as conn:
        with conn:
            # 1. Таблица домкратов (по официальному журналу «ДОМКРАТЫ»)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jacks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    name TEXT NOT NULL DEFAULT '',
                    inv_number TEXT NOT NULL DEFAULT '',
                    capacity TEXT NOT NULL DEFAULT '',
                    prev_test_date TEXT NOT NULL DEFAULT '',
                    test_reason TEXT NOT NULL DEFAULT 'очередное',
                    repair_info TEXT NOT NULL DEFAULT '',
                    inspection_result TEXT NOT NULL DEFAULT 'удовл.',
                    static_test_result TEXT NOT NULL DEFAULT 'удовл.',
                    dynamic_test_result TEXT NOT NULL DEFAULT 'удовл.',
                    test_date TEXT NOT NULL DEFAULT '',
                    next_test_date TEXT NOT NULL DEFAULT '',
                    inspector TEXT NOT NULL DEFAULT 'Шварчков С. А.',
                    in_repair INTEGER NOT NULL DEFAULT 0,
                    notes TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jacks_sort ON jacks(sort_order, id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_jacks_repair ON jacks(in_repair)")

            # 2. Таблица электроинструмента и прочего оборудования
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tools (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    category TEXT NOT NULL DEFAULT 'Электроинструмент',
                    name TEXT NOT NULL DEFAULT '',
                    inv_number TEXT NOT NULL DEFAULT '',
                    location TEXT NOT NULL DEFAULT '',
                    responsible TEXT NOT NULL DEFAULT '',
                    test_type TEXT NOT NULL DEFAULT '',
                    periodicity TEXT NOT NULL DEFAULT '6',
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
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tools_sort ON tools(sort_order, id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tools_repair ON tools(in_repair)")

            # Проверяем наполнение таблицы домкратов
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM jacks")
            jacks_count = int(cur.fetchone()[0] or 0)
            now_str = dt.datetime.now().strftime("%d.%m.%Y %H:%M")

            if jacks_count == 0:
                # Первичные записи домкратов по образцу из реального журнала
                initial_jacks = [
                    (
                        1, "УДС-160(1)", "14123", "40", "21.03.2024", "очередное", "",
                        "удовл.", "удовл.", "удовл.", "21.03.2025", "21.03.2026",
                        "Шварчков С. А.", 0, "Стойка домкратная №1 установки УДС-160", now_str
                    ),
                    (
                        2, "УДС-160(2)", "14128", "40", "21.03.2024", "очередное", "",
                        "удовл.", "удовл.", "удовл.", "21.03.2025", "21.03.2026",
                        "Шварчков С. А.", 0, "Стойка домкратная №2 установки УДС-160", now_str
                    ),
                    (
                        3, "УДС-160(3)", "14129", "40", "21.03.2024", "очередное", "",
                        "удовл.", "удовл.", "удовл.", "21.03.2025", "21.03.2026",
                        "Шварчков С. А.", 0, "Стойка домкратная №3 установки УДС-160", now_str
                    ),
                    (
                        4, "УДС-160(4)", "14130", "40", "21.03.2024", "очередное", "",
                        "удовл.", "удовл.", "удовл.", "21.03.2025", "21.03.2026",
                        "Шварчков С. А.", 0, "Стойка домкратная №4 установки УДС-160", now_str
                    ),
                    (
                        5, "Домкрат гидравлический ДГ-50", "1024", "50", "15.01.2025", "очередное", "",
                        "удовл.", "удовл.", "удовл.", "15.01.2026", "15.01.2027",
                        "Шварчков С. А.", 0, "Проверен гидропресс, стойло 1", now_str
                    ),
                    (
                        6, "Домкрат реечный ДР-5", "1025", "5", "10.12.2024", "очередное", "",
                        "удовл.", "удовл.", "удовл.", "10.12.2025", "10.12.2026",
                        "Шварчков С. А.", 0, "Слесарное отделение", now_str
                    ),
                ]
                conn.executemany(
                    """
                    INSERT INTO jacks (
                        sort_order, name, inv_number, capacity, prev_test_date,
                        test_reason, repair_info, inspection_result, static_test_result,
                        dynamic_test_result, test_date, next_test_date, inspector,
                        in_repair, notes, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    initial_jacks,
                )

            # Проверяем наполнение таблицы инструмента
            cur.execute("SELECT COUNT(*) FROM tools")
            tools_count = int(cur.fetchone()[0] or 0)
            if tools_count == 0:
                initial_tools = [
                    (
                        1, "Электроинструмент", "Угловая шлифмашина Bosch GWS 22-230", "Э-011",
                        "Слесарный верстак №2", "Слесарь Цюрко Г. В.",
                        "Проверка изоляции (мегомметром) и осмотр", "6",
                        "10.06.2026", "10.12.2026", 0, "Годен", "Протокол № 104",
                        "Сопротивление изоляции 4.5 МОм, круг 230 мм", now_str
                    ),
                    (
                        2, "Электроинструмент", "Перфоратор Makita HR2470", "Э-015",
                        "Инструментальная кладовая", "Кладовщик",
                        "Проверка изоляции (мегомметром) и осмотр", "6",
                        "15.05.2026", "15.11.2026", 0, "Годен", "Протокол № 92",
                        "Срок поверки наступает в текущем месяце", now_str
                    ),
                    (
                        3, "Электроинструмент", "Дрель ударная Интерскол ДУ-16/1050ЭР", "Э-024",
                        "Слесарный верстак №1", "Слесарь Бопхоев М. М.",
                        "Проверка изоляции (мегомметром) и осмотр", "6",
                        "05.02.2026", "05.08.2026", 0, "Годен", "Протокол № 18",
                        "Требуется периодическая проверка изоляции", now_str
                    ),
                    (
                        4, "Пневмоинструмент", "Гайковерт ударный пневматический 1/2\" JAI-1054", "П-004",
                        "Участок РТПС (стойло 1)", "Слесарь Цюрко Г. В.",
                        "Осмотр и проверка на холостом ходу", "6",
                        "18.06.2026", "18.12.2026", 0, "Годен", "Акт № 63",
                        "Рабочее давление 6.3 бар", now_str
                    ),
                    (
                        5, "Грузоподъемные механизмы и стропы", "Таль ручная шестеренная ТРШС-3.2", "ГПМ-01",
                        "Тележечное отделение", "Мастер участка",
                        "Техническое освидетельствование (под нагрузкой)", "12",
                        "25.03.2026", "25.03.2027", 0, "Годен", "Акт ТО-14",
                        "Грузоподъемность 3.2 тонны, цепь проверена", now_str
                    ),
                    (
                        6, "Лестницы и стремянки", "Стремянка алюминиевая 7 ступеней (2.0 м)", "Л-01",
                        "Участок РТПС", "Мастер участка",
                        "Статическое испытание ступеней под нагрузкой", "12",
                        "14.02.2026", "14.02.2027", 0, "Годен", "Бирка Л-01",
                        "Ступени испытаны грузом 120 кгс", now_str
                    ),
                    (
                        7, "Диэлектрические средства защиты", "Перчатки диэлектрические бесшовные", "СЗ-01",
                        "Шкаф средств защиты", "Ответственный за электрохозяйство",
                        "Испытание повышенным напряжением", "6",
                        "20.06.2026", "20.12.2026", 0, "Годен", "Штамп испытаний",
                        "Испытаны 6 кВ, ток утечки в норме", now_str
                    ),
                    (
                        8, "Сварочное оборудование", "Сварочный выпрямитель ВД-306", "СВ-02",
                        "Сварочный пост", "Электросварщик",
                        "Проверка сопротивления изоляции", "6",
                        "10.05.2026", "10.11.2026", 1, "Требует ремонта", "Дефектная ведомость №3",
                        "В ремонте: замена силового кабеля и держателя", now_str
                    ),
                ]
                conn.executemany(
                    """
                    INSERT INTO tools (
                        sort_order, category, name, inv_number, location, responsible,
                        test_type, periodicity, last_test_date, next_test_date,
                        in_repair, test_result, protocol_num, notes, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    initial_tools,
                )


def load_jacks_from_db() -> list[dict]:
    """Загрузка полного списка домкратов из базы данных с сортировкой."""
    with conn_ctx() as conn:
        rows = conn.execute(
            """
            SELECT id, sort_order, name, inv_number, capacity, prev_test_date,
                   test_reason, repair_info, inspection_result, static_test_result,
                   dynamic_test_result, test_date, next_test_date, inspector,
                   in_repair, notes, updated_at
            FROM jacks
            ORDER BY sort_order ASC, id ASC
            """
        ).fetchall()
        return [dict(r) for r in rows]


def save_jacks_to_db(items: list[dict]) -> None:
    """Атомарное сохранение списка домкратов в SQLite."""
    normalized = [normalize_jack_item(item, idx) for idx, item in enumerate(items)]
    now_str = dt.datetime.now().strftime("%d.%m.%Y %H:%M")

    with DB_LOCK, conn_ctx() as conn:
        with conn:
            conn.execute("DELETE FROM jacks")
            for idx, item in enumerate(normalized):
                conn.execute(
                    """
                    INSERT INTO jacks (
                        sort_order, name, inv_number, capacity, prev_test_date,
                        test_reason, repair_info, inspection_result, static_test_result,
                        dynamic_test_result, test_date, next_test_date, inspector,
                        in_repair, notes, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        idx + 1,
                        item["name"],
                        item["inv_number"],
                        item["capacity"],
                        item["prev_test_date"],
                        item["test_reason"],
                        item["repair_info"],
                        item["inspection_result"],
                        item["static_test_result"],
                        item["dynamic_test_result"],
                        item["test_date"],
                        item["next_test_date"],
                        item["inspector"],
                        item["in_repair"],
                        item["notes"],
                        item["updated_at"] or now_str,
                    ),
                )


def load_tools_from_db() -> list[dict]:
    """Загрузка полного списка инструмента и прочего оборудования."""
    with conn_ctx() as conn:
        rows = conn.execute(
            """
            SELECT id, sort_order, category, name, inv_number, location, responsible,
                   test_type, periodicity, last_test_date, next_test_date,
                   in_repair, test_result, protocol_num, notes, updated_at
            FROM tools
            ORDER BY sort_order ASC, id ASC
            """
        ).fetchall()
        return [dict(r) for r in rows]


def save_tools_to_db(items: list[dict]) -> None:
    """Атомарное сохранение списка инструмента в SQLite."""
    normalized = [normalize_tool_item(item, idx) for idx, item in enumerate(items)]
    now_str = dt.datetime.now().strftime("%d.%m.%Y %H:%M")

    with DB_LOCK, conn_ctx() as conn:
        with conn:
            conn.execute("DELETE FROM tools")
            for idx, item in enumerate(normalized):
                conn.execute(
                    """
                    INSERT INTO tools (
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
