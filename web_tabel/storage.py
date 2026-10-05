from __future__ import annotations

import datetime as dt
import sqlite3
from contextlib import contextmanager
from typing import Generator

import sys
from pathlib import Path

# Обеспечиваем доступность путей модуля и корня проекта для импортов
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_ROOT.parent))

# Импорт констант и системных утилит
try:
    from .constants import (
        DB_FILE,
        DB_LOCK,
        MONTH_NAMES,
        ROOT,
    )
except (ImportError, ValueError):
    from constants import (
        DB_FILE,
        DB_LOCK,
        MONTH_NAMES,
        ROOT,
    )

from rtps_common import connect_sqlite

# Базовые праздничные дни РФ
FIXED_HOLIDAYS = {
    (1, 1), (1, 2), (1, 3), (1, 4), (1, 5), (1, 6), (1, 7), (1, 8),
    (2, 23), (3, 8), (5, 1), (5, 9), (6, 12), (11, 4),
}


@contextmanager
def conn() -> Generator[sqlite3.Connection, None, None]:
    """Безопасный контекстный менеджер соединения SQLite с гарантированным закрытием."""
    connection = connect_sqlite(DB_FILE)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


def text(value) -> str:
    """Безопасное приведение значения к строке."""
    return "" if value is None else str(value)


def init_db() -> None:
    """Инициализация таблиц базы данных и выполнение миграций структуры."""
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    with conn() as connection:
        cur = connection.cursor()
        with connection:
            cur.execute("CREATE TABLE IF NOT EXISTS month_hints (y INT, m TEXT, hint TEXT, PRIMARY KEY(y,m))")

            # Добавляем колонку is_excluded в таблицу сотрудников при необходимости
            cur.execute("PRAGMA table_info('employees')")
            emp_cols = [c["name"] for c in cur.fetchall()]
            if "is_excluded" not in emp_cols:
                cur.execute("ALTER TABLE employees ADD COLUMN is_excluded INT DEFAULT 0")

            # Проверяем необходимость миграции табелей и отпусков со старой структуры (r -> tab_num)
            cur.execute("PRAGMA table_info('timesheet')")
            cols = [c["name"] for c in cur.fetchall()]
            if "tab_num" not in cols and "r" in cols:
                print("Автомиграция табеля и отпусков на tab_num...")
                years = cur.execute("SELECT DISTINCT y FROM employees").fetchall()
                for y_row in years:
                    year = y_row["y"]

                    # 1. Миграция табеля
                    ts_rows = cur.execute("SELECT m, r, c, v FROM timesheet WHERE y=?", (year,)).fetchall()
                    ts_r_to_tab = {}
                    for row in ts_rows:
                        if row["c"] == 3 and len(str(row["v"])) > 3:
                            ts_r_to_tab[(row["m"], row["r"])] = str(row["v"])

                    cur.execute(
                        "CREATE TABLE IF NOT EXISTS timesheet_new (y INT, m TEXT, tab_num TEXT, c INT, v TEXT, PRIMARY KEY(y,m,tab_num,c))"
                    )
                    for row in ts_rows:
                        m = row["m"]
                        r = row["r"]
                        c = row["c"]
                        v = row["v"]
                        if c >= 4:
                            tab_num = ts_r_to_tab.get((m, r))
                            if tab_num:
                                cur.execute(
                                    "INSERT OR REPLACE INTO timesheet_new (y, m, tab_num, c, v) VALUES (?, ?, ?, ?, ?)",
                                    (year, m, tab_num, c - 3, v),
                                )

                    # 2. Миграция отпусков
                    vac_rows = cur.execute("SELECT r, c, v FROM vacations WHERE y=?", (year,)).fetchall()
                    vac_r_to_tab = {}
                    for row in vac_rows:
                        if row["c"] == 0 and len(str(row["v"])) > 3:
                            vac_r_to_tab[row["r"]] = str(row["v"])

                    cur.execute(
                        "CREATE TABLE IF NOT EXISTS vacations_new (y INT, tab_num TEXT, c INT, v TEXT, PRIMARY KEY(y,tab_num,c))"
                    )
                    for row in vac_rows:
                        r = row["r"]
                        c = row["c"]
                        v = row["v"]
                        if c >= 1:
                            tab_num = vac_r_to_tab.get(r)
                            if tab_num:
                                cur.execute(
                                    "INSERT OR REPLACE INTO vacations_new (y, tab_num, c, v) VALUES (?, ?, ?, ?)",
                                    (year, tab_num, c - 1, v),
                                )

                cur.execute("DROP TABLE IF EXISTS timesheet")
                cur.execute("ALTER TABLE timesheet_new RENAME TO timesheet")
                cur.execute("DROP TABLE IF EXISTS vacations")
                cur.execute("ALTER TABLE vacations_new RENAME TO vacations")


def load_system_dates(year: int) -> dict[str, list[tuple[int, int]]]:
    """Загрузка производственного календаря: праздничные и перенесенные рабочие дни."""
    transfer_dates: set[tuple[int, int]] = set()
    holiday_dates: set[tuple[int, int]] = set(FIXED_HOLIDAYS)
    if not DB_FILE.exists():
        return {
            "transfer": sorted(transfer_dates),
            "holiday": sorted(holiday_dates),
        }

    try:
        with conn() as connection:
            cur = connection.cursor()
            rows = cur.execute(
                "SELECT c, v FROM ts_norms_data WHERE y=? AND c IN (6, 7)",
                (year,),
            ).fetchall()
            for col_idx, raw_text in rows:
                if not raw_text:
                    continue
                parsed_text = str(raw_text).replace(";", "\n").replace(",", "\n")
                for line in parsed_text.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split(".")
                    if len(parts) >= 2:
                        try:
                            d, m = int(parts[0]), int(parts[1])
                            if col_idx == 6:
                                transfer_dates.add((m, d))
                            elif col_idx == 7:
                                holiday_dates.add((m, d))
                        except ValueError:
                            pass
    except Exception:
        pass

    return {
        "transfer": sorted(transfer_dates),
        "holiday": sorted(holiday_dates),
    }


def load_state(year: int, month: int) -> dict:
    """Загрузка полного состояния табеля за указанный год и месяц."""
    with DB_LOCK, conn() as connection:
        cur = connection.cursor()

        # Автоматическая миграция дополнительных колонок
        try:
            cur.execute("SELECT exclude_date FROM employees LIMIT 1")
        except sqlite3.OperationalError:
            try:
                cur.execute("ALTER TABLE employees ADD COLUMN exclude_date TEXT DEFAULT ''")
                connection.commit()
            except Exception:
                pass
            try:
                cur.execute("ALTER TABLE employees ADD COLUMN hire_date TEXT DEFAULT ''")
                connection.commit()
            except Exception:
                pass

        employees = []
        try:
            emp_rows = cur.execute(
                "SELECT pos, name, tab_num, milk, milk_issue, full_name, milk_note, is_excluded, hire_date, exclude_date FROM employees WHERE y=? ORDER BY rowid",
                (year,),
            ).fetchall()
            for idx, r in enumerate(emp_rows, start=1):
                raw_tab = text(r["tab_num"])
                num_part = idx
                if raw_tab.startswith("ID_"):
                    digits = "".join(ch for ch in raw_tab if ch.isdigit())
                    if digits:
                        num_part = int(digits)

                anon_id = f"ID_{num_part:03d}"
                anon_short = f"Работник №{num_part}"
                anon_full = f"СотрудникПолн №{num_part}"
                anon_pos = f"Должность №{num_part}"

                employees.append(
                    {
                        "pos": anon_pos,
                        "name": anon_short,
                        "tab_num": anon_id,
                        "milk": int(r["milk"] or 0),
                        "milk_issue": int(r["milk_issue"] or 0),
                        "full_name": anon_full,
                        "milk_note": text(r["milk_note"]),
                        "is_excluded": int(dict(r).get("is_excluded", 0) or 0),
                        "hire_date": text(dict(r).get("hire_date", "")),
                        "exclude_date": text(dict(r).get("exclude_date", "")),
                    }
                )
        except Exception:
            pass

        timesheet = {}
        try:
            m_str = MONTH_NAMES[month] if 1 <= month <= 12 else str(month)
            ts_rows = cur.execute(
                "SELECT tab_num, c, v FROM timesheet WHERE y=? AND m=?",
                (year, m_str),
            ).fetchall()
            for r in ts_rows:
                timesheet.setdefault(text(r["tab_num"]), {})[int(r["c"])] = text(r["v"])
        except Exception:
            pass

        vacations = {}
        try:
            vac_rows = cur.execute("SELECT tab_num, c, v FROM vacations WHERE y=?", (year,)).fetchall()
            for r in vac_rows:
                vacations.setdefault(text(r["tab_num"]), {})[int(r["c"])] = text(r["v"])
        except Exception:
            pass

        ts_norms_data = {}
        try:
            norms_rows = cur.execute("SELECT r, c, v FROM ts_norms_data WHERE y=?", (year,)).fetchall()
            for r in norms_rows:
                ts_norms_data.setdefault(int(r["r"]), {})[int(r["c"])] = text(r["v"])
        except Exception:
            pass

        month_hint = ""
        try:
            hint_row = cur.execute("SELECT v FROM ts_settings WHERE k='month_hint'").fetchone()
            if hint_row:
                month_hint = str(hint_row["v"])
        except Exception:
            pass

    return {
        "system_dates": load_system_dates(year),
        "year": year,
        "month": month,
        "employees": employees,
        "timesheet": timesheet,
        "vacations": vacations,
        "ts_norms_data": ts_norms_data,
        "month_hint": month_hint,
    }


def save_state(payload: dict) -> dict:
    """Сохранение состояния табеля, сотрудников, отпусков и норм в базу данных."""
    year = int(payload.get("year", dt.date.today().year))
    month = int(payload.get("month", dt.date.today().month))
    timesheet = payload.get("timesheet")
    employees = payload.get("employees")
    vacations = payload.get("vacations")
    ts_norms_data = payload.get("ts_norms_data")
    month_hint = payload.get("month_hint")

    with DB_LOCK, conn() as connection:
        cur = connection.cursor()
        with connection:
            if timesheet is not None:
                m_str = MONTH_NAMES[month] if 1 <= month <= 12 else str(month)
                cur.execute("DELETE FROM timesheet WHERE y=? AND m=?", (year, m_str))
                insert_ts = []
                if isinstance(timesheet, dict):
                    for tab_num, row_data in timesheet.items():
                        if not row_data:
                            continue
                        for c, v in row_data.items():
                            if v:
                                insert_ts.append((year, m_str, str(tab_num), int(c), str(v)))
                cur.executemany("INSERT INTO timesheet(y, m, tab_num, c, v) VALUES(?,?,?,?,?)", insert_ts)

            if employees is not None:
                cur.execute("DELETE FROM employees WHERE y=?", (year,))
                insert_emp = []
                for emp in employees:
                    insert_emp.append(
                        (
                            year,
                            emp.get("pos", ""),
                            emp.get("name", ""),
                            emp.get("tab_num", ""),
                            emp.get("milk", 0),
                            emp.get("milk_issue", 0),
                            emp.get("full_name", ""),
                            emp.get("milk_note", ""),
                            emp.get("hire_date", ""),
                            emp.get("exclude_date", ""),
                        )
                    )
                cur.executemany(
                    "INSERT INTO employees(y, pos, name, tab_num, milk, milk_issue, full_name, milk_note, hire_date, exclude_date) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    insert_emp,
                )

            if vacations is not None:
                cur.execute("DELETE FROM vacations WHERE y=?", (year,))
                insert_vac = []
                if isinstance(vacations, dict):
                    for tab_num, row_data in vacations.items():
                        if not row_data:
                            continue
                        for c, v in row_data.items():
                            if v:
                                insert_vac.append((year, str(tab_num), int(c), str(v)))
                cur.executemany("INSERT INTO vacations(y, tab_num, c, v) VALUES(?,?,?,?)", insert_vac)

            if ts_norms_data is not None:
                cur.execute("DELETE FROM ts_norms_data WHERE y=?", (year,))
                insert_norms = []
                if isinstance(ts_norms_data, (dict, list)):
                    items = ts_norms_data.items() if isinstance(ts_norms_data, dict) else enumerate(ts_norms_data)
                    for r_idx, row_data in items:
                        if not row_data:
                            continue
                        for c, v in row_data.items():
                            if v:
                                insert_norms.append((year, int(r_idx), int(c), str(v)))
                cur.executemany("INSERT INTO ts_norms_data(y, r, c, v) VALUES(?,?,?,?)", insert_norms)

            if month_hint is not None:
                cur.execute("INSERT OR REPLACE INTO ts_settings (k, v) VALUES ('month_hint', ?)", (str(month_hint),))

    return {"status": "ok"}
