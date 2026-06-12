from __future__ import annotations

import calendar
import datetime as dt
import hashlib
import json
import os
from io import BytesIO
import shutil
import hmac
import secrets
import sqlite3
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.parse import parse_qs, quote, urlparse

APP_VERSION = "web-gpp-0.8"
MONTHS_RU = [
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]
TEM_NORM_ROWS = ["ТО2", "ТО3", "ТР1", "ТР2", "ТР3", "СР", "КР"]
AGR_NORM_ROWS = ["ТО", "ТР", "КР"]
REPORT_TEMPLATE_NAME = "Отчет_шаблон.xlsx"
TU28_TEMPLATE_NAME = "ТУ-28_шаблон.xlsx"
MONTH_DAY_LIMIT_FOR_REPORT = 25
TEP_REPORT_FACTORS = {"ТО2": 1, "ТО3": 2, "ТР1": 5, "ТР2": 10, "ТР3": 15}
AGR_REPORT_FACTORS = {"ТО": 1, "ТР": 5}
TEP_HOUR_FACTORS = {"ТО2": 1, "ТО3": 2, "ТР1": 5, "ТР2": 10, "ТР3": 15}
AGR_HOUR_FACTORS = {"ТО": 1, "ТР": 5}
TU28_REPAIR_CODES = {"ТО3", "ТР1", "ТР2", "ТР3", "СР", "КР"}
FIXED_HOLIDAYS = {
    (1, 1), (1, 2), (1, 3), (1, 4), (1, 5), (1, 6), (1, 7), (1, 8),
    (2, 23), (3, 8), (5, 1), (5, 9), (6, 12), (11, 4),
}

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DB_FILE = DATA_DIR / "grafik_ppr_web.db"
SHARED_DATA_DIR = ROOT.parent / "data"
AUTH_FILE = SHARED_DATA_DIR / "web_auth.json"
WEB_SECRET_FILE = SHARED_DATA_DIR / "web_secret.txt"
SOURCE_DB = ROOT.parent / "base" / "common_database.db"
SOURCE_DIR = ROOT.parent / "src" / "График ППР"
ACT_TEMPLATE_NAME = "Акт_шаблон.xlsx"

DB_LOCK = Lock()
SERVER_STARTED_AT = None
SESSION_COOKIE = "grafik_ppr_session"
SESSION_TTL_SECONDS = 7 * 24 * 60 * 60


def format_n(value) -> str:
    try:
        number = float(str(value).replace(",", "."))
    except Exception:
        return "0,00"
    if number.is_integer():
        return f"{int(number)},00"
    return f"{number:.2f}".replace(".", ",")


def load_web_secret() -> str:
    return "opYbo6NB8pb7dChYQkmHEvUH6K4hAHjuzi2qEYOC024"


WEB_SECRET = load_web_secret()
SESSIONS: dict[str, tuple[str, str, str, str, float]] = {}


def load_auth_config() -> tuple[str, str, str]:
    user = os.environ.get("WEB_USER", "admin").strip() or "admin"
    view_password = os.environ.get("WEB_VIEW_PASSWORD", "").strip()
    edit_password = (
        os.environ.get("WEB_EDIT_PASSWORD", "").strip()
        or os.environ.get("WEB_PASSWORD", "").strip()
    )
    if view_password and edit_password:
        return user, view_password, edit_password
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if AUTH_FILE.exists():
        try:
            payload = json.loads(AUTH_FILE.read_text(encoding="utf-8"))
            file_user = str(payload.get("user", user)).strip() or user
            legacy_password = str(payload.get("password", "")).strip()
            file_view = str(payload.get("view_password", legacy_password)).strip()
            file_edit = str(payload.get("edit_password", "")).strip()
            if not file_edit and legacy_password and not payload.get("view_password"):
                file_edit = secrets.token_urlsafe(8)
            if not file_edit:
                file_edit = legacy_password
            if file_view and not file_edit:
                file_edit = secrets.token_urlsafe(8)
            if file_edit and not file_view:
                file_view = secrets.token_urlsafe(8)
            if file_view and file_edit and file_view == file_edit:
                file_edit = secrets.token_urlsafe(8)
            if file_view and file_edit:
                AUTH_FILE.write_text(
                    json.dumps(
                        {"user": file_user, "view_password": file_view, "edit_password": file_edit},
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                return file_user, file_view, file_edit
        except Exception:
            pass
    if not view_password:
        view_password = secrets.token_urlsafe(8)
    if not edit_password:
        edit_password = secrets.token_urlsafe(8)
    AUTH_FILE.write_text(
        json.dumps(
            {"user": user, "view_password": view_password, "edit_password": edit_password},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Web auth created: user={user} view_password={view_password} edit_password={edit_password}")
    return user, view_password, edit_password


WEB_USER, WEB_VIEW_PASSWORD, WEB_EDIT_PASSWORD = load_auth_config()
AUTH_ENABLED = True
APP_PREFIX = "/grafik-ppr"


def ensure_database() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if DB_FILE.exists():
        return
    if SOURCE_DB.exists():
        shutil.copy2(SOURCE_DB, DB_FILE)
        return
    with sqlite3.connect(DB_FILE) as conn:
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS repairs (y INT, m TEXT, t TEXT, r INT, c INT, v TEXT, PRIMARY KEY(y,m,t,r,c))")
        cur.execute("CREATE TABLE IF NOT EXISTS norms (y INT, cat TEXT, k TEXT, v TEXT, PRIMARY KEY(y,cat,k))")
        cur.execute("CREATE TABLE IF NOT EXISTS inventory (y INT, ser TEXT, num TEXT, inv TEXT, PRIMARY KEY(y,ser,num))")
        cur.execute("CREATE TABLE IF NOT EXISTS repair_settings (k TEXT PRIMARY KEY, v TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS acts_state (y INT, m TEXT, act_num TEXT, is_done INT, sap_order_done INT DEFAULT 0, PRIMARY KEY(y, m, act_num))")
        cur.execute("CREATE TABLE IF NOT EXISTS report_notes (y INT, m TEXT, k TEXT, v TEXT, PRIMARY KEY(y,m,k))")
        conn.commit()


def conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_FILE)
    c.row_factory = sqlite3.Row
    return c


def s(value) -> str:
    return "" if value is None else str(value)


def normalize_repair_code(value: str) -> str:
    text = s(value).strip().upper().replace(" ", "").replace("-", "")
    latin_map = str.maketrans({
        "A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н", "K": "К",
        "M": "М", "O": "О", "P": "Р", "T": "Т", "X": "Х", "Y": "У",
    })
    text = text.translate(latin_map)
    if any("А" <= c <= "Я" for c in text):
        return text
    if any(c.isdigit() for c in text):
        return "".join(filter(str.isdigit, text))
    return text


def month_index(month_name: str) -> int:
    return MONTHS_RU.index(month_name) + 1


def load_system_dates(year: int) -> dict[str, list[tuple[int, int]]]:
    transfer_dates: set[tuple[int, int]] = set()
    holiday_dates: set[tuple[int, int]] = set(FIXED_HOLIDAYS)
    if not SOURCE_DB.exists():
        return {
            "transfer": sorted(transfer_dates),
            "holiday": sorted(holiday_dates),
        }

    try:
        with sqlite3.connect(SOURCE_DB) as conn:
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
    }


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


def load_state(year: int) -> dict:
    state = default_state(year)
    with DB_LOCK, conn() as db:
        cur = db.cursor()

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

    return state


def find_act_template_path() -> Path | None:
    candidates = [
        ROOT / ACT_TEMPLATE_NAME,
        SOURCE_DIR / ACT_TEMPLATE_NAME,
        ROOT.parent / "dist" / "РТПС" / "_internal" / "График ППР" / ACT_TEMPLATE_NAME,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def find_report_template_path() -> Path | None:
    candidates = [
        ROOT / REPORT_TEMPLATE_NAME,
        SOURCE_DIR / REPORT_TEMPLATE_NAME,
        ROOT.parent / "dist" / "РТПС" / "_internal" / "График ППР" / REPORT_TEMPLATE_NAME,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def find_tu28_template_path() -> Path | None:
    candidates = [
        ROOT / TU28_TEMPLATE_NAME,
        SOURCE_DIR / TU28_TEMPLATE_NAME,
        ROOT.parent / "dist" / "РТПС" / "_internal" / "График ППР" / TU28_TEMPLATE_NAME,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def read_norm_hours_from_state(items: list[dict]) -> dict[str, float]:
    norms: dict[str, float] = {}
    for item in items or []:
        key = s(item.get("k")).strip()
        value = s(item.get("v")).strip()
        if not key or not value:
            continue
        try:
            norms[key] = float(value.replace(",", "."))
        except Exception:
            continue
    return norms


def report_unit_key(row: dict) -> tuple[str, str] | None:
    cells = row.get("cells") or []
    series = s(cells[1]).strip().upper() if len(cells) > 1 else ""
    number = s(cells[2]).strip().upper() if len(cells) > 2 else ""
    if not series or not number:
        return None
    return series, number


def build_rows_by_unit(month_data: dict, table_type: str) -> dict[tuple[str, str], int]:
    rows_by_unit: dict[tuple[str, str], int] = {}
    for idx, row in enumerate(month_data.get(table_type, []) or []):
        if row.get("excluded"):
            continue
        key = report_unit_key(row)
        if key and key not in rows_by_unit:
            rows_by_unit[key] = idx
    return rows_by_unit


def row_cell_is_numeric(row: dict | None, day: int) -> bool:
    if not row or not row.get("cells"):
        return False
    idx = day + 3
    raw = s(row["cells"][idx]) if idx < len(row["cells"]) else ""
    if not raw.strip():
        return False
    try:
        float(raw.replace(",", "."))
    except ValueError:
        return False
    return True


def collect_unplanned_starts_across_months(
    year: int,
    months: list[dict],
    month_index: int,
    table_type: str,
    row_key: tuple[str, str],
) -> list[tuple[int, int]]:
    if not row_key or not months or not (0 <= month_index < len(months)):
        return []
    row_maps = [build_rows_by_unit(month, table_type) for month in months[: month_index + 1]]
    curr_month = months[month_index]
    curr_month_num = int(curr_month.get("month") or month_index + 1)
    prev_month_num = int(months[month_index - 1].get("month") or month_index) if month_index > 0 else None
    window_start = dt.date(year, prev_month_num, 26) if prev_month_num else dt.date(year, curr_month_num, 1)
    window_end = dt.date(year, curr_month_num, MONTH_DAY_LIMIT_FOR_REPORT)
    def row_for_date(date: dt.date) -> dict | None:
        month_idx = date.month - 1
        if month_idx < 0 or month_idx >= len(row_maps):
            return None
        row_idx = row_maps[month_idx].get(row_key)
        rows = months[month_idx].get(table_type, []) or []
        return rows[row_idx] if row_idx is not None and row_idx < len(rows) else None

    def numeric_on(date: dt.date) -> bool:
        return row_cell_is_numeric(row_for_date(date), date.day)

    starts: list[tuple[int, int]] = []
    seen = set()

    def add_start(date: dt.date) -> None:
        key = (date.day, date.month)
        if key in seen:
            return
        seen.add(key)
        starts.append(key)

    if numeric_on(window_start):
        start = window_start
        prev = start - dt.timedelta(days=1)
        while prev.year == year and prev >= dt.date(year, 1, 1) and numeric_on(prev):
            start = prev
            prev -= dt.timedelta(days=1)
        add_start(start)

    prev_is_num = numeric_on(window_start)
    day = window_start + dt.timedelta(days=1)
    while day <= window_end:
        is_num = numeric_on(day)
        if is_num and not prev_is_num:
            add_start(day)
        prev_is_num = is_num
        day += dt.timedelta(days=1)

    return starts


def collect_row_notes(row: dict, unplanned_starts: list[tuple[int, int]], number: str) -> list[str]:
    row_notes: list[str] = []
    cells = row.get("cells") or []
    note = s(cells[-1]).strip() if cells else ""
    has_unplanned = bool(unplanned_starts)
    is_auto_act_note = note.startswith("Акт № ") and "-" in note
    if note and not is_auto_act_note:
        row_notes.append(note)
    if has_unplanned:
        for day, month in unplanned_starts:
            auto_note = f"Акт № {day:02d}-{month:02d}-{number}"
            if auto_note not in row_notes:
                row_notes.append(auto_note)
    if not row_notes and note and is_auto_act_note:
        row_notes.append(note)
    return row_notes


def collect_report_act_notes_for_category(state: dict, month_index: int, table_type: str, category: str) -> list[str]:
    months = state.get("months", []) or []
    if not months or not (0 <= month_index < len(months)):
        return []
    year = int(state.get("year") or dt.date.today().year)
    month = months[month_index]
    notes: list[str] = []
    for row in month.get(table_type, []) or []:
        if row.get("excluded"):
            continue
        cells = row.get("cells") or []
        series = s(cells[1]).strip().upper() if len(cells) > 1 else ""
        number = s(cells[2]).strip().upper() if len(cells) > 2 else ""
        if not series or not number:
            continue
        row_category = "agr" if "ПЭ" in series else "tep"
        if row_category != category:
            continue
        key = report_unit_key(row)
        if not key:
            continue
        for day, month_num in collect_unplanned_starts_across_months(year, months, month_index, table_type, key):
            note = f"Акт № {day:02d}-{month_num:02d}-{number}"
            if note not in notes:
                notes.append(note)
    return notes


def process_report_day(acc, row: dict, day: int, month_num: int, category: str, table_type: str, state: dict) -> None:
    cells = row.get("cells") or []
    idx = day + 3
    val = s(cells[idx]).strip().upper() if idx < len(cells) else ""
    if val:
        try:
            hours = float(val.replace(",", "."))
        except ValueError:
            acc.result[table_type][category][val] = acc.result[table_type][category].get(val, 0) + 1
            state["last_is_num"] = False
        else:
            acc.unplanned_hours[table_type][category] += hours
            if not state["last_is_num"]:
                acc.unplanned_blocks[table_type][category] += 1
                state["unplanned_starts"].append((day, month_num))
            state["last_is_num"] = True
    else:
        state["last_is_num"] = False


def process_report_row(
    acc,
    table_type: str,
    curr_row: dict,
    prev_row: dict | None,
    curr_m: int,
    prev_m: int | None,
    fund_days: int,
    year: int,
    months: list[dict],
    month_index: int,
) -> None:
    if curr_row.get("excluded"):
        return
    cells = curr_row.get("cells") or []
    series = s(cells[1]).strip().upper() if len(cells) > 1 else ""
    number = s(cells[2]).strip().upper() if len(cells) > 2 else ""
    if not series:
        return
    category = "agr" if "ПЭ" in series else "tep"
    acc.units[table_type][category] += 1
    state = {"last_is_num": False, "unplanned_starts": []}
    if prev_row is not None and prev_m is not None:
        for day in range(MONTH_DAY_LIMIT_FOR_REPORT + 1, fund_days + 1):
            process_report_day(acc, prev_row, day, prev_m, category, table_type, state)
    for day in range(1, MONTH_DAY_LIMIT_FOR_REPORT + 1):
        process_report_day(acc, curr_row, day, curr_m, category, table_type, state)
    row_key = report_unit_key(curr_row)
    if table_type == "fact" and row_key:
        auto_starts = collect_unplanned_starts_across_months(year, months, month_index, table_type, row_key)
    else:
        auto_starts = state["unplanned_starts"]
    for note in collect_row_notes(curr_row, auto_starts, number):
        if note not in acc.notes[table_type][category]:
            acc.notes[table_type][category].append(note)


def get_report_period(year: int, month_name: str) -> tuple[int, int, int | None, str | None, int]:
    m_idx = MONTHS_RU.index(month_name)
    curr_m = m_idx + 1
    if m_idx == 0:
        return m_idx, curr_m, None, None, MONTH_DAY_LIMIT_FOR_REPORT
    prev_m_idx = m_idx - 1
    prev_month_name = MONTHS_RU[prev_m_idx]
    fund_days = calendar.monthrange(year, prev_m_idx + 1)[1]
    return m_idx, curr_m, prev_m_idx + 1, prev_month_name, fund_days


def calculate_ok_units(state: dict, year: int, month_name: str, acc, period_hours: int) -> tuple[float, float]:
    _, curr_m, prev_m, _, fund_days = get_report_period(year, month_name)
    _ = curr_m, prev_m, fund_days
    n_tep = read_norm_hours_from_state(state.get("norms", {}).get("h_tep", []))
    n_agr = read_norm_hours_from_state(state.get("norms", {}).get("h_agr", []))
    fact_tep_hours = acc.unplanned_hours["fact"]["tep"] + sum(
        acc.result["fact"]["tep"].get(code, 0) / factor * n_tep.get(code, 0)
        for code, factor in TEP_HOUR_FACTORS.items()
    )
    fact_agr_hours = acc.unplanned_hours["fact"]["agr"] + sum(
        acc.result["fact"]["agr"].get(code, 0) / factor * n_agr.get(code, 0)
        for code, factor in AGR_HOUR_FACTORS.items()
    )
    fact_tep_ok = acc.units["fact"]["tep"] - (fact_tep_hours / period_hours) if period_hours else 0
    fact_agr_ok = acc.units["fact"]["agr"] - (fact_agr_hours / period_hours) if period_hours else 0
    return fact_tep_ok, fact_agr_ok


def calculate_report_data_from_state(state: dict, month_name: str) -> dict:
    m_idx, curr_m, prev_m, prev_month_name, fund_days = get_report_period(int(state.get("year") or dt.date.today().year), month_name)
    period_hours = fund_days * 24
    acc = type("ReportAccumulatorLike", (), {})()
    acc.result = {"plan": {"tep": {}, "agr": {}}, "fact": {"tep": {}, "agr": {}}}
    acc.unplanned_blocks = {"plan": {"tep": 0, "agr": 0}, "fact": {"tep": 0, "agr": 0}}
    acc.unplanned_hours = {"plan": {"tep": 0.0, "agr": 0.0}, "fact": {"tep": 0.0, "agr": 0.0}}
    acc.units = {"plan": {"tep": 0, "agr": 0}, "fact": {"tep": 0, "agr": 0}}
    acc.notes = {"plan": {"tep": [], "agr": []}, "fact": {"tep": [], "agr": []}}
    acc.excluded = {"plan": set(), "fact": set()}

    months = state.get("months", []) or []
    if not (0 <= m_idx < len(months)):
        raise ValueError("Не найден месяц отчета")
    curr_month = months[m_idx]
    prev_month = months[m_idx - 1] if prev_month_name and m_idx - 1 >= 0 else None
    prev_rows_by_unit = build_rows_by_unit(prev_month, "plan") if prev_month else {}
    prev_rows_by_unit_fact = build_rows_by_unit(prev_month, "fact") if prev_month else {}

    for table_type in ["plan", "fact"]:
        curr_table = curr_month.get(table_type, []) or []
        prev_rows = prev_rows_by_unit_fact if table_type == "fact" else prev_rows_by_unit
        for row in curr_table:
            key = report_unit_key(row)
            if row.get("excluded") and key:
                acc.excluded[table_type].add(key)
            prev_row = prev_month.get(table_type, [])[prev_rows[key]] if prev_month and key and key in prev_rows else None
            process_report_row(acc, table_type, row, prev_row, curr_m, prev_m, fund_days, int(state.get("year") or dt.date.today().year), months, m_idx)

    if acc.notes["fact"]["tep"] is not None:
        for note in collect_report_act_notes_for_category(state, m_idx, "fact", "tep"):
            if note not in acc.notes["fact"]["tep"]:
                acc.notes["fact"]["tep"].append(note)
    if acc.notes["fact"]["agr"] is not None:
        for note in collect_report_act_notes_for_category(state, m_idx, "fact", "agr"):
            if note not in acc.notes["fact"]["agr"]:
                acc.notes["fact"]["agr"].append(note)

    fact_tep_ok, fact_agr_ok = calculate_ok_units(state, int(state.get("year") or dt.date.today().year), month_name, acc, period_hours)

    def month_norm_value(key: str, fallback_index: int) -> str:
        for item in state.get("norms", {}).get(key, []) or []:
            item_key = s(item.get("k")).strip()
            item_value = s(item.get("v")).strip()
            if item_key == month_name:
                return item_value or "0"
        items = state.get("norms", {}).get(key, []) or []
        if 0 <= fallback_index < len(items):
            return s(items[fallback_index].get("v")).strip() or "0"
        return "0"

    return {
        "m": month_name,
        "y": int(state.get("year") or dt.date.today().year),
        "tp": month_norm_value("p_tep", m_idx),
        "tf": fact_tep_ok,
        "ap": month_norm_value("p_agr", m_idx),
        "af": fact_agr_ok,
        "res": acc.result,
        "ub": acc.unplanned_blocks,
        "notes": acc.notes,
        "excluded": {
            "plan": sorted(["|".join(key) for key in acc.excluded["plan"]]),
            "fact": sorted(["|".join(key) for key in acc.excluded["fact"]]),
        },
    }


def build_report_excel_tags(month_name: str, data: dict, saved_notes: dict[str, str]) -> dict[str, str]:
    def count(section: str, category: str, code: str, factor: int) -> float:
        return data["res"][section][category].get(code, 0) / factor

    def merge_notes(saved: str, auto: str) -> str:
        saved = s(saved).strip()
        auto = s(auto).strip()
        if saved and auto:
            lines = []
            seen = set()
            for chunk in (saved, auto):
                for line in chunk.splitlines():
                    line = line.strip()
                    if not line or line in seen:
                        continue
                    seen.add(line)
                    lines.append(line)
            return "\n".join(lines)
        return saved or auto

    tep_plan = {code: count("plan", "tep", code, factor) for code, factor in TEP_REPORT_FACTORS.items()}
    tep_fact = {code: count("fact", "tep", code, factor) for code, factor in TEP_REPORT_FACTORS.items()}
    agr_plan = {code: count("plan", "agr", code, factor) for code, factor in AGR_REPORT_FACTORS.items()}
    agr_fact = {code: count("fact", "agr", code, factor) for code, factor in AGR_REPORT_FACTORS.items()}

    p_tep_ub = data["ub"]["plan"]["tep"]
    f_tep_ub = data["ub"]["fact"]["tep"]
    p_agr_ub = data["ub"]["plan"]["agr"]
    f_agr_ub = data["ub"]["fact"]["agr"]

    sum_p = sum(tep_plan.values()) + p_tep_ub + sum(agr_plan.values()) + p_agr_ub
    sum_f = sum(tep_fact.values()) + f_tep_ub + sum(agr_fact.values()) + f_agr_ub

    return {
        "[МЕСЯЦ]": month_name,
        "[ГОД]": str(data["y"]),
        "[ПЛАН_ТЕП_ПАРК]": format_n(data["tp"]),
        "[ФАКТ_ТЕП_ПАРК]": format_n(data["tf"]),
        "[ПРИМ_ТЕП_ПАРК]": saved_notes.get("tep_park", ""),
        "[ПЛАН_ТЕП_ТО2]": format_n(tep_plan["ТО2"]),
        "[ФАКТ_ТЕП_ТО2]": format_n(tep_fact["ТО2"]),
        "[ПРИМ_ТЕП_ТО2]": saved_notes.get("tep_ТО2", ""),
        "[ПЛАН_ТЕП_ТО3]": format_n(tep_plan["ТО3"]),
        "[ФАКТ_ТЕП_ТО3]": format_n(tep_fact["ТО3"]),
        "[ПРИМ_ТЕП_ТО3]": saved_notes.get("tep_ТО3", ""),
        "[ПЛАН_ТЕП_ТР1]": format_n(tep_plan["ТР1"]),
        "[ФАКТ_ТЕП_ТР1]": format_n(tep_fact["ТР1"]),
        "[ПРИМ_ТЕП_ТР1]": saved_notes.get("tep_ТР1", ""),
        "[ПЛАН_ТЕП_ТР2]": format_n(tep_plan["ТР2"]),
        "[ФАКТ_ТЕП_ТР2]": format_n(tep_fact["ТР2"]),
        "[ПРИМ_ТЕП_ТР2]": saved_notes.get("tep_ТР2", ""),
        "[ПЛАН_ТЕП_ТР3]": format_n(tep_plan["ТР3"]),
        "[ФАКТ_ТЕП_ТР3]": format_n(tep_fact["ТР3"]),
        "[ПРИМ_ТЕП_ТР3]": saved_notes.get("tep_ТР3", ""),
        "[ПЛАН_ТЕП_НЕПЛАН]": format_n(p_tep_ub),
        "[ФАКТ_ТЕП_НЕПЛАН]": format_n(f_tep_ub),
        "[ПРИМ_ТЕП_НЕПЛАН]": merge_notes(saved_notes.get("tep_ТР_unplan", ""), "\n".join(data["notes"]["fact"]["tep"])),
        "[ПЛАН_АГР_ПАРК]": format_n(data["ap"]),
        "[ФАКТ_АГР_ПАРК]": format_n(data["af"]),
        "[ПРИМ_АГР_ПАРК]": saved_notes.get("agr_park", ""),
        "[ПЛАН_АГР_ТО]": format_n(agr_plan["ТО"]),
        "[ФАКТ_АГР_ТО]": format_n(agr_fact["ТО"]),
        "[ПРИМ_АГР_ТО]": saved_notes.get("agr_ТО", ""),
        "[ПЛАН_АГР_ТР]": format_n(agr_plan["ТР"]),
        "[ФАКТ_АГР_ТР]": format_n(agr_fact["ТР"]),
        "[ПРИМ_АГР_ТР]": saved_notes.get("agr_ТР", ""),
        "[ПЛАН_АГР_НЕПЛАН]": format_n(p_agr_ub),
        "[ФАКТ_АГР_НЕПЛАН]": format_n(f_agr_ub),
        "[ПРИМ_АГР_НЕПЛАН]": merge_notes(saved_notes.get("agr_ТР_unplan", ""), "\n".join(data["notes"]["fact"]["agr"])),
        "[ПЛАН_СУММА]": format_n(sum_p),
        "[ФАКТ_СУММА]": format_n(sum_f),
    }


def build_report_preview(month_name: str, data: dict, saved_notes: dict[str, str]) -> dict:
    def count(section: str, category: str, code: str, factor: int) -> str:
        return format_n(data["res"][section][category].get(code, 0) / factor)

    def merge_notes(saved: str, auto: str) -> str:
        saved = s(saved).strip()
        auto = s(auto).strip()
        if saved and auto:
            lines = []
            seen = set()
            for chunk in (saved, auto):
                for line in chunk.splitlines():
                    line = line.strip()
                    if not line or line in seen:
                        continue
                    seen.add(line)
                    lines.append(line)
            return "\n".join(lines)
        return saved or auto

    tep_notes = "\n".join(data["notes"]["fact"]["tep"])
    agr_notes = "\n".join(data["notes"]["fact"]["agr"])
    rows = [
        {"kind": "group", "label": "Кол-во тех.испр. локомотивов\nТЕПЛОВОЗЫ МАНЕВРОВЫЕ", "plan": format_n(data["tp"]), "fact": format_n(data["tf"]), "note_key": "tep_park", "note": saved_notes.get("tep_park", "")},
        {"kind": "row", "key": "tep_ТО2", "label": "ТО2", "plan": count("plan", "tep", "ТО2", 1), "fact": count("fact", "tep", "ТО2", 1), "note": saved_notes.get("tep_ТО2", "")},
        {"kind": "row", "key": "tep_ТО3", "label": "ТО3", "plan": count("plan", "tep", "ТО3", 2), "fact": count("fact", "tep", "ТО3", 2), "note": saved_notes.get("tep_ТО3", "")},
        {"kind": "row", "key": "tep_ТР1", "label": "ТР1", "plan": count("plan", "tep", "ТР1", 5), "fact": count("fact", "tep", "ТР1", 5), "note": saved_notes.get("tep_ТР1", "")},
        {"kind": "row", "key": "tep_ТР2", "label": "ТР2", "plan": count("plan", "tep", "ТР2", 10), "fact": count("fact", "tep", "ТР2", 10), "note": saved_notes.get("tep_ТР2", "")},
        {"kind": "row", "key": "tep_ТР3", "label": "ТР3", "plan": count("plan", "tep", "ТР3", 15), "fact": count("fact", "tep", "ТР3", 15), "note": saved_notes.get("tep_ТР3", "")},
        {"kind": "row", "key": "tep_ТР_unplan", "label": "ТР (текущий ремонт)", "plan": format_n(data["ub"]["plan"]["tep"]), "fact": format_n(data["ub"]["fact"]["tep"]), "note": merge_notes(saved_notes.get("tep_ТР_unplan", ""), tep_notes)},
        {"kind": "group", "label": "Кол-во тех.испр. локомотивов\nАГРЕГАТЫ ТЯГОВЫЕ", "plan": format_n(data["ap"]), "fact": format_n(data["af"]), "note_key": "agr_park", "note": saved_notes.get("agr_park", "")},
        {"kind": "row", "key": "agr_ТО", "label": "ТО", "plan": count("plan", "agr", "ТО", 1), "fact": count("fact", "agr", "ТО", 1), "note": saved_notes.get("agr_ТО", "")},
        {"kind": "row", "key": "agr_ТР", "label": "ТР", "plan": count("plan", "agr", "ТР", 5), "fact": count("fact", "agr", "ТР", 5), "note": saved_notes.get("agr_ТР", "")},
        {"kind": "row", "key": "agr_ТР_unplan", "label": "ТР (текущий ремонт)", "plan": format_n(data["ub"]["plan"]["agr"]), "fact": format_n(data["ub"]["fact"]["agr"]), "note": merge_notes(saved_notes.get("agr_ТР_unplan", ""), agr_notes)},
    ]
    return {"month": month_name, "year": data["y"], "rows": rows}


def build_report_workbook(year: int, month_name: str, state: dict | None = None) -> tuple[bytes, str]:
    try:
        from openpyxl import Workbook, load_workbook
        from openpyxl.styles import Alignment, Font
    except ImportError as exc:
        raise RuntimeError("На сервере не установлен openpyxl") from exc

    state = state or load_state(year)
    data = calculate_report_data_from_state(state, month_name)
    saved_notes = state.get("notes", {}).get(month_name, {}) or {}
    tags = build_report_excel_tags(month_name, data, saved_notes)

    template_path = find_report_template_path()
    if template_path:
        wb = load_workbook(template_path)
        replace_tags_in_workbook(wb, tags)
    else:
        wb = Workbook()
        ws = wb.active
        ws.title = "Отчет"
        for idx, (k, v) in enumerate(tags.items(), start=1):
            ws[f"A{idx}"] = k
            ws[f"B{idx}"] = v
        for cell in ws[1]:
            cell.font = Font(bold=True)
        for row in ws.iter_rows():
            for cell in row:
                cell.alignment = Alignment(horizontal="left", vertical="top")

    out = BytesIO()
    wb.save(out)
    return out.getvalue(), f"Отчет_{month_name}_{year}.xlsx"


def get_act_inventory_item(year: int, number: str) -> tuple[str, str]:
    if not SOURCE_DB.exists():
        return "", ""
    try:
        with sqlite3.connect(SOURCE_DB) as db:
            cur = db.cursor()
            row = cur.execute("SELECT ser, inv FROM inventory WHERE y=? AND num=?", (year, number)).fetchone()
        if not row:
            return "", ""
        return s(row[0]), s(row[1])
    except Exception:
        return "", ""


def format_fio_initials(full_name: str) -> str:
    parts = s(full_name).split()
    if len(parts) >= 3:
        return f"{parts[0]} {parts[1][0]}. {parts[2][0]}."
    if len(parts) == 2:
        return f"{parts[0]} {parts[1][0]}."
    return s(full_name).strip()


def get_all_employee_names() -> list[str]:
    try:
        if not SOURCE_DB.exists():
            return []
        with sqlite3.connect(SOURCE_DB) as db:
            cur = db.cursor()
            cur.execute(
                "SELECT DISTINCT CASE WHEN COALESCE(full_name, '') != '' THEN full_name ELSE name END "
                "FROM employees ORDER BY 1"
            )
            return [s(row[0]).strip() for row in cur.fetchall() if s(row[0]).strip()]
    except Exception:
        return []


def replace_tags_in_workbook(wb, tags: dict[str, str]) -> None:
    for sheet in wb.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                if isinstance(cell.value, str) and cell.value:
                    value = cell.value
                    for tag, rep in tags.items():
                        if tag in value:
                            value = value.replace(tag, s(rep))
                    cell.value = value


def build_act_workbook(year: int, act: str) -> tuple[bytes, str]:
    try:
        from openpyxl import Workbook, load_workbook
        from openpyxl.styles import Alignment, Font
    except ImportError as exc:
        raise RuntimeError("На сервере не установлен openpyxl") from exc

    clean_act_num = act.replace("Акт № ", "").strip()
    parts = clean_act_num.split("-")
    if len(parts) != 3:
        raise ValueError("Не удалось распознать формат акта")

    d_act, m_act, num_act = parts
    months_ru = {
        "01": "января", "02": "февраля", "03": "марта",
        "04": "апреля", "05": "мая", "06": "июня",
        "07": "июля", "08": "августа", "09": "сентября",
        "10": "октября", "11": "ноября", "12": "декабря",
    }
    date_str = f"{d_act} {months_ru.get(m_act, 'января')} {year} г."
    ser, inv = get_act_inventory_item(year, num_act)
    if "ПЭ" in ser.upper():
        eq_type = "Тяговый агрегат"
    elif ser:
        eq_type = "Тепловоз маневровый"
    else:
        eq_type = ""

    tags = {
        "[АКТ]": clean_act_num, "[Акт]": clean_act_num, "[акт]": clean_act_num,
        "[ДАТА]": date_str, "[Дата]": date_str,
        "[НОМЕР]": num_act, "[Номер]": num_act,
        "[АГРЕГАТ]": eq_type, "[Агрегат]": eq_type,
        "[СЕРИЯ]": ser, "[Серия]": ser,
        "[ИНВ]": inv, "[Инв]": inv,
    }

    template_path = find_act_template_path()
    if template_path:
        wb = load_workbook(template_path)
        replace_tags_in_workbook(wb, tags)
    else:
        wb = Workbook()
        ws = wb.active
        ws.title = "Акт"
        ws["A1"] = "Акт"
        ws["B1"] = clean_act_num
        ws["A2"] = "Дата"
        ws["B2"] = date_str
        ws["A3"] = "Серия"
        ws["B3"] = ser
        ws["A4"] = "Инвентарный номер"
        ws["B4"] = inv
        ws["A5"] = "Тип"
        ws["B5"] = eq_type
        for cell in ws[1]:
            cell.font = Font(bold=True)
        for cell in ws["A1:B5"]:
            for item in cell:
                item.alignment = Alignment(horizontal="left")

    out = BytesIO()
    wb.save(out)
    return out.getvalue(), f"Акт_{clean_act_num}.xlsx"


def build_tu28_workbook(year: int, month_name: str, row_idx: int, staff_list: list[str] | None = None, state: dict | None = None, extra_repairs: list[str] | None = None) -> tuple[bytes, str]:
    try:
        from openpyxl import Workbook, load_workbook
        from openpyxl.styles import Alignment, Font
    except ImportError as exc:
        raise RuntimeError("На сервере не установлен openpyxl") from exc

    state = state or load_state(year)
    month = next((m for m in state.get("months", []) if s(m.get("name")) == month_name), None)
    if not month:
        raise ValueError("Не удалось найти месяц")
    fact_rows = month.get("fact") or []
    if row_idx < 0 or row_idx >= len(fact_rows):
        raise ValueError("Не удалось найти строку ремонта")
    row = fact_rows[row_idx]
    cells = row.get("cells") or []
    series = s(cells[1]).strip()
    number = s(cells[2]).strip()
    if not number:
        raise ValueError("Не удалось определить номер")

    repair_code = ""
    repair_days = []
    for col in range(4, 4 + int(month.get("days") or 0)):
        value = normalize_repair_code(s(cells[col]) if col < len(cells) else "")
        if value in TU28_REPAIR_CODES:
            if not repair_code:
                repair_code = s(cells[col]).strip().upper()
            repair_days.append(col - 3)
    if not repair_days:
        raise ValueError("В выбранной строке не найден ремонт для ТУ-28")

    if "ПЭ" in series.upper():
        eq_type = "Тяговый агрегат"
    elif series:
        eq_type = "Тепловоз маневровый"
    else:
        eq_type = ""

    try:
        month_num = int(month.get("month") or 0)
    except Exception:
        month_num = 0
    repair_day = repair_days[0]
    date_str = f"{repair_day:02d}.{month_num:02d}.{year}"

    start_date_str = f"{year}-{month_num:02d}-{repair_days[0]:02d}"
    end_date_str = f"{year}-{month_num:02d}-{repair_days[-1]:02d}"

    db_path = Path(__file__).resolve().parent.parent / "base" / "common_database.db"
    measurements = {}
    if db_path.exists() and number and start_date_str and end_date_str:
        import sqlite3
        try:
            with sqlite3.connect(db_path) as conn:
                cur = conn.cursor()
                db_rows = cur.execute(
                    """
                    SELECT measurement_date, r, c, v 
                    FROM archive_data 
                    WHERE locomotive=? AND measurement_date >= ? AND measurement_date <= ?
                    ORDER BY measurement_date DESC, r, c
                    """,
                    (number, start_date_str, end_date_str)
                ).fetchall()
                dates_dict = {}
                for d_str, r, c, v in db_rows:
                    if d_str not in dates_dict:
                        dates_dict[d_str] = {}
                    dates_dict[d_str].setdefault(r, {})[c] = str(v).strip() if v else ""
                if dates_dict:
                    best_date = sorted(dates_dict.keys(), reverse=True)[0]
                    measurements = dates_dict[best_date]
        except Exception as e:
            print("Error reading Zamer KP archive db:", e)
    tags = {
        "[СЕРИЯ]": series,
        "[НОМЕР]": number,
        "[ДАТА]": date_str,
        "[ВИД]": repair_code,
        "[АГРЕГАТ]": eq_type,
        "[ДИЗЕЛЬ]": "",
        "[ЭКИПАЖ 1]": "",
        "[ЭКИПАЖ 2]": "",
        "[АКБ]": "",
        "[ЭЛМАШ]": "",
        "[ЭЛАП]": "",
        "[ТОРМОЗ]": "",
    }

    col_to_tag_prefix = {
        0: "ПРОКАТ_ЛЕВ", 1: "ПРОКАТ_ПРАВ",
        2: "ТОЛЩИНА_ГРЕБНЯ_ЛЕВ", 3: "ТОЛЩИНА_ГРЕБНЯ_ПРАВ",
        4: "КРУТИЗНА_ЛЕВ", 5: "КРУТИЗНА_ПРАВ",
        6: "ТОЛЩИНА_БАНДАЖА_ЛЕВ", 7: "ТОЛЩИНА_БАНДАЖА_ПРАВ",
        8: "ДИАМЕТР_БАНДАЖА_ЛЕВ", 9: "ДИАМЕТР_БАНДАЖА_ПРАВ"
    }
    for axle in range(1, 13):
        for c_idx, prefix in col_to_tag_prefix.items():
            tags[f"[{prefix}_{axle}]"] = measurements.get(axle - 1, {}).get(c_idx, "")

    components = [
        "ДИЗЕЛЬ",
        "ЭКИПАЖ 1",
        "ЭКИПАЖ 2",
        "АКБ",
        "ЭЛМАШ",
        "ЭЛАП",
        "ТОРМОЗ",
    ]
    for idx, name in enumerate(staff_list or []):
        if idx >= len(components):
            break
        tags[f"[{components[idx]}]"] = format_fio_initials(name)

    extra_repairs = extra_repairs or []
    print(f"DEBUG: build_tu28_workbook received extra_repairs={extra_repairs}", flush=True)
    for i in range(1, 21):
        tags[f"[ДОП_РЕМОНТ_{i}]"] = ""
    for i, extra in enumerate(extra_repairs, start=1):
        if i <= 20:
            tags[f"[ДОП_РЕМОНТ_{i}]"] = str(extra).strip()
    print(f"DEBUG: tags built: {[k for k in tags.keys() if 'ДОП' in k and tags[k]]}", flush=True)

    template_path = find_tu28_template_path()
    if template_path:
        wb = load_workbook(template_path)
        replace_tags_in_workbook(wb, tags)
    else:
        wb = Workbook()
        ws = wb.active
        ws.title = "ТУ-28"
        for idx, (k, v) in enumerate(tags.items(), start=1):
            ws[f"A{idx}"] = k
            ws[f"B{idx}"] = v
        for cell in ws[1]:
            cell.font = Font(bold=True)
        for row_cells in ws.iter_rows():
            for cell in row_cells:
                cell.alignment = Alignment(horizontal="left", vertical="top")

    out = BytesIO()
    wb.save(out)
    return out.getvalue(), f"ТУ-28_{month_name}_{year}.xlsx"


def content_disposition_attachment(filename: str) -> str:
    ascii_name = filename.encode("ascii", "ignore").decode("ascii") or "file.xlsx"
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


def save_state(state: dict) -> dict:
    year = int(state.get("year") or dt.date.today().year)
    with DB_LOCK, conn() as db:
        cur = db.cursor()
        with db:
            cur.execute("DELETE FROM repairs WHERE y=?", (year,))
            cur.execute("DELETE FROM norms WHERE y=?", (year,))
            cur.execute("DELETE FROM acts_state WHERE y=?", (year,))
            cur.execute("DELETE FROM report_notes WHERE y=?", (year,))
            cur.execute("INSERT OR REPLACE INTO repair_settings VALUES ('last_year', ?)", (str(year),))

            for month in state.get("months", []):
                month_name = s(month.get("name"))
                for table_type in ["plan", "fact"]:
                    for r, row in enumerate(month.get(table_type, [])):
                        if row.get("excluded"):
                            cur.execute("INSERT INTO repairs VALUES (?,?,?,?,?,?)", (year, month_name, table_type, r, -1, "EXC"))
                        cells = row.get("cells", [])
                        for c, value in enumerate(cells):
                            value = s(value).strip()
                            if value:
                                if c == 3:
                                    continue
                                db_c = 999 if c == len(cells) - 1 else (c - 1 if c >= 4 else c)
                                cur.execute("INSERT INTO repairs VALUES (?,?,?,?,?,?)", (year, month_name, table_type, r, db_c, value))

            for cat, rows in state.get("norms", {}).items():
                for row in rows:
                    k = s(row.get("k")).strip()
                    v = s(row.get("v")).strip()
                    if k or v:
                        cur.execute("INSERT INTO norms VALUES (?,?,?,?)", (year, cat, k, v))

            for m_name, acts in state.get("acts", {}).items():
                for act_num, flags in acts.items():
                    cur.execute(
                        "INSERT INTO acts_state VALUES (?,?,?,?,?)",
                        (year, m_name, act_num, 1 if flags.get("is_done") else 0, 1 if flags.get("sap_order_done") else 0),
                    )

            for m_name, keys in state.get("notes", {}).items():
                for key, value in keys.items():
                    value = s(value)
                    if value:
                        cur.execute("INSERT INTO report_notes VALUES (?,?,?,?)", (year, m_name, key, value))

    return load_state(year)


def json_response(handler: BaseHTTPRequestHandler, payload: dict, status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
    handler.send_header("Pragma", "no-cache")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _cookie_value(username: str, role: str) -> str:
    payload = f"{username}:{role}:{int(dt.datetime.now().timestamp())}"
    signature = hmac.new(WEB_SECRET.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}:{signature}"


def _verify_cookie(value: str) -> tuple[str, str, str, str] | None:
    for sep in (":", "|"):
        try:
            parts = value.rsplit(sep, 5)
            if len(parts) == 6:
                user_id, role, modules, safe_name, expiry_text, sig = parts
                payload = f"{user_id}{sep}{role}{sep}{modules}{sep}{safe_name}{sep}{expiry_text}"
            elif len(parts) == 4:
                username, role, expiry_text, sig = parts
                payload = f"{username}{sep}{role}{sep}{expiry_text}"
                user_id, modules, safe_name = username, "", username
            else:
                continue
                
            secrets_to_try = [WEB_SECRET]
                
            matched = False
            import hmac
            import hashlib
            for secret in secrets_to_try:
                expected = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
                if hmac.compare_digest(expected, sig):
                    matched = True
                    break
                    
            if not matched:
                continue
            import datetime as dt
            if float(expiry_text) < dt.datetime.now().timestamp():
                return None
                
            import urllib.parse
            return user_id, role, modules, urllib.parse.unquote(safe_name)
        except Exception:
            continue
    return None

def parse_cookie_values(handler, name: str) -> list[str]:
    raw = handler.headers.get("Cookie", "")
    values = []
    for part in raw.split(";"):
        if "=" not in part: continue
        k, v = part.split("=", 1)
        if k.strip() == name: values.append(v.strip())
    return values


def current_session(handler: BaseHTTPRequestHandler) -> tuple[str, str, str, str] | None:
    for token in parse_cookie_values(handler, SESSION_COOKIE):
        session = _verify_cookie(token)
        if session:
            user_id, role, modules, safe_name = session
            SESSIONS[token] = (user_id, role, modules, safe_name, dt.datetime.now().timestamp())
            return session
        else:
            try:
                with open(ROOT.parent / "data" / "grafik_auth.log", "a", encoding="utf-8") as f:
                    f.write(f"Token verification failed for token: {token}\n")
            except Exception:
                pass
    return None


def get_mod_role(session: tuple[str, str, str, str] | None, mod_name: str) -> str | None:
    if not session: return None
    role = session[1]
    modules = session[2]
    for part in modules.split(","):
        part = part.strip()
        if not part: continue
        if ":" in part:
            k, v = part.split(":", 1)
            if k == mod_name: return v
        else:
            if part == mod_name: return role
    if role == "admin": return "admin"
    return None

def require_auth(handler: BaseHTTPRequestHandler, need_edit: bool = False) -> bool:
    if not AUTH_ENABLED:
        return True
    session = current_session(handler)
    mod_role = get_mod_role(session, "grafik_ppr")
    if mod_role and (not need_edit or mod_role in ("edit", "editor", "admin")):
        return True
    handler.send_response(HTTPStatus.UNAUTHORIZED)
    handler.send_header("Content-Type", "text/plain; charset=utf-8")
    handler.send_header("WWW-Authenticate", 'Form realm="Grafik PPR"')
    handler.end_headers()
    handler.wfile.write("Требуется вход".encode("utf-8"))
    return False


def render_page(state: dict, can_edit: bool, username: str | None) -> str:
    state_json = json.dumps(state, ensure_ascii=False).replace("</", "<\\/")
    employees_json = json.dumps(get_all_employee_names(), ensure_ascii=False).replace("</", "<\\/")
    started_at = SERVER_STARTED_AT.strftime("%H:%M:%S %d.%m.%Y") if SERVER_STARTED_AT else "неизвестно"
    toolbar = EDIT_TOOLBAR if can_edit else READONLY_TOOLBAR
    return (
        HTML_TEMPLATE.replace("{{STATE_JSON}}", state_json)
        .replace("{{EMPLOYEE_NAMES}}", employees_json)
        .replace("{{STARTED_AT}}", started_at)
        .replace("{{APP_VERSION}}", APP_VERSION)
        .replace("{{TOOLBAR}}", toolbar)
        .replace("{{CAN_EDIT}}", "true" if can_edit else "false")
        .replace("{{APP_PREFIX}}", APP_PREFIX)
        .replace("{{TEM_NORM_ROWS}}", json.dumps(TEM_NORM_ROWS, ensure_ascii=False))
        .replace("{{AGR_NORM_ROWS}}", json.dumps(AGR_NORM_ROWS, ensure_ascii=False))
    )


def _route_path(path: str) -> str:
    if path == APP_PREFIX:
        return "/grafik-ppr"
    if path.startswith(APP_PREFIX + "/"):
        return path[len(APP_PREFIX):]
    return path


def render_login(extra: str = "") -> str:
    return (
        LOGIN_TEMPLATE.replace("{{USER}}", WEB_USER)
        .replace("{{APP_PREFIX}}", APP_PREFIX)
        + extra
    )


EDIT_TOOLBAR = """
      <div class="toolbar">
        <label>Год <select id="yearInput" onchange="loadYearFromInput()"></select></label>
        <button onclick="openReport()">Отчет</button>
        <button id="saveButton" onclick="saveState()">Сохранить</button>
        <div class="json-menu" id="jsonMenuWrap">
          <button type="button" onclick="toggleJsonMenu(event)">JSON</button>
          <div class="json-menu-panel" id="jsonMenuPanel" aria-hidden="true">
            <button type="button" onclick="downloadJson(); closeJsonMenu()">Экспорт JSON</button>
            <button type="button" onclick="triggerImportJson()">Импорт JSON</button>
          </div>
        </div>
        <input id="importFile" type="file" accept=".json,application/json" style="display:none" onchange="importJson(event)">
      </div>
"""

READONLY_TOOLBAR = """
      <div class="toolbar">
        <label>Год <select id="yearInput" onchange="loadYearFromInput()"></select></label>
        <button onclick="openReport()">Отчет</button>
      </div>
"""

LOGIN_TEMPLATE = """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Вход - График ППР</title>
  <style>
    body { margin:0; font-family:Segoe UI, Arial, sans-serif; background:#f4f7fb; color:#102033; }
    .card { max-width:420px; margin:10vh auto; background:#fff; border:1px solid #d9e2ef; border-radius:18px; padding:24px; box-shadow:0 12px 32px rgba(16,32,51,.08); }
    input,button { width:100%; padding:12px; border-radius:8px; border:1px solid #d9e2ef; font:inherit; }
    button { background:transparent; color:#1d4ed8; font-weight:700; cursor:pointer; border-color:#2f6fed; }
    .muted { color:#607086; font-size:13px; }
  </style>
</head>
<body>
  <form class="card" method="post" action="{{APP_PREFIX}}/login">
    <h1 style="margin-top:0;">Вход</h1>
    <p class="muted">Введите пароль для входа.</p>
    <input name="user" placeholder="Логин" value="{{USER}}" style="margin-bottom:10px;">
    <input name="password" type="password" placeholder="Пароль" style="margin-bottom:12px;">
    <button type="submit">Войти</button>
  </form>
</body>
</html>
"""


HOME_TEMPLATE = """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>РТПС - Главная</title>
  <style>
    :root { --bg:#f4f7fb; --card:#ffffff; --line:#d9e2ef; --text:#102033; --muted:#66758a; --blue:#276ef1; --soft:#eef4ff; }
    * { box-sizing:border-box; }
    body { margin:0; font-family:Segoe UI, Arial, sans-serif; background:linear-gradient(180deg,#f8fbff 0%, #eef4fb 100%); color:var(--text); }
    .wrap { max-width:1180px; margin:0 auto; padding:28px 20px 36px; }
    .hero { display:flex; justify-content:space-between; gap:16px; align-items:flex-start; background:rgba(255,255,255,.8); border:1px solid var(--line); border-radius:24px; padding:24px; box-shadow:0 12px 32px rgba(16,32,51,.06); backdrop-filter:blur(8px); }
    .title { font-size:34px; line-height:1.05; margin:0 0 10px; }
    .sub { margin:0; color:var(--muted); font-size:14px; max-width:720px; }
    .badge { display:inline-flex; align-items:center; gap:8px; padding:10px 14px; border-radius:8px; background:var(--soft); color:#1d4ed8; font-weight:700; text-decoration:none; border:1px solid #cfe0ff; white-space:nowrap; }
    .top-right { display:flex; flex-direction:column; gap:10px; align-items:flex-end; }
    .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(250px,1fr)); gap:16px; margin-top:18px; }
    .card { background:var(--card); border:1px solid var(--line); border-radius:20px; padding:18px; box-shadow:0 10px 28px rgba(16,32,51,.05); min-height:160px; display:flex; flex-direction:column; justify-content:space-between; }
    .card h2 { margin:0 0 8px; font-size:18px; }
    .card p { margin:0; color:var(--muted); font-size:13px; line-height:1.4; }
    .card a { display:inline-flex; margin-top:14px; width:fit-content; align-items:center; gap:8px; padding:10px 14px; border-radius:8px; background:var(--blue); color:#fff; text-decoration:none; font-weight:700; }
    .card .disabled { opacity:.45; cursor:default; pointer-events:none; }
    .status { font-size:12px; color:var(--muted); margin-top:12px; }
    @media (max-width: 720px) {
      .hero { flex-direction:column; }
      .top-right { align-items:flex-start; }
      .title { font-size:28px; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hero">
      <div>
        <h1 class="title">Участок РТПС</h1>
        <p class="sub">Стартовая страница для запуска веб-приложений. Сейчас доступен веб-график ППР, остальные модули можно подключать сюда по мере готовности.</p>
      </div>
      <div class="top-right">
      </div>
    </div>

    <div class="grid">
      <div class="card">
        <div>
          <h2>График ППР</h2>
          <p>План, факт, нормы, инвентарь и акты. Основной рабочий модуль уже перенесён на сервер.</p>
        </div>
        <a href="{{APP_PREFIX}}/">Открыть</a>
      </div>
      <div class="card">
        <div>
          <h2>Замер КП</h2>
          <p>Локальный модуль из desktop-версии. Пока не подключён к вебу.</p>
        </div>
        <a class="disabled" href="#">Скоро</a>
      </div>
      <div class="card">
        <div>
          <h2>Табель учета</h2>
          <p>Отдельное приложение для учёта времени. Подключим следующим шагом.</p>
        </div>
        <a class="disabled" href="#">Скоро</a>
      </div>
      <div class="card">
        <div>
          <h2>АЛСН</h2>
          <p>Следующий модуль из набора РТПС. Сейчас заглушка.</p>
        </div>
        <a class="disabled" href="#">Скоро</a>
      </div>
      <div class="card">
        <div>
          <h2>Обучение</h2>
          <p>Веб-доступ появится после переноса приложения на сервер.</p>
        </div>
        <a class="disabled" href="#">Скоро</a>
      </div>
      <div class="card">
        <div>
          <h2>Справочник</h2>
          <p>Справочные данные и настройки. Будет доступен через этот же хаб.</p>
        </div>
        <a class="disabled" href="#">Скоро</a>
      </div>
    </div>
    <div class="status">Сервер запущен: {{STARTED_AT}}</div>
  </div>
</body>
</html>
"""


def _send_html(handler: BaseHTTPRequestHandler, body: str, status: int = 200) -> None:
    data = body.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
    handler.send_header("Pragma", "no-cache")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def _redirect(handler: BaseHTTPRequestHandler, location: str, cookie: str | None = None) -> None:
    handler.send_response(HTTPStatus.SEE_OTHER)
    handler.send_header("Location", location)
    handler.send_header("Cache-Control", "no-store")
    if cookie is not None:
        handler.send_header("Set-Cookie", cookie)
    handler.end_headers()


def render_home(username: str | None, can_edit: bool) -> str:
    started_at = SERVER_STARTED_AT.strftime("%H:%M:%S %d.%m.%Y") if SERVER_STARTED_AT else "неизвестно"
    return (
        HOME_TEMPLATE.replace("{{STARTED_AT}}", started_at)
    )


def _login_cookie(username: str, role: str) -> str:
    token = _cookie_value(username, role)
    SESSIONS[token] = (username, role, "", username, dt.datetime.now().timestamp())
    return f"{SESSION_COOKIE}={token}; HttpOnly; Path=/; SameSite=Lax"

HTML_TEMPLATE = """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>График ППР web {{APP_VERSION}}</title>
  <style>
    :root { --bg:#f4f7fb; --card:#fff; --line:#d9e2ef; --text:#102033; --muted:#607086; --accent:#276ef1; --soft:#eaf1ff; --shadow:0 12px 32px rgba(16,32,51,.08); --radius:18px; --meta-col-width:110px; --series-col-width:100px; --number-col-width:72px; --cat-col-width:100px; }
    * { box-sizing:border-box; }
    body { margin:0; font-family:"Segoe UI", Arial, sans-serif; background:linear-gradient(180deg,#e8eefb, #f7f9fc 150px) fixed; color:var(--text); }
    .shell { max-width:1700px; margin:0 auto; padding:18px; }
    .topbar,.panel { background:rgba(255,255,255,.88); border:1px solid var(--accent); border-radius:var(--radius); box-shadow:var(--shadow); }
    .topbar {
      position:sticky;
      top:12px;
      z-index:30;
      display:flex;
      gap:14px;
      align-items:center;
      justify-content:space-between;
      padding:14px 16px;
      margin-bottom:14px;
      flex-wrap:wrap;
      backdrop-filter:blur(10px);
    }
    .titlebox h1 { margin:0; font-size:22px; }
    .titlebox .sub { color:var(--muted); font-size:13px; margin-top:2px; }
    .toolbar { display:flex; flex-wrap:wrap; gap:10px; align-items:center; }
    button { border:1px solid var(--accent); border-radius:8px; background:transparent; padding:10px 12px; font:inherit; color:var(--accent); cursor:pointer; }
    button:hover:not(:disabled) { border-color:var(--accent); color:var(--accent); }
    button:disabled { opacity:.55; cursor:default; }
    .toolbar input,select,textarea { border:1px solid var(--line); border-radius:8px; background:#fff; padding:10px 12px; font:inherit; }
    .toolbar #yearInput { border-color:var(--accent); }
    .toolbar button { font-weight:400; }
    .toolbar button.save-ready { background:var(--accent); border-color:var(--accent); color:#fff; }
    .toolbar button.save-ready:hover { background:#1f63df; border-color:#1f63df; color:#fff; }
    .home-link { border:1px solid var(--accent); border-radius:8px; background:#fff; padding:10px 12px; color:var(--accent); font:inherit; font-weight:400; text-decoration:none; box-shadow:0 4px 12px rgba(16,32,51,.06); }
    .json-menu { position:relative; display:inline-flex; }
    .json-menu > button { min-width:84px; }
    .json-menu-panel {
      position:absolute;
      right:0;
      top:calc(100% + 6px);
      display:none;
      flex-direction:column;
      gap:6px;
      padding:8px;
      background:#fff;
      border:1px solid var(--accent);
      border-radius:12px;
      box-shadow:0 16px 30px rgba(16,32,51,.12);
      z-index:40;
      min-width:168px;
    }
    .json-menu.open .json-menu-panel { display:flex; }
    .json-menu-panel button { width:100%; text-align:left; border:1px solid var(--accent); }
    .nav { display:flex; gap:10px; flex-wrap:wrap; padding:0; margin:0; background:transparent; border:0; box-shadow:none; }
    .nav button { font-weight:400; box-shadow:none; }
    .nav button.active { border-color:var(--accent); color:var(--accent); box-shadow:inset 0 -3px 0 var(--accent); }
    .controls { display:flex; gap:8px; align-items:center; flex-wrap:wrap; justify-content:flex-end; }
    .panel { padding:14px; }
    .section-head { display:flex; flex-wrap:wrap; gap:10px; justify-content:space-between; align-items:center; margin-bottom:10px; }
    .section-title { font-size:18px; font-weight:800; }
    .month-table-head { display:grid; grid-template-columns:auto minmax(0, 1fr) auto; gap:10px; align-items:center; }
    .month-table-actions { justify-self:start; min-width:0; }
    .month-table-title { justify-self:center; text-align:center; }
    .months-row { position:sticky; top:0; z-index:4; display:flex; align-items:flex-start; gap:10px; margin:6px 0 10px; background:rgba(255,255,255,.96); padding:0 0 6px; }
    .months-row .month-strip { display:flex; gap:2px; flex-wrap:nowrap; min-width:0; width:100%; overflow:visible; }
    .months-row .row-actions { display:none; }
    .month-strip button { border:1px solid var(--accent); background:transparent; border-radius:8px; padding:6px 10px; font-weight:700; font-size:14px; cursor:pointer; white-space:nowrap; }
    .month-strip button.active { background:var(--accent); border-color:var(--accent); color:#fff; box-shadow:none; }
    .repair-strip { display:flex; gap:3px; flex-wrap:nowrap; margin:0; justify-content:center; }
    .repair-strip button { border:1px solid var(--accent); background:transparent; border-radius:8px; padding:4px 7px; font-weight:700; font-size:12px; cursor:pointer; min-width:40px; }
    .month-tools { display:none; }
    .row-actions { display:flex; gap:4px; align-items:center; justify-content:flex-end; flex-shrink:0; }
    .row-actions button { border:1px solid var(--accent); background:transparent; border-radius:8px; padding:6px 10px; font-weight:700; font-size:14px; cursor:pointer; white-space:nowrap; }
    .row-actions button.danger { border-color:var(--accent); color:var(--accent); }
    .act-report {
      border:1px solid var(--accent);
      background:transparent;
      border-radius:8px;
      padding:6px 10px;
      font:inherit;
      font-weight:700;
      font-size:15px;
      cursor:pointer;
      white-space:nowrap;
    }
    .modal-overlay {
      position:fixed;
      inset:0;
      background:rgba(12,22,38,.45);
      display:none;
      align-items:center;
      justify-content:center;
      padding:18px;
      z-index:50;
    }
    .modal-overlay.visible { display:flex; }
    .modal-window {
      width:min(840px, 100%);
      max-height:calc(100vh - 36px);
      background:#fff;
      border:1px solid rgba(217,226,239,.95);
      border-radius:18px;
      box-shadow:0 24px 70px rgba(16,32,51,.25);
      display:flex;
      flex-direction:column;
      overflow:hidden;
    }
    .modal-window.wide { width:fit-content; max-width:calc(100vw - 36px); }
    .modal-head {
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:12px;
      padding:8px 10px;
      border-bottom:1px solid var(--line);
      font-size:16px;
      font-weight:800;
    }
    .modal-close {
      border:1px solid var(--accent);
      background:transparent;
      border-radius:8px;
      width:30px;
      height:30px;
      cursor:pointer;
      font-weight:700;
      line-height:1;
    }
    .modal-body {
      padding:8px 10px;
      overflow:auto;
    }
    .modal-actions {
      display:flex;
      gap:8px;
      padding:8px 10px 10px;
      border-top:1px solid var(--line);
      background:#fafcff;
    }
    .modal-actions button {
      flex:1;
      border:1px solid var(--accent);
      background:transparent;
      border-radius:8px;
      padding:8px 10px;
      font:inherit;
      font-weight:700;
      font-size:16px;
      cursor:pointer;
    }
    .modal-actions button.primary { border-color:var(--accent); color:var(--accent); }
    .leave-window {
      width:min(460px, calc(100vw - 36px));
    }
    .leave-body {
      padding:18px 18px 8px;
      text-align:center;
      color:var(--text);
      font-size:16px;
      line-height:1.45;
    }
    .report-table { width:max-content; min-width:0; table-layout:auto; border-collapse:separate; border-spacing:0; }
    .report-table th, .report-table td { border-right:1px solid var(--line); border-bottom:1px solid var(--line); padding:2px 4px; vertical-align:middle; background:#fff; }
    .report-table th { position:sticky; top:0; background:linear-gradient(180deg,#f8fbff,#edf4ff); font-size:16px; padding:4px 6px; text-align:center; white-space:nowrap; }
    .report-table td { font-size:16px; }
    .report-table .col-report-name { width:280px; }
    .report-table .col-report-num { width:90px; }
    .report-table .col-report-note { width:360px; }
    .report-table tr.group-row > td,
    .report-table tr.group-row > th {
      background:#f2f2f2 !important;
      box-shadow:inset 0 0 0 9999px #f2f2f2 !important;
    }
    .report-table tr.excluded-row > td,
    .report-table tr.excluded-row > th {
      background:#f3f5f8 !important;
      box-shadow:inset 0 0 0 9999px #f3f5f8 !important;
    }
    .report-wrap { padding:0 !important; background:#fff; }
    #reportModal .modal-head,
    #normsModal .modal-head,
    #actsModal .modal-head {
      display:grid !important;
      grid-template-columns:30px minmax(0, 1fr) 30px;
      align-items:center;
      justify-content:normal;
      text-align:center;
    }
    #reportTitle {
      position:static !important;
      transform:none !important;
      grid-column:2;
      justify-self:center;
      width:auto;
      max-width:100%;
      text-align:center;
      font-weight:800;
    }
    #reportModal .modal-head .section-title,
    #normsModal .modal-head .section-title,
    #actsModal .modal-head .section-title {
      grid-column:2;
      justify-self:center;
      margin:0 !important;
      text-align:center;
    }
    #normsModal .table-wrap {
      width:100% !important;
      max-width:none !important;
    }
    #reportModal .modal-close,
    #normsModal .modal-close,
    #actsModal .modal-close {
      position:static !important;
      transform:none !important;
      grid-column:3;
      justify-self:end;
    }
    #reportModal .modal-body { padding-left:12px !important; padding-right:12px !important; }
    #reportModal .table-wrap { padding-left:0 !important; padding-right:0 !important; }
    #reportModal .report-table { margin-left:0 !important; border-left:0; }
    #reportModal .report-table tr.group-row > *:first-child,
    #reportModal .report-table tr.excluded-row > *:first-child {
      background-clip:border-box !important;
      box-shadow:inset 9999px 0 0 #f2f2f2, inset 0 0 0 9999px #f2f2f2 !important;
    }
    #reportModal .report-table tr.excluded-row > *:first-child {
      box-shadow:inset 9999px 0 0 #f3f5f8, inset 0 0 0 9999px #f3f5f8 !important;
    }
    .report-table tr.group-row { background:#f2f2f2 !important; }
    .report-table tr.excluded-row { background:#f3f5f8 !important; }
    .report-table tr > *:last-child { border-right:0; }
    .report-table tbody tr:last-child > * { border-bottom:0; }
    .report-table tr.group-row > * { background:#f2f2f2 !important; }
    .report-table tr.excluded-row > * { background:#f3f5f8 !important; color:#9aa5b1; }
    .report-table td:first-child { text-align:right; padding-right:10px; }
    .report-table .group-cell { font-weight:800; padding:4px 10px 4px 6px; white-space:pre-line; text-align:right; }
    .report-table .num-cell { text-align:center; padding:4px 4px; white-space:nowrap; }
    .report-table tbody tr { height:auto; }
    .report-note {
      width:100%;
      min-height:16px;
      height:auto;
      resize:none;
      overflow:hidden;
      border:0;
      background:transparent;
      font:inherit;
      font-size:16px;
      line-height:1;
      padding:0 3px;
      box-sizing:border-box;
    }
    .report-act-hint {
      margin-top:4px;
      font-size:12px;
      line-height:1.25;
      color:#48607c;
      white-space:pre-wrap;
    }
    .report-loading { padding:10px; text-align:center; color:var(--muted); font-size:16px; }
    .section-modal-body { padding:8px 14px; overflow:auto; }
    .section-modal-body.centered { text-align:center; }
    .acts-table { font-size:16px; }
    .acts-table th,
    .acts-table td { text-align:center; font-size:16px; }
    .acts-table th { white-space:normal; line-height:1.1; }
    #tu28Modal .acts-table th,
    #tu28Modal .acts-table td { padding:6px 14px; }
    #tu28StaffModal .table-wrap { width:fit-content; max-width:100%; margin:0 auto; }
    #tu28StaffModal .acts-table { width:max-content; table-layout:auto; }
    #tu28StaffModal .acts-table th,
    #tu28StaffModal .acts-table td { padding:4px 10px; }
    #tu28StaffModal .tu28-staff-select { width:100%; min-width:240px; padding:6px 10px; }
    .acts-table input[type="checkbox"] { display:block; margin:0 auto; transform:scale(1.15); }
    .acts-table td:nth-child(2) { padding:0; }
    .acts-table .act-start { width:100%; height:100%; min-height:34px; display:flex; align-items:center; justify-content:center; font-size:16px; border:1px solid var(--accent); background:transparent; }
    .section-modal-actions {
      display:flex;
      gap:8px;
      padding:8px 10px 10px;
      border-top:1px solid var(--line);
      background:#fafcff;
    }
    .section-modal-actions button {
      flex:1;
      border:1px solid var(--accent);
      background:transparent;
      border-radius:8px;
      padding:8px 10px;
      font:inherit;
      font-weight:700;
      font-size:16px;
      cursor:pointer;
    }
    .section-modal-actions button.primary { border-color:var(--accent); color:var(--accent); }
    .error-modal-text {
      white-space:pre-wrap;
      word-break:break-word;
      font:13px/1.45 Consolas, "Courier New", monospace;
      max-height:50vh;
      overflow:auto;
      border:1px solid var(--line);
      border-radius:12px;
      padding:12px;
      background:#fff7f7;
      color:#7a1620;
      user-select:text;
    }
    .norms-table th,
    .norms-table td { text-align:center; }
    .norms-table td:first-child { text-align:right; padding-right:10px; }
    .norms-table .group-row td { text-align:center; }
    .table-wrap > table.norms-table,
    .table-wrap > table.acts-table { table-layout:auto; width:max-content; min-width:0; }
    #normsModal .table-wrap > table.norms-table {
      width:100%;
      min-width:100%;
    }
    .norms-table th,
    .norms-table td { padding:4px 6px; font-size:16px; }
    .norms-table .cell { height:24px; padding:2px 2px; font-size:16px; }
    .norms-table .col-name { width:50px; }
    .norms-table .col-hours { width:30px; }
    .norms-table .col-month { width:40px; }
    .norms-table .col-tep { width:60px; }
    .norms-table .col-agr { width:60px; }
    .act-start {
      width:100%;
      border:1px solid #9fb4d2;
      background:transparent;
      border-radius:8px;
      padding:8px 12px;
      font:inherit;
      font-weight:700;
      font-size:16px;
      cursor:pointer;
    }
    .act-start:disabled { opacity:.5; cursor:default; }
    .table-wrap { overflow:auto; border:1px solid var(--accent); border-radius:18px; background:#fff; }
    .month-table-wrap { width:fit-content; max-width:100%; margin:0 auto; }
    .table-wrap > table { border-collapse:separate; border-spacing:0; width:100%; min-width:720px; table-layout:fixed; }
    .table-wrap > table th,
    .table-wrap > table td { border-right:1px solid var(--line); border-bottom:1px solid var(--line); padding:0; background:#fff; vertical-align:middle; }
    .table-wrap > table th { position:sticky; top:0; z-index:1; background:linear-gradient(180deg,#f8fbff,#edf4ff); font-size:15px; padding:14px 10px; text-align:center; white-space:nowrap; }
    .table-wrap > table tr > *:last-child { border-right:0; }
    .table-wrap > table tbody tr:last-child > * { border-bottom:0; }
    .cell { display:block; width:100%; min-width:0; box-sizing:border-box; border:0; margin:0; padding:3px 4px; height:100%; min-height:28px; line-height:1; font:inherit; font-size:16px; background:transparent; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; text-transform:uppercase; outline:none; }
    .cell.center { text-align:center; }
    .cell.small { font-size:14px; padding:2px 2px; }
    .col-day { position:relative; padding:0; height:28px; }
    .cell.day-cell {
      display:block;
      width:100%;
      height:100%;
      padding:0;
      margin:0;
      box-sizing:border-box;
      appearance:none;
      -webkit-appearance:none;
      border-radius:0;
      outline:0;
      background-color:transparent !important;
      background-image:none !important;
      box-shadow:none !important;
      -webkit-box-shadow:none !important;
      text-align:center;
      line-height:28px;
    }
    .cell.selected-cell,
    .cell.day-cell.selected-cell,
    td.transfer-col .cell.day-cell.selected-cell,
    td.holiday-col .cell.day-cell.selected-cell {
      background:#e8f0fe !important;
      outline:none;
      position:relative;
      z-index:3;
    }
    .cell.cat-toggle {
      display:block;
      box-sizing:border-box;
      align-items:center;
      width:100%;
      text-align:center;
    }
    .rownum { display:flex; gap:8px; align-items:center; justify-content:center; padding:2px 6px; min-height:28px; font-size:16px; }
    .rowbtn { width:26px; height:26px; border-radius:8px; border:1px solid var(--accent); background:transparent; cursor:pointer; font-weight:800; font-size:15px; }
    .rowbtn.cat-toggle { width:100%; height:30px; border-radius:0; border:0; background:transparent; display:flex; align-items:center; justify-content:center; line-height:1; }
    .badge { padding:5px 10px; border-radius:8px; background:var(--soft); color:#1d4aa6; font-weight:700; }
    .footerbar { margin-top:12px; display:flex; gap:10px; flex-wrap:wrap; align-items:center; justify-content:space-between; color:var(--muted); font-size:13px; }
    .danger { border-color:var(--accent); color:var(--accent); background:transparent; }
    .small { width:100%; min-width:0; text-align:center; font-size:12px; }
    .notes { width:100%; min-height:120px; resize:vertical; padding:10px; border:1px solid var(--line); border-radius:14px; }
    .excluded-row > * { color:#9aa5b1 !important; }
    .excluded-row > td:not(.transfer-col):not(.holiday-col) {
      background:#f3f5f8 !important;
      box-shadow:inset 0 0 0 9999px #f3f5f8 !important;
      padding-top:0 !important;
      padding-bottom:0 !important;
    }
    .excluded-row > td:not(.transfer-col):not(.holiday-col) > .cell,
    .excluded-row > td:not(.transfer-col):not(.holiday-col) > button,
    .excluded-row > td:not(.transfer-col):not(.holiday-col) > textarea {
      background:transparent !important;
      color:#9aa5b1 !important;
      padding-top:0 !important;
      padding-bottom:0 !important;
    }
    .excluded-row input:not(.day-cell) { background:#f3f5f8 !important; color:#9aa5b1 !important; }
    .excluded-row .cell.day-cell { color:#9aa5b1 !important; }
    .table-wrap > table td.transfer-col { background:#dcf8dc !important; }
    .table-wrap > table td.holiday-col { background:#ffdede !important; }
    .table-wrap > table thead th.transfer-col { background:#dcf8dc !important; }
    .table-wrap > table thead th.holiday-col { background:#ffdede !important; }
    .table-wrap > table thead th.transfer-col,
    .table-wrap > table thead th.holiday-col { position:sticky; z-index:2; }
    td.transfer-col,
    td.holiday-col,
    td.col-day { padding:0; height:100%; position:relative; }
    td.transfer-col .cell,
    td.holiday-col .cell { padding:0; height:28px; line-height:28px; }
    td.transfer-col .cell.small,
    td.holiday-col .cell.small { padding:0; height:28px; line-height:28px; }
    td.transfer-col .cell.day-cell { background:#dcf8dc !important; color:#102033 !important; }
    td.holiday-col .cell.day-cell { background:#ffdede !important; color:#102033 !important; }
    td.transfer-col .cell.day-cell::selection,
    td.holiday-col .cell.day-cell::selection { background:rgba(16,32,51,.15); }
    .col-idx { width:36px; }
    .col-series { width:var(--series-col-width); min-width:var(--series-col-width); }
    .col-number { width:var(--number-col-width); }
    .col-number .cell { padding-left:0; padding-right:0; text-align:center; }
    .col-cat { width:var(--cat-col-width); }
    .month-table th:nth-child(3),
    .month-table th:nth-child(4) { white-space:normal; line-height:1.05; }
    .col-day { width:30px; }
    .col-note { width:120px; }
    .grid2 { display:grid; gap:14px; grid-template-columns:1fr; }
    .month-table.compact th,
    .month-table.compact td,
    .norms-table.compact th,
    .norms-table.compact td { font-size:16px; }
    .month-table { table-layout:fixed; width:auto; }
    .month-table tbody tr { height:28px; }
    .group-row td { background:#f5f8fd; font-weight:700; text-align:center; }
    #tu28Modal tr.selected-row > * { background:#e8f0ff !important; box-shadow:inset 0 0 0 1px rgba(39,110,241,.45); }
    @media (max-width:900px) { .topbar { flex-direction:column; align-items:stretch; } .controls { justify-content:flex-start; } .months-row { display:flex; align-items:flex-start; flex-direction:column; position:static; } .month-strip { flex-wrap:wrap; overflow:visible; } .month-tools { display:none; } .repair-strip { flex-wrap:wrap; } }
  </style>
</head>
<body>
  <div class="shell">
    <div class="topbar">
      <div class="titlebox">
        <h1>График ППР</h1>
        <div class="sub">Версия {{APP_VERSION}}</div>
      </div>
      <div class="controls">
      <a class="home-link" href="/" onclick="return requestHomeClick(event)">На главную</a>
      <div class="nav" id="sectionNav"></div>
      {{TOOLBAR}}
      </div>
    </div>
  <div class="panel">
      <div id="content"></div>
    </div>
  </div>
  <div id="leaveModal" class="modal-overlay" aria-hidden="true">
    <div class="modal-window leave-window" onclick="event.stopPropagation()">
      <div class="modal-head">
        <div class="section-title" style="margin:0 auto;">Сохранить изменения?</div>
      </div>
      <div id="leaveMessage" class="leave-body">Есть несохранённые изменения.</div>
      <div class="section-modal-actions">
        <button onclick="resolveLeaveChoice(true)">Да</button>
        <button class="primary" onclick="resolveLeaveChoice(false)">Нет</button>
      </div>
    </div>
  </div>
  <div id="reportModal" class="modal-overlay" aria-hidden="true" onclick="closeReportModal()">
    <div class="modal-window" onclick="event.stopPropagation()">
      <div class="modal-head">
        <div id="reportTitle">Отчет</div>
        <button class="modal-close" onclick="closeReportModal()">×</button>
      </div>
      <div id="reportBody" class="modal-body">
        <div class="report-loading">Подготовка отчета...</div>
      </div>
      <div class="modal-actions">
        <button onclick="downloadReportExcel()">Отчет в Excel</button>
        <button class="primary" onclick="saveReportAndClose()">Сохранить примечания и Закрыть</button>
      </div>
    </div>
  </div>
  <div id="normsModal" class="modal-overlay" aria-hidden="true" onclick="closeNormsModal()">
    <div class="modal-window" style="width:fit-content; max-width:calc(100vw - 36px);" onclick="event.stopPropagation()">
      <div class="modal-head">
        <div class="section-title" style="margin:0 auto;">Нормы / парк</div>
        <button class="modal-close" onclick="closeNormsModal()">×</button>
      </div>
      <div id="normsModalBody" class="section-modal-body"></div>
      <div class="section-modal-actions">
        <button class="primary" onclick="closeNormsModal()">Закрыть</button>
      </div>
    </div>
  </div>
  <div id="actsModal" class="modal-overlay" aria-hidden="true" onclick="closeActsModal()">
    <div class="modal-window wide" style="width:fit-content; max-width:calc(100vw - 36px);" onclick="event.stopPropagation()">
      <div class="modal-head">
        <div class="section-title" style="margin:0 auto;">Акты</div>
        <button class="modal-close" onclick="closeActsModal()">×</button>
      </div>
      <div id="actsModalBody" class="section-modal-body"></div>
      <div class="section-modal-actions">
        <button onclick="saveActsAndClose()">Сохранить и Закрыть</button>
        <button class="primary" onclick="closeActsModal()">Закрыть</button>
      </div>
    </div>
  </div>
  <div id="tu28Modal" class="modal-overlay" aria-hidden="true" onclick="closeTu28Modal()">
    <div class="modal-window wide" style="width:fit-content; max-width:calc(100vw - 36px);" onclick="event.stopPropagation()">
      <div class="modal-head">
        <div class="section-title" style="margin:0 auto;">ТУ-28</div>
        <button class="modal-close" onclick="closeTu28Modal()">×</button>
      </div>
      <div id="tu28ModalBody" class="section-modal-body"></div>
      <div class="section-modal-actions">
        <button onclick="closeTu28Modal()">Закрыть</button>
        <button id="btnTu28Staff" class="primary" onclick="openTu28StaffModal()">Персонал</button>
      </div>
    </div>
  </div>
  <div id="tu28StaffModal" class="modal-overlay" aria-hidden="true" onclick="closeTu28StaffModal()">
    <div class="modal-window wide" style="width:fit-content; max-width:calc(100vw - 36px);" onclick="event.stopPropagation()">
      <div class="modal-head">
        <div class="section-title" style="margin:0 auto;">Ответственные за ремонт</div>
        <button class="modal-close" onclick="closeTu28StaffModal()">×</button>
      </div>
      <div id="tu28StaffModalBody" class="section-modal-body"></div>
      <div class="section-modal-actions">
        <button onclick="closeTu28StaffModal()">Отмена</button>
        <button class="primary" onclick="confirmTu28Staff()">OK</button>
      </div>
    </div>
  </div>
  <div id="errorModal" class="modal-overlay" aria-hidden="true" onclick="closeErrorModal()">
    <div class="modal-window" style="width:min(900px, calc(100vw - 36px));" onclick="event.stopPropagation()">
      <div class="modal-head">
        <div class="section-title" style="margin:0 auto;">Ошибка</div>
        <button class="modal-close" onclick="closeErrorModal()">×</button>
      </div>
      <div id="errorModalBody" class="section-modal-body"></div>
      <div class="section-modal-actions">
        <button onclick="closeErrorModal()">Закрыть</button>
      </div>
    </div>
  </div>
<script>
const BOOT_VERSION = "{{APP_VERSION}}";
let appState = {{STATE_JSON}};
const EMPLOYEE_NAMES = {{EMPLOYEE_NAMES}};
let ui = { section: 'months', modal: null, monthIndex: new Date().getMonth(), mode: 'plan', selected: { months: null, norms: null }, monthSelection: null, draggingSelection: false, lastCell: null, tu28MonthIndex: new Date().getMonth(), tu28RowIndex: null, tu28Staff: {}, tu28ExtraRepairs: {} };
let dirty = false;
let savedAppState = null;
let savedMonthsState = null;
let canceledMonthsState = null;
const CAN_EDIT = {{CAN_EDIT}};
const TEM_NORM_ROWS = {{TEM_NORM_ROWS}};
const AGR_NORM_ROWS = {{AGR_NORM_ROWS}};
const REPAIR_AUTO_FILL_DAYS = {"ТО3": 1, "ТР1": 4, "ТР": 4, "ТР2": 9, "ТР3": 14};
const sections = [{id:'norms',label:'Нормы / парк'},{id:'acts',label:'Акты'},{id:'tu28',label:'ТУ-28'}];
let leaveGuardInstalled = false;
let pendingLeaveAction = null;

function esc(v){ return String(v ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#39;'); }
function normalizeRepairCode(v){
  const map = {A:'А', B:'В', C:'С', E:'Е', H:'Н', K:'К', M:'М', O:'О', P:'Р', T:'Т', X:'Х', Y:'У'};
  return String(v ?? '')
    .trim()
    .toUpperCase()
    .replace(/\\s+/g, '')
    .replace(/-/g, '')
    .replace(/[ABCEHKMOPTXY]/g, (ch) => map[ch] || ch);
}
function setStatus(t){ void t; }
function closeJsonMenu(){
  const wrap = document.getElementById('jsonMenuWrap');
  const panel = document.getElementById('jsonMenuPanel');
  if (wrap) wrap.classList.remove('open');
  if (panel) panel.setAttribute('aria-hidden', 'true');
}
function toggleJsonMenu(event){
  if (event) event.stopPropagation();
  const wrap = document.getElementById('jsonMenuWrap');
  const panel = document.getElementById('jsonMenuPanel');
  if (!wrap || !panel) return;
  const open = !wrap.classList.contains('open');
  wrap.classList.toggle('open', open);
  panel.setAttribute('aria-hidden', open ? 'false' : 'true');
}
function triggerImportJson(){
  const input = document.getElementById('importFile');
  if (input) input.click();
  closeJsonMenu();
}
function showErrorModal(message){
  const modal = document.getElementById('errorModal');
  const body = document.getElementById('errorModalBody');
  if (!modal || !body) return;
  body.innerHTML = `<div class="error-modal-text" tabindex="0">${esc(message || 'Неизвестная ошибка')}</div>`;
  modal.classList.add('visible');
  modal.setAttribute('aria-hidden', 'false');
}
function closeErrorModal(){
  const modal = document.getElementById('errorModal');
  if (!modal) return;
  modal.classList.remove('visible');
  modal.setAttribute('aria-hidden', 'true');
}
function markDirty(v=true){ dirty=v; updateSaveButtonState(); }
function updateSaveButtonState(){
  const btn = document.getElementById('saveButton');
  if (!btn) return;
  btn.classList.toggle('save-ready', !!dirty && !!CAN_EDIT);
}
function cloneState(value){
  return value ? JSON.parse(JSON.stringify(value)) : null;
}
function updateHistoryButtons(){
  const cancelBtn = document.getElementById('cancelButton');
  const restoreBtn = document.getElementById('restoreButton');
  if (cancelBtn) cancelBtn.style.display = '';
  if (restoreBtn) restoreBtn.style.display = '';
  if (cancelBtn) cancelBtn.disabled = !CAN_EDIT || !savedMonthsState;
  if (restoreBtn) restoreBtn.disabled = !CAN_EDIT || !canceledMonthsState;
}
function ensureLeaveGuard(){
  if (!CAN_EDIT || leaveGuardInstalled) return;
  history.pushState({leaveGuard:true}, '', location.href);
  leaveGuardInstalled = true;
}
function openLeaveModal(message, action){
  pendingLeaveAction = action;
  const modal = document.getElementById('leaveModal');
  const body = document.getElementById('leaveMessage');
  if (body) body.textContent = message || 'Есть несохранённые изменения.';
  if (!modal) return;
  modal.classList.add('visible');
  modal.setAttribute('aria-hidden', 'false');
}
function closeLeaveModal(){
  const modal = document.getElementById('leaveModal');
  if (!modal) return;
  modal.classList.remove('visible');
  modal.setAttribute('aria-hidden', 'true');
}
async function resolveLeaveChoice(shouldSave){
  const action = pendingLeaveAction;
  if (!action) return;
  if (shouldSave && dirty && CAN_EDIT) {
    await saveState({refreshReport:false});
    if (dirty) return;
  }
  pendingLeaveAction = null;
  closeLeaveModal();
  await action();
}
function promptLeave(message, action){
  if (!dirty || !CAN_EDIT) {
    action();
    return false;
  }
  openLeaveModal(message, action);
  return false;
}
function setLastCell(el){
  if (!el || !el.dataset) return;
  ui.lastCell = {
    table: el.dataset.table,
    row: Number(el.dataset.row),
    col: Number(el.dataset.col),
    path: el.dataset.path,
  };
}
function getMonthCellInfo(el){
  if (!el || !el.dataset || el.dataset.month === undefined) return null;
  const monthIndex = Number(el.dataset.month);
  const row = Number(el.dataset.row);
  const col = Number(el.dataset.col);
  if (!Number.isFinite(monthIndex) || !Number.isFinite(row) || !Number.isFinite(col)) return null;
  return { monthIndex, table: el.dataset.table, row, col, path: el.dataset.path };
}
function selectionBounds(a, b){
  return {
    startRow: Math.min(a.row, b.row),
    endRow: Math.max(a.row, b.row),
    startCol: Math.min(a.col, b.col),
    endCol: Math.max(a.col, b.col),
  };
}
function clearMonthSelection(){
  ui.monthSelection = null;
  applyMonthSelectionClasses();
}
function setMonthSelection(anchor, focus){
  if (!anchor || !focus || anchor.monthIndex !== focus.monthIndex || anchor.table !== focus.table) return;
  ui.monthSelection = {
    monthIndex: anchor.monthIndex,
    table: anchor.table,
    anchor,
    focus,
    ...selectionBounds(anchor, focus),
  };
  applyMonthSelectionClasses();
}
function applyMonthSelectionClasses(){
  document.querySelectorAll('input.selected-cell').forEach((el) => {
    el.classList.remove('selected-cell');
    el.style.boxShadow = '';
  });
  if (ui.section !== 'months' || !ui.monthSelection) return;
  const sel = ui.monthSelection;
  document.querySelectorAll(`input[data-month="${sel.monthIndex}"][data-table="${sel.table}"]`).forEach((el) => {
    const row = Number(el.dataset.row);
    const col = Number(el.dataset.col);
    if (row >= sel.startRow && row <= sel.endRow && col >= sel.startCol && col <= sel.endCol) {
      el.classList.add('selected-cell');
      const shadows = [];
      if (row === sel.startRow) shadows.push('inset 0 1.5px 0 0 #276ef1');
      if (row === sel.endRow) shadows.push('inset 0 -1.5px 0 0 #276ef1');
      if (col === sel.startCol) shadows.push('inset 1.5px 0 0 0 #276ef1');
      if (col === sel.endCol) shadows.push('inset -1.5px 0 0 0 #276ef1');
      if (shadows.length > 0) {
        el.style.setProperty('box-shadow', shadows.join(', '), 'important');
      } else {
        el.style.boxShadow = '';
      }
    }
  });
}
function isMonthSelectionTarget(el){
  const info = getMonthCellInfo(el);
  return !!info && ui.section === 'months';
}
function beginMonthSelection(e){
  if (!CAN_EDIT || e.button !== 0) return;
  const target = e.currentTarget || e.target;
  const info = getMonthCellInfo(target);
  if (!info || ui.section !== 'months') return;
  e.preventDefault();
  setLastCell(target);
  const keepAnchor = e.shiftKey && ui.monthSelection && ui.monthSelection.monthIndex === info.monthIndex && ui.monthSelection.table === info.table;
  const anchor = keepAnchor ? ui.monthSelection.anchor : info;
  setMonthSelection(anchor, info);
  ui.draggingSelection = true;
  focusCell(target);
}
function extendMonthSelection(e){
  if (!ui.draggingSelection || ui.section !== 'months') return;
  const target = e.currentTarget || e.target;
  const info = getMonthCellInfo(target);
  if (!info || !ui.monthSelection) return;
  const anchor = ui.monthSelection.anchor;
  if (anchor.monthIndex !== info.monthIndex || anchor.table !== info.table) return;
  setMonthSelection(anchor, info);
}
function endMonthSelection(){
  ui.draggingSelection = false;
}
function selectedMonthCellText(info){
  const month = appState.months[info.monthIndex];
  if (!month) return '';
  const row = month[info.table] && month[info.table][info.row];
  if (!row || !row.cells) return '';
  return String(row.cells[info.col] ?? '');
}
function getSelectedMonthSelection(){
  if (ui.section !== 'months' || !ui.monthSelection) return null;
  return ui.monthSelection;
}
function copyMonthSelectionText(){
  const sel = getSelectedMonthSelection();
  if (!sel) return '';
  const lines = [];
  for (let row = sel.startRow; row <= sel.endRow; row++) {
    const values = [];
    for (let col = sel.startCol; col <= sel.endCol; col++) {
      values.push(selectedMonthCellText({ monthIndex: sel.monthIndex, table: sel.table, row, col }));
    }
    lines.push(values.join('\\t'));
  }
  return lines.join('\\n');
}
function writeMonthCellValue(monthIndex, table, row, col, value){
  const selector = `input[data-month="${monthIndex}"][data-table="${table}"][data-row="${row}"][data-col="${col}"]`;
  const cell = document.querySelector(selector);
  if (!cell) return false;
  const normalized = value ?? '';
  cell.value = normalized;
  setPath(cell.dataset.path, normalized);
  return true;
}
function pasteMonthSelectionText(target, text){
  if (!CAN_EDIT) return;
  const info = getMonthCellInfo(target);
  if (!info || ui.section !== 'months') return;
  const rows = String(text ?? '').replace(/\\r/g, '').split('\\n');
  while (rows.length && rows[rows.length - 1] === '') rows.pop();
  if (!rows.length) return;
  const matrix = rows.map((line) => line.split('\\t'));
  const sel = getSelectedMonthSelection();
  const useSelection = sel && sel.monthIndex === info.monthIndex && sel.table === info.table;
  const startRow = useSelection ? sel.startRow : info.row;
  const startCol = useSelection ? sel.startCol : info.col;
  const sourceRows = matrix.length;
  const sourceCols = Math.max(...matrix.map((row) => row.length), 1);
  const targetRows = matrix.length === 1 && matrix[0].length === 1 && useSelection
    ? (sel.endRow - sel.startRow + 1)
    : sourceRows;
  const targetCols = matrix.length === 1 && matrix[0].length === 1 && useSelection
    ? (sel.endCol - sel.startCol + 1)
    : sourceCols;
  const fillSingle = matrix.length === 1 && matrix[0].length === 1 && useSelection;
  for (let r = 0; r < targetRows; r++) {
    for (let c = 0; c < targetCols; c++) {
      const sourceRow = fillSingle ? 0 : Math.min(r, matrix.length - 1);
      const sourceCol = fillSingle ? 0 : Math.min(c, matrix[sourceRow].length - 1);
      const value = matrix[sourceRow][sourceCol] ?? '';
      writeMonthCellValue(info.monthIndex, info.table, startRow + r, startCol + c, value);
    }
  }
  if (useSelection) setMonthSelection(sel.anchor, { monthIndex: info.monthIndex, table: info.table, row: startRow + targetRows - 1, col: startCol + targetCols - 1 });
  markDirty(true);
}
function handleMonthCopy(e){
  const sel = getSelectedMonthSelection();
  if (!sel) return;
  const text = copyMonthSelectionText();
  if (text === '') return;
  e.preventDefault();
  e.clipboardData.setData('text/plain', text);
}
function handleMonthPaste(e){
  if (!CAN_EDIT) return;
  if (e.defaultPrevented) return;
  const target = (e.target && e.target.dataset && e.target.dataset.month !== undefined)
    ? e.target
    : ui.lastCell;
  if (!target || !target.dataset || target.dataset.month === undefined) return;
  const text = (e.clipboardData || window.clipboardData).getData('text');
  if (!text) return;
  const sel = getSelectedMonthSelection();
  if (sel && sel.monthIndex !== Number(target.dataset.month)) {
    clearMonthSelection();
  }
  e.preventDefault();
  pasteMonthSelectionText(target, text);
}
document.addEventListener('mouseup', endMonthSelection, true);
document.addEventListener('copy', handleMonthCopy, true);
document.addEventListener('paste', handleMonthPaste, true);
document.addEventListener('keydown', event => {
  if (event.key === 'Escape') closeJsonMenu();
});
document.addEventListener('click', event => {
  const wrap = document.getElementById('jsonMenuWrap');
  if (!wrap || !wrap.classList.contains('open')) return;
  if (wrap.contains(event.target)) return;
  closeJsonMenu();
});
function setPath(path, value){
  if (!CAN_EDIT) return;
  if (typeof value === 'string') value = value.toUpperCase();
  const p = path.split('.');
  let o = appState;
  for (let i=0; i<p.length-1; i++) o = o[p[i]];
  const last = p[p.length-1];
  o[last] = value;
  markDirty(true);
}
function handleGridInput(el){
  if (!el || !el.dataset) return;
  setLastCell(el);
  const value = String(el.value ?? '').toUpperCase();
  if (el.value !== value) el.value = value;
  setPath(el.dataset.path, value);
}
function focusCell(el){ if (el) el.focus(); }
function monthCells(type){
  return Array.from(document.querySelectorAll(`input[data-month="${ui.monthIndex}"][data-table="${type}"]`));
}
function moveCell(current, dx, dy){
  const table = current.dataset.table;
  const row = parseInt(current.dataset.row, 10);
  const col = parseInt(current.dataset.col, 10);
  const targetRow = row + dy;
  const targetCol = col + dx;
  const next = document.querySelector(`input[data-month="${ui.monthIndex}"][data-table="${table}"][data-row="${targetRow}"][data-col="${targetCol}"]`);
  if (next) next.focus();
}
function handleMonthKeydown(e){
  const keys = ['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','Enter','Delete','Backspace'];
  if (!keys.includes(e.key)) return;
  if (e.key === 'Delete' || e.key === 'Backspace'){
    e.preventDefault();
    e.target.value = '';
    setPath(e.target.dataset.path, '');
    return;
  }
  const step = e.key === 'ArrowLeft' ? [-1,0] : e.key === 'ArrowRight' ? [1,0] : e.key === 'ArrowUp' ? [0,-1] : e.key === 'ArrowDown' ? [0,1] : [0,1];
  e.preventDefault();
  moveCell(e.target, step[0], step[1]);
}
function bindNav(){
  document.getElementById('sectionNav').innerHTML = sections.map(s => `<button class="${ui.section===s.id || ui.modal===s.id ? 'active' : ''}" onclick="setSection('${s.id}')">${s.label}</button>`).join('');
}
function setSection(section){
  if (section === 'norms' || section === 'acts' || section === 'tu28') {
    ui.section = 'months';
    openSectionModal(section);
    return;
  }
  ui.modal = null;
  ui.section = section;
  render();
}
function setMonth(index){ ui.monthIndex = index; clearMonthSelection(); render(); }
function setMode(mode){ ui.mode = mode; render(); }
function currentMonth(){ return appState.months[ui.monthIndex]; }
function safeCurrentMonth(){
  const months = Array.isArray(appState.months) ? appState.months : [];
  return months[ui.monthIndex] || months[0] || { name:'', month:1, days:31, plan:[], fact:[] };
}
function isRepairSkipDay(year, month, day){
  if (hasSystemDate('holiday', month, day)) return true;
  if (hasSystemDate('transfer', month, day)) return true;
  return isWeekend(year, month, day);
}
function systemDates(){
  return appState.system_dates || { transfer: [], holiday: [] };
}
function hasSystemDate(kind, month, day){
  const items = systemDates()[kind] || [];
  return items.some(([m, d]) => m === month && d === day);
}
function dayClass(month, day){
  if (hasSystemDate('holiday', month, day)) return 'holiday-col';
  if (hasSystemDate('transfer', month, day) || isWeekend(appState.year, month, day)) return 'transfer-col';
  return '';
}
function isWeekend(year, month, day){
  const d = new Date(year, month - 1, day);
  const wd = d.getDay();
  return wd === 0 || wd === 6;
}
function ensureYearOptions(){
  const select = document.getElementById('yearInput');
  if (!select) return;
  const selectedYear = Number(appState.year) || new Date().getFullYear();
  const selected = String(selectedYear);
  const current = new Date().getFullYear();
  const minYear = Math.min(2020, selectedYear - 2, current - 2);
  const maxYear = Math.max(2100, selectedYear + 2, current + 2);
  const options = [];
  for (let y=minYear; y<=maxYear; y++) {
    options.push(`<option value="${y}" ${String(y)===selected ? 'selected' : ''}>${y}</option>`);
  }
  select.innerHTML = options.join('');
}
function render(){
  try {
    renderSafe();
  } catch (err) {
    const content = document.getElementById('content');
    if (content) {
      content.innerHTML = `<div style="padding:14px;border:1px solid #f0c2c2;background:#fff5f5;color:#9b1c1c;border-radius:12px;white-space:pre-wrap;font:14px/1.4 monospace;">${esc(err && err.stack ? err.stack : err)}</div>`;
    }
    throw err;
  }
}
function renderSafe(){
  ensureYearOptions();
  ensureLeaveGuard();
  document.title = `График ППР web ${BOOT_VERSION}`;
  bindNav();
  updateSaveButtonState();
  const content = document.getElementById('content');
  if (!content) return;
  content.innerHTML = renderMonths();
  applyMonthSelectionClasses();
  renderOpenModals();
  updateHistoryButtons();
}
window.addEventListener('error', (event) => {
  const content = document.getElementById('content');
  if (!content) return;
  const text = event && event.error && event.error.stack ? event.error.stack : (event && event.message ? event.message : 'Unknown error');
  content.innerHTML = `<div style="padding:14px;border:1px solid #f0c2c2;background:#fff5f5;color:#9b1c1c;border-radius:12px;white-space:pre-wrap;font:14px/1.4 monospace;">${esc(text)}</div>`;
});
function repairButtonsHtml(){
  return `
      <div class="repair-strip">
        <button type="button" ${CAN_EDIT ? '' : 'disabled'} onclick="insertRepair('ТО2')">ТО2</button>
        <button type="button" ${CAN_EDIT ? '' : 'disabled'} onclick="insertRepair('ТО3')">ТО3</button>
        <button type="button" ${CAN_EDIT ? '' : 'disabled'} onclick="insertRepair('ТР1')">ТР1</button>
        <button type="button" ${CAN_EDIT ? '' : 'disabled'} onclick="insertRepair('ТР2')">ТР2</button>
        <button type="button" ${CAN_EDIT ? '' : 'disabled'} onclick="insertRepair('ТР3')">ТР3</button>
        <button type="button" ${CAN_EDIT ? '' : 'disabled'} onclick="insertRepair('ТО')">ТО</button>
        <button type="button" ${CAN_EDIT ? '' : 'disabled'} onclick="insertRepair('ТР')">ТР</button>
      </div>
    `;
}
function rowActionsHtml(){
  return `
      <div class="row-actions">
        <button type="button" onclick="addRow('plan'); addRow('fact')">+ строку</button>
        <button type="button" class="danger" onclick="deleteRow('plan'); deleteRow('fact')">- строку</button>
        <button type="button" id="cancelButton" title="Отмена" aria-label="Отмена" onclick="cancelChanges()">↺</button>
        <button type="button" id="restoreButton" title="Вернуть" aria-label="Вернуть" onclick="restoreChanges()">↻</button>
      </div>
  `;
}
function monthSelectHtml(){
  return `
    <select id="actsMonthSelect" onchange="setMonth(parseInt(this.value, 10))" style="border:1px solid var(--line); border-radius:8px; padding:2px 8px; font:inherit; font-size:15px; background:#fff; width:112px; min-width:112px; max-width:112px;">
      ${appState.months.map((m, i) => `<option value="${i}" ${i === ui.monthIndex ? 'selected' : ''}>${m.name}</option>`).join('')}
    </select>
  `;
}
function renderMonths(){
  const m = safeCurrentMonth();
  const headers = ['№','Серия','Номер','Категория',...Array.from({length:m.days},(_,i)=>String(i+1).padStart(2,'0')),'Примечание'];
  const monthButtons = appState.months.map((x,i)=>`<button class="${i===ui.monthIndex?'active':''}" onclick="setMonth(${i})">${x.name}</button>`).join('');
  return `
    <div class="months-row">
      <div class="month-strip">${monthButtons}</div>
    </div>
    ${renderMonthTable('plan', 'План', m, headers)}
    ${renderMonthTable('fact', 'Факт', m, headers)}
  `;
}
function renderMonthTable(type, title, m, headers){
  const tableRows = m[type].map((row, rIdx) => {
    const rowHtml = [];
    rowHtml.push(`<td class="col-idx"><div class="rownum"><span>${rIdx+1}</span></div></td>`);
    rowHtml.push(`<td class="col-series">${cell(`months.${ui.monthIndex}.${type}.${rIdx}.cells.1`, row.cells[1] || '', 'cell', ui.monthIndex, type, rIdx, 1) }</td>`);
    rowHtml.push(`<td class="col-number">${cell(`months.${ui.monthIndex}.${type}.${rIdx}.cells.2`, row.cells[2] || '', 'cell', ui.monthIndex, type, rIdx, 2) }</td>`);
    rowHtml.push(`<td class="col-cat">${catButton(ui.monthIndex, type, rIdx, row.excluded)}</td>`);
    for (let d=0; d<m.days; d++) {
      const cls = dayClass(m.month, d + 1);
      const dayFillStyle = cls === 'transfer-col'
        ? 'background-color:#dcf8dc !important;'
        : cls === 'holiday-col'
          ? 'background-color:#ffdede !important;'
          : '';
      const tdStyle = dayFillStyle ? ` style="${dayFillStyle}"` : '';
      const inputStyle = row.excluded
        ? 'color:#9aa5b1 !important;'
        : cls === 'transfer-col'
          ? 'background-color:#dcf8dc !important;'
          : cls === 'holiday-col'
            ? 'background-color:#ffdede !important;'
          : '';
      rowHtml.push(`<td class="col-day ${cls}"${tdStyle}>${cell(`months.${ui.monthIndex}.${type}.${rIdx}.cells.${4+d}`, row.cells[4+d] || '', `cell small center ${cls} day-cell`, ui.monthIndex, type, rIdx, 4+d, inputStyle) }</td>`);
    }
    rowHtml.push(`<td class="col-note">${cell(`months.${ui.monthIndex}.${type}.${rIdx}.cells.${4+m.days}`, row.cells[4+m.days] || '', 'cell', ui.monthIndex, type, rIdx, 4+m.days) }</td>`);
    return `<tr class="${row.excluded ? 'excluded-row' : ''}">${rowHtml.join('')}</tr>`;
  }).join('');
  const headHtml = headers.map((h, idx) => {
    if (idx < 4 || idx === headers.length - 1) return `<th>${h}</th>`;
    const day = idx - 3;
    return `<th class="${dayClass(m.month, day)}">${h}</th>`;
  }).join('');
  const colHtml = [
    '<col style="width:45px">',
    '<col style="width:var(--series-col-width)">',
    '<col style="width:var(--number-col-width)">',
    '<col style="width:var(--cat-col-width)">',
    ...Array.from({length:m.days}, (_, d) => `<col style="width:36px" class="${dayClass(m.month, d + 1)}">`),
    '<col style="width:120px">'
  ].join('');
  const controlsHtml = type === 'plan' ? rowActionsHtml() : '<div></div>';
  return `
    <div class="section-head month-table-head" style="margin-top:16px;">
      <div class="month-table-actions">
        ${repairButtonsHtml()}
      </div>
      <div class="section-title month-table-title">${title}</div>
      ${controlsHtml}
    </div>
    <div class="table-wrap month-table-wrap">
      <table class="compact month-table">
        <colgroup>${colHtml}</colgroup>
        <thead><tr>${headHtml}</tr></thead>
        <tbody>${tableRows}</tbody>
      </table>
    </div>
  `;
}
function catButton(monthIndex, type, rowIndex, excluded){
  const label = excluded ? '↺' : '–';
  return `<button class="rowbtn cat-toggle" onclick="toggleExcluded(${monthIndex},'${type}',${rowIndex})">${label}</button>`;
}
function insertRepair(text){
  if (!CAN_EDIT) return;
  const el = document.activeElement;
  const cell = (el && el.dataset && el.dataset.month !== undefined) ? el : null;
  const targetCell = cell || (ui.lastCell ? document.querySelector(`input[data-table="${ui.lastCell.table}"][data-row="${ui.lastCell.row}"][data-col="${ui.lastCell.col}"]`) : null);
  if (!targetCell || !targetCell.dataset) return;
  const month = currentMonth();
  const row = parseInt(targetCell.dataset.row, 10);
  const col = parseInt(targetCell.dataset.col, 10);
  if (!Number.isFinite(row) || !Number.isFinite(col) || col < 4 || col >= 4 + month.days) return;
  const apply = (targetCol, value) => {
    const target = document.querySelector(`input[data-month="${ui.monthIndex}"][data-table="${targetCell.dataset.table}"][data-row="${row}"][data-col="${targetCol}"]`);
    if (target) {
      target.value = value;
      setPath(target.dataset.path, value);
    }
  };
  apply(col, text);
  const days = REPAIR_AUTO_FILL_DAYS[text] || 0;
  if (!days) return;
  const year = appState.year;
  const day = col - 3;
  let filled = 0;
  let check = day + 1;
  while (filled < days && check <= month.days) {
    if (!isRepairSkipDay(year, month.month, check)) {
      apply(check + 3, text);
      filled += 1;
    }
    check += 1;
  }
}
function renderNorms(){
  const leftRows = [
    { kind:'group', label:'Тепловозы' },
    ...TEM_NORM_ROWS.map((label, idx) => ({ kind:'item', group:'h_tep', idx, label })),
    { kind:'group', label:'Тяговые агрегаты' },
    ...AGR_NORM_ROWS.map((label, idx) => ({ kind:'item', group:'h_agr', idx, label })),
  ];
  const parkRows = Array.from({length:12}, (_, idx) => {
    const month = String(idx + 1).padStart(2, '0');
    const tep = appState.norms.p_tep[idx] || {k: month, v: ''};
    const agr = appState.norms.p_agr[idx] || {k: month, v: ''};
    return { idx, month, tep, agr };
  });
  const rows = Array.from({length: 12}, (_, idx) => ({ left: leftRows[idx] || null, park: parkRows[idx] }));
  const bodyHtml = rows.map((entry, rowIndex) => {
    const left = entry.left;
    const park = entry.park;
    const leftHtml = left && left.kind === 'item'
      ? `<td>${left.label}</td><td>${cell(`norms.${left.group}.${left.idx}.v`, (appState.norms[left.group][left.idx] || {v:''}).v, 'cell center')}</td>`
      : `<td class="group-row" colspan="2">${left ? left.label : ''}</td>`;
    return `<tr onclick="selectRow('norms', ${rowIndex})">${leftHtml}<td>${park.month}</td><td>${cell(`norms.p_tep.${park.idx}.v`, park.tep.v, 'cell center')}</td><td>${cell(`norms.p_agr.${park.idx}.v`, park.agr.v, 'cell center')}</td></tr>`;
  }).join('');
  return `
    <div class="section-head" style="justify-content:center; text-align:center;">
      <div style="width:100%;">
      </div>
    </div>
    <div class="table-wrap" style="margin:0 auto 14px; width:100%; max-width:none; padding:0;">
      <table class="compact norms-table">
        <colgroup>
          <col class="col-name">
          <col class="col-hours">
          <col class="col-month">
          <col class="col-tep">
          <col class="col-agr">
        </colgroup>
        <thead>
          <tr>
            <th rowspan="2">Вид ремонта</th>
            <th rowspan="2">Часы</th>
            <th colspan="3">ПЛАН ИСПРАВНЫХ НА ${appState.year} г.</th>
          </tr>
          <tr>
            <th>Месяц</th>
            <th>Тепловозы</th>
            <th>Тяговые агрегаты</th>
          </tr>
        </thead>
        <tbody>${bodyHtml}</tbody>
      </table>
    </div>
  `;
}
function reportUnitKey(row){
  const cells = row && row.cells ? row.cells : [];
  const series = String(cells[1] ?? '').trim().toUpperCase();
  const number = String(cells[2] ?? '').trim().toUpperCase();
  if (!series || !number) return null;
  return [series, number];
}
function buildRowsByUnit(monthData, tableType){
  const rowsByUnit = {};
  if (!monthData || !monthData[tableType]) return rowsByUnit;
  monthData[tableType].forEach((row, idx) => {
    if (!row || row.excluded) return;
    const key = reportUnitKey(row);
    if (key) rowsByUnit[key.join('|')] = idx;
  });
  return rowsByUnit;
}
function rowCellIsNumeric(row, day){
  if (!row || !row.cells) return false;
  const idx = day + 3;
  const raw = String(row.cells[idx] ?? '').trim();
  if (!raw) return false;
  const numeric = Number(raw.replace(',', '.'));
  return Number.isFinite(numeric);
}
function collectUnplannedStartsAcrossMonths(monthIndex, tableType, rowKey){
  const months = appState.months || [];
  if (!rowKey || !months.length || monthIndex < 0 || monthIndex >= months.length) return [];
  const year = Number(appState.year) || new Date().getFullYear();
  const rowKeyStr = rowKey.join('|');
  const rowMaps = months.slice(0, monthIndex + 1).map((month) => buildRowsByUnit(month, tableType));
  const currMonth = months[monthIndex];
  const currMonthNum = Number(currMonth.month || monthIndex + 1);
  const prevMonthNum = monthIndex > 0 ? Number(months[monthIndex - 1].month || monthIndex) : null;
  const windowStart = prevMonthNum ? new Date(year, prevMonthNum - 1, 26) : new Date(year, currMonthNum - 1, 1);
  const windowEnd = new Date(year, currMonthNum - 1, 25);
  const rowForDate = (date) => {
    const monthIdx = date.getMonth();
    if (monthIdx < 0 || monthIdx >= rowMaps.length) return null;
    const rowIdx = (rowMaps[monthIdx] || {})[rowKeyStr];
    const rows = months[monthIdx][tableType] || [];
    return Number.isInteger(rowIdx) && rowIdx < rows.length ? rows[rowIdx] : null;
  };
  const numericOn = (date) => rowCellIsNumeric(rowForDate(date), date.getDate());
  const starts = [];
  const seen = new Set();
  const addStart = (date) => {
    const key = `${date.getMonth() + 1}-${date.getDate()}`;
    if (seen.has(key)) return;
    seen.add(key);
    starts.push(new Date(date));
  };
  if (numericOn(windowStart)) {
    let start = new Date(windowStart);
    let prev = new Date(start);
    prev.setDate(prev.getDate() - 1);
    while (prev.getFullYear() === year && prev >= new Date(year, 0, 1) && numericOn(prev)) {
      start = new Date(prev);
      prev.setDate(prev.getDate() - 1);
    }
    addStart(start);
  }
  let prevIsNum = numericOn(windowStart);
  for (let day = new Date(windowStart); day <= windowEnd; day.setDate(day.getDate() + 1)) {
    if (day.getTime() === windowStart.getTime()) continue;
    const isNum = numericOn(day);
    if (isNum && !prevIsNum) addStart(day);
    prevIsNum = isNum;
  }
  return starts.map((date) => `Акт № ${String(date.getDate()).padStart(2, '0')}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(rowKey[1] || '').trim().toUpperCase()}`);
}
function collectActNumbersFromRow(currRow, monthIndex, tableType, rowKey){
  const cells = currRow && currRow.cells ? currRow.cells : [];
  const note = String(cells[cells.length - 1] ?? '').trim();
  const candidates = collectUnplannedStartsAcrossMonths(monthIndex, tableType, rowKey);
  const seen = new Set();
  const result = [];
  const add = (value) => {
    const clean = String(value || '').replace(/^Акт №\\s*/i, '').trim();
    if (!clean || seen.has(clean)) return;
    seen.add(clean);
    result.push(clean);
  };
  candidates.forEach(add);
  if (!result.length && /^Акт №\\s*\\d{2}-\\d{2}-/i.test(note)) add(note);
  return result;
}
function parseActSortKey(act){
  const clean = String(act || '').replace(/^Акт №\\s*/i, '').trim();
  const parts = clean.split('-').map((x) => x.trim());
  if (parts.length < 3) return { month: 99, day: 99, tail: clean };
  const day = Number(parts[0]);
  const month = Number(parts[1]);
  return {
    month: Number.isFinite(month) ? month : 99,
    day: Number.isFinite(day) ? day : 99,
    tail: parts.slice(2).join('-'),
    raw: clean,
  };
}
function compareActsByDate(a, b){
  const aa = parseActSortKey(a);
  const bb = parseActSortKey(b);
  if (aa.month !== bb.month) return aa.month - bb.month;
  if (aa.day !== bb.day) return aa.day - bb.day;
  if (aa.tail !== bb.tail) return aa.tail.localeCompare(bb.tail, 'ru');
  return aa.raw.localeCompare(bb.raw, 'ru');
}
function collectActRowsForMonth(monthIndex){
  const month = appState.months[monthIndex];
  if (!month) return [];
  const savedActs = (appState.acts && appState.acts[month.name]) || {};
  const rows = [];
  const seen = new Set();
  (month.fact || []).forEach((row, rowIndex) => {
    if (!row || row.excluded) return;
    const key = reportUnitKey(row);
    if (!key) return;
    const acts = collectActNumbersFromRow(row, monthIndex, 'fact', key);
    acts.forEach((act) => {
      if (seen.has(act)) return;
      seen.add(act);
      rows.push({ act, saved: savedActs[act] || { is_done: false, sap_order_done: false }, rowIndex });
    });
  });
  Object.keys(savedActs).sort().forEach((act) => {
    if (seen.has(act)) return;
    seen.add(act);
    rows.push({ act, saved: savedActs[act] || { is_done: false, sap_order_done: false }, rowIndex: null });
  });
  return rows.sort((a, b) => compareActsByDate(a.act, b.act));
}
function renderActs(){
  const month = currentMonth().name;
  const rows = collectActRowsForMonth(ui.monthIndex).map(({ act, saved }) => {
    const x = saved || {};
    return `<tr>
      <td>${esc(act)}</td>
      <td style="text-align:center; font-size:16px;"><button class="act-start" style="width:100%; height:100%; min-height:34px; display:flex; align-items:center; justify-content:center;" ${CAN_EDIT ? '' : 'disabled'} onclick="startAct('${month}', '${act}')">Пуск</button></td>
      <td class="center"><input type="checkbox" ${x.is_done ? 'checked' : ''} onchange="setActInfoFlag('${month}', '${act}', 'is_done', this.checked)"></td>
      <td class="center"><input type="checkbox" ${x.sap_order_done ? 'checked' : ''} onchange="setActInfoFlag('${month}', '${act}', 'sap_order_done', this.checked)"></td>
    </tr>`;
  }).join('');
  return `
    <div class="section-head">
      <div style="display:flex; justify-content:center; width:100%;">
        ${monthSelectHtml()}
      </div>
    </div>
    <div class="table-wrap" style="width:fit-content; max-width:100%; margin:0 auto;">
      <table class="acts-table">
        <colgroup>
          <col style="width:150px;">
          <col style="width:120px;">
          <col style="width:120px;">
          <col style="width:130px;">
        </colgroup>
        <thead><tr><th>№<br>акта</th><th>Сформировать<br>акт</th><th>Сформирован<br>акт</th><th>Создан заказ<br>в SAP</th></tr></thead>
        <tbody>${rows || '<tr><td colspan="4">Нет данных</td></tr>'}</tbody>
      </table>
    </div>
  `;
}
function ensureActStateBucket(month, act){
  if (!appState.acts) appState.acts = {};
  if (!appState.acts[month]) appState.acts[month] = {};
  if (!appState.acts[month][act]) appState.acts[month][act] = { is_done: false, sap_order_done: false };
  return appState.acts[month][act];
}
function setActInfoFlag(month, act, key, value){
  if (!CAN_EDIT) return;
  const bucket = ensureActStateBucket(month, act);
  bucket[key] = !!value;
  markDirty(true);
}
function tu28Month(){
  return appState.months[ui.tu28MonthIndex] || currentMonth();
}
function tu28CandidatesForMonth(monthIndex){
  const month = appState.months[monthIndex];
  if (!month) return [];
  const rows = month.fact || [];
  const candidates = [];
  rows.forEach((row, rowIndex) => {
    if (!row || row.excluded) return;
    const cells = row.cells || [];
    for (let col = 4; col < 4 + month.days; col++) {
      const code = normalizeRepairCode(String(cells[col] ?? ''));
      if (['ТО3','ТР1','ТР2','ТР3','СР','КР'].includes(code)) {
        candidates.push({
          rowIndex,
          date: `${String(col - 3).padStart(2, '0')}.${String(month.month).padStart(2, '0')}.${appState.year}`,
          code: String(cells[col] ?? '').trim().toUpperCase(),
          series: String(cells[1] ?? '').trim(),
          number: String(cells[2] ?? '').trim(),
        });
        break;
      }
    }
  });
  return candidates;
}
function renderTu28(){
  const month = tu28Month();
  const candidates = tu28CandidatesForMonth(ui.tu28MonthIndex);
  if (ui.tu28RowIndex == null && candidates.length) ui.tu28RowIndex = candidates[0].rowIndex;
  if (!candidates.some((x) => x.rowIndex === ui.tu28RowIndex)) {
    ui.tu28RowIndex = candidates.length ? candidates[0].rowIndex : null;
  }
  const rows = candidates.map((c, idx) => `
    <tr class="${c.rowIndex === ui.tu28RowIndex ? 'selected-row' : ''}" onclick="selectTu28Row(${c.rowIndex})">
      <td>${idx + 1}</td>
      <td>${esc(c.series)}</td>
      <td>${esc(c.number)}</td>
      <td>${esc(c.date)}</td>
      <td>${esc(c.code)}</td>
    </tr>
  `).join('');
  const m = appState.months[ui.tu28MonthIndex];
  const rowObj = m && ui.tu28RowIndex != null ? m.fact[ui.tu28RowIndex] : null;
  const extraList = rowObj && rowObj.tu28_extra ? rowObj.tu28_extra : [];
  const extraRows = extraList.map((txt, idx) => `
    <div style="display:flex; gap:8px; margin-top:8px;">
      <input type="text" style="flex:1; border:1px solid var(--line); border-radius:4px; padding:6px 10px;" value="${esc(txt)}" onchange="updateTu28Extra(${idx}, this.value)" placeholder="Описание доп. ремонта">
      <button style="padding:4px 12px; color:#b00020; font-weight:bold; background:#ffebee; border-radius:4px;" onclick="removeTu28Extra(${idx})">×</button>
    </div>
  `).join('');
  return `
    <div class="section-head">
      <div style="display:flex; justify-content:center; width:100%;">
        <select id="tu28MonthSelect" onchange="setTu28Month(this.value)" style="border:1px solid var(--line); border-radius:8px; background:#fff; padding:10px 12px; font:inherit;">
          ${appState.months.map((m, i) => `<option value="${i}" ${i === ui.tu28MonthIndex ? 'selected' : ''}>${m.name}</option>`).join('')}
        </select>
      </div>
    </div>
    <div class="table-wrap" style="margin:0 auto; width:fit-content; max-width:100%;">
      <table class="acts-table" style="width:max-content; min-width:0; table-layout:auto;">
        <colgroup>
          <col style="width:70px;">
          <col style="width:160px;">
          <col style="width:120px;">
          <col style="width:120px;">
          <col style="width:130px;">
        </colgroup>
        <thead>
          <tr>
            <th>№</th>
            <th>Серия</th>
            <th>Номер</th>
            <th>Дата</th>
            <th>Ремонт</th>
          </tr>
        </thead>
        <tbody>${rows || '<tr><td colspan="5">В месяце нет ремонтов для ТУ-28</td></tr>'}</tbody>
      </table>
    </div>
    <div style="margin-top:16px; padding:0 8px; text-align:left; max-width:600px; margin-left:auto; margin-right:auto;">
      <div style="font-weight:600; margin-bottom:8px; color:#334155;">Дополнительные ремонты:</div>
      ${extraRows}
      <div style="margin-top:12px;">
        <button onclick="addTu28Extra()" style="background:#e2e8f0; color:#102033; font-weight:600; padding:6px 12px; border-radius:6px; font-size:13px;">+ Добавить Доп. ремонт</button>
      </div>
    </div>
  `;
}
function renderTu28Staff(){
  const rows = [
    "Дизель, топливная, вспом. оборуд.",
    "Экипаж",
    "Экипаж",
    "Аккумуляторная батарея",
    "Электрические машины",
    "Эл. аппаратура, КИП, АЛСН, рация",
    "Тормозное оборудование",
  ];
  const options = ['<option value=""></option>'].concat(EMPLOYEE_NAMES.map((name) => `<option value="${esc(name)}">${esc(name)}</option>`)).join('');
  const tableRows = rows.map((label, idx) => {
    const currentStaff = ui.tu28Staff[ui.tu28RowIndex] || [];
    const current = currentStaff[idx] || '';
    return `
      <tr>
        <td>${idx + 1}</td>
        <td>${esc(label)}</td>
        <td>
          <select data-index="${idx}" class="tu28-staff-select">
            ${options.replace(`value="${esc(current)}"`, `value="${esc(current)}" selected`)}
          </select>
        </td>
      </tr>
    `;
  }).join('');
  return `
    <div style="margin-bottom:10px; font-weight:700;">Выберите ФИО исполнителей из списка:</div>
    <div class="table-wrap" style="margin:0 auto; width:fit-content; max-width:100%;">
      <table class="acts-table" style="width:max-content; table-layout:auto;">
        <colgroup>
          <col style="width:40px;">
          <col style="width:auto;">
          <col style="width:260px;">
        </colgroup>
        <thead>
          <tr>
            <th>#</th>
            <th>Вид работ (узел)</th>
            <th>ФИО</th>
          </tr>
        </thead>
        <tbody>${tableRows}</tbody>
      </table>
    </div>
  `;
}
function addTu28Extra(){
  const rowObj = appState.months[ui.tu28MonthIndex].fact[ui.tu28RowIndex];
  if (!rowObj.tu28_extra) rowObj.tu28_extra = [];
  rowObj.tu28_extra.push("");
  saveState();
  render();
}
function updateTu28Extra(idx, val){
  const rowObj = appState.months[ui.tu28MonthIndex].fact[ui.tu28RowIndex];
  if (!rowObj.tu28_extra) rowObj.tu28_extra = [];
  rowObj.tu28_extra[idx] = val;
  saveState();
}
function removeTu28Extra(idx){
  const rowObj = appState.months[ui.tu28MonthIndex].fact[ui.tu28RowIndex];
  if (rowObj.tu28_extra) {
    rowObj.tu28_extra.splice(idx, 1);
    saveState();
    render();
  }
}
function openTu28Modal(){
  ui.tu28RowIndex = null;
  ui.modal = 'tu28';
  render();
}
function renderOpenModals(){
  const normsModal = document.getElementById('normsModal');
  const normsBody = document.getElementById('normsModalBody');
  const actsModal = document.getElementById('actsModal');
  const actsBody = document.getElementById('actsModalBody');
  const tu28Modal = document.getElementById('tu28Modal');
  const tu28Body = document.getElementById('tu28ModalBody');
  if (normsModal && normsBody) {
    if (ui.modal === 'norms') {
      normsModal.classList.add('visible');
      normsModal.setAttribute('aria-hidden', 'false');
      normsBody.innerHTML = renderNorms();
    } else {
      normsModal.classList.remove('visible');
      normsModal.setAttribute('aria-hidden', 'true');
      normsBody.innerHTML = '';
    }
  }
  if (actsModal && actsBody) {
    if (ui.modal === 'acts') {
      actsModal.classList.add('visible');
      actsModal.setAttribute('aria-hidden', 'false');
      actsBody.innerHTML = renderActs();
      requestAnimationFrame(() => {
        const select = document.getElementById('actsMonthSelect');
        if (select) select.focus();
      });
    } else {
      actsModal.classList.remove('visible');
      actsModal.setAttribute('aria-hidden', 'true');
      actsBody.innerHTML = '';
    }
  }
  if (tu28Modal && tu28Body) {
    if (ui.modal === 'tu28') {
      tu28Modal.classList.add('visible');
      tu28Modal.setAttribute('aria-hidden', 'false');
      tu28Body.innerHTML = renderTu28();
      const btnTu28Staff = document.getElementById('btnTu28Staff');
      if (btnTu28Staff) {
        btnTu28Staff.style.display = CAN_EDIT ? '' : 'none';
      }
    } else {
      tu28Modal.classList.remove('visible');
      tu28Modal.setAttribute('aria-hidden', 'true');
      tu28Body.innerHTML = '';
    }
  }
  const tu28StaffModal = document.getElementById('tu28StaffModal');
  const tu28StaffBody = document.getElementById('tu28StaffModalBody');
  if (tu28StaffModal && tu28StaffBody) {
    if (ui.modal === 'tu28staff') {
      tu28StaffModal.classList.add('visible');
      tu28StaffModal.setAttribute('aria-hidden', 'false');
      tu28StaffBody.innerHTML = renderTu28Staff();
      requestAnimationFrame(() => {
        const selects = document.querySelectorAll('.tu28-staff-select');
        selects.forEach((sel) => {
          sel.onchange = (e) => {
            const idx = Number(e.target.dataset.index);
            if (!ui.tu28Staff[ui.tu28RowIndex]) ui.tu28Staff[ui.tu28RowIndex] = [];
            ui.tu28Staff[ui.tu28RowIndex][idx] = e.target.value;
          };
        });
      });
    } else {
      tu28StaffModal.classList.remove('visible');
      tu28StaffModal.setAttribute('aria-hidden', 'true');
      tu28StaffBody.innerHTML = '';
    }
  }
}
function openSectionModal(section){
  ui.modal = section;
  render();
}
function closeNormsModal(){
  if (ui.modal === 'norms') {
    ui.modal = null;
    render();
  }
}
function closeActsModal(){
  if (ui.modal === 'acts') {
    ui.modal = null;
    render();
  }
}
function closeTu28Modal(){
  if (ui.modal === 'tu28') {
    ui.modal = null;
    render();
  }
}
function openTu28StaffModal(){
  const candidates = tu28CandidatesForMonth(ui.tu28MonthIndex);
  const row = candidates.find((x) => x.rowIndex === ui.tu28RowIndex) || candidates[0];
  if (!row) { alert('В месяце нет ремонтов для ТУ-28'); return; }
  ui.tu28RowIndex = row.rowIndex;
  const rowObj = appState.months[ui.tu28MonthIndex].fact[ui.tu28RowIndex];
  if (!rowObj.tu28_staff) {
    rowObj.tu28_staff = ["", "", "", "", "", "", ""];
  }
  ui.modal = 'tu28staff';
  render();
}
function closeTu28StaffModal(){
  if (ui.modal === 'tu28staff') {
    ui.modal = 'tu28';
    render();
  }
}
function setTu28Month(index){
  ui.tu28MonthIndex = Number(index);
  ui.tu28RowIndex = null;
  render();
}
function selectTu28Row(rowIndex){
  if (ui.tu28RowIndex !== Number(rowIndex)) {
    ui.tu28RowIndex = Number(rowIndex);
    render();
  }
}
function downloadTu28(){
  const month = tu28Month();
  if (!month) return;
  const candidates = tu28CandidatesForMonth(ui.tu28MonthIndex);
  const row = candidates.find((x) => x.rowIndex === ui.tu28RowIndex) || candidates[0];
  if (!row) { alert('В месяце нет ремонтов для ТУ-28'); return; }
  const payload = { month: month.name, year: appState.year, row: row.rowIndex, staff: ui.tu28Staff[row.rowIndex] || [], extra_repairs: ui.tu28ExtraRepairs[row.rowIndex] || [], debugger_tu28ExtraRepairs: ui.tu28ExtraRepairs, debugger_tu28RowIndex: ui.tu28RowIndex, debugger_row_rowIndex: row.rowIndex };
  fetch(`{{APP_PREFIX}}/api/tu28-export`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json; charset=utf-8'},
    body: JSON.stringify(payload),
  }).then(async (res) => {
    if (!res.ok) {
      const text = await res.text().catch(() => '');
      try {
        const err = JSON.parse(text || '{}');
        showErrorModal(err.error || text || 'Не удалось сформировать ТУ-28');
      } catch (_) {
        showErrorModal(text ? `Не удалось сформировать ТУ-28:\n${text}` : 'Не удалось сформировать ТУ-28');
      }
      return;
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `ТУ-28_${month.name}_${appState.year}.xlsx`;
    a.click();
    URL.revokeObjectURL(url);
    closeTu28StaffModal();
    closeTu28Modal();
  }).catch((err) => showErrorModal(err && err.stack ? err.stack : 'Не удалось сформировать ТУ-28'));
}
function confirmTu28Staff(){
  downloadTu28();
}
async function saveActsAndClose(){
  if (dirty && CAN_EDIT) {
    await saveState();
  }
  closeActsModal();
}
async function startAct(month, act){
  if (!CAN_EDIT) return;
  setActInfoFlag(month, act, 'is_done', true);
  await saveState();
  const url = `{{APP_PREFIX}}/api/act-export?month=${encodeURIComponent(month)}&act=${encodeURIComponent(act)}&year=${encodeURIComponent(appState.year)}`;
  const a = document.createElement('a');
  a.href = url;
  a.target = '_blank';
  a.rel = 'noopener';
  a.click();
}
let reportDialogState = null;
function openReportModalShell(title){
  document.getElementById('reportTitle').textContent = title;
  document.getElementById('reportBody').innerHTML = '<div class="report-loading">Подготовка отчета...</div>';
  document.getElementById('reportModal').classList.add('visible');
  document.getElementById('reportModal').setAttribute('aria-hidden', 'false');
}
function closeReportModal(){
  const modal = document.getElementById('reportModal');
  modal.classList.remove('visible');
  modal.setAttribute('aria-hidden', 'true');
  reportDialogState = null;
}
function setReportNote(key, value){
  if (!reportDialogState) return;
  const month = reportDialogState.month;
  if (!appState.notes[month]) appState.notes[month] = {};
  appState.notes[month][key] = value;
  reportDialogState.rows = reportDialogState.rows.map((row) => row.key === key ? {...row, note: value} : row);
  autosizeReportNotes();
  markDirty(true);
}
function autosizeReportNotes(){
  document.querySelectorAll('#reportBody textarea.report-note').forEach((el) => {
    el.style.height = '0px';
    el.style.height = `${el.scrollHeight}px`;
  });
}
async function refreshReportDialog(){
  if (!reportDialogState) return;
  if (dirty && CAN_EDIT) {
    await saveState({ refreshReport: false });
  }
  const month = reportDialogState.month;
  const res = await fetch(`{{APP_PREFIX}}/api/report-preview?month=${encodeURIComponent(month)}&year=${encodeURIComponent(reportDialogState.year)}&_=${Date.now()}`, { cache: 'no-store' });
  if (!res.ok) return;
  reportDialogState = await res.json();
  renderReportBody();
}
function renderReportBody(){
  if (!reportDialogState) return;
  const excluded = new Set([
    ...((reportDialogState.excluded && reportDialogState.excluded.plan) || []),
    ...((reportDialogState.excluded && reportDialogState.excluded.fact) || []),
  ]);
  const rows = reportDialogState.rows.map((row) => {
    const rowClass = row.key && (row.excluded || excluded.has(row.key)) ? 'excluded-row' : '';
    if (row.kind === 'group') {
      return `
        <tr class="group-row ${rowClass}">
          <td class="group-cell col-report-name">${esc(row.label)}</td>
          <td class="num-cell col-report-num">${esc(row.plan)}</td>
          <td class="num-cell col-report-num">${esc(row.fact)}</td>
          <td class="group-cell col-report-note">${esc(row.note || '')}</td>
        </tr>
      `;
    }
    return `
      <tr class="${rowClass}">
        <td class="col-report-name">${esc(row.label)}</td>
        <td class="num-cell col-report-num">${esc(row.plan)}</td>
        <td class="num-cell col-report-num">${esc(row.fact)}</td>
        <td class="col-report-note"><textarea rows="1" class="report-note" oninput="setReportNote('${row.key}', this.value)">${esc(row.note || '')}</textarea></td>
      </tr>
    `;
  }).join('');
  document.getElementById('reportBody').innerHTML = `
    <div class="table-wrap report-wrap" style="margin:0 auto; width:fit-content; max-width:100%; padding:0;">
    <table class="report-table">
      <colgroup>
        <col class="col-report-name">
        <col class="col-report-num">
        <col class="col-report-num">
        <col class="col-report-note">
      </colgroup>
      <thead>
        <tr>
          <th>Показатель</th>
          <th>План</th>
          <th>Факт</th>
          <th>Примечание</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
    </div>
  `;
  autosizeReportNotes();
}
async function openReport(){
  if (dirty && CAN_EDIT) {
    await saveState();
  }
  const month = currentMonth().name;
  openReportModalShell(`Отчет ${month} ${appState.year}`);
  const res = await fetch(`{{APP_PREFIX}}/api/report-preview?month=${encodeURIComponent(month)}&year=${encodeURIComponent(appState.year)}&_=${Date.now()}`, { cache: 'no-store' });
  if (!res.ok) {
    document.getElementById('reportBody').innerHTML = '<div class="report-loading">Не удалось подготовить отчет.</div>';
    return;
  }
  reportDialogState = await res.json();
  renderReportBody();
}
async function saveReportAndClose(){
  if (CAN_EDIT && dirty) {
    await saveState();
  }
  closeReportModal();
}
function downloadReportExcel(){
  if (!reportDialogState) return;
  const month = reportDialogState.month;
  const url = `{{APP_PREFIX}}/api/report-export?month=${encodeURIComponent(month)}&year=${encodeURIComponent(reportDialogState.year)}`;
  const a = document.createElement('a');
  a.href = url;
  a.target = '_blank';
  a.rel = 'noopener';
  a.click();
}
function cell(path, value, cls, month, table, row, col, style=''){
  const ro = CAN_EDIT ? '' : 'readonly';
  const styleAttr = style ? ` style="${esc(style)}"` : '';
  return `<input ${ro} class="${cls}" data-path="${path}" data-month="${month}" data-table="${table}" data-row="${row}" data-col="${col}" value="${esc(value)}"${styleAttr} onfocus="setLastCell(this)" onmousedown="beginMonthSelection(event)" onmouseenter="extendMonthSelection(event)" onmouseup="endMonthSelection()" oninput="handleGridInput(this)" onkeydown="handleMonthKeydown(event)" oncopy="handleMonthCopy(event)" onpaste="handleMonthPaste(event)">`;
}
function addRow(type){
  if (!CAN_EDIT) return;
  const m = currentMonth();
  m[type].push({ excluded:false, cells:[String(m[type].length+1),'','','',...Array.from({length:m.days},()=>''),''] });
  markDirty(true); render();
}
function deleteRow(type){ if (!CAN_EDIT) return; const m = currentMonth(); if (m[type].length>0) { m[type].pop(); markDirty(true); render(); } }
async function toggleExcluded(mi, tt, r){
  if (!CAN_EDIT) return;
  const m = appState.months[mi];
  const next = !(m[tt][r] && m[tt][r].excluded);
  ['plan', 'fact'].forEach((kind) => {
    if (m[kind] && m[kind][r]) m[kind][r].excluded = next;
  });
  markDirty(true);
  if (reportDialogState && document.getElementById('reportModal').classList.contains('visible')) {
    await refreshReportDialog();
  } else {
    render();
  }
}
function addNorm(){ if (!CAN_EDIT) return; appState.norms.h_tep.push({k:'', v:''}); markDirty(true); render(); }
function removeNorm(cat, idx){ if (!CAN_EDIT) return; appState.norms[cat].splice(idx,1); markDirty(true); render(); }
function selectRow(section, idx){ ui.selected[section] = idx; }
async function saveState(options = {}){
  const refreshReport = options.refreshReport !== false;
  if (!CAN_EDIT) { alert('Нужен вход'); return; }
  setStatus('Сохранение...');
  const res = await fetch('{{APP_PREFIX}}/api/state', { method:'POST', headers:{'Content-Type':'application/json; charset=utf-8'}, body: JSON.stringify(appState) });
  if (!res.ok) { setStatus('Ошибка'); return; }
  appState = await res.json();
  savedAppState = cloneState(appState);
  savedMonthsState = cloneState(appState.months);
  canceledMonthsState = null;
  markDirty(false);
  setStatus('Сохранено');
  render();
  if (refreshReport && reportDialogState && document.getElementById('reportModal') && document.getElementById('reportModal').classList.contains('visible')) {
    await refreshReportDialog();
  }
}
function downloadJson(){
  const b = new Blob([JSON.stringify(appState, null, 2)], {type:'application/json;charset=utf-8'});
  const u = URL.createObjectURL(b);
  const a = document.createElement('a'); a.href = u; a.download = `grafik_ppr_${appState.year}.json`; a.click(); URL.revokeObjectURL(u);
}
async function importJson(event){
  if (!CAN_EDIT) { alert('Нужен вход'); return; }
  const f = event.target.files[0]; event.target.value = ''; if (!f) return;
  const payload = JSON.parse(await f.text());
  const res = await fetch('{{APP_PREFIX}}/api/import', { method:'POST', headers:{'Content-Type':'application/json; charset=utf-8'}, body: JSON.stringify(payload) });
  if (!res.ok) { alert('Импорт не удался'); return; }
  appState = await res.json();
  savedAppState = cloneState(appState);
  savedMonthsState = cloneState(appState.months);
  canceledMonthsState = null;
  markDirty(false);
  render();
}
async function loadYear(year){
  const res = await fetch(`{{APP_PREFIX}}/api/state?year=${encodeURIComponent(year)}`);
  if (!res.ok) { alert('Не удалось загрузить год'); return; }
  appState = await res.json();
  savedAppState = cloneState(appState);
  savedMonthsState = cloneState(appState.months);
  canceledMonthsState = null;
  markDirty(false);
  render();
}
async function loadYearFromInput(){
  const year = parseInt(document.getElementById('yearInput').value, 10);
  if (!year) return;
  promptLeave('Есть несохранённые изменения. Сохранить перед открытием другого года?', () => loadYear(year));
}
function requestHomeClick(event){
  if (event) event.preventDefault();
  return promptLeave('Есть несохранённые изменения. Сохранить перед переходом на главную?', () => { location.href = '/'; });
}
function cancelChanges(){
  if (!CAN_EDIT || !savedMonthsState) return;
  canceledMonthsState = cloneState(appState.months);
  appState.months = cloneState(savedMonthsState);
  markDirty(JSON.stringify(appState) !== JSON.stringify(savedAppState));
  render();
}
function restoreChanges(){
  if (!CAN_EDIT || !canceledMonthsState) return;
  appState.months = cloneState(canceledMonthsState);
  canceledMonthsState = null;
  markDirty(JSON.stringify(appState) !== JSON.stringify(savedAppState));
  render();
}
window.addEventListener('beforeunload', (e)=>{ if (dirty && CAN_EDIT) { e.preventDefault(); e.returnValue=''; } });
window.addEventListener('popstate', () => {
  if (!leaveGuardInstalled || !CAN_EDIT) return;
  promptLeave('Есть несохранённые изменения. Сохранить перед уходом?', () => { location.href = '/'; });
});
savedAppState = cloneState(appState);
savedMonthsState = cloneState(appState.months);
updateHistoryButtons();
render();
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # noqa: D401
        return

    def do_GET(self):
        parsed = urlparse(self.path)
        route = _route_path(parsed.path)
        session = current_session(self)
        user = session[0] if session else None
        mod_role = get_mod_role(session, "grafik_ppr")
        if route == "/":
            _redirect(self, APP_PREFIX)
            return
        if route == "/grafik-ppr":
            year = dt.date.today().year
            qs = parse_qs(parsed.query)
            if "year" in qs:
                try:
                    year = int(qs["year"][0])
                except ValueError:
                    year = dt.date.today().year
            # Logging
            try:
                raw_cookie = self.headers.get("Cookie", "")
                with open(ROOT.parent / "data" / "grafik_auth.log", "a", encoding="utf-8") as f:
                    f.write(f"Access /grafik-ppr. Session: {session}. Cookie: {raw_cookie}\n")
            except Exception:
                pass
            
            if AUTH_ENABLED and not mod_role:
                self.send_response(HTTPStatus.UNAUTHORIZED)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("WWW-Authenticate", 'Form realm="Grafik PPR"')
                self.end_headers()
                self.wfile.write("Требуется вход".encode("utf-8"))
                return
                
            _send_html(self, render_page(load_state(year), mod_role in ("edit", "editor", "admin") if AUTH_ENABLED else True, user))
            return
        if route == "/login":
            if not AUTH_ENABLED:
                _redirect(self, APP_PREFIX)
                return
            if user:
                _redirect(self, APP_PREFIX)
                return
            _send_html(self, render_login())
            return
        if route == "/logout":
            _redirect(self, "/")
            return
        if route == "/api/state":
            qs = parse_qs(parsed.query)
            year = dt.date.today().year
            if "year" in qs:
                try:
                    year = int(qs["year"][0])
                except ValueError:
                    year = dt.date.today().year
            json_response(self, load_state(year))
            return
        if route == "/api/export":
            if not require_auth(self):
                return
            qs = parse_qs(parsed.query)
            year = dt.date.today().year
            if "year" in qs:
                try:
                    year = int(qs["year"][0])
                except ValueError:
                    year = dt.date.today().year
            body = json.dumps(load_state(year), ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Disposition", f'attachment; filename="grafik_ppr_{year}.json"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if route == "/api/act-export":
            if not require_auth(self):
                return
            qs = parse_qs(parsed.query)
            year = dt.date.today().year
            if "year" in qs:
                try:
                    year = int(qs["year"][0])
                except ValueError:
                    year = dt.date.today().year
            month = s(qs.get("month", [""])[0]).strip()
            act = s(qs.get("act", [""])[0]).strip()
            try:
                body, filename = build_act_workbook(year, act)
            except Exception as exc:
                json_response(self, {"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            self.send_header("Content-Disposition", content_disposition_attachment(filename))
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if route == "/api/report-export":
            if not require_auth(self):
                return
            qs = parse_qs(parsed.query)
            year = dt.date.today().year
            if "year" in qs:
                try:
                    year = int(qs["year"][0])
                except ValueError:
                    year = dt.date.today().year
            month = s(qs.get("month", [""])[0]).strip() or MONTHS_RU[dt.date.today().month - 1]
            try:
                body, filename = build_report_workbook(year, month)
            except Exception as exc:
                json_response(self, {"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            self.send_header("Content-Disposition", content_disposition_attachment(filename))
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if route == "/api/report-preview":
            if not require_auth(self):
                return
            qs = parse_qs(parsed.query)
            year = dt.date.today().year
            if "year" in qs:
                try:
                    year = int(qs["year"][0])
                except ValueError:
                    year = dt.date.today().year
            month = s(qs.get("month", [""])[0]).strip() or MONTHS_RU[dt.date.today().month - 1]
            try:
                state = load_state(year)
                data = calculate_report_data_from_state(state, month)
                saved_notes = state.get("notes", {}).get(month, {}) or {}
                json_response(self, build_report_preview(month, data, saved_notes))
            except Exception as exc:
                json_response(self, {"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self):
        parsed = urlparse(self.path)
        route = _route_path(parsed.path)
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        if route == "/login":
            if not AUTH_ENABLED:
                _redirect(self, APP_PREFIX)
                return
            form = parse_qs(raw.decode("utf-8", errors="ignore"))
            username = form.get("user", [""])[0].strip()
            password = form.get("password", [""])[0]
            if username == WEB_USER and password == WEB_VIEW_PASSWORD:
                _redirect(self, APP_PREFIX, _login_cookie(username, "view"))
                return
            if username == WEB_USER and password == WEB_EDIT_PASSWORD:
                _redirect(self, APP_PREFIX, _login_cookie(username, "edit"))
                return
            _send_html(self, render_login("<p style='text-align:center;color:#b00020;'>Неверный логин или пароль</p>"), status=HTTPStatus.UNAUTHORIZED)
            return
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            payload = {}
        if route in {"/api/state", "/api/import"}:
            if not require_auth(self, need_edit=True):
                return
            try:
                saved = save_state(payload)
            except Exception as exc:
                json_response(self, {"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            json_response(self, saved)
            return
        if route == "/api/tu28-export":
            if not require_auth(self):
                return
            year = int(payload.get("year") or dt.date.today().year)
            month = s(payload.get("month", "")).strip() or MONTHS_RU[dt.date.today().month - 1]
            row_raw = payload.get("row", None)
            if row_raw in (None, ""):
                json_response(self, {"error": "В месяце нет ремонтов для ТУ-28"}, status=HTTPStatus.BAD_REQUEST)
                return
            try:
                row_idx = int(row_raw)
            except Exception:
                json_response(self, {"error": "Не удалось определить строку ремонта"}, status=HTTPStatus.BAD_REQUEST)
                return
            staff_list = payload.get("staff") or []
            if not isinstance(staff_list, list):
                staff_list = []
            extra_repairs = payload.get("extra_repairs") or []
            print(f"DEBUG: raw extra_repairs={payload.get('extra_repairs')} | tu28ExtraRepairs={payload.get('debugger_tu28ExtraRepairs')} | ui.tu28RowIndex={payload.get('debugger_tu28RowIndex')} | row.rowIndex={payload.get('debugger_row_rowIndex')}", flush=True)
            if not isinstance(extra_repairs, list):
                extra_repairs = []
            try:
                body, filename = build_tu28_workbook(year, month, row_idx, staff_list, extra_repairs=extra_repairs)
            except Exception as exc:
                json_response(self, {"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                return
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            self.send_header("Content-Disposition", content_disposition_attachment(filename))
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")


def main() -> None:
    global SERVER_STARTED_AT
    SERVER_STARTED_AT = dt.datetime.now()
    ensure_database()
    host = os.environ.get("WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("WEB_PORT", "8000"))
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    url = f"http://{host}:{port}"
    print(f"График ППР web ready: {url} | started at {SERVER_STARTED_AT:%H:%M:%S %d.%m.%Y}")
    if host in {"127.0.0.1", "localhost", "0.0.0.0"}:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    server.serve_forever()


if __name__ == "__main__":
    main()