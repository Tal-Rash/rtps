from __future__ import annotations

import calendar
import datetime as dt
import json
import shutil
import sqlite3
from pathlib import Path
from threading import RLock

from rtps_common import connect_sqlite
try:
    from .constants import (
        DATA_DIR,
        DB_FILE,
        SOURCE_DB,
        MONTHS_RU,
        TEM_NORM_ROWS,
        AGR_NORM_ROWS,
        TRANSFER_HOLIDAYS_BY_YEAR,
        FIXED_HOLIDAYS,
    )
    from .calculations import (
        s,
        normalize_repair_code,
        compute_repair_schedule_derived,
        default_repair_schedule_state,
    )
except (ImportError, ValueError):
    from constants import (
        DATA_DIR,
        DB_FILE,
        SOURCE_DB,
        MONTHS_RU,
        TEM_NORM_ROWS,
        AGR_NORM_ROWS,
        TRANSFER_HOLIDAYS_BY_YEAR,
        FIXED_HOLIDAYS,
    )
    from calculations import (
        s,
        normalize_repair_code,
        compute_repair_schedule_derived,
        default_repair_schedule_state,
    )

# Глобальная блокировка для безопасных транзакций в базе данных
DB_LOCK = RLock()

def ensure_database() -> None:
    # Инициализация рабочей базы данных и создание схемы при старте
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not DB_FILE.exists() and SOURCE_DB.exists():
        shutil.copy2(SOURCE_DB, DB_FILE)
    with connect_sqlite(DB_FILE) as db:
        ensure_schema(db.cursor())
        db.commit()


def conn() -> sqlite3.Connection:
    # Возвращаем настроенное подключение SQLite (WAL-режим, таймаут ожидания)
    return connect_sqlite(DB_FILE)


def ensure_schema(cur: sqlite3.Cursor) -> None:
    cur.execute("CREATE TABLE IF NOT EXISTS repairs (y INT, m TEXT, t TEXT, r INT, c INT, v TEXT, PRIMARY KEY(y,m,t,r,c))")
    cur.execute("CREATE TABLE IF NOT EXISTS norms (y INT, cat TEXT, k TEXT, v TEXT, PRIMARY KEY(y,cat,k))")
    cur.execute("CREATE TABLE IF NOT EXISTS inventory (y INT, ser TEXT, num TEXT, inv TEXT, PRIMARY KEY(y,ser,num))")
    cur.execute("CREATE TABLE IF NOT EXISTS repair_settings (k TEXT PRIMARY KEY, v TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS acts_state (y INT, m TEXT, act_num TEXT, is_done INT, sap_order_done INT DEFAULT 0, PRIMARY KEY(y, m, act_num))")
    cur.execute("CREATE TABLE IF NOT EXISTS report_notes (y INT, m TEXT, k TEXT, v TEXT, PRIMARY KEY(y,m,k))")
    cur.execute("CREATE TABLE IF NOT EXISTS tu28_data (y INT, m TEXT, r INT, k TEXT, v TEXT, PRIMARY KEY(y,m,r,k))")
    cur.execute("CREATE TABLE IF NOT EXISTS repair_schedule (y INT, r INT, k TEXT, v TEXT, PRIMARY KEY(y,r,k))")


def load_system_dates(year: int) -> dict[str, list[tuple[int, int]]]:
    transfer_dates: set[tuple[int, int]] = set(TRANSFER_HOLIDAYS_BY_YEAR.get(year, set()))
    holiday_dates: set[tuple[int, int]] = set(FIXED_HOLIDAYS)
    if not SOURCE_DB.exists():
        return {
            "transfer": sorted(transfer_dates),
            "holiday": sorted(holiday_dates),
        }

    try:
        with connect_sqlite(SOURCE_DB) as conn:
            cur = conn.cursor()
            rows = cur.execute(
                "SELECT c, v FROM ts_norms_data WHERE y=? AND c IN (6, 7)",
                (year,),
            ).fetchall()
        for col_idx, raw_text in rows:
            if not raw_text:
                continue
            text = str(raw_text).replace(";", "\n").replace(",", "\n")
            for line in text.splitlines():
                parts = line.strip().split(".")
                if len(parts) < 2:
                    continue
                try:
                    day = int(parts[0])
                    month = int(parts[1])
                except ValueError:
                    continue
                if col_idx == 6:
                    transfer_dates.add((month, day))
                else:
                    holiday_dates.add((month, day))
    except Exception:
        pass

    return {
        "transfer": sorted(transfer_dates),
        "holiday": sorted(holiday_dates),
    }


def default_state(year: int) -> dict:
    months = []
    for month_num, month_name in enumerate(MONTHS_RU, 1):
        days = calendar.monthrange(year, month_num)[1]
        months.append(
            {
                "name": month_name,
                "month": month_num,
                "days": days,
                "plan": _default_table_rows(year, month_num, "plan"),
                "fact": _default_table_rows(year, month_num, "fact"),
            }
        )

    norms = {
        "h_tep": [{"k": label, "v": ""} for label in TEM_NORM_ROWS],
        "h_agr": [{"k": label, "v": ""} for label in AGR_NORM_ROWS],
        "p_tep": [{"k": MONTHS_RU[i], "v": ""} for i in range(12)],
        "p_agr": [{"k": MONTHS_RU[i], "v": ""} for i in range(12)],
    }
    inventory = []
    acts = {}
    notes = {}
    return {
        "year": year,
        "system_dates": load_system_dates(year),
        "months": months,
        "norms": norms,
        "acts": acts,
        "notes": notes,
        "repair_schedule": default_repair_schedule_state(),
        "repair_schedule_year": year,
    }


def load_repair_schedule_for_year(cur: sqlite3.Cursor, year: int) -> dict:
    schedule_rows = cur.execute("SELECT r, k, v FROM repair_schedule WHERE y=? ORDER BY r, k", (year,)).fetchall()
    schedule = default_repair_schedule_state()
    columns = schedule["columns"]
    objects: dict[int, dict[str, dict[int, str] | dict[str, str] | str]] = {}
    for row in schedule_rows:
        idx = int(row["r"])
        key = s(row["k"])
        value = s(row["v"])
        if idx == -1 and key.startswith("col_"):
            try:
                cidx = int(key[4:])
            except ValueError:
                continue
            if 0 <= cidx < len(columns) and value:
                columns[cidx]["code"] = normalize_repair_code(value)
            continue
        if idx >= 0 and key.startswith("periodicity_series_"):
            try:
                sidx = int(key.rsplit("_", 1)[1])
            except Exception:
                continue
            while len(schedule["periodicity"]["series"]) <= sidx:
                schedule["periodicity"]["series"].append("")
                schedule["periodicity"]["values"].append(["", "", "", "", ""])
            if 0 <= sidx < len(schedule["periodicity"]["series"]):
                schedule["periodicity"]["series"][sidx] = value
            continue
        if idx >= 0 and key.startswith("periodicity_value_"):
            try:
                _, _, r_str, c_str = key.split("_", 3)
                r_idx = int(r_str)
                c_idx = int(c_str)
            except Exception:
                continue
            while len(schedule["periodicity"]["values"]) <= r_idx:
                schedule["periodicity"]["series"].append("")
                schedule["periodicity"]["values"].append(["", "", "", "", ""])
            while len(schedule["periodicity"]["values"][r_idx]) <= c_idx:
                schedule["periodicity"]["values"][r_idx].append("")
            schedule["periodicity"]["values"][r_idx][c_idx] = value
            continue
        if idx < 0:
            continue
        obj = objects.setdefault(idx, {"series": "", "number": "", "plan": {}, "fact": {}})
        if key == "series":
            obj["series"] = value
        elif key == "number":
            obj["number"] = value
        elif key == "kr_plan":
            obj.setdefault("kr", {})["plan"] = value
        elif key == "kr_fact":
            obj.setdefault("kr", {})["fact"] = value
        elif key.startswith("plan_"):
            try:
                cidx = int(key[5:])
            except ValueError:
                continue
            obj["plan"][cidx] = value
        elif key.startswith("fact_"):
            try:
                cidx = int(key[5:])
            except ValueError:
                continue
            obj["fact"][cidx] = value
    schedule["columns"] = columns
    schedule["objects"] = []
    for idx in sorted(objects):
        obj = objects[idx]
        schedule["objects"].append({
            "series": s(obj["series"]),
            "number": s(obj["number"]),
            "kr": {
                "plan": s((obj.get("kr") or {}).get("plan", "")),
                "fact": s((obj.get("kr") or {}).get("fact", "")),
            },
            "plan": [s(obj["plan"].get(i, "")) for i in range(len(columns))],
            "fact": [s(obj["fact"].get(i, "")) for i in range(len(columns))],
        })
    if not schedule["objects"]:
        schedule["objects"] = default_repair_schedule_state()["objects"]
    return compute_repair_schedule_derived(schedule)


def _default_table_rows(year: int, month: int, table_type: str, rows: int = 14) -> list[dict]:
    days = calendar.monthrange(year, month)[1]
    result = []
    for idx in range(rows):
        result.append(
            {
                "excluded": False,
                "cells": [str(idx + 1), "", "", ""]
                + ["" for _ in range(days)]
                + [""],
            }
        )
    return result


def load_state(year: int, include_summary: bool = True) -> dict:
    state = default_state(year)
    with DB_LOCK, conn() as db:
        cur = db.cursor()
        repair_schedule_year = year
        try:
            row = cur.execute("SELECT v FROM repair_settings WHERE k='last_year'").fetchone()
            if row and s(row["v"]).strip():
                repair_schedule_year = int(s(row["v"]))
        except Exception:
            repair_schedule_year = year

        repairs = cur.execute(
            "SELECT m, t, r, c, v FROM repairs WHERE y=? ORDER BY m, t, r, c",
            (year,),
        ).fetchall()
        month_map = {m["name"]: m for m in state["months"]}
        for row in repairs:
            month_name = s(row["m"])
            table_type = s(row["t"])
            if month_name not in month_map or table_type not in {"plan", "fact"}:
                continue
            table = month_map[month_name][table_type]
            r = int(row["r"])
            c = int(row["c"])
            value = s(row["v"])
            while r >= len(table):
                table.append(_default_table_rows(year, month_index(month_name), table_type, 1)[0])
            if c == -1:
                table[r]["excluded"] = True
                continue
            if c == 999:
                table[r]["cells"][-1] = value
            elif 0 <= c <= 2:
                table[r]["cells"][c] = value
            elif 3 <= c < len(table[r]["cells"]) - 1:
                table[r]["cells"][c + 1] = value

        norms = cur.execute("SELECT cat, k, v FROM norms WHERE y=? ORDER BY cat, k", (year,)).fetchall()
        for row in norms:
            cat = s(row["cat"])
            if cat not in state["norms"]:
                continue
            key = s(row["k"])
            value = s(row["v"])
            if cat == "h_tep":
                idx = TEM_NORM_ROWS.index(key) if key in TEM_NORM_ROWS else -1
                if 0 <= idx < len(state["norms"][cat]):
                    state["norms"][cat][idx] = {"k": key or TEM_NORM_ROWS[idx], "v": value}
            elif cat == "h_agr":
                idx = AGR_NORM_ROWS.index(key) if key in AGR_NORM_ROWS else -1
                if 0 <= idx < len(state["norms"][cat]):
                    state["norms"][cat][idx] = {"k": key or AGR_NORM_ROWS[idx], "v": value}
            elif cat in {"p_tep", "p_agr"}:
                idx = -1
                if key in MONTHS_RU:
                    idx = MONTHS_RU.index(key)
                else:
                    try:
                        idx = int(key) - 1
                    except ValueError:
                        idx = -1
                if 0 <= idx < 12:
                    state["norms"][cat][idx] = {"k": key or MONTHS_RU[idx], "v": value}
            else:
                state["norms"][cat].append({"k": key, "v": value})

        acts = cur.execute("SELECT m, act_num, is_done, sap_order_done FROM acts_state WHERE y=? ORDER BY m, act_num", (year,)).fetchall()
        for row in acts:
            state["acts"].setdefault(s(row["m"]), {})[s(row["act_num"])] = {
                "is_done": bool(row["is_done"]),
                "sap_order_done": bool(row["sap_order_done"]),
            }

        notes = cur.execute("SELECT m, k, v FROM report_notes WHERE y=? ORDER BY m, k", (year,)).fetchall()
        for row in notes:
            state["notes"].setdefault(s(row["m"]), {})[s(row["k"])] = s(row["v"])

        state["repair_schedule_year"] = repair_schedule_year
        state["repair_schedule"] = load_repair_schedule_for_year(cur, repair_schedule_year)

        tu28_data = cur.execute("SELECT m, r, k, v FROM tu28_data WHERE y=? ORDER BY m, r, k", (year,)).fetchall()
        for row in tu28_data:
            month_name = s(row["m"])
            r = int(row["r"])
            k = s(row["k"])
            v = s(row["v"])
            if month_name not in month_map:
                continue
            table = month_map[month_name]["fact"]
            while r >= len(table):
                table.append(_default_table_rows(year, month_index(month_name), "fact", 1)[0])
            try:
                parsed_v = json.loads(v) if v else []
            except Exception:
                parsed_v = []
            if k == "tu28_extra":
                table[r]["tu28_extra"] = parsed_v
            elif k == "tu28_staff":
                table[r]["tu28_staff"] = parsed_v

        if include_summary:
            state["repair_summary"] = build_repair_summary_state(cur)

    return state


def _repair_summary_rows_from_month_state(state: dict) -> list[dict]:
    rows: list[dict] = []
    year = int(state.get("year") or 0)
    for month_index0, month in enumerate(state.get("months", []) or []):
        month_number = int(month.get("month") or month_index0 + 1)
        if not (1 <= month_number <= 12):
            continue
        month_days = int(month.get("days") or calendar.monthrange(year, month_number)[1])
        for row_index, row in enumerate(month.get("fact", []) or []):
            if not row or row.get("excluded"):
                continue
            key = report_unit_key(row)
            if not key:
                continue
            series, number = key
            cells = row.get("cells") or []
            for cell_index, value in enumerate(cells):
                if cell_index < 4 or cell_index >= 4 + month_days:
                    continue
                code = normalize_repair_code(value)
                if not code or not any("А" <= ch <= "Я" for ch in code):
                    continue
                day = cell_index - 3
                try:
                    date_value = dt.date(year, month_number, day)
                except Exception:
                    continue
                rows.append({
                    "rowIndex": row_index,
                    "locoKey": f"{series}|{number}",
                    "locoLabel": f"{series} {number}".strip(),
                    "series": series,
                    "number": number,
                    "repairCode": code,
                    "repairDate": _repair_schedule_format_date(date_value),
                    "repairDateSort": int(dt.datetime(year, month_number, day).timestamp() * 1000),
                    "columnIndex": cell_index,
                    "sourceKind": "month",
                })
    return rows


def _repair_summary_rows_from_schedule_state(state: dict) -> list[dict]:
    rows: list[dict] = []
    schedule = state.get("repair_schedule", {}) or {}
    columns = schedule.get("columns", []) if isinstance(schedule, dict) else []
    for row_index, row in enumerate(schedule.get("objects", []) or []):
        series = s(row.get("series")).strip()
        number = s(row.get("number")).strip()
        if not series and not number:
            continue
        loco_label = " ".join(part for part in [series, number] if part).strip()
        loco_key = f"{series}|{number}"

        def push_row(repair_code: str, date_value, column_index: int, source_kind: str):
            code = normalize_repair_code(repair_code)
            date_text = s(date_value).strip()
            if not code or not date_text or not any("А" <= ch <= "Я" for ch in code):
                return
            parsed = _repair_schedule_parse_date(date_text)
            if not parsed:
                return
            rows.append({
                "rowIndex": row_index,
                "locoKey": loco_key,
                "locoLabel": loco_label,
                "series": series,
                "number": number,
                "repairCode": code,
                "repairDate": date_text,
                "repairDateSort": int(dt.datetime(parsed.year, parsed.month, parsed.day).timestamp() * 1000),
                "columnIndex": column_index,
                "sourceKind": source_kind,
            })

        push_row("КР", (row.get("kr") or {}).get("fact", ""), -1, "kr")
        for cidx, col in enumerate(columns):
            push_row((col or {}).get("code", ""), (row.get("fact") or [])[cidx] if cidx < len(row.get("fact") or []) else "", cidx, "fact")
    return rows


def _repair_summary_pack(rows: list[dict]) -> dict:
    rows = list(rows or [])
    rows.sort(key=lambda item: (
        -int(item.get("repairDateSort") or 0),
        s(item.get("locoLabel")),
        s(item.get("repairCode")),
        int(item.get("columnIndex") or 0),
    ))
    types: list[str] = []
    locos: list[dict] = []
    seen_types: set[str] = set()
    seen_locos: set[str] = set()
    for row in rows:
        code = s(row.get("repairCode")).strip()
        if code and any("А" <= ch <= "Я" for ch in code) and code not in seen_types:
            seen_types.add(code)
            types.append(code)
        loco_key = s(row.get("locoKey")).strip()
        loco_label = s(row.get("locoLabel")).strip() or loco_key.replace("|", " ").strip()
        if loco_key and loco_key not in seen_locos:
            seen_locos.add(loco_key)
            locos.append({"key": loco_key, "label": loco_label})
    locos.sort(key=lambda item: s(item.get("label")).lower())
    return {"rows": rows, "types": types, "loco_options": locos}


def _load_kp_archive_measurements() -> list[dict]:
    if not SOURCE_DB.exists():
        return []
    try:
        with connect_sqlite(SOURCE_DB) as archive_conn:
            archive_rows = archive_conn.execute(
                """
                SELECT DISTINCT measurement_date, locomotive, repair_type
                FROM archive_data
                WHERE TRIM(COALESCE(measurement_date, '')) <> ''
                  AND TRIM(COALESCE(locomotive, '')) <> ''
                  AND TRIM(COALESCE(repair_type, '')) <> ''
                ORDER BY measurement_date
                """
            ).fetchall()
    except Exception:
        return []

    measurements: list[dict] = []
    for row in archive_rows:
        measurement_date = s(row["measurement_date"]).strip()
        locomotive = s(row["locomotive"]).strip()
        repair_code = normalize_repair_code(row["repair_type"])
        try:
            parsed_date = dt.date.fromisoformat(measurement_date)
        except Exception:
            parsed_date = _repair_schedule_parse_date(measurement_date)
        if not parsed_date or not locomotive or not repair_code:
            continue
        measurements.append({
            "number": locomotive,
            "repairCode": repair_code,
            "measurementDate": parsed_date.isoformat(),
        })
    return measurements


def build_repair_summary_state(cur: sqlite3.Cursor) -> dict:
    years: set[int] = set()
    for table in ("repairs", "repair_schedule"):
        try:
            fetched = cur.execute(f"SELECT DISTINCT y FROM {table}").fetchall()
        except Exception:
            fetched = []
        for row in fetched:
            try:
                years.add(int(row["y"]))
            except Exception:
                continue

    months_rows: list[dict] = []
    schedule_rows: list[dict] = []
    system_dates_by_year: dict[str, dict] = {}
    for year in sorted(years):
        try:
            year_state = load_state(year, include_summary=False)
        except Exception:
            continue
        system_dates_by_year[str(year)] = year_state.get("system_dates") or load_system_dates(year)
        months_rows.extend(_repair_summary_rows_from_month_state(year_state))
        schedule_rows.extend(_repair_summary_rows_from_schedule_state(year_state))

    return {
        "months": _repair_summary_pack(months_rows),
        "schedule": _repair_summary_pack(schedule_rows),
        "kp_measurements": _load_kp_archive_measurements(),
        "system_dates_by_year": system_dates_by_year,
    }


def get_act_inventory_item(year: int, number: str) -> tuple[str, str]:
    if not SOURCE_DB.exists():
        return "", ""
    try:
        with connect_sqlite(SOURCE_DB) as db:
            cur = db.cursor()
            row = cur.execute("SELECT ser, inv FROM inventory WHERE y=? AND num=?", (year, number)).fetchone()
        if not row:
            return "", ""
        return s(row[0]), s(row[1])
    except Exception:
        return "", ""


def get_all_employee_names() -> list[str]:
    """Возвращает список анонимизированных меток сотрудников (Работник №1, Работник №2...) для безопасного отображения без закладки"""
    try:
        if not SOURCE_DB.exists():
            return []
        with connect_sqlite(SOURCE_DB) as db:
            cur = db.cursor()
            cur.execute("SELECT rowid, name, full_name, tab_num FROM employees ORDER BY rowid")
            rows = cur.fetchall()
            names = []
            for idx, r in enumerate(rows, start=1):
                raw_tab = s(r[3]).strip()
                num_part = idx
                if raw_tab.startswith("ID_"):
                    digits = "".join(ch for ch in raw_tab if ch.isdigit())
                    if digits:
                        num_part = int(digits)
                names.append(f"Работник №{num_part}")
            # Удаляем дубликаты с сохранением порядка
            seen = set()
            unique_names = []
            for n in names:
                if n not in seen:
                    seen.add(n)
                    unique_names.append(n)
            return unique_names
    except Exception:
        return []


def _parse_tabel_date(value: str, year: int | None = None) -> dt.date | None:
    text = s(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return dt.datetime.strptime(text, fmt).date()
        except Exception:
            pass
    parts = text.split(".")
    if len(parts) == 2 and year:
        try:
            return dt.date(int(year), int(parts[1]), int(parts[0]))
        except Exception:
            return None
    return None


def get_employee_vacations() -> dict[str, list[dict]]:
    if not SOURCE_DB.exists():
        return {}
    try:
        with connect_sqlite(SOURCE_DB) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute(
                """
                SELECT e.y, e.name, e.full_name, e.tab_num, v.c, v.v
                FROM employees e
                JOIN vacations v ON v.y=e.y AND v.tab_num=e.tab_num
                WHERE TRIM(COALESCE(e.tab_num, '')) <> ''
                  AND TRIM(COALESCE(v.v, '')) <> ''
                ORDER BY e.y, e.rowid, v.c
                """
            ).fetchall()
    except Exception:
        return {}

    grouped: dict[tuple[int, str], dict[int, str]] = {}
    names: dict[tuple[int, str], set[str]] = {}
    for row in rows:
        try:
            year = int(row["y"])
            col = int(row["c"])
        except Exception:
            continue
        tab_num = s(row["tab_num"]).strip()
        if not tab_num:
            continue
        key = (year, tab_num)
        grouped.setdefault(key, {})[col] = s(row["v"]).strip()
        name_values = {s(row["name"]).strip(), s(row["full_name"]).strip()}
        digits = "".join(ch for ch in tab_num if ch.isdigit())
        if digits:
            num = int(digits)
            name_values.add(f"Работник №{num}")
            name_values.add(f"СотрудникПолн №{num}")
            name_values.add(f"ID_{num:03d}")
        names.setdefault(key, set()).update(item for item in name_values if item)

    result: dict[str, list[dict]] = {}
    for (year, _tab_num), cells in grouped.items():
        for start_col, end_col in ((1, 2), (5, 6), (9, 10)):
            start = _parse_tabel_date(cells.get(start_col, ""), year)
            end = _parse_tabel_date(cells.get(end_col, ""), year)
            if not start or not end:
                continue
            if end < start:
                start, end = end, start
            item = {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "label": f"Отпуск {start.strftime('%d.%m.%Y')}-{end.strftime('%d.%m.%Y')}",
            }
            for name in names.get((year, _tab_num), set()):
                result.setdefault(name, []).append(item)

    try:
        with connect_sqlite(SOURCE_DB) as db:
            db.row_factory = sqlite3.Row
            ts_rows = db.execute(
                """
                SELECT e.y, e.name, e.full_name, t.m, t.c, t.v
                FROM employees e
                JOIN timesheet t ON t.y=e.y AND t.tab_num=e.tab_num
                WHERE TRIM(COALESCE(e.tab_num, '')) <> ''
                  AND TRIM(COALESCE(t.v, '')) <> ''
                """
            ).fetchall()
            for row in ts_rows:
                try:
                    year = int(row["y"])
                    day = int(row["c"])
                    month_name = s(row["m"]).strip()
                except Exception:
                    continue
                v = s(row["v"]).strip()
                if not v or any(char.isdigit() for char in v):
                    continue
                try:
                    month_index = MONTHS_RU.index(month_name) + 1
                    date_obj = dt.date(year, month_index, day)
                except ValueError:
                    continue
                item = {
                    "start": date_obj.isoformat(),
                    "end": date_obj.isoformat(),
                    "label": f"Отсутствует: {v} ({date_obj.strftime('%d.%m.%Y')})",
                }
                name_values = {s(row["name"]).strip(), s(row["full_name"]).strip()}
                for name in name_values:
                    if name:
                        result.setdefault(name, []).append(item)
    except Exception as e:
        print("Error fetching timesheet for vacations:", e)

    return result


def save_state(state: dict) -> dict:
    year = int(state.get("year") or dt.date.today().year)
    with DB_LOCK, conn() as db:
        cur = db.cursor()
        with db:
            cur.execute("DELETE FROM repairs WHERE y=?", (year,))
            cur.execute("DELETE FROM norms WHERE y=?", (year,))
            cur.execute("DELETE FROM acts_state WHERE y=?", (year,))
            cur.execute("DELETE FROM report_notes WHERE y=?", (year,))
            cur.execute("DELETE FROM tu28_data WHERE y=?", (year,))
            cur.execute("DELETE FROM repair_schedule WHERE y=?", (year,))
            cur.execute("INSERT OR REPLACE INTO repair_settings VALUES ('last_year', ?)", (str(year),))

            repairs_ins = []
            tu28_ins = []
            for month in state.get("months", []):
                month_name = s(month.get("name"))
                for table_type in ["plan", "fact"]:
                    for r, row in enumerate(month.get(table_type, [])):
                        if row.get("excluded"):
                            repairs_ins.append((year, month_name, table_type, r, -1, "EXC"))
                        cells = row.get("cells", [])
                        for c, value in enumerate(cells):
                            value = s(value).strip()
                            if value:
                                if c == 3:
                                    continue
                                db_c = 999 if c == len(cells) - 1 else (c - 1 if c >= 4 else c)
                                repairs_ins.append((year, month_name, table_type, r, db_c, value))
                        if table_type == "fact":
                            if "tu28_extra" in row:
                                tu28_ins.append((year, month_name, r, "tu28_extra", json.dumps(row["tu28_extra"])))
                            if "tu28_staff" in row:
                                tu28_ins.append((year, month_name, r, "tu28_staff", json.dumps(row["tu28_staff"])))
                            if "tu28_locked" in row:
                                tu28_ins.append((year, month_name, r, "tu28_locked", json.dumps(row["tu28_locked"])))

            cur.executemany("INSERT INTO repairs VALUES (?,?,?,?,?,?)", repairs_ins)
            cur.executemany("INSERT INTO tu28_data VALUES (?,?,?,?,?)", tu28_ins)

            norms_ins = []
            for cat, rows in state.get("norms", {}).items():
                for row in rows:
                    k = s(row.get("k")).strip()
                    v = s(row.get("v")).strip()
                    if k or v:
                        norms_ins.append((year, cat, k, v))
            cur.executemany("INSERT INTO norms VALUES (?,?,?,?)", norms_ins)

            acts_ins = []
            for m_name, acts in state.get("acts", {}).items():
                for act_num, flags in acts.items():
                    acts_ins.append((year, m_name, act_num, 1 if flags.get("is_done") else 0, 1 if flags.get("sap_order_done") else 0))
            cur.executemany("INSERT INTO acts_state VALUES (?,?,?,?,?)", acts_ins)

            notes_ins = []
            for m_name, keys in state.get("notes", {}).items():
                for key, value in keys.items():
                    value = s(value)
                    if value:
                        notes_ins.append((year, m_name, key, value))
            cur.executemany("INSERT INTO report_notes VALUES (?,?,?,?)", notes_ins)

            schedule = state.get("repair_schedule", {}) or {}
            if isinstance(schedule, dict):
                schedule = compute_repair_schedule_derived(schedule)
                state["repair_schedule"] = schedule
            columns = schedule.get("columns", []) if isinstance(schedule, dict) else []
            objects = schedule.get("objects", []) if isinstance(schedule, dict) else []
            periodicity = schedule.get("periodicity", {}) if isinstance(schedule, dict) else {}
            
            schedule_ins = []
            for cidx, col in enumerate(columns):
                value = normalize_repair_code(s((col or {}).get("code")).strip())
                if value:
                    schedule_ins.append((year, -1, f"col_{cidx}", value))
            
            series_rows = periodicity.get("series", []) if isinstance(periodicity, dict) else []
            for r, value in enumerate(series_rows):
                value = s(value).strip()
                if value:
                    schedule_ins.append((year, r, f"periodicity_series_{r}", value))
            
            values_rows = periodicity.get("values", []) if isinstance(periodicity, dict) else []
            for r, row in enumerate(values_rows):
                if not isinstance(row, list):
                    continue
                for cidx, value in enumerate(row):
                    value = s(value).strip()
                    if value:
                        schedule_ins.append((year, r, f"periodicity_value_{r}_{cidx}", value))
                        
            for r, row in enumerate(objects):
                if not isinstance(row, dict):
                    continue
                series = s(row.get("series")).strip()
                number = s(row.get("number")).strip()
                if series:
                    schedule_ins.append((year, r, "series", series))
                if number:
                    schedule_ins.append((year, r, "number", number))
                kr = row.get("kr") or {}
                kr_plan = s(kr.get("plan")).strip()
                kr_fact = s(kr.get("fact")).strip()
                if kr_plan:
                    schedule_ins.append((year, r, "kr_plan", kr_plan))
                if kr_fact:
                    schedule_ins.append((year, r, "kr_fact", kr_fact))
                for cidx, value in enumerate(row.get("plan", []) or []):
                    value = s(value).strip()
                    if value:
                        schedule_ins.append((year, r, f"plan_{cidx}", value))
                for cidx, value in enumerate(row.get("fact", []) or []):
                    value = s(value).strip()
                    if value:
                        schedule_ins.append((year, r, f"fact_{cidx}", value))
                        
            cur.executemany("INSERT INTO repair_schedule VALUES (?,?,?,?)", schedule_ins)

    return load_state(year)

