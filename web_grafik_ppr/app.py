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

APP_VERSION = "web-gpp-0.1"
MONTHS_RU = [
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]
TEM_NORM_ROWS = ["ТО2", "ТО3", "ТР1", "ТР2", "ТР3", "СР", "КР"]
AGR_NORM_ROWS = ["ТО", "ТР", "КР"]
FIXED_HOLIDAYS = {
    (1, 1), (1, 2), (1, 3), (1, 4), (1, 5), (1, 6), (1, 7), (1, 8),
    (2, 23), (3, 8), (5, 1), (5, 9), (6, 12), (11, 4),
}

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DB_FILE = DATA_DIR / "grafik_ppr_web.db"
AUTH_FILE = DATA_DIR / "web_auth.json"
SHARED_DATA_DIR = ROOT.parent / "data"
WEB_SECRET_FILE = SHARED_DATA_DIR / "web_secret.txt"
SOURCE_DB = ROOT.parent / "base" / "common_database.db"
SOURCE_DIR = ROOT.parent / "src" / "График ППР"
ACT_TEMPLATE_NAME = "Акт_шаблон.xlsx"

DB_LOCK = Lock()
SERVER_STARTED_AT = None
SESSION_COOKIE = "grafik_ppr_session"
SESSION_TTL_SECONDS = 7 * 24 * 60 * 60


def load_web_secret() -> str:
    secret = os.environ.get("WEB_SECRET", "").strip()
    if secret:
        return secret
    SHARED_DATA_DIR.mkdir(parents=True, exist_ok=True)
    if WEB_SECRET_FILE.exists():
        try:
            secret = WEB_SECRET_FILE.read_text(encoding="utf-8").strip()
            if secret:
                return secret
        except Exception:
            pass
    secret = secrets.token_urlsafe(32)
    WEB_SECRET_FILE.write_text(secret, encoding="utf-8")
    return secret


WEB_SECRET = load_web_secret()
SESSIONS: dict[str, tuple[str, str, float]] = {}


def load_auth_config() -> tuple[str, str]:
    user = os.environ.get("WEB_USER", "admin").strip() or "admin"
    password = (
        os.environ.get("WEB_PASSWORD", "").strip()
        or os.environ.get("WEB_EDIT_PASSWORD", "").strip()
        or os.environ.get("WEB_VIEW_PASSWORD", "").strip()
    )
    if password:
        return user, password
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if AUTH_FILE.exists():
        try:
            payload = json.loads(AUTH_FILE.read_text(encoding="utf-8"))
            file_user = str(payload.get("user", user)).strip() or user
            file_password = str(payload.get("password", "")).strip()
            if file_password:
                return file_user, file_password
            file_password = str(payload.get("edit_password", "")).strip()
            if file_password:
                AUTH_FILE.write_text(
                    json.dumps(
                        {"user": file_user, "password": file_password},
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                return file_user, file_password
            file_password = str(payload.get("view_password", "")).strip()
            if file_password:
                AUTH_FILE.write_text(
                    json.dumps(
                        {"user": file_user, "password": file_password},
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                return file_user, file_password
        except Exception:
            pass
    password = secrets.token_urlsafe(8)
    AUTH_FILE.write_text(
        json.dumps(
            {"user": user, "password": password},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Web auth created: user={user} password={password}")
    return user, password


WEB_USER, WEB_PASSWORD = load_auth_config()
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


def _verify_cookie(value: str) -> tuple[str, str] | None:
    try:
        username, role, ts, signature = value.rsplit(":", 3)
        payload = f"{username}:{role}:{ts}"
        expected = hmac.new(WEB_SECRET.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        if int(ts) + SESSION_TTL_SECONDS < int(dt.datetime.now().timestamp()):
            return None
        if role not in {"view", "edit"}:
            return None
        return username, role
    except Exception:
        return None


def _parse_cookies(handler: BaseHTTPRequestHandler) -> dict[str, str]:
    raw = handler.headers.get("Cookie", "")
    cookies: dict[str, str] = {}
    for part in raw.split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        cookies[key.strip()] = value.strip()
    return cookies


def current_session(handler: BaseHTTPRequestHandler) -> tuple[str, str] | None:
    if not AUTH_ENABLED:
        return WEB_USER, "edit"
    cookies = _parse_cookies(handler)
    token = cookies.get(SESSION_COOKIE)
    if not token:
        return None
    session = _verify_cookie(token)
    if session:
        username, role = session
        SESSIONS[token] = (username, role, dt.datetime.now().timestamp())
    return session


def require_auth(handler: BaseHTTPRequestHandler, need_edit: bool = False) -> bool:
    if not AUTH_ENABLED:
        return True
    session = current_session(handler)
    if session and (not need_edit or session[1] == "edit"):
        return True
    handler.send_response(HTTPStatus.UNAUTHORIZED)
    handler.send_header("Content-Type", "text/plain; charset=utf-8")
    handler.send_header("WWW-Authenticate", 'Form realm="Grafik PPR"')
    handler.end_headers()
    handler.wfile.write("Требуется вход".encode("utf-8"))
    return False


def render_page(state: dict, can_edit: bool, username: str | None) -> str:
    state_json = json.dumps(state, ensure_ascii=False).replace("</", "<\\/")
    started_at = SERVER_STARTED_AT.strftime("%H:%M:%S %d.%m.%Y") if SERVER_STARTED_AT else "неизвестно"
    toolbar = EDIT_TOOLBAR if can_edit else READONLY_TOOLBAR
    auth_badge = "Вход открыт" if not AUTH_ENABLED else (f"Пользователь: {username}" if username else "Режим: вход")
    return (
        HTML_TEMPLATE.replace("{{STATE_JSON}}", state_json)
        .replace("{{STARTED_AT}}", started_at)
        .replace("{{APP_VERSION}}", APP_VERSION)
        .replace("{{TOOLBAR}}", toolbar)
        .replace("{{AUTH_BADGE}}", auth_badge)
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
        <button onclick="saveState()">Сохранить</button>
        <button onclick="downloadJson()">Экспорт JSON</button>
        <button onclick="document.getElementById('importFile').click()">Импорт JSON</button>
        <a class="badge" href="/" style="text-decoration:none;">Выйти</a>
        <input id="importFile" type="file" accept=".json,application/json" style="display:none" onchange="importJson(event)">
      </div>
"""

READONLY_TOOLBAR = """
      <div class="toolbar">
        <label>Год <select id="yearInput" onchange="loadYearFromInput()"></select></label>
        <a class="badge" href="{{APP_PREFIX}}/login" style="text-decoration:none;">Войти</a>
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
    button { background:#276ef1; color:#fff; font-weight:700; cursor:pointer; border:0; }
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
        <a class="badge" href="{{APP_PREFIX}}/logout">Выйти</a>
        <div class="badge">{{AUTH_BADGE}}</div>
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
    auth_badge = "Вход открыт" if not AUTH_ENABLED else (f"Пользователь: {username}" if username else "Режим: вход")
    return (
        HOME_TEMPLATE.replace("{{STARTED_AT}}", started_at)
        .replace("{{AUTH_BADGE}}", auth_badge)
    )


def _login_cookie(username: str, role: str) -> str:
    token = _cookie_value(username, role)
    SESSIONS[token] = (username, role, dt.datetime.now().timestamp())
    return f"{SESSION_COOKIE}={token}; HttpOnly; Path=/; SameSite=Lax"

HTML_TEMPLATE = """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>График ППР web {{APP_VERSION}}</title>
  <style>
    :root { --bg:#f4f7fb; --card:#fff; --line:#d9e2ef; --text:#102033; --muted:#607086; --accent:#276ef1; --soft:#eaf1ff; --shadow:0 12px 32px rgba(16,32,51,.08); --radius:18px; --meta-col-width:80px; }
    * { box-sizing:border-box; }
    body { margin:0; font-family:"Segoe UI", Arial, sans-serif; background:linear-gradient(180deg,#e8eefb, #f7f9fc 150px) fixed; color:var(--text); }
    .shell { max-width:1700px; margin:0 auto; padding:18px; }
    .topbar,.nav,.panel { background:rgba(255,255,255,.88); border:1px solid rgba(217,226,239,.9); border-radius:var(--radius); box-shadow:var(--shadow); }
    .topbar { display:flex; gap:14px; align-items:center; justify-content:space-between; padding:14px 16px; margin-bottom:14px; flex-wrap:wrap; }
    .titlebox h1 { margin:0; font-size:22px; }
    .titlebox .sub { color:var(--muted); font-size:13px; margin-top:2px; }
    .toolbar { display:flex; flex-wrap:wrap; gap:10px; align-items:center; }
    .toolbar input,.toolbar button,select,textarea { border:1px solid var(--line); border-radius:8px; background:#fff; padding:10px 12px; font:inherit; }
    .toolbar button { font-weight:700; cursor:pointer; background:linear-gradient(180deg,#fff,#f3f7ff); }
    .nav { display:flex; gap:8px; flex-wrap:wrap; padding:0; margin:0; }
    .nav button { border:1px solid var(--line); background:#fff; border-radius:8px; padding:10px 14px; font-weight:700; cursor:pointer; }
    .nav button.active { background:var(--accent); color:#fff; border-color:var(--accent); }
    .controls { display:flex; gap:8px; align-items:center; flex-wrap:wrap; justify-content:flex-end; }
    .panel { padding:14px; }
    .section-head { display:flex; flex-wrap:wrap; gap:10px; justify-content:space-between; align-items:center; margin-bottom:10px; }
    .section-title { font-size:18px; font-weight:800; }
    .months-row { position:sticky; top:0; z-index:4; display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:10px; align-items:start; margin:6px 0 10px; background:rgba(255,255,255,.96); padding:0 0 6px; }
    .months-row .month-strip { display:flex; gap:2px; flex-wrap:nowrap; min-width:0; width:100%; overflow:visible; }
    .months-row .row-actions { display:flex; gap:4px; align-items:center; justify-content:flex-end; justify-self:end; align-self:start; flex-shrink:0; }
    .month-strip button { border:1px solid var(--line); background:#fff; border-radius:8px; padding:4px 7px; font-weight:700; font-size:12px; cursor:pointer; white-space:nowrap; }
    .month-strip button.active { background:#0e5bd8; border-color:#0e5bd8; color:#fff; }
    .repair-strip { display:flex; gap:3px; flex-wrap:nowrap; margin:0; justify-content:center; }
    .repair-strip button { border:1px solid var(--line); background:#fff; border-radius:8px; padding:4px 7px; font-weight:700; font-size:12px; cursor:pointer; min-width:40px; }
    .month-tools { display:none; }
    .row-actions { display:flex; gap:4px; align-items:center; justify-content:flex-end; flex-shrink:0; }
    .row-actions button { border:1px solid var(--line); background:#fff; border-radius:8px; padding:4px 7px; font-weight:700; font-size:12px; cursor:pointer; white-space:nowrap; }
    .row-actions button.danger { background:#fff; }
    .act-start {
      width:100%;
      border:1px solid var(--line);
      background:linear-gradient(180deg,#fff,#f3f7ff);
      border-radius:8px;
      padding:8px 12px;
      font:inherit;
      font-weight:700;
      font-size:16px;
      cursor:pointer;
    }
    .act-start:disabled { opacity:.5; cursor:default; }
    .table-wrap { overflow:auto; border:1px solid var(--line); border-radius:18px; background:#fff; }
    table { border-collapse:separate; border-spacing:0; width:100%; min-width:720px; table-layout:fixed; }
    th,td { border-right:1px solid var(--line); border-bottom:1px solid var(--line); padding:0; background:#fff; vertical-align:middle; }
    th { position:sticky; top:0; z-index:1; background:linear-gradient(180deg,#f8fbff,#edf4ff); font-size:15px; padding:14px 10px; text-align:center; white-space:nowrap; }
    .cell { display:block; width:100%; min-width:0; box-sizing:border-box; border:0; margin:0; padding:5px 8px; height:34px; line-height:1; font:inherit; font-size:15px; background:transparent; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .cell.center { text-align:center; }
    .cell.cat-toggle {
      display:block;
      box-sizing:border-box;
      align-items:center;
      width:100%;
      text-align:center;
    }
    .rownum { display:flex; gap:8px; align-items:center; justify-content:center; padding:2px 6px; min-height:28px; font-size:15px; }
    .rowbtn { width:26px; height:26px; border-radius:8px; border:1px solid var(--line); background:#fff; cursor:pointer; font-weight:800; font-size:14px; }
    .rowbtn.cat-toggle { width:100%; height:30px; border-radius:0; border:0; background:transparent; }
    .badge { padding:5px 10px; border-radius:8px; background:var(--soft); color:#1d4aa6; font-weight:700; }
    .footerbar { margin-top:12px; display:flex; gap:10px; flex-wrap:wrap; align-items:center; justify-content:space-between; color:var(--muted); font-size:13px; }
    .danger { background:#fff3f3; }
    .small { width:100%; min-width:0; text-align:center; font-size:15px; }
    .notes { width:100%; min-height:120px; resize:vertical; padding:10px; border:1px solid var(--line); border-radius:14px; }
    .excluded-row { color:#9aa5b1; background:#f3f5f8; }
    .excluded-row input { background:#f3f5f8; color:#9aa5b1; }
    .transfer-col { background:#dcf8dc; }
    .transfer-col input { background:#dcf8dc; }
    .holiday-col { background:#ffdede; }
    .holiday-col input { background:#ffdede; }
    .col-idx { width:36px; }
    .col-series { width:72px; }
    .col-number { width:72px; }
    .col-cat { width:72px; }
    .col-day { width:28px; }
    .col-note { width:120px; }
    .grid2 { display:grid; gap:14px; grid-template-columns:1fr; }
    .compact th, .compact td { font-size:15px; }
    .month-table { table-layout:fixed; width:max-content; }
    .month-table tbody tr { height:34px; }
    .group-row td { background:#f5f8fd; font-weight:700; text-align:center; }
    @media (max-width:900px) { .topbar { flex-direction:column; align-items:stretch; } .controls { justify-content:flex-start; } .months-row { display:flex; align-items:flex-start; flex-direction:column; position:static; } .month-strip { flex-wrap:wrap; overflow:visible; } .month-tools { display:none; } .repair-strip { flex-wrap:wrap; } }
  </style>
</head>
<body>
  <div class="shell">
    <div class="topbar">
      <div class="titlebox">
        <h1>График ППР</h1>
        <div class="sub">Web-копия {{APP_VERSION}}. Отдельная база, исходный PyQt-файл не тронут.</div>
      </div>
      <div class="controls">
      <div class="badge">{{AUTH_BADGE}}</div>
      <div class="nav" id="sectionNav"></div>
      {{TOOLBAR}}
      </div>
    </div>
    <div class="panel">
      <div id="content"></div>
      <div class="footerbar">
        <div id="serverInfo" class="badge">Сервер: {{STARTED_AT}}</div>
        <div id="status" class="badge">Готово</div>
        <div id="dirtyHint">Изменений нет</div>
      </div>
    </div>
  </div>
<script>
const BOOT_VERSION = "{{APP_VERSION}}";
const BOOT_STARTED_AT = "{{STARTED_AT}}";
let appState = {{STATE_JSON}};
let ui = { section: 'months', monthIndex: new Date().getMonth(), mode: 'plan', selected: { months: null, norms: null } };
let dirty = false;
const CAN_EDIT = {{CAN_EDIT}};
const TEM_NORM_ROWS = {{TEM_NORM_ROWS}};
const AGR_NORM_ROWS = {{AGR_NORM_ROWS}};
const REPAIR_AUTO_FILL_DAYS = {"ТО3": 1, "ТР1": 4, "ТР": 4, "ТР2": 9, "ТР3": 14};
const sections = [{id:'months',label:'Месяцы'},{id:'norms',label:'Нормы / парк'},{id:'acts',label:'Акты'}];

function esc(v){ return String(v ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#39;'); }
function setStatus(t){ document.getElementById('status').textContent = t; }
function markDirty(v=true){ dirty=v; document.getElementById('dirtyHint').textContent = v ? 'Есть несохранённые изменения' : 'Изменений нет'; }
function setLastCell(el){
  if (!el || !el.dataset) return;
  ui.lastCell = {
    table: el.dataset.table,
    row: Number(el.dataset.row),
    col: Number(el.dataset.col),
    path: el.dataset.path,
  };
}
function setPath(path, value){
  if (!CAN_EDIT) return;
  const p = path.split('.');
  let o = appState;
  for (let i=0; i<p.length-1; i++) o = o[p[i]];
  const last = p[p.length-1];
  o[last] = value;
  markDirty(true);
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
function handleMonthPaste(e){
  if (!CAN_EDIT) return;
  const target = e.target;
  if (!target || !target.dataset || target.dataset.month === undefined) return;
  const text = (e.clipboardData || window.clipboardData).getData('text');
  if (!text) return;
  const table = target.dataset.table;
  const startRow = parseInt(target.dataset.row, 10);
  const startCol = parseInt(target.dataset.col, 10);
  if (!Number.isFinite(startRow) || !Number.isFinite(startCol)) return;
  const rows = text.replace(/\\r/g, '').split('\\n').filter((row, idx, arr) => !(row === '' && idx === arr.length - 1));
  if (!rows.length) return;
  e.preventDefault();
  rows.forEach((line, rOffset) => {
    const cols = line.split('\\t');
    cols.forEach((value, cOffset) => {
      const row = startRow + rOffset;
      const col = startCol + cOffset;
      const selector = `input[data-month="${ui.monthIndex}"][data-table="${table}"][data-row="${row}"][data-col="${col}"]`;
      const cell = document.querySelector(selector);
      if (!cell) return;
      const normalized = value ?? '';
      cell.value = normalized;
      setPath(cell.dataset.path, normalized);
    });
  });
  markDirty(true);
}
function bindNav(){
  document.getElementById('sectionNav').innerHTML = sections.map(s => `<button class="${ui.section===s.id?'active':''}" onclick="setSection('${s.id}')">${s.label}</button>`).join('');
}
function setSection(section){ ui.section = section; render(); }
function setMonth(index){ ui.monthIndex = index; render(); }
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
  ensureYearOptions();
  const serverInfo = document.getElementById('serverInfo');
  if (serverInfo) serverInfo.textContent = `Сервер: ${BOOT_STARTED_AT}`;
  const sub = document.querySelector('.sub');
  if (sub) sub.textContent = `Web-копия ${BOOT_VERSION}. Отдельная база, исходный PyQt-файл не тронут.`;
  document.title = `График ППР web ${BOOT_VERSION}`;
  bindNav();
  const content = document.getElementById('content');
  if (!content) return;
  if (ui.section === 'months') content.innerHTML = renderMonths();
  if (ui.section === 'norms') content.innerHTML = renderNorms();
  if (ui.section === 'acts') content.innerHTML = renderActs();
  if (ui.section === 'acts') {
    requestAnimationFrame(() => {
      const select = document.getElementById('actsMonthSelect');
      if (select) select.focus();
    });
  }
}
function repairButtonsHtml(){
  return `
      <div class="repair-strip">
        <button ${CAN_EDIT ? '' : 'disabled'} onclick="insertRepair('ТО2')">ТО2</button>
        <button ${CAN_EDIT ? '' : 'disabled'} onclick="insertRepair('ТО3')">ТО3</button>
        <button ${CAN_EDIT ? '' : 'disabled'} onclick="insertRepair('ТР1')">ТР1</button>
        <button ${CAN_EDIT ? '' : 'disabled'} onclick="insertRepair('ТР2')">ТР2</button>
        <button ${CAN_EDIT ? '' : 'disabled'} onclick="insertRepair('ТР3')">ТР3</button>
        <button ${CAN_EDIT ? '' : 'disabled'} onclick="insertRepair('ТО')">ТО</button>
        <button ${CAN_EDIT ? '' : 'disabled'} onclick="insertRepair('ТР')">ТР</button>
      </div>
    `;
}
function monthSelectHtml(){
  return `
    <select id="actsMonthSelect" onchange="setMonth(parseInt(this.value, 10))" style="border:1px solid var(--line); border-radius:8px; padding:2px 4px; font:inherit; font-size:15px; background:#fff; width:72px; min-width:72px; max-width:72px;">
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
      <div class="row-actions">
        <button onclick="addRow('plan'); addRow('fact')">+ строку</button>
        <button class="danger" onclick="deleteRow('plan'); deleteRow('fact')">- строку</button>
      </div>
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
      rowHtml.push(`<td class="col-day ${cls}">${cell(`months.${ui.monthIndex}.${type}.${rIdx}.cells.${4+d}`, row.cells[4+d] || '', `cell small center ${cls}`, ui.monthIndex, type, rIdx, 4+d) }</td>`);
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
    '<col style="width:var(--meta-col-width)">',
    '<col style="width:var(--meta-col-width)">',
    '<col style="width:var(--meta-col-width)">',
    ...Array.from({length:m.days}, (_, d) => `<col style="width:36px" class="${dayClass(m.month, d + 1)}">`),
    '<col style="width:180px">'
  ].join('');
  return `
    <div class="section-head" style="margin-top:16px;">
      <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;">
        <div class="section-title">${title}</div>
        ${repairButtonsHtml()}
      </div>
    </div>
    <div class="table-wrap">
      <table class="compact month-table" style="min-width:${(4+m.days+2)*34 + 300}px">
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
    <div class="section-head">
      <div><div class="section-title">Нормы / парк</div><div class="sub">Нормативы часов и план парка.</div></div>
    </div>
    <div class="table-wrap" style="margin-bottom:14px;">
      <table class="compact">
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
function renderActs(){
  const month = currentMonth().name;
  const acts = appState.acts[month] || {};
  const rows = Object.keys(acts).sort().map(act => {
    const x = acts[act];
    return `<tr>
      <td>${esc(act)}</td>
      <td><button class="act-start" ${CAN_EDIT ? '' : 'disabled'} onclick="startAct('${month}', '${act}')">Пуск</button></td>
      <td class="center"><input type="checkbox" ${x.is_done ? 'checked' : ''} onchange="setPath('acts.${month}.${act}.is_done', this.checked)"></td>
      <td class="center"><input type="checkbox" ${x.sap_order_done ? 'checked' : ''} onchange="setPath('acts.${month}.${act}.sap_order_done', this.checked)"></td>
    </tr>`;
  }).join('');
  return `
    <div class="section-head">
      <div style="display:flex; align-items:center; gap:6px; flex-wrap:nowrap; justify-content:center; width:100%;">
        <div class="section-title">Акты</div>
        ${monthSelectHtml()}
      </div>
    </div>
    <div class="table-wrap" style="width:fit-content; max-width:100%; margin:0 auto;">
      <table class="compact" style="width:max-content; min-width:0;">
        <colgroup>
          <col style="width:220px;">
          <col style="width:160px;">
          <col style="width:150px;">
          <col style="width:170px;">
        </colgroup>
        <thead><tr><th>№ акта</th><th>Сформировать акт</th><th>Акт сформирован</th><th>Создан заказ в SAP</th></tr></thead>
        <tbody>${rows || '<tr><td colspan="4">Нет данных</td></tr>'}</tbody>
      </table>
    </div>
  `;
}
async function startAct(month, act){
  if (!CAN_EDIT) return;
  setPath(`acts.${month}.${act}.is_done`, true);
  await saveState();
  const url = `{{APP_PREFIX}}/api/act-export?month=${encodeURIComponent(month)}&act=${encodeURIComponent(act)}&year=${encodeURIComponent(appState.year)}`;
  const a = document.createElement('a');
  a.href = url;
  a.target = '_blank';
  a.rel = 'noopener';
  a.click();
}
function cell(path, value, cls, month, table, row, col){
  const ro = CAN_EDIT ? '' : 'readonly';
  return `<input ${ro} class="${cls}" data-path="${path}" data-month="${month}" data-table="${table}" data-row="${row}" data-col="${col}" value="${esc(value)}" onfocus="setLastCell(this)" oninput="setPath(this.dataset.path, this.value)" onkeydown="handleMonthKeydown(event)" onpaste="handleMonthPaste(event)">`;
}
function addRow(type){
  if (!CAN_EDIT) return;
  const m = currentMonth();
  m[type].push({ excluded:false, cells:[String(m[type].length+1),'','','',...Array.from({length:m.days},()=>''),''] });
  markDirty(true); render();
}
function deleteRow(type){ if (!CAN_EDIT) return; const m = currentMonth(); if (m[type].length>0) { m[type].pop(); markDirty(true); render(); } }
function toggleExcluded(mi, tt, r){ if (!CAN_EDIT) return; appState.months[mi][tt][r].excluded = !appState.months[mi][tt][r].excluded; markDirty(true); render(); }
function addNorm(){ if (!CAN_EDIT) return; appState.norms.h_tep.push({k:'', v:''}); markDirty(true); render(); }
function removeNorm(cat, idx){ if (!CAN_EDIT) return; appState.norms[cat].splice(idx,1); markDirty(true); render(); }
function selectRow(section, idx){ ui.selected[section] = idx; }
async function saveState(){
  if (!CAN_EDIT) { alert('Нужен вход'); return; }
  setStatus('Сохранение...');
  const res = await fetch('{{APP_PREFIX}}/api/state', { method:'POST', headers:{'Content-Type':'application/json; charset=utf-8'}, body: JSON.stringify(appState) });
  if (!res.ok) { setStatus('Ошибка'); return; }
  appState = await res.json();
  markDirty(false);
  setStatus('Сохранено');
  render();
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
  appState = await res.json(); markDirty(false); render();
}
async function loadYear(year){
  const res = await fetch(`{{APP_PREFIX}}/api/state?year=${encodeURIComponent(year)}`);
  if (!res.ok) { alert('Не удалось загрузить год'); return; }
  appState = await res.json(); markDirty(false); render();
}
async function loadYearFromInput(){
  const year = parseInt(document.getElementById('yearInput').value, 10);
  if (!year) return;
  if (dirty && !confirm('Есть несохранённые изменения. Открыть год без сохранения?')) { ensureYearOptions(); return; }
  await loadYear(year);
}
window.addEventListener('beforeunload', (e)=>{ if (dirty) { e.preventDefault(); e.returnValue=''; } });
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
        role = session[1] if session else None
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
            _send_html(self, render_page(load_state(year), role == "edit", user))
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
            if username == WEB_USER and password == WEB_PASSWORD:
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
