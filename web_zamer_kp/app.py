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
APP_VERSION = "web-zkp-1.23"
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
            "CREATE TABLE IF NOT EXISTS input_meta (y INT, locomotive TEXT, measurement_date TEXT, wheel_pair_count INT, section_count INT, PRIMARY KEY(y, locomotive))"
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
        existing_input_meta_cols = {row[1] for row in cur.execute("PRAGMA table_info(input_meta)").fetchall()}
        if "wheel_pair_count" not in existing_input_meta_cols:
            cur.execute("ALTER TABLE input_meta ADD COLUMN wheel_pair_count INT")
        if "section_count" not in existing_input_meta_cols:
            cur.execute("ALTER TABLE input_meta ADD COLUMN section_count INT")
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


def default_section_count(axis_count: int) -> int:
    return 1 if int(axis_count or 0) <= 6 else 3


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


def load_state(locomotive: str | None = None, wheel_pair_count: int | None = None, section_count: int | None = None) -> dict:
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
                "SELECT y, measurement_date, wheel_pair_count, section_count FROM input_meta WHERE locomotive=? ORDER BY y DESC LIMIT 1",
                (locomotive,),
            ).fetchone()

        measurement_date = dt.date.today().isoformat()
        year = dt.date.today().year
        if wheel_pair_count is None:
            wheel_pair_count = axis_count
        if section_count is None:
            section_count = default_section_count(axis_count)
        has_manual_meta = False
        if meta:
            year = int(meta["y"] or year)
            measurement_date = text(meta["measurement_date"]).strip() or measurement_date
            try:
                year = int(measurement_date[:4])
            except Exception:
                pass
            try:
                meta_wheel_pairs = int(meta["wheel_pair_count"] or 0)
            except Exception:
                meta_wheel_pairs = 0
            try:
                meta_sections = int(meta["section_count"] or 0)
            except Exception:
                meta_sections = 0
            if meta_wheel_pairs > 0:
                wheel_pair_count = meta_wheel_pairs
            if meta_sections > 0:
                section_count = meta_sections
            has_manual_meta = meta_wheel_pairs > 0 or meta_sections > 0
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
        "wheel_pair_count": int(wheel_pair_count or axis_count),
        "section_count": int(section_count or default_section_count(axis_count)),
        "has_manual_meta": has_manual_meta,
    }


def kp_completion_state(cur: sqlite3.Cursor, locomotive: str) -> str | None:
    locomotive = text(locomotive).strip()
    if not locomotive:
        return None

    series = series_for_locomotive(cur, locomotive)
    expected_rows = locomotive_axis_count(series, locomotive)
    rows = cur.execute(
        "SELECT r, c, v FROM kp_data WHERE locomotive=? AND c IN (2, 3)",
        (locomotive,),
    ).fetchall()
    if not rows:
        return None

    values: dict[tuple[int, int], str] = {}
    for row in rows:
        values[(int(row["r"]), int(row["c"]))] = text(row["v"]).strip()

    for row_index in range(expected_rows):
        if not values.get((row_index, 2), "") or not values.get((row_index, 3), ""):
            return "yellow"
    return "green"


def load_kp_view(selected_locomotive: str = "") -> dict:
    selected_locomotive = text(selected_locomotive).strip()
    with DB_LOCK, connect() as conn:
        cur = conn.cursor()
        locomotives = load_locomotives(cur)
        if not selected_locomotive and locomotives:
            selected_locomotive = locomotives[0]["number"]

        all_mode = selected_locomotive == "Все локомотивы"
        kp_map: dict[int, dict[int, str]] = {}
        rows: list[dict[str, object]] = []
        axis_count = 0
        status = None

        if all_mode:
            all_values = cur.execute(
                "SELECT locomotive, r, c, v FROM kp_data WHERE TRIM(COALESCE(locomotive, '')) <> '' ORDER BY locomotive, r, c"
            ).fetchall()
            kp_values: dict[tuple[str, int, int], str] = {}
            for row in all_values:
                kp_values[(text(row["locomotive"]).strip(), int(row["r"]), int(row["c"]))] = text(row["v"])

            for loco in locomotives:
                number = loco["number"]
                series = loco["series"]
                count = locomotive_axis_count(series, number)
                for row_index in range(count):
                    values = [
                        number,
                        str(row_index + 1),
                        kp_values.get((number, row_index, 1), ""),
                        kp_values.get((number, row_index, 2), ""),
                        kp_values.get((number, row_index, 3), ""),
                    ]
                    rows.append(
                        {
                            "locomotive": number,
                            "row": row_index,
                            "values": values,
                            "search": " ".join(text(v).strip().lower() for v in values),
                            "editable": False,
                        }
                    )
            status = "all"
        else:
            series = series_for_locomotive(cur, selected_locomotive)
            axis_count = locomotive_axis_count(series, selected_locomotive)
            kp_rows = cur.execute(
                "SELECT r, c, v FROM kp_data WHERE locomotive=? ORDER BY r, c",
                (selected_locomotive,),
            ).fetchall()
            if not kp_rows:
                kp_rows = cur.execute(
                    "SELECT r, c, v FROM kp_data WHERE locomotive='' ORDER BY r, c"
                ).fetchall()
            for row in kp_rows:
                kp_map.setdefault(int(row["r"]), {})[int(row["c"])] = text(row["v"])

            for row_index in range(axis_count):
                values = [
                    str(row_index + 1),
                    kp_map.get(row_index, {}).get(1, ""),
                    kp_map.get(row_index, {}).get(2, ""),
                    kp_map.get(row_index, {}).get(3, ""),
                ]
                rows.append(
                    {
                        "locomotive": selected_locomotive,
                        "row": row_index,
                        "values": values,
                        "search": " ".join(text(v).strip().lower() for v in values),
                        "editable": True,
                    }
                )
            status = kp_completion_state(cur, selected_locomotive)

        return {
            "selected_locomotive": selected_locomotive,
            "all_mode": all_mode,
            "axis_count": axis_count,
            "locomotives": locomotives,
            "rows": rows,
            "kp_map": kp_map,
            "status": status,
        }


def save_kp_data(payload: dict) -> dict:
    locomotive = text(payload.get("locomotive")).strip()
    if not locomotive or locomotive == "Все локомотивы":
        return {"error": "Выберите конкретный локомотив."}, 400

    rows = payload.get("rows") or []
    if not isinstance(rows, list):
        return {"error": "Некорректные данные КП."}, 400

    with DB_LOCK, connect() as conn:
        cur = conn.cursor()
        cur.execute("BEGIN")
        cur.execute("DELETE FROM kp_data WHERE locomotive=?", (locomotive,))

        insert_rows: list[tuple[str, int, int, str]] = []
        for r, row in enumerate(rows):
            values = list(row or []) + [""] * 4
            for c, value in enumerate(values[:4]):
                value = text(value).strip()
                if value:
                    insert_rows.append((locomotive, r, c, value))
        cur.executemany("INSERT INTO kp_data (locomotive, r, c, v) VALUES (?, ?, ?, ?)", insert_rows)
        conn.commit()

    return load_kp_view(locomotive)


def save_state(payload: dict) -> dict:
    locomotive = text(payload.get("locomotive")).strip()
    measurement_date = text(payload.get("measurement_date")).strip() or dt.date.today().isoformat()
    rows = payload.get("measurements") or []
    try:
        wheel_pair_count = int(payload.get("wheel_pair_count") or 0)
    except Exception:
        wheel_pair_count = 0
    try:
        section_count = int(payload.get("section_count") or 0)
    except Exception:
        section_count = 0

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
            "INSERT OR REPLACE INTO input_meta(y, locomotive, measurement_date, wheel_pair_count, section_count) VALUES(?,?,?,?,?)",
            (
                year,
                locomotive,
                measurement_date,
                wheel_pair_count or None,
                section_count or None,
            ),
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
        try:
            wheel_pair_count = int(payload.get("wheel_pair_count") or axis_count)
        except Exception:
            wheel_pair_count = axis_count
        try:
            section_count = int(payload.get("section_count") or default_section_count(axis_count))
        except Exception:
            section_count = default_section_count(axis_count)
        visible_rows = max(1, min(wheel_pair_count, INPUT_ROWS))
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
        section_sizes: list[int] = []
        base = visible_rows // max(1, section_count)
        remainder = visible_rows % max(1, section_count)
        for i in range(max(1, section_count)):
            section_sizes.append(base + (1 if i < remainder else 0))
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
            running = 0
            section_value = "1"
            for section_index, span in enumerate(section_sizes, start=1):
                running += span
                if row_index < running:
                    section_value = str(section_index)
                    break
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
    try:
        wheel_pair_count = int(payload.get("wheel_pair_count") or 0)
    except Exception:
        wheel_pair_count = 0
    try:
        section_count = int(payload.get("section_count") or 0)
    except Exception:
        section_count = 0

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
            "INSERT OR REPLACE INTO input_meta(y, locomotive, measurement_date, wheel_pair_count, section_count) VALUES(?,?,?,?,?)",
            (
                year,
                locomotive,
                measurement_date,
                wheel_pair_count or None,
                section_count or None,
            ),
        )
        conn.commit()

    return load_state(locomotive)


def update_archive_cells(payload: dict) -> dict:
    changes = payload.get("changes") or []
    if not isinstance(changes, list) or not changes:
        return {"error": "Нет изменений для сохранения."}, 400

    normalized: list[tuple[int, str, str, str, int, int, str]] = []
    for change in changes:
        if not isinstance(change, dict):
            return {"error": "Некорректный формат изменений."}, 400
        try:
            year = int(change.get("year"))
            measurement_date = text(change.get("measurement_date")).strip()
            locomotive = text(change.get("locomotive")).strip()
            repair_type = text(change.get("repair_type")).strip()
            source_r = int(change.get("source_r"))
            display_col = int(change.get("display_col"))
            if display_col < 10 or display_col > 19:
                return {"error": "Можно редактировать только правую часть таблицы архива."}, 400
            source_c = display_col - 8
            value = text(change.get("value"))
        except Exception:
            return {"error": "Некорректные данные изменения архива."}, 400

        if not measurement_date or not locomotive or not repair_type:
            return {"error": "Не удалось определить строку архива для изменения."}, 400

        normalized.append((year, measurement_date, locomotive, repair_type, source_r, source_c, value))

    with DB_LOCK, connect() as conn:
        cur = conn.cursor()
        cur.execute("BEGIN")
        for year, measurement_date, locomotive, repair_type, source_r, source_c, value in normalized:
            cur.execute(
                "INSERT OR REPLACE INTO archive_data (y, measurement_date, locomotive, repair_type, r, c, v) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (year, measurement_date, locomotive, repair_type, source_r, source_c, value),
            )
        conn.commit()

    return {"ok": True}


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
                "source_r": row_index,
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
    .kp-shell { margin-top:12px; }
    .kp-controls { display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin-bottom:10px; }
    .kp-note { margin:6px 0 8px; color:var(--muted); font-size:13px; line-height:1.4; }
    .kp-legend { display:flex; gap:12px; flex-wrap:wrap; align-items:center; margin-bottom:10px; font-size:13px; color:#44556b; }
    .kp-legend-item { display:flex; align-items:center; gap:6px; }
    .kp-legend-swatch { width:14px; height:14px; border:1px solid #7f8ea5; border-radius:3px; box-sizing:border-box; }
    .kp-legend-green { background:#c8e6c9; }
    .kp-legend-yellow { background:#fff0a6; }
    .kp-legend-empty { background:transparent; }
    .kp-status { min-height:20px; margin-top:8px; font-size:13px; color:var(--muted); }
    .kp-table-shell { margin-top:0; padding-top:8px; }
    .kp-table th, .kp-table td { font-size:12px; }
    .kp-table td { white-space:pre-line; }
    .kp-table td input { width:100%; height:34px; border:0; text-align:center; background:transparent; padding:2px 3px; font-size:12px; }
    .kp-table td.readonly { background:#f7fafc; font-weight:600; }
    .kp-table td.selected { box-shadow: inset 0 0 0 2px #2f6fed; }
    .loco-picker { position:relative; width:220px; }
    .loco-picker input { width:100%; box-sizing:border-box; }
    .loco-dropdown {
      position:absolute;
      left:0;
      top:calc(100% + 4px);
      z-index:30;
      min-width:220px;
      max-height:240px;
      overflow:auto;
      background:#fff;
      border:1px solid var(--line);
      border-radius:10px;
      box-shadow:0 12px 28px rgba(16,32,51,.12);
      display:none;
    }
    .loco-dropdown.open { display:block; }
    .loco-dropdown button {
      display:block;
      width:100%;
      border:0;
      background:#fff;
      padding:8px 10px;
      text-align:left;
      font:inherit;
      color:var(--text);
      cursor:pointer;
    }
    .loco-dropdown button:hover,
    .loco-dropdown button:focus {
      background:#eef4ff;
      outline:none;
    }
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
    .archive-table td.axis-col { width:80px; background:#f7fafc; font-weight:600; }
    .archive-table td.archive-raw { width:60px; }
    .archive-table td.archive-raw input {
      width:100%;
      height:34px;
      border:0;
      text-align:center;
      background:transparent;
      padding:2px 3px;
      font-size:12px;
    }
    .archive-table td.summary { width:110px; }
    .archive-table td.first-col { width:220px; }
    .status { min-height:20px; margin-top:10px; font-size:13px; color:var(--muted); }
    .input-meta { margin-top:8px; font-size:13px; color:var(--muted); }
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
      <button id="tabKp" class="tab" type="button" onclick="switchTab('kp')">КП данные</button>
      <button id="tabArchive" class="tab" type="button" onclick="switchTab('archive')">Архив замеров</button>
    </div>

    <div id="panelInput" class="panel active">
      <div class="filters" style="margin-top:0;">
        <label>Локомотив
          <div class="loco-picker">
            <input id="locomotive" type="text" autocomplete="off" aria-autocomplete="list" style="width:220px">
            <div id="locomotiveDropdown" class="loco-dropdown" role="listbox" aria-label="Список локомотивов"></div>
          </div>
        </label>
        <label>Дата замера
          <input id="measurementDate" type="date" style="width:150px">
        </label>
        <label>Вид ремонта
          <select id="repairType" style="width:150px"></select>
        </label>
      <button id="saveBtn" class="primary" onclick="saveToArchive()">Сохранить в архив</button>
      </div>
      <div id="inputMeta" class="input-meta"></div>
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

    <div id="panelKp" class="panel">
      <div class="kp-controls" style="margin-top:0;">
        <label>Локомотив
          <select id="kpLocomotive" style="width:220px"></select>
        </label>
        <label>Поиск
          <input id="kpSearch" type="text" placeholder="№ КП, ось, диаметр" style="width:260px">
        </label>
      </div>
      <div class="kp-note">Памятка: редактирование диаметров колесных центров доступно только при выборе конкретного локомотива.</div>
      <div class="kp-legend">
        <div class="kp-legend-item"><span class="kp-legend-swatch kp-legend-yellow"></span><span>жёлтый - данные диаметров заполнены не полностью</span></div>
        <div class="kp-legend-item"><span class="kp-legend-swatch kp-legend-green"></span><span>зелёный - все данные диаметров внесены</span></div>
        <div class="kp-legend-item"><span class="kp-legend-swatch kp-legend-empty"></span><span>без цвета - данных по диаметрам нет</span></div>
      </div>
      <div class="table-shell kp-table-shell">
        <table id="kpTable" class="kp-table" aria-label="КП данные">
          <colgroup id="kpColgroup">
            <col style="width:160px">
            <col style="width:160px">
            <col style="width:160px">
            <col style="width:160px">
          </colgroup>
          <thead id="kpHead"></thead>
          <tbody id="kpBody"></tbody>
        </table>
      </div>
      <div id="kpStatus" class="kp-status"></div>
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
const LOCOMOTIVE_CHOICES = {{LOCOMOTIVE_CHOICES}};
let state = null;
let dirty = false;
let currentRepairType = '';
let savedState = null;
let canceledState = null;
let savedRepairType = '';
let canceledRepairType = '';
let kpRows = [];
let kpSelectedLoco = '';
let kpAllMode = false;
let kpSearchText = '';
let kpLoading = false;
let kpSelectedStatus = null;
let archiveRows = [];
let archiveSortDesc = true;
let selectionAnchor = null;
let selectionFocus = null;
let clipboardCache = '';
let archiveSelectionAnchor = null;
let archiveSelectionFocus = null;
let locomotiveInputSource = 'loaded';
let initialLoadPromise = null;

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
function archiveRowMeta(row){
  return archiveRows[row] || null;
}
function archiveCellElement(row, col){
  return document.querySelector(`#archiveBody input[data-row="${row}"][data-col="${col}"]`);
}
function archiveCellValue(row, col){
  const input = archiveCellElement(row, col);
  if (input) return input.value ?? '';
  return archiveRowMeta(row)?.values?.[col] ?? '';
}
function archiveCellInBounds(row, col){
  return row >= 0 && row < archiveRows.length && col >= 10 && col <= 19;
}
function clearArchiveSelection(){
  archiveSelectionAnchor = null;
  archiveSelectionFocus = null;
  document.querySelectorAll('#archiveBody td.selected').forEach(td => td.classList.remove('selected'));
}
function archiveSelectionRect(){
  if (!archiveSelectionAnchor || !archiveSelectionFocus) return null;
  return {
    top: Math.min(archiveSelectionAnchor.row, archiveSelectionFocus.row),
    bottom: Math.max(archiveSelectionAnchor.row, archiveSelectionFocus.row),
    left: Math.min(archiveSelectionAnchor.col, archiveSelectionFocus.col),
    right: Math.max(archiveSelectionAnchor.col, archiveSelectionFocus.col),
  };
}
function renderArchiveSelectionHighlight(){
  document.querySelectorAll('#archiveBody td.selected').forEach(td => td.classList.remove('selected'));
  const rect = archiveSelectionRect();
  if (!rect) return;
  for (let r = rect.top; r <= rect.bottom; r += 1) {
    for (let c = rect.left; c <= rect.right; c += 1) {
      const td = document.querySelector(`#archiveBody tr[data-row="${r}"] td[data-col="${c}"]`);
      if (td) td.classList.add('selected');
    }
  }
}
function selectArchiveCell(row, col, extend = false){
  const cell = { row, col };
  if (!extend || !archiveSelectionAnchor) {
    archiveSelectionAnchor = cell;
  }
  archiveSelectionFocus = cell;
  renderArchiveSelectionHighlight();
}
function focusArchiveCell(row, col, extend = false){
  if (!archiveCellInBounds(row, col)) return;
  selectArchiveCell(row, col, extend);
  const target = archiveCellElement(row, col);
  if (target) target.focus();
}
function archiveCellChangePayload(row, col, value){
  const meta = archiveRowMeta(row);
  if (!meta) return null;
  return {
    year: meta.year,
    measurement_date: meta.measurement_date,
    locomotive: meta.locomotive,
    repair_type: meta.repair_type,
    source_r: meta.source_r,
    display_col: col,
    value,
  };
}
async function saveArchiveChanges(changes, statusText){
  if (!CAN_EDIT) return false;
  if (!changes.length) return true;
  const status = document.getElementById('archiveStatus');
  if (status) status.textContent = statusText || 'Сохранение архива...';
  const res = await fetch(`${API}/api/archive`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json; charset=utf-8' },
    body: JSON.stringify({ changes }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    await loadArchive();
    if (status) status.textContent = err.error || err.message || 'Ошибка сохранения архива';
    return false;
  }
  await loadArchive();
  clearArchiveSelection();
  if (status) status.textContent = 'Архив обновлен';
  return true;
}
async function copyArchiveSelectionToClipboard(){
  const rect = archiveSelectionRect();
  const start = rect ? { row: rect.top, col: rect.left } : (archiveSelectionFocus || archiveSelectionAnchor);
  if (!start || !archiveCellInBounds(start.row, start.col)) return;
  const end = rect ? { row: rect.bottom, col: rect.right } : start;
  const lines = [];
  for (let r = start.row; r <= end.row; r += 1) {
    const rowValues = [];
    for (let c = start.col; c <= end.col; c += 1) {
      rowValues.push(archiveCellValue(r, c));
    }
    lines.push(rowValues.join('\\t'));
  }
  await writeClipboardText(lines.join('\\n'));
  const status = document.getElementById('archiveStatus');
  if (status) status.textContent = 'Скопировано';
}
async function applyArchivePastedBlock(text, startRow, startCol){
  if (!CAN_EDIT) return false;
  const rows = String(text ?? '').replace(/\\r/g, '').split('\\n');
  if (rows.length && rows[rows.length - 1] === '') rows.pop();
  if (!rows.length) return false;
  const changes = [];
  for (let i = 0; i < rows.length; i += 1) {
    const cells = rows[i].split('\t');
    for (let j = 0; j < cells.length; j += 1) {
      const tr = startRow + i;
      const tc = startCol + j;
      if (!archiveCellInBounds(tr, tc)) continue;
      const input = archiveCellElement(tr, tc);
      if (!input) continue;
      const value = cells[j].trim();
      input.value = value;
      input.dataset.original = value;
      const payload = archiveCellChangePayload(tr, tc, value);
      if (payload) changes.push(payload);
    }
  }
  if (!changes.length) return false;
  return saveArchiveChanges(changes, 'Сохранение архива...');
}
async function clearArchiveSelectedCells(){
  if (!CAN_EDIT) return false;
  const rect = archiveSelectionRect();
  const start = rect ? { row: rect.top, col: rect.left } : (archiveSelectionFocus || archiveSelectionAnchor);
  if (!start || !archiveCellInBounds(start.row, start.col)) return false;
  const end = rect ? { row: rect.bottom, col: rect.right } : start;
  const changes = [];
  for (let r = start.row; r <= end.row; r += 1) {
    for (let c = start.col; c <= end.col; c += 1) {
      if (!archiveCellInBounds(r, c)) continue;
      const input = archiveCellElement(r, c);
      if (!input) continue;
      input.value = '';
      input.dataset.original = '';
      const payload = archiveCellChangePayload(r, c, '');
      if (payload) changes.push(payload);
    }
  }
  if (!changes.length) return false;
  return saveArchiveChanges(changes, 'Очистка архива...');
}
function handleArchiveCellMouseDown(event, row, col){
  if (!CAN_EDIT) return true;
  if (event.button !== 0) return true;
  if (event.shiftKey && archiveSelectionAnchor) {
    selectArchiveCell(archiveSelectionAnchor.row, archiveSelectionAnchor.col, true);
    selectArchiveCell(row, col, true);
  } else {
    selectArchiveCell(row, col, false);
  }
  const target = event.currentTarget;
  if (target) target.focus();
  event.preventDefault();
  return false;
}
function handleArchiveCellFocus(row, col){
  if (!archiveSelectionAnchor || !archiveSelectionFocus || archiveSelectionAnchor.row !== row || archiveSelectionAnchor.col !== col || archiveSelectionFocus.row !== row || archiveSelectionFocus.col !== col) {
    selectArchiveCell(row, col, false);
  }
}
async function handleArchiveCellChange(row, col, value, input){
  if (!CAN_EDIT) return;
  const meta = archiveRowMeta(row);
  if (!meta) return;
  const current = String(input?.dataset?.original ?? '');
  const next = String(value ?? '').trim();
  if (current === next) return;
  const ok = confirm('Вы уверены, что хотите изменить данные в архиве?');
  if (!ok) {
    if (input) input.value = current;
    return;
  }
  const saved = await saveArchiveChanges([archiveCellChangePayload(row, col, next)], 'Сохранение архива...');
  if (!saved && input) {
    input.value = current;
  }
}
async function handleArchiveKeydown(event, row, col){
  const key = event.key;
  const ctrlOrMeta = event.ctrlKey || event.metaKey;
  if (ctrlOrMeta && key.toLowerCase() === 'c') {
    event.preventDefault();
    await copyArchiveSelectionToClipboard();
    return;
  }
  if (ctrlOrMeta && key.toLowerCase() === 'v') {
    event.preventDefault();
    const ok = confirm('Вы уверены, что хотите вставить данные в архив?');
    if (!ok) return;
    const text = await readClipboardText();
    if (!text) return;
    const rect = archiveSelectionRect();
    const start = rect ? { row: rect.top, col: rect.left } : { row, col };
    await applyArchivePastedBlock(text, start.row, start.col);
    return;
  }
  if (key === 'Delete' || key === 'Backspace') {
    event.preventDefault();
    const ok = confirm('Вы уверены, что хотите очистить выбранные ячейки в архиве?');
    if (!ok) return;
    await clearArchiveSelectedCells();
    return;
  }
  if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(key)) return;
  event.preventDefault();
  if (event.shiftKey) {
    if (!archiveSelectionAnchor) archiveSelectionAnchor = { row, col };
    let nextRow = row;
    let nextCol = col;
    if (key === 'ArrowLeft' && col > 10) nextCol = col - 1;
    if (key === 'ArrowRight' && col < 19) nextCol = col + 1;
    if (key === 'ArrowUp' && row > 0) nextRow = row - 1;
    if (key === 'ArrowDown' && row < (archiveRows.length - 1)) nextRow = row + 1;
    focusArchiveCell(nextRow, nextCol, true);
    return;
  }
  if (key === 'ArrowLeft' && col > 10) focusArchiveCell(row, col - 1, false);
  if (key === 'ArrowRight' && col < 19) focusArchiveCell(row, col + 1, false);
  if (key === 'ArrowUp' && row > 0) focusArchiveCell(row - 1, col, false);
  if (key === 'ArrowDown' && row < (archiveRows.length - 1)) focusArchiveCell(row + 1, col, false);
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
  const kpTab = document.getElementById('tabKp');
  const archiveTab = document.getElementById('tabArchive');
  const panelInput = document.getElementById('panelInput');
  const panelKp = document.getElementById('panelKp');
  const panelArchive = document.getElementById('panelArchive');
  if (inputTab) inputTab.classList.toggle('active', tab === 'input');
  if (kpTab) kpTab.classList.toggle('active', tab === 'kp');
  if (archiveTab) archiveTab.classList.toggle('active', tab === 'archive');
  if (panelInput) panelInput.classList.toggle('active', tab === 'input');
  if (panelKp) panelKp.classList.toggle('active', tab === 'kp');
  if (panelArchive) panelArchive.classList.toggle('active', tab === 'archive');
}
async function switchTab(tab){
  setActiveTab(tab);
  if (tab === 'kp') {
    renderKpLocomotiveOptions();
    await loadKpData(document.getElementById('kpLocomotive')?.value || kpSelectedLoco || state?.locomotive || '');
  }
  if (tab === 'archive') {
    await loadArchive();
  }
}
function getCurrentLoco(){
  return document.getElementById('locomotive').value.trim();
}
function isKnownLocomotive(number){
  return (LOCOMOTIVE_CHOICES || []).some(item => item.number === String(number || '').trim());
}
function currentWheelPairCount(number){
  if (state && String(number || '').trim() === String(state.locomotive || '').trim() && Number.isFinite(Number(state.wheel_pair_count))) {
    return Number(state.wheel_pair_count) || 12;
  }
  return 12;
}
function currentSectionCount(number){
  if (state && String(number || '').trim() === String(state.locomotive || '').trim() && Number.isFinite(Number(state.section_count))) {
    return Math.max(1, Number(state.section_count) || 1);
  }
  return 0;
}
function getSeries(number){
  const item = (state?.locomotives || []).find(x => x.number === number);
  return item ? (item.series || '') : '';
}
function getAxisCount(number){
  if (state && String(number || '').trim() === String(state.locomotive || '').trim() && Number.isFinite(Number(state.wheel_pair_count))) {
    return Math.max(1, Number(state.wheel_pair_count) || 12);
  }
  const series = getSeries(number);
  const text = (series + ' ' + number).toLowerCase().replaceAll('ё','е');
  if (text.includes('пэ-2м') || text.includes('пэ2м') || text.includes('пэ 2м') || text.includes('pe-2m') || text.includes('pe2m')) return 12;
  if (text.includes('тэм') || text.includes('tem')) return 6;
  return 12;
}
function defaultSectionCount(axisCount){
  return Number(axisCount) <= 6 ? 1 : 3;
}
function allowedRepairs(number){
  const series = getSeries(number);
  const text = (series + ' ' + number).toLowerCase().replaceAll('ё','е');
  if (text.includes('пэ-2м') || text.includes('пэ2м') || text.includes('пэ 2м') || text.includes('pe-2m') || text.includes('pe2m')) {
    return ['', 'ТО', 'ТР', 'СР', 'КР'];
  }
  return ['', 'ТО-2', 'ТО-3', 'ТО-4', 'ТР-1', 'ТР-2', 'ТР-3', 'СР', 'КР'];
}
function sectionSpec(axisCount, sectionCount){
  const total = Math.max(1, Number(axisCount) || 1);
  const sections = Math.max(1, Math.min(Number(sectionCount) || defaultSectionCount(total), total));
  const base = Math.floor(total / sections);
  const remainder = total % sections;
  const result = [];
  let start = 0;
  for (let i = 0; i < sections; i += 1) {
    const span = base + (i < remainder ? 1 : 0);
    result.push({ start, span, value: String(i + 1) });
    start += span;
  }
  return result;
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
  const input = document.getElementById('locomotive');
  const items = state?.locomotives || [];
  const choices = LOCOMOTIVE_CHOICES || [];
  if (!input) return;
  if (state?.locomotive && (items.some(x => x.number === state.locomotive) || choices.some(x => x.number === state.locomotive))) {
    input.value = state.locomotive;
  } else if (choices.length && !input.value) {
    input.value = choices[0].number;
  }
  renderLocoDropdown('', false);
  renderMeta();
}
function renderLocoDropdown(filterText = '', open = true){
  const dropdown = document.getElementById('locomotiveDropdown');
  const items = LOCOMOTIVE_CHOICES || [];
  if (!dropdown) return;
  const textValue = String(filterText || '').trim().toLowerCase();
  const filtered = textValue
    ? items.filter(item => String(item.number || '').toLowerCase().includes(textValue) || String(item.label || '').toLowerCase().includes(textValue))
    : items;
  if (!filtered.length) {
    dropdown.innerHTML = '<button type="button" disabled>Нет совпадений</button>';
    dropdown.classList.toggle('open', !!open);
    return;
  }
  dropdown.innerHTML = filtered
    .map(item => `<button type="button" data-loco="${esc(item.number)}">${esc(item.number)}</button>`)
    .join('');
  dropdown.classList.toggle('open', !!open);
}
function hideLocoDropdown(){
  const dropdown = document.getElementById('locomotiveDropdown');
  if (dropdown) dropdown.classList.remove('open');
}
function showLocoDropdown(){
  const input = document.getElementById('locomotive');
  if (!input) return;
  renderLocoDropdown(input.value, true);
}
function chooseLoco(value){
  const input = document.getElementById('locomotive');
  if (!input) return;
  locomotiveInputSource = 'picked';
  input.value = value;
  hideLocoDropdown();
  onLocomotiveCommit();
}
function parsePositiveInt(value){
  const n = parseInt(String(value ?? '').trim(), 10);
  return Number.isFinite(n) && n > 0 ? n : null;
}
async function promptManualLocoCounts(loco){
  const fallbackWheelPairs = 12;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    const wheelPairText = prompt(`Локомотив ${loco} не найден в справочнике.\nСколько у него колесных пар?`, String(fallbackWheelPairs));
    if (wheelPairText === null) return null;
    const wheelPairCount = parsePositiveInt(wheelPairText);
    if (!wheelPairCount) {
      alert('Введите положительное число колесных пар.');
      continue;
    }
    const defaultSections = wheelPairCount <= 6 ? 1 : 3;
    const sectionText = prompt(`Сколько секций у локомотива ${loco}?`, String(defaultSections));
    if (sectionText === null) return null;
    const sectionCount = parsePositiveInt(sectionText);
    if (!sectionCount || sectionCount > wheelPairCount) {
      alert('Число секций должно быть положительным и не больше числа колесных пар.');
      continue;
    }
    return { wheel_pair_count: wheelPairCount, section_count: sectionCount };
  }
  return null;
}
function renderArchiveLocomotives(){
  const select = document.getElementById('archiveLocomotive');
  const items = LOCOMOTIVE_CHOICES || [];
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
function kpStatusLabel(status, allMode, rowCount){
  if (allMode) {
    return rowCount ? `Показано строк: ${rowCount}` : 'Нет данных по КП';
  }
  if (status === 'green') return 'Диаметры заполнены полностью';
  if (status === 'yellow') return 'Есть неполные данные по диаметрам';
  return 'Данных по диаметрам нет';
}
function renderKpLocomotiveOptions(){
  const select = document.getElementById('kpLocomotive');
  const items = LOCOMOTIVE_CHOICES || [];
  if (!select) return;
  const current = select.value || kpSelectedLoco || state?.locomotive || '';
  select.innerHTML = items.length
    ? ['<option value="">Выберите локомотив</option>', '<option value="Все локомотивы">Все локомотивы</option>']
        .concat(items.map(x => `<option value="${esc(x.number)}">${esc(x.number)}</option>`))
        .join('')
    : '<option value="">Нет локомотивов в справочнике</option>';
  if (current && (current === 'Все локомотивы' || items.some(x => x.number === current))) {
    select.value = current;
  } else if (state?.locomotive && items.some(x => x.number === state.locomotive)) {
    select.value = state.locomotive;
  } else if (items.length) {
    select.value = items[0].number;
  }
  kpSelectedLoco = select.value || '';
}
function renderKpStatus(textValue){
  const status = document.getElementById('kpStatus');
  if (status) status.textContent = textValue || '';
}
function renderKpTable(){
  const head = document.getElementById('kpHead');
  const body = document.getElementById('kpBody');
  const colgroup = document.getElementById('kpColgroup');
  if (!head || !body || !colgroup) return;

  const allMode = kpAllMode;
  const headers = allMode
    ? ['Локомотив', '№ КП', '№ оси', 'Диаметр КЦ<br>лев', 'Диаметр КЦ<br>прав']
    : ['№ КП', '№ оси', 'Диаметр КЦ<br>лев', 'Диаметр КЦ<br>прав'];
  const widths = allMode ? [120, 120, 160, 160, 160] : [160, 160, 160, 160];
  colgroup.innerHTML = widths.map(w => `<col style="width:${w}px">`).join('');
  head.innerHTML = `<tr>${headers.map(value => `<th>${value}</th>`).join('')}</tr>`;

  if (!kpRows.length) {
    body.innerHTML = `<tr><td colspan="${headers.length}" style="padding:14px;color:var(--muted);">Нет данных</td></tr>`;
    renderKpStatus(kpStatusLabel(null, allMode, 0));
    return;
  }

  body.innerHTML = kpRows.map((row, rowIndex) => {
    const values = row.values || [];
    const search = row.search || values.map(value => String(value ?? '').trim().toLowerCase()).join(' ');
    const editable = !!row.editable && CAN_EDIT && !allMode;
    if (allMode) {
      return `
        <tr data-row="${rowIndex}" data-search="${esc(search)}">
          ${values.map((value, colIndex) => {
            const cls = colIndex === 0 ? 'readonly' : '';
            return `<td class="${cls}">${esc(value)}</td>`;
          }).join('')}
        </tr>`;
    }
    return `
      <tr data-row="${rowIndex}" data-search="${esc(search)}">
        <td class="readonly">${esc(values[0] ?? '')}</td>
        ${[1, 2, 3].map(colIndex => `
          <td>
            <input
              value="${esc(values[colIndex] ?? '')}"
              ${editable ? '' : 'readonly'}
              data-row="${rowIndex}"
              data-col="${colIndex}"
              onfocus="handleKpCellFocus(this)"
              onmousedown="return handleKpCellMouseDown(event, ${rowIndex}, ${colIndex})"
              onchange="handleKpCellChange(${rowIndex}, ${colIndex}, this.value, this)"
              onkeydown="handleKpKeydown(event, ${rowIndex}, ${colIndex})"
            >
          </td>`).join('')}
      </tr>`;
  }).join('');
  applyKpSearchFilter();
  renderKpStatus(kpStatusLabel(kpSelectedStatus, allMode, kpRows.length));
}
function applyKpSearchFilter(){
  const textValue = (document.getElementById('kpSearch')?.value || kpSearchText || '').trim().toLowerCase();
  kpSearchText = textValue;
  document.querySelectorAll('#kpBody tr').forEach(tr => {
    const haystack = (tr.dataset.search || tr.textContent || '').toLowerCase();
    tr.style.display = !textValue || haystack.includes(textValue) ? '' : 'none';
  });
}
function kpCellElement(row, col){
  return document.querySelector(`#kpBody input[data-row="${row}"][data-col="${col}"]`);
}
function kpRowValues(rowIndex){
  const row = kpRows[rowIndex];
  if (!row) return [];
  return row.values || [];
}
function handleKpCellFocus(input){
  if (!input) return;
  input.select?.();
}
function handleKpCellMouseDown(event, row, col){
  if (!CAN_EDIT || kpAllMode) return true;
  if (event.button !== 0) return true;
  const input = event.currentTarget;
  if (input) input.focus();
  event.preventDefault();
  return false;
}
function handleKpCellChange(row, col, value, input){
  if (!CAN_EDIT || kpAllMode || kpLoading) return;
  const next = String(value ?? '').trim();
  if (!kpRows[row]) return;
  kpRows[row].values[col] = next;
  if (input) input.value = next;
  saveKpDataChanges();
}
function handleKpKeydown(event, row, col){
  if (kpAllMode) return;
  const key = event.key;
  if (key === 'Delete' || key === 'Backspace') {
    event.preventDefault();
    const input = kpCellElement(row, col);
    if (input) {
      input.value = '';
      handleKpCellChange(row, col, '', input);
    }
    return;
  }
  if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(key)) {
    event.preventDefault();
    let nextRow = row;
    let nextCol = col;
    if (key === 'ArrowLeft' && col > 1) nextCol = col - 1;
    if (key === 'ArrowRight' && col < 3) nextCol = col + 1;
    if (key === 'ArrowUp' && row > 0) nextRow = row - 1;
    if (key === 'ArrowDown' && row < kpRows.length - 1) nextRow = row + 1;
    const next = kpCellElement(nextRow, nextCol);
    if (next) next.focus();
  }
}
function collectKpRowsFromView(){
  return kpRows.map((row, rowIndex) => {
    if (kpAllMode) return row.values || [];
    const values = [`${rowIndex + 1}`, '', '', ''];
    values[1] = kpCellElement(rowIndex, 1)?.value ?? row.values?.[1] ?? '';
    values[2] = kpCellElement(rowIndex, 2)?.value ?? row.values?.[2] ?? '';
    values[3] = kpCellElement(rowIndex, 3)?.value ?? row.values?.[3] ?? '';
    return values.map(value => String(value ?? '').trim());
  });
}
async function saveKpDataChanges(){
  if (!CAN_EDIT || kpAllMode || kpLoading) return false;
  const loco = (kpSelectedLoco || '').trim();
  if (!loco || loco === 'Все локомотивы') return false;
  const rows = collectKpRowsFromView();
  kpLoading = true;
  renderKpStatus('Сохранение КП данных...');
    try {
      const res = await fetch(`${API}/api/kp-data`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json; charset=utf-8' },
        body: JSON.stringify({ locomotive: loco, rows }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        kpLoading = false;
        await loadKpData(loco);
        renderKpStatus(err.error || 'Не удалось сохранить КП данные');
        return false;
      }
    const payload = await res.json();
    kpSelectedLoco = payload.selected_locomotive || loco;
    kpAllMode = !!payload.all_mode;
    kpSelectedStatus = payload.status || null;
    kpRows = payload.rows || [];
    if (state && kpSelectedLoco && kpSelectedLoco === state.locomotive) {
      state.kp = payload.kp_map || {};
      recalcDiameters();
    }
    renderKpLocomotiveOptions();
    renderKpTable();
    renderKpStatus(kpStatusLabel(kpSelectedStatus, kpAllMode, kpRows.length));
    return true;
  } finally {
    kpLoading = false;
  }
}
async function loadKpData(nextValue){
  const select = document.getElementById('kpLocomotive');
  const value = String(nextValue ?? select?.value ?? kpSelectedLoco ?? state?.locomotive ?? '').trim();
  if (select && value && select.value !== value) {
    select.value = value;
  }
  kpSelectedLoco = value || (state?.locomotive || '');
  kpLoading = true;
  renderKpStatus('Загрузка КП данных...');
  try {
    const res = await fetch(`${API}/api/kp-data?locomotive=${encodeURIComponent(kpSelectedLoco)}`, { cache: 'no-store' });
    if (!res.ok) {
      kpRows = [];
      kpAllMode = false;
      renderKpTable();
      renderKpStatus('Не удалось загрузить КП данные');
      return;
    }
    const payload = await res.json();
    kpSelectedLoco = payload.selected_locomotive || kpSelectedLoco;
    kpAllMode = !!payload.all_mode;
    kpSelectedStatus = payload.status || null;
    kpRows = payload.rows || [];
    renderKpLocomotiveOptions();
    renderKpTable();
    renderKpStatus(kpStatusLabel(kpSelectedStatus, kpAllMode, kpRows.length));
  } finally {
    kpLoading = false;
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
  const meta = document.getElementById('inputMeta');
  if (!meta) return;
  const loco = getCurrentLoco() || state?.locomotive || '';
  const axisCount = getAxisCount(loco);
  const wheelPairCount = Math.max(1, Number(state?.wheel_pair_count) || axisCount);
  const sectionCount = Math.max(1, Number(state?.section_count) || defaultSectionCount(axisCount));
  meta.textContent = `Колесных пар: ${wheelPairCount} · Секций: ${sectionCount}`;
}
function renderArchiveTable(){
  const tbody = document.getElementById('archiveBody');
  if (!tbody) return;
  if (!archiveRows.length) {
    tbody.innerHTML = '<tr><td colspan="20" style="padding:14px;color:var(--muted);">Архив пуст</td></tr>';
    return;
  }
  tbody.innerHTML = archiveRows.map((row, rowIndex) => {
    const values = row.values || [];
    const cells = values.map((value, index) => {
      if (index >= 10) {
        return `
          <td class="measure-cell archive-raw" data-col="${index}">
            <input
              value="${esc(value)}"
              data-row="${rowIndex}"
              data-col="${index}"
              data-original="${esc(value)}"
              ${CAN_EDIT ? '' : 'readonly'}
              onmousedown="return handleArchiveCellMouseDown(event, ${rowIndex}, ${index})"
              onfocus="handleArchiveCellFocus(${rowIndex}, ${index})"
              onchange="handleArchiveCellChange(${rowIndex}, ${index}, this.value, this)"
              onkeydown="handleArchiveKeydown(event, ${rowIndex}, ${index})"
            >
          </td>`;
      }
      const cls = index === 0 ? 'first-col' : (index === 9 ? 'axis-col' : 'summary');
      return `<td class="${cls}" data-col="${index}">${esc(value)}</td>`;
    }).join('');
    return `<tr data-row="${rowIndex}" data-year="${esc(row.year)}" data-measurement-date="${esc(row.measurement_date)}" data-locomotive="${esc(row.locomotive)}" data-repair-type="${esc(row.repair_type)}" data-source-r="${esc(row.source_r)}">${cells}</tr>`;
  }).join('');
  renderArchiveSelectionHighlight();
}
function renderTable(){
  const tbody = document.getElementById('inputBody');
  const loco = getCurrentLoco();
  const axisCount = getAxisCount(loco);
  const sectionCount = (state && String(loco) === String(state.locomotive || ''))
    ? Math.max(1, Number(state.section_count) || defaultSectionCount(axisCount))
    : defaultSectionCount(axisCount);
  const visibleRows = Math.max(1, Math.min(axisCount, INPUT_ROWS));
  const sections = sectionSpec(axisCount, sectionCount);
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
  clearArchiveSelection();
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
async function fetchStatePayload(locomotive){
  const loco = String(locomotive ?? '').trim();
  const res = await fetch(`${API}/api/state?locomotive=${encodeURIComponent(loco)}`, { cache: 'no-store' });
  if (!res.ok) {
    return null;
  }
  return res.json();
}
async function loadState(nextLocomotive, preloadedState = null, manualConfig = null){
  const loco = (nextLocomotive ?? getCurrentLoco()).trim();
  setStatus('Загрузка...');
  let loaded = preloadedState;
  if (!loaded) {
    loaded = await fetchStatePayload(loco);
  }
  if (!loaded) {
    setStatus('Не удалось загрузить данные');
    return;
  }
  if (manualConfig && !loaded.has_manual_meta) {
    loaded.wheel_pair_count = manualConfig.wheel_pair_count;
    loaded.section_count = manualConfig.section_count;
    const res = await fetch(`${API}/api/state`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json; charset=utf-8' },
      body: JSON.stringify({
        locomotive: loaded.locomotive,
        measurement_date: loaded.measurement_date,
        measurements: loaded.measurements,
        wheel_pair_count: loaded.wheel_pair_count,
        section_count: loaded.section_count,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      setStatus(err.error || 'Не удалось сохранить параметры локомотива');
      return;
    }
    loaded = await res.json();
  }
  state = loaded;
  locomotiveInputSource = 'loaded';
  state.locomotives = state.locomotives && state.locomotives.length ? state.locomotives : (LOCOMOTIVE_CHOICES || []);
  savedState = cloneState(state);
  canceledState = null;
  currentRepairType = state.repair_type || currentRepairType || '';
  savedRepairType = currentRepairType;
  canceledRepairType = '';
  document.getElementById('locomotive').value = state.locomotive || '';
  document.getElementById('measurementDate').value = state.measurement_date || '';
  renderLocoOptions();
  renderArchiveLocomotives();
  renderKpLocomotiveOptions();
  renderRepairOptions();
  renderMeta();
  renderTable();
  updateArchiveSortButton();
  await loadArchive();
  setDirty(false);
  setStatus('Готово');
}
async function maybeSwitchLocomotive(nextValue){
  if (initialLoadPromise) {
    await initialLoadPromise.catch(() => undefined);
  }
  const next = nextValue.trim();
  const current = state?.locomotive || '';
  if (!next) {
    const input = document.getElementById('locomotive');
    if (input) input.value = current;
    return;
  }
  if (dirty && current) {
    const ok = confirm('Есть несохранённые изменения. Сохранить перед сменой локомотива?');
    if (!ok) {
      document.getElementById('locomotive').value = current;
      return;
    }
    await saveDraft();
  }
  if (locomotiveInputSource === 'typed') {
    const preview = await fetchStatePayload(next);
    if (!preview) {
      document.getElementById('locomotive').value = current;
      setStatus('Не удалось загрузить данные локомотива');
      return;
    }
    if (preview.has_manual_meta) {
      await loadState(next, preview);
      return;
    }
    const manualConfig = await promptManualLocoCounts(next);
    if (!manualConfig) {
      document.getElementById('locomotive').value = current;
      return;
    }
    await loadState(next, preview, manualConfig);
    return;
  }
  const known = isKnownLocomotive(next);
  if (!known) {
    const preview = await fetchStatePayload(next);
    if (!preview) {
      document.getElementById('locomotive').value = current;
      setStatus('Не удалось загрузить данные локомотива');
      return;
    }
    if (!preview.has_manual_meta) {
      const manualConfig = await promptManualLocoCounts(next);
      if (!manualConfig) {
        document.getElementById('locomotive').value = current;
        return;
      }
      await loadState(next, preview, manualConfig);
      return;
    }
    await loadState(next, preview);
    return;
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
      wheel_pair_count: state.wheel_pair_count,
      section_count: state.section_count,
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
    wheel_pair_count: state.wheel_pair_count,
    section_count: state.section_count,
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
  renderKpLocomotiveOptions();
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
  renderKpLocomotiveOptions();
  renderRepairOptions();
  renderMeta();
  renderTable();
  setDirty(true);
  setStatus('Восстановлено');
  canceledState = null;
  canceledRepairType = '';
}

document.getElementById('locomotive').addEventListener('change', onLocomotiveCommit);
document.getElementById('locomotive').addEventListener('keydown', event => {
  if (event.key === 'Enter') {
    event.preventDefault();
    onLocomotiveCommit();
  }
});
document.getElementById('locomotive').addEventListener('focus', showLocoDropdown);
document.getElementById('locomotive').addEventListener('input', event => {
  locomotiveInputSource = 'typed';
  renderLocoDropdown(event.target.value);
});
document.getElementById('locomotive').addEventListener('blur', () => setTimeout(hideLocoDropdown, 150));
document.getElementById('locomotiveDropdown').addEventListener('mousedown', event => {
  const btn = event.target.closest('button[data-loco]');
  if (!btn) return;
  event.preventDefault();
  chooseLoco(btn.dataset.loco || '');
});
document.getElementById('measurementDate').addEventListener('change', onDateChange);
document.getElementById('repairType').addEventListener('change', onRepairChange);
document.getElementById('kpLocomotive').addEventListener('change', e => loadKpData(e.target.value));
document.getElementById('kpSearch').addEventListener('input', applyKpSearchFilter);
document.getElementById('archiveLocomotive').addEventListener('change', loadArchive);
document.getElementById('archiveSearch').addEventListener('input', loadArchive);
document.getElementById('saveBtn').style.display = CAN_EDIT ? '' : 'none';
updateHistoryButtons();
initialLoadPromise = loadState();
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
    with DB_LOCK, connect() as conn:
        loco_choices = load_locomotives(conn.cursor())
    return (
        HTML.replace("{{APP_PREFIX}}", APP_PREFIX)
        .replace("{{APP_VERSION}}", APP_VERSION)
        .replace("{{CAN_EDIT}}", "true" if role == "edit" else "false")
        .replace("{{LOCOMOTIVE_CHOICES}}", json.dumps(loco_choices, ensure_ascii=False))
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

        if route == "/api/kp-data":
            if not require_auth(self):
                return
            qs = parse_qs(parsed.query)
            locomotive = text(qs.get("locomotive", [""])[0]).strip()
            send_json(self, load_kp_view(locomotive))
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
                if payload.get("changes"):
                    result = update_archive_cells(payload)
                else:
                    result = save_archive(payload)
                if isinstance(result, tuple):
                    body, status = result
                    send_json(self, body, status)
                else:
                    send_json(self, result)
            except Exception as exc:
                send_json(self, {"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return

        if route == "/api/kp-data":
            if not require_auth(self, need_edit=True):
                return
            try:
                payload = json.loads(raw.decode("utf-8"))
                result = save_kp_data(payload)
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
