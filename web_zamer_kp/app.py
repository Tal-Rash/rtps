from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parent
SHARED_DATA_DIR = ROOT.parent / "data"
LEGACY_WEB_SECRET_FILE = ROOT / "data" / "web_secret.txt"
WEB_SECRET_FILE = SHARED_DATA_DIR / "web_secret.txt"
ACCESS_STATE_FILE = SHARED_DATA_DIR / "web_access.json"
DB_FILE = ROOT.parent / "base" / "common_database.db"
SESSION_COOKIE = "grafik_ppr_session"
SESSION_TTL_SECONDS = 7 * 24 * 60 * 60
APP_PREFIX = "/zamer-kp"
APP_VERSION = "web-zkp-1.15"
DB_LOCK = Lock()

INPUT_ROWS = 12
INPUT_DATA_COLS = 10
DEFAULT_REPAIR_OPTIONS = {
    "tem": ["", "ТО-2", "ТО-3", "ТО-4", "ТР-1", "ТР-2", "ТР-3", "СР", "КР"],
    "pe": ["", "ТО", "ТР", "СР", "КР"],
}
DEFAULT_NORMS = [
    ("max_prokat", "Прокат", "больше или равно", "6", "7"),
    ("min_greben", "Толщина гребня", "меньше или равно", "26", "25"),
    ("min_krut", "Крутизна гребня", "меньше или равно", "7", "6"),
    ("min_bandage_thickness", "Толщина бандажа", "меньше или равно", "", ""),
    ("max_diameter_diff", "Разница диаметров", "больше или равно", "", ""),
    ("prokat_6_count", "Число КП с прокатом 6 мм и более", "больше или равно", "", ""),
]


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
    if LEGACY_WEB_SECRET_FILE.exists():
        try:
            secret = LEGACY_WEB_SECRET_FILE.read_text(encoding="utf-8").strip()
            if secret:
                WEB_SECRET_FILE.write_text(secret, encoding="utf-8")
                return secret
        except Exception:
            pass
    secret = secrets.token_urlsafe(32)
    WEB_SECRET_FILE.write_text(secret, encoding="utf-8")
    return secret


WEB_SECRET = load_web_secret()
LEGACY_WEB_SECRET = ""
try:
    if LEGACY_WEB_SECRET_FILE.exists():
        LEGACY_WEB_SECRET = LEGACY_WEB_SECRET_FILE.read_text(encoding="utf-8").strip()
except Exception:
    LEGACY_WEB_SECRET = ""


def connect() -> sqlite3.Connection:
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_db() -> None:
    with DB_LOCK, connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "CREATE TABLE IF NOT EXISTS input_meta (y INT, locomotive TEXT, measurement_date TEXT, PRIMARY KEY(y, locomotive))"
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS input_data (y INT, locomotive TEXT, r INT, c INT, v TEXT, PRIMARY KEY(y, locomotive, r, c))"
        )
        cur.execute("CREATE TABLE IF NOT EXISTS inventory (y INT, ser TEXT, num TEXT, inv TEXT, PRIMARY KEY(y, ser, num))")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS kp_data (
                locomotive TEXT, r INT, c INT, v TEXT,
                PRIMARY KEY(locomotive, r, c)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS archive_data (
                y INT,
                measurement_date TEXT,
                locomotive TEXT,
                repair_type TEXT,
                r INT,
                c INT,
                v TEXT,
                PRIMARY KEY(y, measurement_date, locomotive, repair_type, r, c)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS kp_norms_data (
                metric_key TEXT PRIMARY KEY,
                label TEXT,
                condition TEXT,
                yellow_value TEXT,
                red_value TEXT
            )
            """
        )
        cur.executemany(
            "INSERT OR IGNORE INTO kp_norms_data(metric_key, label, condition, yellow_value, red_value) VALUES(?,?,?,?,?)",
            DEFAULT_NORMS,
        )
        conn.commit()


def text(value) -> str:
    return "" if value is None else str(value)


def parse_cookie_values(handler: BaseHTTPRequestHandler, name: str) -> list[str]:
    values: list[str] = []
    for part in handler.headers.get("Cookie", "").split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        if key.strip() == name:
            values.append(value.strip())
    return values


def verify_cookie(value: str) -> tuple[str, str] | None:
    for sep in (":", "|"):
        try:
            username, role, expiry_text, sig = value.rsplit(sep, 3)
            payload = f"{username}{sep}{role}{sep}{expiry_text}"
            secrets_to_try = [WEB_SECRET]
            if LEGACY_WEB_SECRET and LEGACY_WEB_SECRET not in secrets_to_try:
                secrets_to_try.append(LEGACY_WEB_SECRET)
            matched = False
            for secret in secrets_to_try:
                expected = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
                if hmac.compare_digest(expected, sig):
                    matched = True
                    break
            if not matched:
                continue
            if float(expiry_text) < dt.datetime.now().timestamp():
                return None
            if role in {"view", "edit"}:
                return username, role
        except Exception:
            continue
    return None


def current_session(handler: BaseHTTPRequestHandler) -> tuple[str, str] | None:
    for token in parse_cookie_values(handler, SESSION_COOKIE):
        session = verify_cookie(token)
        if session:
            return session
    try:
        if ACCESS_STATE_FILE.exists():
            payload = json.loads(ACCESS_STATE_FILE.read_text(encoding="utf-8"))
            role = text(payload.get("role", "")).strip()
            expiry = float(payload.get("expires_at", 0) or 0)
            if role in {"view", "edit"} and expiry >= dt.datetime.now().timestamp():
                username = text(payload.get("username", "main")).strip() or "main"
                return username, role
    except Exception:
        pass
    return None


def route_path(path: str) -> str:
    if path == APP_PREFIX:
        return "/"
    if path.startswith(APP_PREFIX + "/"):
        return path[len(APP_PREFIX) :] or "/"
    return path


def send_html(handler: BaseHTTPRequestHandler, body: str, status: int = 200) -> None:
    data = body.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def send_json(handler: BaseHTTPRequestHandler, payload, status: int = 200) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def redirect(handler: BaseHTTPRequestHandler, location: str, cookie: str | None = None) -> None:
    handler.send_response(HTTPStatus.SEE_OTHER)
    handler.send_header("Location", location)
    handler.send_header("Cache-Control", "no-store")
    if cookie:
        handler.send_header("Set-Cookie", cookie)
    handler.end_headers()


def require_auth(handler: BaseHTTPRequestHandler, need_edit: bool = False) -> tuple[str, str] | None:
    session = current_session(handler)
    if session and (not need_edit or session[1] == "edit"):
        return session
    send_json(handler, {"error": "Требуется вход с правом редактирования" if need_edit else "Требуется вход"}, HTTPStatus.UNAUTHORIZED)
    return None


def normalize_text(value: str) -> str:
    text_value = text(value).strip().lower()
    text_value = text_value.replace("ё", "е")
    return text_value


def series_for_locomotive(cur: sqlite3.Cursor, locomotive: str) -> str:
    locomotive = text(locomotive).strip()
    if not locomotive:
        return ""
    row = cur.execute(
        "SELECT ser FROM inventory WHERE TRIM(COALESCE(num, ''))=? ORDER BY y DESC, rowid DESC LIMIT 1",
        (locomotive,),
    ).fetchone()
    if row:
        return text(row["ser"]).strip()
    return ""


def locomotive_axis_count(series: str, locomotive: str) -> int:
    normalized = normalize_text(series + " " + locomotive)
    if "пэ-2м" in normalized or "пэ2м" in normalized or "пэ 2м" in normalized or "pe-2m" in normalized or "pe2m" in normalized:
        return 12
    if "тэм" in normalized or "tem" in normalized:
        return 6
    return 12


def allowed_repairs(series: str, locomotive: str) -> list[str]:
    normalized = normalize_text(series + " " + locomotive)
    if "пэ-2м" in normalized or "пэ2м" in normalized or "пэ 2м" in normalized or "pe-2m" in normalized or "pe2m" in normalized:
        return DEFAULT_REPAIR_OPTIONS["pe"]
    return DEFAULT_REPAIR_OPTIONS["tem"]


def load_locomotives(cur: sqlite3.Cursor) -> list[dict[str, str]]:
    rows = cur.execute(
        """
        SELECT y, ser, num, inv
        FROM inventory
        WHERE TRIM(COALESCE(num, '')) <> ''
        ORDER BY y DESC, rowid
        """
    ).fetchall()

    seen: set[str] = set()
    result: list[dict[str, str]] = []
    for row in rows:
        number = text(row["num"]).strip()
        if not number or number in seen:
            continue
        seen.add(number)
        series = text(row["ser"]).strip()
        inv = text(row["inv"]).strip()
        label = f"{series} {number}".strip()
        if inv:
            label = f"{label} (инв. {inv})"
        result.append({"series": series, "number": number, "label": label})
    return result


def empty_measurements() -> list[list[str]]:
    return [["" for _ in range(INPUT_DATA_COLS)] for _ in range(INPUT_ROWS)]


def row_to_index(row_value: int) -> int | None:
    idx = int(row_value) - 2
    return idx if 0 <= idx < INPUT_ROWS else None


def load_state(locomotive: str | None = None) -> dict:
    with DB_LOCK, connect() as conn:
        cur = conn.cursor()
        locomotives = load_locomotives(cur)
        if not locomotive:
            locomotive = locomotives[0]["number"] if locomotives else ""
        locomotive = text(locomotive).strip()

        series = series_for_locomotive(cur, locomotive)
        axis_count = locomotive_axis_count(series, locomotive)
        repair_options = allowed_repairs(series, locomotive)

        meta = None
        if locomotive:
            meta = cur.execute(
                "SELECT y, measurement_date FROM input_meta WHERE locomotive=? ORDER BY y DESC LIMIT 1",
                (locomotive,),
            ).fetchone()

        measurement_date = dt.date.today().isoformat()
        year = dt.date.today().year
        if meta:
            year = int(meta["y"] or year)
            measurement_date = text(meta["measurement_date"]).strip() or measurement_date
            try:
                year = int(measurement_date[:4])
            except Exception:
                pass
        elif measurement_date:
            try:
                year = int(measurement_date[:4])
            except Exception:
                year = dt.date.today().year

        rows = empty_measurements()
        if locomotive:
            db_rows = cur.execute(
                "SELECT r, c, v FROM input_data WHERE y=? AND locomotive=? ORDER BY r, c",
                (year, locomotive),
            ).fetchall()
            for row in db_rows:
                idx = row_to_index(int(row["r"]))
                col = int(row["c"]) - 2
                if idx is None or not (0 <= col < INPUT_DATA_COLS):
                    continue
                rows[idx][col] = text(row["v"])

        kp_rows = cur.execute("SELECT r, c, v FROM kp_data WHERE locomotive=? ORDER BY r, c", (locomotive,)).fetchall()
        if not kp_rows:
            kp_rows = cur.execute("SELECT r, c, v FROM kp_data WHERE locomotive='' ORDER BY r, c").fetchall()

        kp_map: dict[int, dict[int, str]] = {}
        for row in kp_rows:
            kp_map.setdefault(int(row["r"]), {})[int(row["c"])] = text(row["v"])

        norms = {
            row["metric_key"]: {
                "label": text(row["label"]),
                "condition": text(row["condition"]),
                "yellow_value": text(row["yellow_value"]),
                "red_value": text(row["red_value"]),
            }
            for row in cur.execute(
                "SELECT metric_key, label, condition, yellow_value, red_value FROM kp_norms_data ORDER BY rowid"
            ).fetchall()
        }

    return {
        "locomotive": locomotive,
        "series": series,
        "axis_count": axis_count,
        "measurement_date": measurement_date,
        "repair_type": "",
        "repair_options": repair_options,
        "locomotives": locomotives,
        "measurements": rows,
        "kp": kp_map,
        "norms": norms,
        "year": year,
    }


def save_state(payload: dict) -> dict:
    locomotive = text(payload.get("locomotive")).strip()
    measurement_date = text(payload.get("measurement_date")).strip() or dt.date.today().isoformat()
    rows = payload.get("measurements") or []

    try:
        year = int(measurement_date[:4])
    except Exception:
        year = dt.date.today().year

    with DB_LOCK, connect() as conn:
        cur = conn.cursor()
        cur.execute("BEGIN")
        cur.execute("DELETE FROM input_data WHERE y=? AND locomotive=?", (year, locomotive))
        insert_rows: list[tuple[int, str, int, int, str]] = []
        for r, row in enumerate(rows):
            row = list(row or []) + [""] * INPUT_DATA_COLS
            for c, value in enumerate(row[:INPUT_DATA_COLS]):
                value = text(value).strip()
                if value:
                    insert_rows.append((year, locomotive, r + 2, c + 2, value))
        cur.executemany("INSERT INTO input_data(y, locomotive, r, c, v) VALUES(?,?,?,?,?)", insert_rows)
        cur.execute(
            "INSERT OR REPLACE INTO input_meta(y, locomotive, measurement_date) VALUES(?,?,?)",
            (year, locomotive, measurement_date),
        )
        conn.commit()
    return load_state(locomotive)


def build_archive_rows(payload: dict) -> tuple[dict, list[tuple[int, str, str, str, int, int, str]], list[str]]:
    locomotive = text(payload.get("locomotive")).strip()
    measurement_date = text(payload.get("measurement_date")).strip() or dt.date.today().isoformat()
    repair_type = text(payload.get("repair_type")).strip()
    rows = payload.get("measurements") or []

    try:
        year = int(measurement_date[:4])
    except Exception:
        year = dt.date.today().year

    with DB_LOCK, connect() as conn:
        cur = conn.cursor()
        series = series_for_locomotive(cur, locomotive)
        series_text = normalize_text(series + " " + locomotive)
        axis_count = locomotive_axis_count(series, locomotive)
        visible_rows = 6 if axis_count == 6 else 12
        if "пэ-2м" in series_text or "пэ2м" in series_text or "пэ 2м" in series_text or "pe-2m" in series_text or "pe2m" in series_text:
            required_columns = [0, 1, 2, 3, 6, 7]
        else:
            required_columns = [0, 1, 2, 3, 4, 5, 6, 7]

        kp_rows = cur.execute("SELECT r, c, v FROM kp_data WHERE locomotive=? ORDER BY r, c", (locomotive,)).fetchall()
        if not kp_rows:
            kp_rows = cur.execute("SELECT r, c, v FROM kp_data WHERE locomotive='' ORDER BY r, c").fetchall()
        kp_map: dict[int, dict[int, str]] = {}
        for row in kp_rows:
            kp_map.setdefault(int(row["r"]), {})[int(row["c"])] = text(row["v"])

        def parse_float(v):
            try:
                return float(text(v).replace(",", "."))
            except Exception:
                return None

        missing_cells: list[str] = []
        normalized_rows: list[list[str]] = []
        for row_index in range(visible_rows):
            row = list(rows[row_index] if row_index < len(rows) else []) + [""] * INPUT_DATA_COLS
            normalized_rows.append(row[:INPUT_DATA_COLS])
            for col in required_columns:
                value = text(row[col]).strip()
                if not value:
                    axis_number = row_index + 1
                    missing_cells.append(f"ось {axis_number}, колонка {col + 1}")

        if missing_cells:
            return {"error": "missing", "measurement_date": measurement_date, "locomotive": locomotive, "repair_type": repair_type}, [], missing_cells

        if not repair_type:
            return {"error": "repair", "measurement_date": measurement_date, "locomotive": locomotive, "repair_type": repair_type}, [], []

        archive_rows: list[tuple[int, str, str, str, int, int, str]] = []
        for row_index in range(visible_rows):
            row = normalized_rows[row_index]
            table_row = row_index + 2
            section_value = "1" if axis_count == 6 else str((row_index // 4) + 1)
            kp_row = kp_map.get(row_index, {})

            left_band = parse_float(row[6])
            right_band = parse_float(row[7])
            left_kp = parse_float(kp_row.get(2, ""))
            right_kp = parse_float(kp_row.get(3, ""))
            left_diam = "" if left_kp is None or left_band is None else str(int(round(left_kp + left_band * 2)))
            right_diam = "" if right_kp is None or right_band is None else str(int(round(right_kp + right_band * 2)))

            values = {
                0: section_value,
                1: str(row_index + 1),
                2: row[0],
                3: row[1],
                4: row[2],
                5: row[3],
                6: row[4],
                7: row[5],
                8: row[6],
                9: row[7],
                10: left_diam,
                11: right_diam,
            }
            for col, value in values.items():
                value = text(value).strip()
                if value:
                    archive_rows.append((year, measurement_date, locomotive, repair_type, table_row, col, value))

        return {
            "year": year,
            "measurement_date": measurement_date,
            "locomotive": locomotive,
            "repair_type": repair_type,
            "axis_count": axis_count,
        }, archive_rows, []


def save_archive(payload: dict) -> dict:
    meta, archive_rows, missing_cells = build_archive_rows(payload)
    if meta.get("error") == "missing":
        return {"error": "Не все обязательные ячейки заполнены.", "missing_cells": missing_cells}, 400
    if meta.get("error") == "repair":
        return {"error": "Выберите вид ремонта."}, 400

    year = int(meta["year"])
    measurement_date = meta["measurement_date"]
    locomotive = meta["locomotive"]
    repair_type = meta["repair_type"]
    overwrite = bool(payload.get("overwrite"))

    with DB_LOCK, connect() as conn:
        cur = conn.cursor()
        existing = cur.execute(
            "SELECT COUNT(*) FROM archive_data WHERE y=? AND measurement_date=? AND locomotive=? AND repair_type=?",
            (year, measurement_date, locomotive, repair_type),
        ).fetchone()[0]
        if existing and not overwrite:
            return {
                "error": "duplicate",
                "message": "Запись с таким локомотивом, датой и видом ремонта уже есть в архиве.",
            }, 409

        cur.execute("BEGIN")
        cur.execute(
            "DELETE FROM archive_data WHERE y=? AND measurement_date=? AND locomotive=? AND repair_type=?",
            (year, measurement_date, locomotive, repair_type),
        )
        cur.executemany(
            "INSERT INTO archive_data (y, measurement_date, locomotive, repair_type, r, c, v) VALUES (?, ?, ?, ?, ?, ?, ?)",
            archive_rows,
        )
        cur.execute("DELETE FROM input_data WHERE y=? AND locomotive=?", (year, locomotive))
        cur.execute(
            "INSERT OR REPLACE INTO input_meta(y, locomotive, measurement_date) VALUES(?,?,?)",
            (year, locomotive, measurement_date),
        )
        conn.commit()

    return load_state(locomotive)


def load_archive_rows(locomotive: str = "", search_text: str = "", sort_desc: bool = True) -> list[dict]:
    locomotive = text(locomotive).strip()
    search_text = text(search_text).strip().lower()
    with DB_LOCK, connect() as conn:
        cur = conn.cursor()
        order_direction = "DESC" if sort_desc else "ASC"
        params: list[str] = []
        query = """
            SELECT y, measurement_date, locomotive, repair_type, r, c, v
            FROM archive_data
        """
        where: list[str] = []
        if locomotive and locomotive != "Все локомотивы":
            where.append("locomotive = ?")
            params.append(locomotive)
        if where:
            query += " WHERE " + " AND ".join(where)
        query += f" ORDER BY y {order_direction}, measurement_date {order_direction}, locomotive ASC, repair_type ASC, r ASC, c ASC"
        rows = cur.execute(query, params).fetchall()

        grouped: dict[tuple[int, str, str, str, int], list[str]] = {}
        for row in rows:
            r = int(row["r"])
            if r < 2:
                continue
            key = (
                int(row["y"] or 0),
                text(row["measurement_date"]).strip(),
                text(row["locomotive"]).strip(),
                text(row["repair_type"]).strip(),
                r,
            )
            grouped.setdefault(key, [""] * 12)
            c = int(row["c"])
            if 0 <= c < 12:
                grouped[key][c] = text(row["v"])

        def to_float(v):
            try:
                return float(text(v).replace(",", "."))
            except Exception:
                return None

        def fmt_num(v):
            if v is None:
                return ""
            try:
                value = float(v)
            except Exception:
                return text(v).strip()
            if value.is_integer():
                return str(int(value))
            return str(value).rstrip("0").rstrip(".").replace(".", ",")

        stats_by_section: dict[tuple[int, str, str, str, str], dict[str, str]] = {}
        for (year, measurement_date, loco, repair_type, row_index), values in grouped.items():
            section_value = values[0] or "1"
            key = (year, measurement_date, loco, repair_type, section_value)
            stats = stats_by_section.setdefault(
                key,
                {
                    "max_prokat": "",
                    "min_greben": "",
                    "min_krut": "",
                    "min_bandage_thickness": "",
                    "max_diameter_diff": "",
                    "prokat_6_count": "0",
                    "bandage_limit_count": "0",
                },
            )
            prokat_pair = [v for v in [to_float(values[2]), to_float(values[3])] if v is not None]
            greben_pair = [v for v in [to_float(values[4]), to_float(values[5])] if v is not None]
            krut_pair = [v for v in [to_float(values[6]), to_float(values[7])] if v is not None]
            bandage_pair = [v for v in [to_float(values[8]), to_float(values[9])] if v is not None]
            diameter_pair = [v for v in [to_float(values[10]), to_float(values[11])] if v is not None]

            if prokat_pair:
                current = to_float(stats["max_prokat"])
                stats["max_prokat"] = fmt_num(max(prokat_pair)) if current is None else fmt_num(max([current, *prokat_pair]))
                if max(prokat_pair) >= 6:
                    stats["prokat_6_count"] = fmt_num((to_float(stats["prokat_6_count"]) or 0) + 1)
            if greben_pair:
                current = to_float(stats["min_greben"])
                stats["min_greben"] = fmt_num(min(greben_pair)) if current is None else fmt_num(min([current, *greben_pair]))
            if krut_pair:
                current = to_float(stats["min_krut"])
                stats["min_krut"] = fmt_num(min(krut_pair)) if current is None else fmt_num(min([current, *krut_pair]))
            if bandage_pair:
                current = to_float(stats["min_bandage_thickness"])
                stats["min_bandage_thickness"] = fmt_num(min(bandage_pair)) if current is None else fmt_num(min([current, *bandage_pair]))
            if len(diameter_pair) >= 2:
                diff = max(diameter_pair) - min(diameter_pair)
                current = to_float(stats["max_diameter_diff"])
                stats["max_diameter_diff"] = fmt_num(diff) if current is None else fmt_num(max([current, diff]))
            if bandage_pair:
                check_text = normalize_text(loco)
                is_limit = False
                if any(x in check_text for x in ["пэ-2м", "пэ2м", "пэ 2м", "pe-2m", "pe2m"]):
                    is_limit = any(v < 51 for v in bandage_pair)
                elif "тэм" in check_text or "tem" in check_text:
                    is_limit = any(v < 41 for v in bandage_pair)
                if is_limit:
                    stats["bandage_limit_count"] = fmt_num((to_float(stats["bandage_limit_count"]) or 0) + 1)

        def sort_key(item):
            (year, measurement_date, loco, repair_type, row_index), _ = item
            try:
                year_key = int(year)
            except Exception:
                year_key = 0
            try:
                date_key = int((measurement_date or "").replace("-", ""))
            except Exception:
                date_key = 0
            if sort_desc:
                return (-year_key, -date_key, loco, repair_type, row_index)
            return (year_key, date_key, loco, repair_type, row_index)

        archive_rows: list[dict] = []
        for (year, measurement_date, loco, repair_type, row_index), values in sorted(grouped.items(), key=sort_key):
            if search_text:
                probe = " ".join(
                    [
                        text(year),
                        measurement_date,
                        loco,
                        repair_type,
                        *[text(v) for v in values],
                    ]
                ).lower()
                if search_text not in probe:
                    continue

            formatted_date = measurement_date
            if measurement_date and len(measurement_date) >= 10:
                parts = measurement_date.split("-")
                if len(parts) == 3:
                    formatted_date = f"{parts[2]}.{parts[1]}.{parts[0][-2:]}"

            date_and_repair = f"{loco}\n{formatted_date}"
            if repair_type:
                date_and_repair += f"\n{repair_type}"

            section_value = values[0] or "1"
            stats = stats_by_section.get((year, measurement_date, loco, repair_type, section_value), {})
            row_values = [
                date_and_repair,
                section_value,
                stats.get("max_prokat", ""),
                stats.get("min_greben", ""),
                stats.get("min_krut", ""),
                stats.get("min_bandage_thickness", ""),
                stats.get("max_diameter_diff", ""),
                stats.get("bandage_limit_count", "0"),
                stats.get("prokat_6_count", "0"),
                values[1],
                values[2],
                values[3],
                values[4],
                values[5],
                values[6],
                values[7],
                values[8],
                values[9],
                values[10],
                values[11],
            ]
            archive_rows.append({
                "values": row_values,
                "year": year,
                "measurement_date": measurement_date,
                "locomotive": loco,
                "repair_type": repair_type,
                "section": section_value,
                "stats": stats,
            })

        return archive_rows


HTML = """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Замер КП</title>
  <style>
    :root { --line:#d8e0ea; --text:#102033; --muted:#66758a; --blue:#276ef1; --bg:#f5f7fb; --ok:#eef7f0; --warn:#fff8d5; --bad:#ffe5e5; }
    * { box-sizing:border-box; }
    body { margin:0; font-family:Segoe UI,Arial,sans-serif; background:var(--bg); color:var(--text); }
    .wrap { max-width: 1540px; margin:0 auto; padding:16px; }
    .top { display:flex; justify-content:space-between; gap:12px; align-items:flex-start; background:#fff; border:1px solid var(--line); border-radius:16px; padding:14px 16px; }
    h1 { margin:0; font-size:24px; }
    .muted { color:var(--muted); font-size:13px; }
    .actions, .filters { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
    button, a, input, select { border:1px solid var(--line); border-radius:8px; padding:9px 11px; background:#fff; color:var(--text); font:inherit; text-decoration:none; }
    button { cursor:pointer; font-weight:700; }
    .primary { background:var(--blue); border-color:var(--blue); color:#fff; }
    .meta { display:none; }
    .badge { display:inline-flex; align-items:center; gap:6px; padding:8px 10px; background:#fff; border:1px solid var(--line); border-radius:8px; font-size:13px; }
    .badge strong { font-weight:700; }
    #saveBtn { margin-left:auto; }
    .tabs { display:flex; gap:8px; margin-top:12px; }
    .tab { background:#fff; border:1px solid var(--line); border-bottom-color:#c9d4e3; padding:10px 14px; border-radius:10px 10px 0 0; font-weight:700; cursor:pointer; }
    .tab.active { background:#eef3f8; border-bottom-color:#eef3f8; }
    .panel { display:none; background:#fff; border:1px solid var(--line); border-top:none; border-radius:0 16px 16px 16px; padding:12px; }
    .panel.active { display:block; }
    .archive-controls { display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin-bottom:12px; }
    .archive-controls label { display:flex; align-items:center; gap:8px; }
    .archive-controls input { width:240px; }
    .table-shell { background:#fff; border:1px solid var(--line); border-radius:16px; padding:12px; overflow:auto; display:flex; justify-content:center; margin-top:16px; }
    .archive-table-shell { margin-top:0; padding-top:10px; }
    table { border-collapse:collapse; width:max-content; table-layout:fixed; }
    th, td { border:1px solid var(--line); padding:0; text-align:center; height:34px; }
    thead th { background:#eef3f8; font-weight:700; font-size:14px; line-height:1.1; }
    th.small { font-size:14px; line-height:1.1; }
    th.measure-head, td.measure-cell { width:60px; }
    th.section-col, td.section-col { width:80px; }
    th.number-col, td.number-col { width:80px; }
    td.fixed { background:#f7fafc; font-weight:600; }
    td.measure-cell input { width:100%; height:34px; border:0; text-align:center; background:transparent; padding:2px 3px; font-size:12px; }
    td.measure-cell.selected { box-shadow: inset 0 0 0 2px #2f6fed; }
    td input { width:100%; height:34px; border:0; text-align:center; background:transparent; padding:5px 7px; }
    td input.left { text-align:left; }
    td.warn { background:var(--warn); }
    td.bad { background:var(--bad); }
    .archive-table th, .archive-table td { font-size:12px; }
    .archive-table td { white-space:pre-line; }
    .archive-table td.raw { width:60px; }
    .archive-table td.summary { width:110px; }
    .archive-table td.first-col { width:220px; }
    .status { min-height:20px; margin-top:10px; font-size:13px; color:var(--muted); }
    @media (max-width: 900px) {
      .top { display:block; }
      .actions, .filters { margin-top:10px; }
      table { min-width: 980px; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="top">
      <div>
        <h1>Замер КП</h1>
        <div class="muted">Версия {{APP_VERSION}}</div>
      </div>
      <div class="actions">
        <a href="/">На главную</a>
        <button id="cancelBtn" title="Отмена" aria-label="Отмена" onclick="cancelChanges()">↺</button>
        <button id="restoreBtn" title="Вернуть" aria-label="Вернуть" onclick="restoreChanges()">↻</button>
      </div>
    </div>

    <div class="tabs" role="tablist" aria-label="Разделы">
      <button id="tabInput" class="tab active" type="button" onclick="switchTab('input')">Ввод замера</button>
      <button id="tabArchive" class="tab" type="button" onclick="switchTab('archive')">Архив замеров</button>
    </div>

    <div id="panelInput" class="panel active">
      <div class="filters" style="margin-top:0;">
        <label>Локомотив
          <select id="locomotive" style="width:220px"></select>
        </label>
        <label>Дата замера
          <input id="measurementDate" type="date" style="width:150px">
        </label>
        <label>Вид ремонта
          <select id="repairType" style="width:150px"></select>
        </label>
      <button id="saveBtn" class="primary" onclick="saveToArchive()">Сохранить в архив</button>
      </div>

      <div class="table-shell">
        <table id="inputTable" aria-label="Ввод замера КП">
          <colgroup>
            <col style="width:80px">
            <col style="width:80px">
            <col style="width:60px"><col style="width:60px">
            <col style="width:60px"><col style="width:60px">
            <col style="width:60px"><col style="width:60px">
            <col style="width:60px"><col style="width:60px">
            <col style="width:60px"><col style="width:60px">
          </colgroup>
          <thead>
            <tr>
              <th class="small section-col" rowspan="2">Секция<br>(вагон)</th>
              <th class="small number-col" rowspan="2">Номер<br>КП</th>
              <th class="measure-head" colspan="2">Прокат</th>
              <th class="measure-head" colspan="2">Толщина гребня</th>
              <th class="measure-head" colspan="2">Параметр крутизны гребня</th>
              <th class="measure-head" colspan="2">Толщина бандажа</th>
              <th class="measure-head" colspan="2">Диаметр бандажа</th>
            </tr>
            <tr>
              <th class="small measure-head">лев</th>
              <th class="small measure-head">прав</th>
              <th class="small measure-head">лев</th>
              <th class="small measure-head">прав</th>
              <th class="small measure-head">лев</th>
              <th class="small measure-head">прав</th>
              <th class="small measure-head">лев</th>
              <th class="small measure-head">прав</th>
              <th class="small measure-head">лев</th>
              <th class="small measure-head">прав</th>
            </tr>
          </thead>
          <tbody id="inputBody"></tbody>
        </table>
      </div>

      <div id="status" class="status"></div>
    </div>

    <div id="panelArchive" class="panel">
      <div class="archive-controls">
        <label>Локомотив
          <select id="archiveLocomotive" style="width:220px"></select>
        </label>
        <label>Поиск
          <input id="archiveSearch" type="text" placeholder="Дата, локомотив, вид ремонта" />
        </label>
        <button id="archiveSortBtn" type="button" onclick="toggleArchiveSort()">⬇ НОВЫЕ → СТАРЫЕ</button>
      </div>

      <div class="table-shell archive-table-shell">
        <table id="archiveTable" class="archive-table" aria-label="Архив замеров">
          <colgroup>
            <col style="width:220px">
            <col style="width:80px">
            <col style="width:110px">
            <col style="width:110px">
            <col style="width:110px">
            <col style="width:110px">
            <col style="width:110px">
            <col style="width:90px">
            <col style="width:90px">
            <col style="width:80px">
            <col style="width:60px"><col style="width:60px">
            <col style="width:60px"><col style="width:60px">
            <col style="width:60px"><col style="width:60px">
            <col style="width:60px"><col style="width:60px">
            <col style="width:60px"><col style="width:60px">
          </colgroup>
          <thead>
            <tr>
              <th>Локомотив<br>Дата<br>Вид ремонта</th>
              <th>Секция</th>
              <th>Прокат,<br>макс</th>
              <th>Гребень,<br>мин</th>
              <th>Крутизна,<br>мин</th>
              <th>Бандаж,<br>мин</th>
              <th>Диаметр,<br>разница</th>
              <th>КП с<br>бандажом</th>
              <th>КП с<br>прокатом 6+</th>
              <th>Номер<br>КП</th>
              <th>Прокат<br>лев</th><th>Прокат<br>прав</th>
              <th>Гребень<br>лев</th><th>Гребень<br>прав</th>
              <th>Крутизна<br>лев</th><th>Крутизна<br>прав</th>
              <th>Бандаж<br>лев</th><th>Бандаж<br>прав</th>
              <th>Диаметр<br>лев</th><th>Диаметр<br>прав</th>
            </tr>
          </thead>
          <tbody id="archiveBody"></tbody>
        </table>
      </div>
      <div id="archiveStatus" class="status"></div>
    </div>
  </div>

<script>
const API = '{{APP_PREFIX}}';
const CAN_EDIT = {{CAN_EDIT}};
let state = null;
let dirty = false;
let currentRepairType = '';
let savedState = null;
let canceledState = null;
let savedRepairType = '';
let canceledRepairType = '';
let archiveRows = [];
let archiveSortDesc = true;
let selectionAnchor = null;
let selectionFocus = null;
let clipboardCache = '';

function esc(value){
  return String(value ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
}
function n(value){
  const x = parseFloat(String(value ?? '').replace(',', '.'));
  return Number.isFinite(x) ? x : null;
}
function clampCell(row, col){
  return {
    row: Math.max(0, row),
    col: Math.max(0, Math.min(9, col)),
  };
}
function getVisibleAxisCount(){
  return getAxisCount(getCurrentLoco());
}
function isCellInBounds(row, col){
  return row >= 0 && col >= 0 && col < 10 && row < getVisibleAxisCount();
}
function clearSelection(){
  selectionAnchor = null;
  selectionFocus = null;
  document.querySelectorAll('#inputBody td.measure-cell.selected').forEach(td => td.classList.remove('selected'));
}
function selectionRect(){
  if (!selectionAnchor || !selectionFocus) return null;
  const top = Math.min(selectionAnchor.row, selectionFocus.row);
  const bottom = Math.max(selectionAnchor.row, selectionFocus.row);
  const left = Math.min(selectionAnchor.col, selectionFocus.col);
  const right = Math.max(selectionAnchor.col, selectionFocus.col);
  return { top, bottom, left, right };
}
function renderSelectionHighlight(){
  document.querySelectorAll('#inputBody td.measure-cell.selected').forEach(td => td.classList.remove('selected'));
  const rect = selectionRect();
  if (!rect) return;
  for (let r = rect.top; r <= rect.bottom; r += 1) {
    for (let c = rect.left; c <= rect.right; c += 1) {
      const td = document.querySelector(`#inputBody tr[data-row="${r}"] td.measure-cell[data-col="${c}"]`);
      if (td) td.classList.add('selected');
    }
  }
}
function selectCell(row, col, extend = false){
  const cell = clampCell(row, col);
  if (!extend || !selectionAnchor) {
    selectionAnchor = cell;
  }
  selectionFocus = cell;
  renderSelectionHighlight();
}
function focusCell(row, col, extend = false){
  const cell = clampCell(row, col);
  if (!isCellInBounds(cell.row, cell.col)) return;
  selectCell(cell.row, cell.col, extend);
  const target = document.querySelector(`input[data-row="${cell.row}"][data-col="${cell.col}"]`);
  if (target) target.focus();
}
function cellValue(row, col){
  return state?.measurements?.[row]?.[col] ?? '';
}
function setCellValue(row, col, value){
  if (!state?.measurements?.[row]) return;
  state.measurements[row][col] = value;
  const input = document.querySelector(`input[data-row="${row}"][data-col="${col}"]`);
  if (input && input.value !== value) input.value = value;
}
function readClipboardText(){
  if (navigator.clipboard?.readText) {
    return navigator.clipboard.readText().catch(() => clipboardCache || '');
  }
  return Promise.resolve(clipboardCache || '');
}
function writeClipboardText(text){
  clipboardCache = String(text ?? '');
  if (navigator.clipboard?.writeText) {
    return navigator.clipboard.writeText(clipboardCache).catch(() => undefined);
  }
  const ta = document.createElement('textarea');
  ta.value = clipboardCache;
  ta.style.position = 'fixed';
  ta.style.left = '-9999px';
  document.body.appendChild(ta);
  ta.select();
  try {
    document.execCommand('copy');
  } finally {
    ta.remove();
  }
  return Promise.resolve();
}
async function copySelectionToClipboard(){
  const rect = selectionRect();
  const start = rect ? { row: rect.top, col: rect.left } : (selectionFocus || selectionAnchor);
  if (!start || !isCellInBounds(start.row, start.col)) return;
  const end = rect ? { row: rect.bottom, col: rect.right } : start;
  const lines = [];
  for (let r = start.row; r <= end.row; r += 1) {
    const rowValues = [];
    for (let c = start.col; c <= end.col; c += 1) {
      rowValues.push(cellValue(r, c));
    }
    lines.push(rowValues.join('\\t'));
  }
  await writeClipboardText(lines.join('\\n'));
  setStatus('Скопировано');
}
function applyPastedBlock(text, startRow, startCol){
  if (!CAN_EDIT || !state) return;
  const rows = String(text ?? '').replace(/\\r/g, '').split('\\n');
  if (rows.length && rows[rows.length - 1] === '') rows.pop();
  if (!rows.length) return;
  let touched = false;
  const axisCount = getVisibleAxisCount();
  for (let i = 0; i < rows.length; i += 1) {
    const cells = rows[i].split('\\t');
    for (let j = 0; j < cells.length; j += 1) {
      const tr = startRow + i;
      const tc = startCol + j;
      if (tr >= axisCount || tc >= 10) continue;
      const value = cells[j].trim();
      setCellValue(tr, tc, value);
      touched = true;
    }
  }
  if (!touched) return;
  setDirty(true);
  for (let r = startRow; r < Math.min(axisCount, startRow + rows.length); r += 1) {
    refreshRowClasses(r);
  }
  recalcDiameters();
}
async function pasteClipboardIntoSelection(row, col){
  const text = await readClipboardText();
  if (!text) return;
  const rect = selectionRect();
  const start = rect ? { row: rect.top, col: rect.left } : clampCell(row, col);
  applyPastedBlock(text, start.row, start.col);
  focusCell(start.row, start.col);
  setStatus('Вставлено');
}
function clearSelectedCells(){
  if (!CAN_EDIT || !state) return;
  const rect = selectionRect();
  const start = rect ? { row: rect.top, col: rect.left } : (selectionFocus || selectionAnchor);
  if (!start || !isCellInBounds(start.row, start.col)) return;
  const end = rect ? { row: rect.bottom, col: rect.right } : start;
  const axisCount = getVisibleAxisCount();
  let touched = false;
  for (let r = start.row; r <= end.row; r += 1) {
    if (r >= axisCount) continue;
    for (let c = start.col; c <= end.col; c += 1) {
      if (c >= 10) continue;
      setCellValue(r, c, '');
      touched = true;
      refreshRowClasses(r);
    }
  }
  if (!touched) return;
  setDirty(true);
  recalcDiameters();
  setStatus('Очищено');
}
function setStatus(text){
  document.getElementById('status').textContent = text || '';
}
function setDirty(flag){
  dirty = !!flag;
  updateHistoryButtons();
}
function cloneState(value){
  return value ? JSON.parse(JSON.stringify(value)) : null;
}
function updateHistoryButtons(){
  const cancelBtn = document.getElementById('cancelBtn');
  const restoreBtn = document.getElementById('restoreBtn');
  if (cancelBtn) cancelBtn.style.display = '';
  if (restoreBtn) restoreBtn.style.display = '';
  if (cancelBtn) cancelBtn.disabled = !CAN_EDIT || !savedState;
  if (restoreBtn) restoreBtn.disabled = !CAN_EDIT || !canceledState;
}
function setActiveTab(tab){
  const inputTab = document.getElementById('tabInput');
  const archiveTab = document.getElementById('tabArchive');
  const panelInput = document.getElementById('panelInput');
  const panelArchive = document.getElementById('panelArchive');
  if (inputTab) inputTab.classList.toggle('active', tab === 'input');
  if (archiveTab) archiveTab.classList.toggle('active', tab === 'archive');
  if (panelInput) panelInput.classList.toggle('active', tab === 'input');
  if (panelArchive) panelArchive.classList.toggle('active', tab === 'archive');
}
async function switchTab(tab){
  setActiveTab(tab);
  if (tab === 'archive') {
    await loadArchive();
  }
}
function getCurrentLoco(){
  return document.getElementById('locomotive').value.trim();
}
function getSeries(number){
  const item = (state?.locomotives || []).find(x => x.number === number);
  return item ? (item.series || '') : '';
}
function getAxisCount(number){
  const series = getSeries(number);
  const text = (series + ' ' + number).toLowerCase().replaceAll('ё','е');
  if (text.includes('пэ-2м') || text.includes('пэ2м') || text.includes('пэ 2м') || text.includes('pe-2m') || text.includes('pe2m')) return 12;
  if (text.includes('тэм') || text.includes('tem')) return 6;
  return 12;
}
function allowedRepairs(number){
  const series = getSeries(number);
  const text = (series + ' ' + number).toLowerCase().replaceAll('ё','е');
  if (text.includes('пэ-2м') || text.includes('пэ2м') || text.includes('пэ 2м') || text.includes('pe-2m') || text.includes('pe2m')) {
    return ['', 'ТО', 'ТР', 'СР', 'КР'];
  }
  return ['', 'ТО-2', 'ТО-3', 'ТО-4', 'ТР-1', 'ТР-2', 'ТР-3', 'СР', 'КР'];
}
function sectionSpec(axisCount){
  return axisCount === 6
    ? [{ start: 0, span: 6, value: '1' }]
    : [{ start: 0, span: 4, value: '1' }, { start: 4, span: 4, value: '2' }, { start: 8, span: 4, value: '3' }];
}
function measurementClass(col, value){
  const val = n(value);
  if (val === null) return '';
  const norm = state?.norms || {};
  const pair = (left, right) => col === left || col === right;
  let item = null;
  if (pair(0,1)) item = norm.max_prokat;
  if (pair(2,3)) item = norm.min_greben;
  if (pair(4,5)) item = norm.min_krut;
  if (pair(6,7)) item = norm.min_bandage_thickness;
  if (!item) return '';
  const yellow = n(item.yellow_value), red = n(item.red_value);
  const less = String(item.condition || '').toLowerCase().includes('меньше');
  if (red !== null && (less ? val <= red : val >= red)) return 'bad';
  if (yellow !== null && (less ? val <= yellow : val >= yellow)) return 'warn';
  return '';
}
function renderLocoOptions(){
  const select = document.getElementById('locomotive');
  const items = state?.locomotives || [];
  select.innerHTML = items.length
    ? ['<option value="">Выберите локомотив</option>']
        .concat(items.map(x => `<option value="${esc(x.number)}">${esc(x.number)}</option>`))
        .join('')
    : '<option value="">Нет локомотивов в справочнике</option>';
  select.disabled = !items.length;
  if (state?.locomotive && items.some(x => x.number === state.locomotive)) {
    select.value = state.locomotive;
  } else if (items.length && !select.value) {
    select.value = items[0].number;
  }
}
function renderArchiveLocomotives(){
  const select = document.getElementById('archiveLocomotive');
  const items = state?.locomotives || [];
  const current = select?.value || '';
  if (!select) return;
  select.innerHTML = items.length
    ? ['<option value="">Все локомотивы</option>']
        .concat(items.map(x => `<option value="${esc(x.number)}">${esc(x.number)}</option>`))
        .join('')
    : '<option value="">Нет локомотивов в справочнике</option>';
  if (current && items.some(x => x.number === current)) {
    select.value = current;
  } else if (state?.locomotive && items.some(x => x.number === state.locomotive)) {
    select.value = state.locomotive;
  }
}
function renderRepairOptions(){
  const select = document.getElementById('repairType');
  const current = currentRepairType || '';
  const options = allowedRepairs(getCurrentLoco());
  select.innerHTML = options.map(value => `<option value="${esc(value)}">${esc(value)}</option>`).join('');
  select.value = options.includes(current) ? current : '';
  currentRepairType = select.value || '';
}
function updateArchiveSortButton(){
  const btn = document.getElementById('archiveSortBtn');
  if (!btn) return;
  if (archiveSortDesc) {
    btn.textContent = '⬇ НОВЫЕ → СТАРЫЕ';
    btn.title = 'Показать замеры от новых к старым';
  } else {
    btn.textContent = '⬆ СТАРЫЕ → НОВЫЕ';
    btn.title = 'Показать замеры от старых к новым';
  }
}
function renderMeta(){
  return;
}
function renderArchiveTable(){
  const tbody = document.getElementById('archiveBody');
  if (!tbody) return;
  if (!archiveRows.length) {
    tbody.innerHTML = '<tr><td colspan="20" style="padding:14px;color:var(--muted);">Архив пуст</td></tr>';
    return;
  }
  tbody.innerHTML = archiveRows.map(row => {
    const values = row.values || [];
    const cells = values.map((value, index) => {
      const cls = index === 0 ? 'first-col' : (index >= 2 && index <= 8 ? 'summary' : (index >= 10 ? 'raw' : ''));
      return `<td class="${cls}">${esc(value)}</td>`;
    }).join('');
    return `<tr>${cells}</tr>`;
  }).join('');
}
function renderTable(){
  const tbody = document.getElementById('inputBody');
  const loco = getCurrentLoco();
  const axisCount = getAxisCount(loco);
  const visibleRows = axisCount === 6 ? 6 : 12;
  const sections = sectionSpec(axisCount);
  const sectionMap = new Map(sections.map(item => [item.start, item]));
  const rows = state?.measurements || [];
  let html = '';
  for (let r = 0; r < visibleRows; r += 1) {
    const section = sectionMap.get(r);
    html += `<tr data-row="${r}">`;
    if (section) {
      html += `<td class="fixed section-col" rowspan="${section.span}">${esc(section.value)}</td>`;
    }
    html += `<td class="fixed number-col">${r + 1}</td>`;
    for (let c = 0; c < 10; c += 1) {
      const value = rows[r]?.[c] ?? '';
      const cls = measurementClass(c, value);
      html += `
        <td class="measure-cell ${cls}" data-col="${c}">
          <input
            value="${esc(value)}"
            ${CAN_EDIT ? '' : 'readonly'}
            data-row="${r}"
            data-col="${c}"
            onmousedown="return handleCellMouseDown(event, ${r}, ${c})"
            onfocus="handleCellFocus(${r}, ${c})"
            oninput="handleCellInput(${r}, ${c}, this.value)"
            onkeydown="handleKeydown(event, ${r}, ${c})"
          >
        </td>`;
    }
    html += '</tr>';
  }
  tbody.innerHTML = html;
  recalcDiameters();
  renderSelectionHighlight();
}
async function loadArchive(){
  const status = document.getElementById('archiveStatus');
  const loco = document.getElementById('archiveLocomotive')?.value || '';
  const search = document.getElementById('archiveSearch')?.value || '';
  if (status) status.textContent = 'Загрузка архива...';
  updateArchiveSortButton();
  const res = await fetch(`${API}/api/archive?locomotive=${encodeURIComponent(loco)}&search=${encodeURIComponent(search)}&sort=${archiveSortDesc ? 'desc' : 'asc'}`, { cache: 'no-store' });
  if (!res.ok) {
    archiveRows = [];
    renderArchiveTable();
    if (status) status.textContent = 'Не удалось загрузить архив';
    return;
  }
  const payload = await res.json();
  archiveRows = payload.rows || [];
  renderArchiveTable();
  if (status) status.textContent = archiveRows.length ? `Записей: ${archiveRows.length}` : 'Архив пуст';
}
function toggleArchiveSort(){
  archiveSortDesc = !archiveSortDesc;
  loadArchive();
}
function refreshRowClasses(rowIndex){
  const row = document.querySelector(`tr[data-row="${rowIndex}"]`);
  if (!row) return;
  for (let c = 0; c < 10; c += 1) {
    const td = row.querySelector(`td[data-col="${c}"]`);
    const input = td ? td.querySelector('input') : null;
    if (!td || !input) continue;
    td.className = measurementClass(c, input.value);
  }
}
function recalcDiameters(){
  const loco = getCurrentLoco();
  const axisCount = getAxisCount(loco);
  const kpMap = state?.kp || {};
  const rows = state?.measurements || [];
  for (let r = 0; r < axisCount; r += 1) {
    const kpRow = r;
    const leftKp = n(kpMap[kpRow]?.[2]);
    const rightKp = n(kpMap[kpRow]?.[3]);
    const leftBand = n(rows[r]?.[6]);
    const rightBand = n(rows[r]?.[7]);
    const leftValue = (leftKp !== null && leftBand !== null) ? String(Math.round(leftKp + leftBand * 2)) : '';
    const rightValue = (rightKp !== null && rightBand !== null) ? String(Math.round(rightKp + rightBand * 2)) : '';
    rows[r][8] = leftValue;
    rows[r][9] = rightValue;
    const leftInput = document.querySelector(`input[data-row="${r}"][data-col="8"]`);
    const rightInput = document.querySelector(`input[data-row="${r}"][data-col="9"]`);
    if (leftInput) leftInput.value = leftValue;
    if (rightInput) rightInput.value = rightValue;
    refreshRowClasses(r);
  }
}
function handleCellInput(row, col, value){
  if (!CAN_EDIT) return;
  state.measurements[row][col] = value;
  setDirty(true);
  refreshRowClasses(row);
  if (col === 6 || col === 7) {
    recalcDiameters();
  }
}
function handleCellMouseDown(event, row, col){
  if (!CAN_EDIT) return true;
  if (event.button !== 0) return true;
  if (event.shiftKey && selectionAnchor) {
    selectCell(selectionAnchor.row, selectionAnchor.col, true);
    selectCell(row, col, true);
  } else {
    selectCell(row, col, false);
  }
  const target = event.currentTarget;
  if (target) target.focus();
  event.preventDefault();
  return false;
}
function handleCellFocus(row, col){
  if (!selectionAnchor || !selectionFocus || selectionAnchor.row !== row || selectionAnchor.col !== col || selectionFocus.row !== row || selectionFocus.col !== col) {
    selectCell(row, col, false);
  }
}
function moveFocus(row, col){
  focusCell(row, col, false);
}
function handleKeydown(event, row, col){
  const key = event.key;
  const ctrlOrMeta = event.ctrlKey || event.metaKey;
  if (ctrlOrMeta && key.toLowerCase() === 'c') {
    event.preventDefault();
    copySelectionToClipboard();
    return;
  }
  if (ctrlOrMeta && key.toLowerCase() === 'v') {
    event.preventDefault();
    pasteClipboardIntoSelection(row, col);
    return;
  }
  if (key === 'Delete' || key === 'Backspace') {
    event.preventDefault();
    clearSelectedCells();
    return;
  }
  if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(key)) return;
  event.preventDefault();
  if (event.shiftKey) {
    if (!selectionAnchor) selectionAnchor = { row, col };
    let nextRow = row;
    let nextCol = col;
    if (key === 'ArrowLeft' && col > 0) nextCol = col - 1;
    if (key === 'ArrowRight' && col < 9) nextCol = col + 1;
    if (key === 'ArrowUp' && row > 0) nextRow = row - 1;
    if (key === 'ArrowDown' && row < (getVisibleAxisCount() - 1)) nextRow = row + 1;
    focusCell(nextRow, nextCol, true);
    return;
  }
  if (key === 'ArrowLeft' && col > 0) moveFocus(row, col - 1);
  if (key === 'ArrowRight' && col < 9) moveFocus(row, col + 1);
  if (key === 'ArrowUp' && row > 0) moveFocus(row - 1, col);
  if (key === 'ArrowDown' && row < (getVisibleAxisCount() - 1)) moveFocus(row + 1, col);
}
async function loadState(nextLocomotive){
  const loco = (nextLocomotive ?? getCurrentLoco()).trim();
  setStatus('Загрузка...');
  const res = await fetch(`${API}/api/state?locomotive=${encodeURIComponent(loco)}`, { cache: 'no-store' });
  if (!res.ok) {
    setStatus('Не удалось загрузить данные');
    return;
  }
  state = await res.json();
  savedState = cloneState(state);
  canceledState = null;
  currentRepairType = state.repair_type || currentRepairType || '';
  savedRepairType = currentRepairType;
  canceledRepairType = '';
  document.getElementById('locomotive').value = state.locomotive || '';
  document.getElementById('measurementDate').value = state.measurement_date || '';
  renderLocoOptions();
  renderArchiveLocomotives();
  renderRepairOptions();
  renderMeta();
  renderTable();
  updateArchiveSortButton();
  await loadArchive();
  setDirty(false);
  setStatus('Готово');
}
async function maybeSwitchLocomotive(nextValue){
  const next = nextValue.trim();
  const current = state?.locomotive || '';
  if (next === current) return;
  if (dirty && current) {
    const ok = confirm('Есть несохранённые изменения. Сохранить перед сменой локомотива?');
    if (!ok) {
      document.getElementById('locomotive').value = current;
      return;
    }
    await saveDraft();
  }
  await loadState(next);
}
function onLocomotiveCommit(){
  maybeSwitchLocomotive(document.getElementById('locomotive').value);
}
function onDateChange(){
  setDirty(true);
}
function onRepairChange(){
  currentRepairType = document.getElementById('repairType').value || '';
}
async function saveDraft(){
  if (!CAN_EDIT) return;
  if (!state) return;
  state.locomotive = getCurrentLoco();
  state.measurement_date = document.getElementById('measurementDate').value || state.measurement_date || new Date().toISOString().slice(0, 10);
  currentRepairType = document.getElementById('repairType').value || '';
  setStatus('Сохранение...');
  const res = await fetch(`${API}/api/state`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json; charset=utf-8' },
    body: JSON.stringify({
      locomotive: state.locomotive,
      measurement_date: state.measurement_date,
      measurements: state.measurements,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    setStatus(err.error || 'Ошибка сохранения');
    return;
  }
  state = await res.json();
  savedState = cloneState(state);
  canceledState = null;
  savedRepairType = currentRepairType;
  canceledRepairType = '';
  document.getElementById('locomotive').value = state.locomotive || '';
  document.getElementById('measurementDate').value = state.measurement_date || '';
  renderRepairOptions();
  renderMeta();
  renderTable();
  await loadArchive();
  setDirty(false);
  setStatus('Сохранено');
}

function blankMeasurements(){
  return Array.from({ length: 12 }, () => Array.from({ length: 10 }, () => ''));
}

async function saveToArchive(){
  if (!CAN_EDIT) return;
  if (!state) return;
  const payload = {
    locomotive: getCurrentLoco(),
    measurement_date: document.getElementById('measurementDate').value || state.measurement_date || new Date().toISOString().slice(0, 10),
    repair_type: document.getElementById('repairType').value || '',
    measurements: state.measurements,
    overwrite: false,
  };
  state.locomotive = payload.locomotive;
  state.measurement_date = payload.measurement_date;
  currentRepairType = payload.repair_type;
  setStatus('Сохранение в архив...');
  const sendRequest = async (overwrite) => {
    const res = await fetch(`${API}/api/archive`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json; charset=utf-8' },
      body: JSON.stringify({ ...payload, overwrite }),
    });
    return res;
  };

  let res = await sendRequest(false);
  if (res.status === 409) {
    const err = await res.json().catch(() => ({}));
    const ok = confirm((err.message || 'Запись уже есть в архиве.') + '\\n\\nПерезаписать существующую запись?');
    if (!ok) {
      setStatus('Сохранение в архив отменено');
      return;
    }
    res = await sendRequest(true);
  }

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    setStatus(err.error || err.message || 'Ошибка архивации');
    return;
  }

  state = await res.json();
  state.measurements = blankMeasurements();
  savedState = cloneState(state);
  canceledState = null;
  savedRepairType = currentRepairType;
  canceledRepairType = '';
  renderRepairOptions();
  renderMeta();
  renderTable();
  await loadArchive();
  setDirty(false);
  setStatus('Данные сохранены в архив');
}

function cancelChanges(){
  if (!CAN_EDIT || !savedState) return;
  canceledState = cloneState(state);
  canceledRepairType = currentRepairType;
  state = cloneState(savedState);
  currentRepairType = savedRepairType || '';
  document.getElementById('locomotive').value = state.locomotive || '';
  document.getElementById('measurementDate').value = state.measurement_date || '';
  renderLocoOptions();
  renderRepairOptions();
  renderMeta();
  renderTable();
  setDirty(false);
  setStatus('Отменено');
}

function restoreChanges(){
  if (!CAN_EDIT || !canceledState) return;
  state = cloneState(canceledState);
  currentRepairType = canceledRepairType || '';
  document.getElementById('locomotive').value = state.locomotive || '';
  document.getElementById('measurementDate').value = state.measurement_date || '';
  renderLocoOptions();
  renderRepairOptions();
  renderMeta();
  renderTable();
  setDirty(true);
  setStatus('Восстановлено');
  canceledState = null;
  canceledRepairType = '';
}

document.getElementById('locomotive').addEventListener('change', onLocomotiveCommit);
document.getElementById('measurementDate').addEventListener('change', onDateChange);
document.getElementById('repairType').addEventListener('change', onRepairChange);
document.getElementById('archiveLocomotive').addEventListener('change', loadArchive);
document.getElementById('archiveSearch').addEventListener('input', loadArchive);
document.getElementById('saveBtn').style.display = CAN_EDIT ? '' : 'none';
updateHistoryButtons();
loadState();
</script>
</body>
</html>
"""


UNAUTH_HTML = """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Замер КП</title>
  <style>
    body{margin:0;font-family:Segoe UI,Arial,sans-serif;background:#f4f7fb;color:#102033}
    .card{max-width:520px;margin:10vh auto;background:#fff;border:1px solid #d9e2ef;border-radius:18px;padding:24px;box-shadow:0 12px 32px rgba(16,32,51,.08)}
    a{display:inline-block;margin-top:12px;padding:12px 16px;border-radius:8px;background:#276ef1;color:#fff;text-decoration:none;font-weight:700}
    .muted{color:#607086;font-size:13px;line-height:1.5}
  </style>
</head>
<body>
  <div class="card">
    <h1 style="margin-top:0;">Вход через главное приложение</h1>
    <p class="muted">В `Замере КП` отдельный пароль больше не нужен. Сначала войдите в главное приложение, а затем откройте модуль снова.</p>
    <a href="/login">Открыть вход</a>
  </div>
</body>
</html>
"""


def render_page(role: str) -> str:
    return (
        HTML.replace("{{APP_PREFIX}}", APP_PREFIX)
        .replace("{{APP_VERSION}}", APP_VERSION)
        .replace("{{CAN_EDIT}}", "true" if role == "edit" else "false")
    )


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # noqa: D401
        return

    def do_GET(self):
        parsed = urlparse(self.path)
        route = route_path(parsed.path)
        session = current_session(self)
        role = session[1] if session else None

        if route == "/login":
            if session:
                redirect(self, APP_PREFIX)
                return
            send_html(self, UNAUTH_HTML)
            return

        if route == "/logout":
            redirect(self, "/logout")
            return

        if route == "/":
            if not session:
                send_html(self, UNAUTH_HTML)
                return
            send_html(self, render_page(role or "view"))
            return

        if route == "/api/state":
            if not require_auth(self):
                return
            qs = parse_qs(parsed.query)
            locomotive = text(qs.get("locomotive", [""])[0]).strip()
            send_json(self, load_state(locomotive))
            return

        if route == "/api/archive":
            if not require_auth(self):
                return
            qs = parse_qs(parsed.query)
            locomotive = text(qs.get("locomotive", [""])[0]).strip()
            search = text(qs.get("search", [""])[0]).strip()
            sort = text(qs.get("sort", ["desc"])[0]).strip().lower()
            rows = load_archive_rows(locomotive, search, sort != "asc")
            send_json(self, {"rows": rows})
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self):
        parsed = urlparse(self.path)
        route = route_path(parsed.path)
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length) if length else b"{}"

        if route == "/api/state":
            if not require_auth(self, need_edit=True):
                return
            try:
                payload = json.loads(raw.decode("utf-8"))
                send_json(self, save_state(payload))
            except Exception as exc:
                send_json(self, {"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return

        if route == "/api/archive":
            if not require_auth(self, need_edit=True):
                return
            try:
                payload = json.loads(raw.decode("utf-8"))
                result = save_archive(payload)
                if isinstance(result, tuple):
                    body, status = result
                    send_json(self, body, status)
                else:
                    send_json(self, result)
            except Exception as exc:
                send_json(self, {"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return

        self.send_error(HTTPStatus.NOT_FOUND, "Not found")


def main() -> None:
    ensure_db()
    host = os.environ.get("WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("WEB_PORT", "8003"))
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    url = f"http://{host}:{port}{APP_PREFIX}"
    print(f"Замер КП ready: {url}")
    if host in {"127.0.0.1", "localhost", "0.0.0.0"}:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    server.serve_forever()


if __name__ == "__main__":
    main()
