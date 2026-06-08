from __future__ import annotations

import datetime as dt
import base64
import hashlib
import hmac
import io
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
APP_VERSION = "web-zkp-1.54"
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
        _ensure_inventory_sync_columns(conn)
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
        existing_inventory_cols = {row[1] for row in cur.execute("PRAGMA table_info(inventory)").fetchall()}
        if "sort_order" not in existing_inventory_cols:
            cur.execute("ALTER TABLE inventory ADD COLUMN sort_order INT")
        if "updated_at" not in existing_inventory_cols:
            cur.execute("ALTER TABLE inventory ADD COLUMN updated_at INT")
            cur.execute("UPDATE inventory SET updated_at = 0 WHERE updated_at IS NULL")
        if "deleted_at" not in existing_inventory_cols:
            cur.execute("ALTER TABLE inventory ADD COLUMN deleted_at INT")
            cur.execute("UPDATE inventory SET deleted_at = 0 WHERE deleted_at IS NULL")
        if "wheel_pair_count" not in existing_inventory_cols:
            cur.execute("ALTER TABLE inventory ADD COLUMN wheel_pair_count INT")
        if "section_count" not in existing_inventory_cols:
            cur.execute("ALTER TABLE inventory ADD COLUMN section_count INT")
        if "eight_digit_number" not in existing_inventory_cols:
            cur.execute("ALTER TABLE inventory ADD COLUMN eight_digit_number TEXT")
        cur.execute("UPDATE inventory SET sort_order = rowid WHERE sort_order IS NULL OR sort_order <= 0")
        cur.executemany(
            "INSERT OR IGNORE INTO kp_norms_data(metric_key, label, condition, yellow_value, red_value) VALUES(?,?,?,?,?)",
            DEFAULT_NORMS,
        )
        conn.commit()


def _ensure_inventory_sync_columns(conn: sqlite3.Connection) -> None:
    columns = {text(row[1]).strip().lower() for row in conn.execute("PRAGMA table_info(inventory)").fetchall()}
    if "updated_at" not in columns:
        conn.execute("ALTER TABLE inventory ADD COLUMN updated_at INT NOT NULL DEFAULT 0")
    if "deleted_at" not in columns:
        conn.execute("ALTER TABLE inventory ADD COLUMN deleted_at INT NOT NULL DEFAULT 0")


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


def send_file(handler: BaseHTTPRequestHandler, data: bytes, filename: str, content_type: str) -> None:
    safe_filename = filename.replace('"', "").replace("\r", "").replace("\n", "")
    encoded = "".join(f"%{byte:02X}" for byte in safe_filename.encode("utf-8"))
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Content-Disposition", f'attachment; filename="{safe_filename}"; filename*=UTF-8\'\'{encoded}')
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
        "SELECT ser FROM inventory WHERE TRIM(COALESCE(num, ''))=? ORDER BY COALESCE(sort_order, 0) ASC, COALESCE(updated_at, y) DESC, y DESC, rowid DESC LIMIT 1",
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
    return load_inventory_records(cur, include_deleted=False)


def load_inventory_records(cur: sqlite3.Cursor, include_deleted: bool = False) -> list[dict[str, str]]:
    query = """
        SELECT y, ser, num, inv, COALESCE(sort_order, 0) AS sort_order, COALESCE(updated_at, 0) AS updated_at, COALESCE(deleted_at, 0) AS deleted_at, COALESCE(wheel_pair_count, 0) AS wheel_pair_count, COALESCE(section_count, 0) AS section_count, COALESCE(eight_digit_number, '') AS eight_digit_number
        FROM inventory
        WHERE TRIM(COALESCE(num, '')) <> ''
    """
    if not include_deleted:
        query += " AND COALESCE(deleted_at, 0) = 0"
    query += " ORDER BY COALESCE(sort_order, 0) ASC, COALESCE(updated_at, 0) DESC, rowid DESC"
    rows = cur.execute(query).fetchall()

    best_rows: dict[str, sqlite3.Row] = {}
    for row in rows:
        number = text(row["num"]).strip()
        if not number:
            continue
        series = normalize_text(row["ser"]).strip().upper()
        key = f"{series}|{number}"
        current = best_rows.get(key)
        if current is None:
            best_rows[key] = row
            continue
        current_rank = (
            int(current["updated_at"] or 0),
            int(current["deleted_at"] or 0),
            int(current["sort_order"] or 0),
            int(current["rowid"] or 0),
        )
        row_rank = (
            int(row["updated_at"] or 0),
            int(row["deleted_at"] or 0),
            int(row["sort_order"] or 0),
            int(row["rowid"] or 0),
        )
        if row_rank > current_rank:
            best_rows[key] = row

    result: list[dict[str, str]] = []
    for row in sorted(
        best_rows.values(),
        key=lambda item: (
            int(item["sort_order"] or 0),
            -int(item["updated_at"] or 0),
            -int(item["deleted_at"] or 0),
            normalize_text(item["ser"]).strip().upper(),
            text(item["num"]).strip(),
        ),
    ):
        number = text(row["num"]).strip()
        if not number:
            continue
        deleted_at = int(row["deleted_at"] or 0)
        if deleted_at > 0 and not include_deleted:
            continue
        series = normalize_text(row["ser"]).strip().upper()
        inv = text(row["inv"]).strip()
        sort_order = int(row["sort_order"] or 0)
        updated_at = int(row["updated_at"] or 0)
        wheel_pair_count = int(row["wheel_pair_count"] or 0)
        section_count = int(row["section_count"] or 0)
        eight_digit_number = text(row["eight_digit_number"]).strip()
        label = f"{series} {number}".strip()
        if inv:
            label = f"{label} (инв. {inv})"
        result.append(
            {
                "series": series,
                "number": number,
                "label": label,
                "sortOrder": sort_order,
                "updatedAt": updated_at,
                "deletedAt": deleted_at,
                "wheelPairCount": wheel_pair_count,
                "sectionCount": section_count,
                "eightDigitNumber": eight_digit_number,
            }
        )
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
        locomotive_record = next((item for item in locomotives if text(item.get("number")).strip() == locomotive), None)

        meta = None
        if locomotive:
            meta = cur.execute(
                "SELECT y, measurement_date, wheel_pair_count, section_count FROM input_meta WHERE locomotive=? ORDER BY y DESC LIMIT 1",
                (locomotive,),
            ).fetchone()

        measurement_date = dt.date.today().isoformat()
        year = dt.date.today().year
        if wheel_pair_count is None:
            wheel_pair_count = int(locomotive_record.get("wheelPairCount") or 0) if locomotive_record else 0
            if wheel_pair_count <= 0:
                wheel_pair_count = axis_count
        if section_count is None:
            section_count = int(locomotive_record.get("sectionCount") or 0) if locomotive_record else 0
            if section_count <= 0:
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


def delete_archive_measurement(payload: dict) -> dict:
    try:
        year = int(payload.get("year"))
        measurement_date = text(payload.get("measurement_date")).strip()
        locomotive = text(payload.get("locomotive")).strip()
        repair_type = text(payload.get("repair_type")).strip()
    except Exception:
        return {"error": "Некорректные данные для удаления архива."}, 400

    if not measurement_date or not locomotive or not repair_type:
        return {"error": "Не удалось определить замер для удаления."}, 400

    with DB_LOCK, connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM archive_data WHERE y=? AND measurement_date=? AND locomotive=? AND repair_type=?",
            (year, measurement_date, locomotive, repair_type),
        )
        deleted = cur.rowcount
        conn.commit()

    return {"ok": True, "deleted": deleted}


def load_norms_rows() -> list[dict[str, str | bool]]:
    default_keys = [item[0] for item in DEFAULT_NORMS]
    with DB_LOCK, connect() as conn:
        rows = conn.execute(
            "SELECT metric_key, label, condition, yellow_value, red_value FROM kp_norms_data ORDER BY rowid"
        ).fetchall()

    db_norms = {text(row["metric_key"]): row for row in rows}
    result: list[dict[str, str | bool]] = []
    for metric_key, label, condition, yellow, red in DEFAULT_NORMS:
        row = db_norms.get(metric_key)
        result.append(
            {
                "metric_key": metric_key,
                "label": label,
                "condition": text(row["condition"] if row else condition),
                "yellow_value": text(row["yellow_value"] if row else yellow),
                "red_value": text(row["red_value"] if row else red),
                "is_default": True,
            }
        )

    for row in rows:
        metric_key = text(row["metric_key"])
        if metric_key in default_keys:
            continue
        result.append(
            {
                "metric_key": metric_key,
                "label": text(row["label"]),
                "condition": text(row["condition"]),
                "yellow_value": text(row["yellow_value"]),
                "red_value": text(row["red_value"]),
                "is_default": False,
            }
        )
    return result


def save_norms_rows(payload: dict) -> dict:
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return {"error": "rows"}, HTTPStatus.BAD_REQUEST

    normalized: list[tuple[str, str, str, str, str]] = []
    seen: set[str] = set()
    default_keys = {item[0] for item in DEFAULT_NORMS}
    conditions = {"меньше или равно", "больше или равно"}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        metric_key = text(row.get("metric_key")).strip()
        label = text(row.get("label")).strip()
        condition = text(row.get("condition")).strip()
        yellow = text(row.get("yellow_value")).strip()
        red = text(row.get("red_value")).strip()
        if not label:
            continue
        if not metric_key:
            metric_key = f"custom_{index + 1}"
        if metric_key in seen:
            suffix = 2
            base_key = metric_key
            while f"{base_key}_{suffix}" in seen:
                suffix += 1
            metric_key = f"{base_key}_{suffix}"
        if condition not in conditions:
            condition = "меньше или равно"
        if metric_key in default_keys:
            default_label = next((item[1] for item in DEFAULT_NORMS if item[0] == metric_key), label)
            label = default_label
        seen.add(metric_key)
        normalized.append((metric_key, label, condition, yellow, red))

    with DB_LOCK, connect() as conn:
        conn.execute("DELETE FROM kp_norms_data")
        conn.executemany(
            """
            INSERT INTO kp_norms_data(metric_key, label, condition, yellow_value, red_value)
            VALUES(?,?,?,?,?)
            """,
            normalized,
        )
        conn.commit()

    return {"ok": True, "rows": load_norms_rows()}
def phone_json_number(value):
    raw = text(value).strip()
    if not raw:
        return None
    try:
        number = float(raw.replace(",", "."))
    except ValueError:
        return None
    return int(number) if number.is_integer() else number


def decode_phone_payload_text(raw_text: str) -> dict | None:
    raw_text = text(raw_text).strip()
    if not raw_text:
        return None
    try:
        decoded_bytes = base64.b64decode(raw_text.encode("utf-8"))
        decompressed = zlib.decompress(decoded_bytes)
        payload = json.loads(decompressed.decode("utf-8"))
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass
    try:
        payload = json.loads(raw_text)
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass
    return None


def require_qrcode():
    try:
        import qrcode
        from qrcode.image.svg import SvgImage
    except ImportError as exc:
        raise RuntimeError("Для QR нужен пакет qrcode.") from exc
    return qrcode, SvgImage


def build_phone_reference_payload(selected_numbers: list[str] | None = None) -> dict:
    selected = {text(number).strip() for number in (selected_numbers or []) if text(number).strip()}
    with DB_LOCK, connect() as conn:
        cur = conn.cursor()
        locomotives = load_inventory_records(cur, include_deleted=True)
        if selected:
            locomotives = [item for item in locomotives if item["number"] in selected]

        exported = []
        for loco in locomotives:
            number = loco["number"]
            series = loco.get("series", "")
            axis_count = locomotive_axis_count(series, number)
            kp_rows = cur.execute(
                "SELECT r, c, v FROM kp_data WHERE locomotive=? AND c IN (0, 1, 2, 3) ORDER BY r, c",
                (number,),
            ).fetchall()
            kp_values = {(int(row["r"]), int(row["c"])): text(row["v"]).strip() for row in kp_rows}
            wheel_pairs = []
            for row_index in range(axis_count):
                wheel_pairs.append(
                    {
                        "number": phone_json_number(kp_values.get((row_index, 0), str(row_index + 1))),
                        "axisNumber": phone_json_number(kp_values.get((row_index, 1), str(row_index + 1))),
                        "diameterLeft": phone_json_number(kp_values.get((row_index, 2), "")),
                        "diameterRight": phone_json_number(kp_values.get((row_index, 3), "")),
                    }
                )
            exported.append(
                {
                    "series": series,
                    "number": number,
                    "wheelPairCount": axis_count,
                    "wheelPairs": wheel_pairs,
                    "sortOrder": int(loco.get("sortOrder") or 0),
                    "updatedAt": int(loco.get("updatedAt") or 0),
                    "deletedAt": int(loco.get("deletedAt") or 0),
                }
            )

    return {
        "formatVersion": 2,
        "exportType": "referenceData",
        "exportedAt": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "locomotives": exported,
    }


def build_phone_archive_measurement_record(year_value, measurement_date, locomotive_value, repair_type_value, rows_by_index) -> dict | None:
    locomotive_value = text(locomotive_value).strip()
    repair_type_value = text(repair_type_value).strip()
    measurement_date = text(measurement_date).strip()
    if not locomotive_value or not repair_type_value or not measurement_date:
        return None

    with DB_LOCK, connect() as conn:
        cur = conn.cursor()
        series = series_for_locomotive(cur, locomotive_value)
        wheel_pair_count = locomotive_axis_count(series, locomotive_value)
        wheel_pairs = []
        for row_index in sorted(rows_by_index.keys()):
            if row_index < 2:
                continue
            values = rows_by_index.get(row_index, {})
            pair_number = row_index - 1
            left = {
                "flangeThickness": phone_json_number(values.get(4, "")),
                "flangeWear": phone_json_number(values.get(2, "")),
                "flangeSteepness": phone_json_number(values.get(6, "")),
                "bandageThickness": phone_json_number(values.get(8, "")),
                "bandageDiameter": phone_json_number(values.get(10, "")),
            }
            right = {
                "flangeThickness": phone_json_number(values.get(5, "")),
                "flangeWear": phone_json_number(values.get(3, "")),
                "flangeSteepness": phone_json_number(values.get(7, "")),
                "bandageThickness": phone_json_number(values.get(9, "")),
                "bandageDiameter": phone_json_number(values.get(11, "")),
            }
            wheel_pairs.append({"number": pair_number, "left": left, "right": right})

    return {
        "createdAt": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "measurementId": f"pc-{year_value}-{measurement_date}-{locomotive_value}-{repair_type_value}",
        "locomotive": {
            "series": series,
            "number": locomotive_value,
            "wheelPairCount": wheel_pair_count,
            "comment": "",
            "isNew": False,
        },
        "repairType": repair_type_value,
        "measurementDate": measurement_date,
        "wheelPairs": wheel_pairs,
        "source": "pc",
    }


def build_phone_archive_payload(selected_locomotives: list[str] | None = None, selected_period: tuple[str, str] | None = None) -> dict:
    locomotives_filter = {text(item).strip() for item in (selected_locomotives or []) if text(item).strip()}
    date_from = date_to = ""
    if selected_period:
        date_from, date_to = selected_period
    with DB_LOCK, connect() as conn:
        query = """
            SELECT y, measurement_date, locomotive, repair_type, r, c, v
            FROM archive_data
            WHERE TRIM(COALESCE(measurement_date, '')) <> ''
        """
        params: list[str] = []
        if locomotives_filter:
            placeholders = ",".join("?" for _ in locomotives_filter)
            query += f" AND locomotive IN ({placeholders})"
            params.extend(sorted(locomotives_filter))
        if date_from:
            query += " AND measurement_date >= ?"
            params.append(date_from)
        if date_to:
            query += " AND measurement_date <= ?"
            params.append(date_to)
        query += " ORDER BY y DESC, measurement_date, locomotive, repair_type, r, c"
        rows = conn.execute(query, params).fetchall()

    grouped: dict[tuple[int, str, str, str], dict[int, dict[int, str]]] = {}
    for row in rows:
        r = int(row["r"])
        if r < 2:
            continue
        key = (int(row["y"] or 0), text(row["measurement_date"]), text(row["locomotive"]), text(row["repair_type"]))
        grouped.setdefault(key, {})
        grouped[key].setdefault(r, {})[int(row["c"])] = text(row["v"])

    archive = []
    for (year, measurement_date, locomotive, repair_type), values_by_row in grouped.items():
        record = build_phone_archive_measurement_record(year, measurement_date, locomotive, repair_type, values_by_row)
        if record:
            archive.append(record)

    return {
        "formatVersion": 1,
        "exportType": "archiveData",
        "exportedAt": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "archive": archive,
    }


def build_phone_qr_frames(payload: dict) -> list[str]:
    qrcode, SvgImage = require_qrcode()
    json_data = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    compressed = zlib.compress(json_data.encode("utf-8"), level=9)
    base64_str = base64.b64encode(compressed).decode("utf-8")
    chunk_size = 400
    chunks = [base64_str[i : i + chunk_size] for i in range(0, len(base64_str), chunk_size)] or [""]
    frames = []
    for index, chunk in enumerate(chunks):
        frame_header = f"{index + 1:02d}/{len(chunks):02d}|{chunk}"
        qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=10, border=4)
        qr.add_data(frame_header)
        qr.make(fit=True)
        image = qr.make_image(image_factory=SvgImage)
        buf = io.BytesIO()
        image.save(buf)
        frames.append("data:image/svg+xml;base64," + base64.b64encode(buf.getvalue()).decode("ascii"))
    return frames


def build_phone_export_payload(kind: str, selected_locomotives: list[str] | None = None, selected_period: tuple[str, str] | None = None) -> dict:
    kind = text(kind).strip().lower()
    if kind == "reference":
        return build_phone_reference_payload(selected_locomotives)
    return build_phone_archive_payload(selected_locomotives, selected_period)


def upsert_inventory_locomotive(
    cur: sqlite3.Cursor,
    series: str,
    loco_number: str,
    wheel_pair_count: int,
    *,
    sort_order: int = 0,
    deleted_at: int = 0,
) -> None:
    series = text(series).strip().upper()
    loco_number = text(loco_number).strip()
    if not loco_number:
        return
    year = dt.date.today().year
    now_ms = int(dt.datetime.now().timestamp() * 1000)
    existing = cur.execute(
        "SELECT y, ser, num, inv, COALESCE(sort_order, 0) AS sort_order, COALESCE(updated_at, 0) AS updated_at, COALESCE(deleted_at, 0) AS deleted_at "
        "FROM inventory WHERE UPPER(TRIM(COALESCE(num, ''))) = UPPER(TRIM(?)) ORDER BY COALESCE(updated_at, 0) DESC, COALESCE(deleted_at, 0) DESC, COALESCE(sort_order, 0) ASC, rowid DESC LIMIT 1",
        (loco_number,),
    ).fetchone()
    inv = text(existing["inv"]).strip() if existing else ""
    sort_order_value = int(sort_order or 0)
    if existing:
        series = series or text(existing["ser"]).strip().upper()
        if sort_order_value <= 0:
            sort_order_value = int(existing["sort_order"] or 0)
    if sort_order_value <= 0:
        max_row = cur.execute(
            "SELECT COALESCE(MAX(sort_order), 0) AS max_sort_order FROM inventory"
        ).fetchone()
        sort_order_value = int(max_row["max_sort_order"] or 0) + 1
    cur.execute(
        "INSERT OR REPLACE INTO inventory (y, ser, num, inv, sort_order, updated_at, deleted_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            year,
            series,
            loco_number,
            inv,
            sort_order_value,
            now_ms,
            int(deleted_at or 0),
        ),
    )
    if int(deleted_at or 0) <= 0:
        for index in range(max(1, int(wheel_pair_count or 1))):
            cur.execute("INSERT OR IGNORE INTO kp_data (locomotive, r, c, v) VALUES (?, ?, 0, ?)", (loco_number, index, str(index + 1)))
            cur.execute("INSERT OR IGNORE INTO kp_data (locomotive, r, c, v) VALUES (?, ?, 1, ?)", (loco_number, index, str(index + 1)))


def ensure_phone_locomotive(cur: sqlite3.Cursor, series: str, loco_number: str, wheel_pair_count: int) -> None:
    loco_number = text(loco_number).strip()
    if not loco_number:
        return
    existing = cur.execute(
        "SELECT inv, COALESCE(wheel_pair_count, 0) AS wheel_pair_count, COALESCE(section_count, 0) AS section_count, COALESCE(eight_digit_number, '') AS eight_digit_number, COALESCE(sort_order, 0) AS sort_order, COALESCE(deleted_at, 0) AS deleted_at "
        "FROM inventory WHERE UPPER(TRIM(COALESCE(num, ''))) = UPPER(TRIM(?)) LIMIT 1",
        (loco_number,),
    ).fetchone()
    if existing and int(existing["deleted_at"] or 0) > 0:
        return
    if existing:
        upsert_inventory_locomotive(
            cur,
            text(series).strip().upper(),
            loco_number,
            inv=text(existing["inv"]).strip(),
            wheel_pair_count=int(existing["wheel_pair_count"] or 0),
            section_count=int(existing["section_count"] or 0),
            eight_digit_number=text(existing["eight_digit_number"]).strip(),
            sort_order=int(existing["sort_order"] or 0),
            deleted_at=0,
        )
        return
    upsert_inventory_locomotive(
        cur,
        text(series).strip().upper(),
        loco_number,
        wheel_pair_count=wheel_pair_count,
        section_count=default_section_count(wheel_pair_count),
        deleted_at=0,
    )


def phone_measurement_missing_fields(payload: dict) -> list[str]:
    missing = []

    def has_value(value):
        if value is None:
            return False
        if isinstance(value, str):
            return value.strip() != ""
        return True

    if not has_value(payload.get("formatVersion")):
        missing.append("formatVersion")
    if not has_value(payload.get("createdAt")):
        missing.append("createdAt")
    if not has_value(payload.get("measurementId")):
        missing.append("measurementId")
    if not has_value(payload.get("repairType")):
        missing.append("repairType")
    if not has_value(payload.get("measurementDate")):
        missing.append("measurementDate")

    locomotive = payload.get("locomotive")
    if not isinstance(locomotive, dict):
        missing.append("locomotive")
        locomotive = {}

    for key in ("series", "number", "wheelPairCount"):
        if not has_value(locomotive.get(key)):
            missing.append(f"locomotive.{key}")

    wheel_pairs = payload.get("wheelPairs")
    if not isinstance(wheel_pairs, list) or not wheel_pairs:
        missing.append("wheelPairs")
        return missing

    side_fields = ("flangeThickness", "flangeWear", "flangeSteepness", "bandageThickness")
    for pair_index, pair in enumerate(wheel_pairs, start=1):
        if not isinstance(pair, dict):
            missing.append(f"wheelPairs[{pair_index}]")
            continue
        if not has_value(pair.get("number")):
            missing.append(f"wheelPairs[{pair_index}].number")
        for side_name in ("left", "right"):
            side = pair.get(side_name)
            if not isinstance(side, dict):
                missing.append(f"wheelPairs[{pair_index}].{side_name}")
                continue
            for field_name in side_fields:
                if not has_value(side.get(field_name)):
                    missing.append(f"wheelPairs[{pair_index}].{side_name}.{field_name}")

    return missing


def phone_archive_rows_from_payload(
    measurement_date: str,
    loco_number: str,
    repair_type: str,
    wheel_pairs: list[dict],
    kp_values: dict[tuple[int, int], str] | None = None,
) -> list[tuple[int, str, str, str, int, int, str]]:
    year_value = int(measurement_date[:4]) if len(measurement_date) >= 4 and measurement_date[:4].isdigit() else dt.date.today().year
    rows: list[tuple[int, str, str, str, int, int, str]] = []
    kp_values = kp_values or {}

    def parse_float(v):
        if v is None:
            return None
        try:
            return float(text(v).replace(",", "."))
        except ValueError:
            return None

    axis_count = len(wheel_pairs)
    for pair in wheel_pairs:
        pair_number = int(pair.get("number") or 1)
        kp_row_index = pair_number - 1
        table_row = pair_number + 1
        section_value = "1" if axis_count == 6 else str(((pair_number - 1) // 4) + 1)
        left = pair.get("left") or {}
        right = pair.get("right") or {}

        left_thick = parse_float(left.get("bandageThickness"))
        right_thick = parse_float(right.get("bandageThickness"))

        left_diam = left.get("bandageDiameter")
        if left_diam is None or text(left_diam).strip() == "":
            kp_left = parse_float(kp_values.get((kp_row_index, 2), ""))
            if kp_left is not None and left_thick is not None:
                left_diam = str(int(round(kp_left + left_thick * 2)))
            else:
                left_diam = ""

        right_diam = right.get("bandageDiameter")
        if right_diam is None or text(right_diam).strip() == "":
            kp_right = parse_float(kp_values.get((kp_row_index, 3), ""))
            if kp_right is not None and right_thick is not None:
                right_diam = str(int(round(kp_right + right_thick * 2)))
            else:
                right_diam = ""

        values = {
            0: section_value,
            1: str(pair_number),
            2: phone_json_number(left.get("flangeWear")),
            3: phone_json_number(right.get("flangeWear")),
            4: phone_json_number(left.get("flangeThickness")),
            5: phone_json_number(right.get("flangeThickness")),
            6: phone_json_number(left.get("flangeSteepness")),
            7: phone_json_number(right.get("flangeSteepness")),
            8: phone_json_number(left.get("bandageThickness")),
            9: phone_json_number(right.get("bandageThickness")),
            10: phone_json_number(left_diam),
            11: phone_json_number(right_diam),
        }

        for col, value in values.items():
            if value != "" and value is not None:
                rows.append((year_value, measurement_date, loco_number, repair_type, table_row, col, text(value)))

    return rows


def import_phone_reference_payload(payload: dict) -> dict:
    locomotives = payload.get("locomotives", [])
    if not isinstance(locomotives, list) or not locomotives:
        return {"error": "В файле справочника нет локомотивов."}, HTTPStatus.BAD_REQUEST

    grouped: dict[str, dict[str, object]] = {}
    for loco in locomotives:
        if not isinstance(loco, dict):
            continue
        series = text(loco.get("series")).strip().upper()
        number = text(loco.get("number")).strip()
        if not number:
            continue
        key = f"{series}|{number}"
        candidate = {
            "series": series,
            "number": number,
            "sortOrder": int(loco.get("sortOrder") or 0),
            "updatedAt": int(loco.get("updatedAt") or 0),
            "deletedAt": int(loco.get("deletedAt") or 0),
            "wheelPairCount": int(loco.get("wheelPairCount") or 6),
            "wheelPairs": loco.get("wheelPairs", []),
        }
        current = grouped.get(key)
        if current is None or (
            candidate["updatedAt"],
            candidate["deletedAt"],
            candidate["sortOrder"],
        ) > (
            current["updatedAt"],
            current["deletedAt"],
            current["sortOrder"],
        ):
            grouped[key] = candidate

    imported_count = 0
    with DB_LOCK, connect() as conn:
        cur = conn.cursor()
        cur.execute("BEGIN")
        for loco in grouped.values():
            series = text(loco["series"]).strip().upper()
            number = text(loco["number"]).strip()
            sort_order = int(loco["sortOrder"] or 0)
            updated_at = int(loco["updatedAt"] or 0)
            deleted_at = int(loco["deletedAt"] or 0)
            wheel_pair_count = int(loco["wheelPairCount"] or 6)
            upsert_inventory_locomotive(
                cur,
                series,
                number,
                wheel_pair_count=wheel_pair_count,
                sort_order=sort_order,
                deleted_at=deleted_at,
            )
            wheel_pairs = loco.get("wheelPairs", [])
            if not isinstance(wheel_pairs, list):
                continue
            if deleted_at > 0:
                cur.execute("DELETE FROM kp_data WHERE locomotive=?", (number,))
                imported_count += 1
                continue
            cur.execute("DELETE FROM kp_data WHERE locomotive=?", (number,))
            for pair in wheel_pairs:
                if not isinstance(pair, dict):
                    continue
                try:
                    r = int(pair.get("number") or 1) - 1
                except Exception:
                    continue
                kp_number = text(pair.get("number") or r + 1)
                axis_number = text(pair.get("axisNumber") or kp_number)
                diameter_left = text(pair.get("diameterLeft") or "").strip()
                diameter_right = text(pair.get("diameterRight") or "").strip()
                cur.execute("INSERT OR REPLACE INTO kp_data (locomotive, r, c, v) VALUES (?, ?, 0, ?)", (number, r, kp_number))
                cur.execute("INSERT OR REPLACE INTO kp_data (locomotive, r, c, v) VALUES (?, ?, 1, ?)", (number, r, axis_number))
                if diameter_left:
                    cur.execute("INSERT OR REPLACE INTO kp_data (locomotive, r, c, v) VALUES (?, ?, 2, ?)", (number, r, diameter_left))
                if diameter_right:
                    cur.execute("INSERT OR REPLACE INTO kp_data (locomotive, r, c, v) VALUES (?, ?, 3, ?)", (number, r, diameter_right))
            imported_count += 1
        conn.commit()

    return {"ok": True, "imported_count": imported_count}


def import_phone_archive_payload(payload: dict) -> dict:
    archive_items = payload.get("archive", [])
    if not isinstance(archive_items, list) or not archive_items:
        return {"error": "В архивном JSON нет данных."}, HTTPStatus.BAD_REQUEST

    imported_measurements = 0
    imported_cells = 0
    with DB_LOCK, connect() as conn:
        cur = conn.cursor()
        cur.execute("BEGIN")
        for item in archive_items:
            if not isinstance(item, dict):
                continue
            locomotive = item.get("locomotive") or {}
            if not isinstance(locomotive, dict):
                continue
            series = text(locomotive.get("series")).strip()
            loco_number = text(locomotive.get("number")).strip()
            measurement_date = text(item.get("measurementDate")).strip()
            repair_type = text(item.get("repairType")).strip()
            wheel_pairs = item.get("wheelPairs") or []
            if not loco_number or not measurement_date or not repair_type or not isinstance(wheel_pairs, list) or not wheel_pairs:
                continue
            wheel_pair_count = int(locomotive.get("wheelPairCount") or len(wheel_pairs))
            ensure_phone_locomotive(cur, series, loco_number, wheel_pair_count)
            kp_rows = cur.execute("SELECT r, c, v FROM kp_data WHERE locomotive=?", (loco_number,)).fetchall()
            kp_values = {(int(r), int(c)): text(v) for r, c, v in kp_rows}
            rows = phone_archive_rows_from_payload(measurement_date, loco_number, repair_type, wheel_pairs, kp_values)
            if not rows:
                continue
            year_value = int(measurement_date[:4]) if len(measurement_date) >= 4 and measurement_date[:4].isdigit() else dt.date.today().year
            cur.execute(
                "DELETE FROM archive_data WHERE y=? AND measurement_date=? AND locomotive=? AND repair_type=?",
                (year_value, measurement_date, loco_number, repair_type),
            )
            cur.executemany(
                "INSERT OR REPLACE INTO archive_data (y, measurement_date, locomotive, repair_type, r, c, v) VALUES (?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            imported_measurements += 1
            imported_cells += len(rows)
        conn.commit()

    return {"ok": True, "imported_measurements": imported_measurements, "imported_cells": imported_cells}


def import_phone_measurement_payload(payload: dict) -> dict:
    if not isinstance(payload, dict):
        return {"error": "Некорректный JSON."}, HTTPStatus.BAD_REQUEST

    missing = phone_measurement_missing_fields(payload)
    if missing:
        return {"error": "В замере не заполнены обязательные данные.", "missing": missing[:20]}, HTTPStatus.BAD_REQUEST

    locomotive = payload.get("locomotive") or {}
    series = text(locomotive.get("series")).strip()
    loco_number = text(locomotive.get("number")).strip()
    measurement_date = text(payload.get("measurementDate")).strip()
    repair_type = text(payload.get("repairType")).strip()
    wheel_pairs = payload.get("wheelPairs") or []
    wheel_pair_count = int(locomotive.get("wheelPairCount") or len(wheel_pairs))

    with DB_LOCK, connect() as conn:
        cur = conn.cursor()
        cur.execute("BEGIN")
        ensure_phone_locomotive(cur, series, loco_number, wheel_pair_count)
        kp_rows = cur.execute("SELECT r, c, v FROM kp_data WHERE locomotive=?", (loco_number,)).fetchall()
        kp_values = {(int(r), int(c)): text(v) for r, c, v in kp_rows}
        rows = phone_archive_rows_from_payload(measurement_date, loco_number, repair_type, wheel_pairs, kp_values)
        if not rows:
            return {"error": "Не удалось собрать строки замера."}, HTTPStatus.BAD_REQUEST
        year_value = int(measurement_date[:4]) if len(measurement_date) >= 4 and measurement_date[:4].isdigit() else dt.date.today().year
        cur.execute(
            "DELETE FROM archive_data WHERE y=? AND measurement_date=? AND locomotive=? AND repair_type=?",
            (year_value, measurement_date, loco_number, repair_type),
        )
        cur.executemany(
            "INSERT OR REPLACE INTO archive_data (y, measurement_date, locomotive, repair_type, r, c, v) VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()

    return {"ok": True, "imported_measurements": 1, "imported_cells": len(rows)}


def import_phone_payload(payload: dict) -> dict:
    if not isinstance(payload, dict):
        return {"error": "Некорректный JSON."}, HTTPStatus.BAD_REQUEST
    if payload.get("exportType") == "archiveData" or "archive" in payload:
        return import_phone_archive_payload(payload)
    if payload.get("exportType") == "referenceData" or "locomotives" in payload:
        return import_phone_reference_payload(payload)
    if int(payload.get("formatVersion", 0) or 0) == 1:
        return import_phone_measurement_payload(payload)
    return {"error": "Нераспознанный формат телефона."}, HTTPStatus.BAD_REQUEST


def require_openpyxl():
    try:
        from openpyxl import Workbook, load_workbook
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
        from openpyxl.worksheet.datavalidation import DataValidation
    except ImportError as exc:
        raise RuntimeError("Для работы с Excel нужен пакет openpyxl.") from exc
    return Workbook, load_workbook, Alignment, Border, Font, PatternFill, Side, DataValidation


def archive_excel_template_bytes() -> bytes:
    Workbook, _, Alignment, Border, Font, PatternFill, Side, DataValidation = require_openpyxl()
    wb = Workbook()
    ws = wb.active
    ws.title = "Архив"
    ws.append(ARCHIVE_EXCEL_HEADERS)

    header_fill = PatternFill("solid", fgColor="D9EAF7")
    thin = Side(style="thin", color="BFBFBF")
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = Border(left=thin, right=thin, top=thin, bottom=thin)

    widths = [14, 12, 14, 12, 10, 10, 14, 14, 18, 18, 18, 18, 18, 18, 18, 18]
    for index, width in enumerate(widths, start=1):
        ws.column_dimensions[ws.cell(1, index).column_letter].width = width

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = "A1:P1"
    ws.row_dimensions[1].height = 34

    notes = wb.create_sheet("Памятка")
    notes["A1"] = "Как заполнять шаблон"
    notes["A1"].font = Font(bold=True, size=14)
    notes["A3"] = "1. Каждая строка = одна колесная пара."
    notes["A4"] = "2. Для 6 КП просто заполните 6 строк подряд с одинаковыми датой, локомотивом и видом ремонта."
    notes["A5"] = "3. Для импорта важны дата замера, локомотив, вид ремонта, номер КП и значения по сторонам КП."
    notes["A6"] = "4. Для чисел можно использовать запятую или точку."
    notes["A7"] = "5. Пустые обязательные поля импорт не примет."
    notes.column_dimensions["A"].width = 120

    repair_dv = DataValidation(type="list", formula1='"ТО-1,ТО-2,ТО-3,ТР-1,ТР-2,ТР-3"', allow_blank=True)
    ws.add_data_validation(repair_dv)
    repair_dv.add("C2:C5000")

    output = io.BytesIO()
    wb.save(output)
    return output.getvalue()


def parse_excel_date(value) -> str:
    if value is None:
        return ""
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    raw = text(value).strip()
    if not raw:
        return ""
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y", "%Y/%m/%d"):
        try:
            return dt.datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            pass
    return raw


def format_excel_export_date(value: str) -> str:
    raw = text(value).strip()
    if not raw:
        return ""
    try:
        return dt.datetime.strptime(raw, "%Y-%m-%d").strftime("%d.%m.%Y")
    except ValueError:
        return raw


def parse_excel_int(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raw = text(value).strip().replace(",", ".")
    if not raw:
        return None
    try:
        number = float(raw)
    except ValueError:
        return None
    return int(number) if number.is_integer() else None


def parse_float_value(value) -> float | None:
    raw = text(value).strip().replace(",", ".")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def excel_cell_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    return text(value).strip()


def excel_num_text(value) -> str:
    raw = text(value).strip()
    return raw.replace(".", ",") if raw else ""


def normalize_excel_header(value) -> str:
    return "".join(ch for ch in text(value).strip().lower() if ch.isalnum())


def archive_export_locomotives(cur: sqlite3.Cursor) -> list[str]:
    rows = cur.execute(
        "SELECT DISTINCT locomotive FROM archive_data WHERE TRIM(COALESCE(locomotive, '')) <> '' ORDER BY locomotive"
    ).fetchall()
    return [text(row["locomotive"]).strip() for row in rows if text(row["locomotive"]).strip()]


def build_archive_export_rows(selected_locomotives: list[str] | None = None, date_from: str = "", date_to: str = "") -> list[list[str]]:
    locomotives_filter = {text(item).strip() for item in selected_locomotives or [] if text(item).strip()}
    date_from = text(date_from).strip()
    date_to = text(date_to).strip()
    query = """
        SELECT y, measurement_date, locomotive, repair_type, r, c, v
        FROM archive_data
        WHERE TRIM(COALESCE(measurement_date, '')) <> ''
    """
    params: list[str] = []
    if locomotives_filter:
        query += f" AND locomotive IN ({','.join('?' for _ in locomotives_filter)})"
        params.extend(sorted(locomotives_filter))
    if date_from:
        query += " AND measurement_date >= ?"
        params.append(date_from)
    if date_to:
        query += " AND measurement_date <= ?"
        params.append(date_to)
    query += " ORDER BY y, measurement_date, locomotive, repair_type, r, c"

    with DB_LOCK, connect() as conn:
        cur = conn.cursor()
        rows = cur.execute(query, params).fetchall()
        grouped: dict[tuple[int, str, str, str, int], list[str]] = {}
        for row in rows:
            r = int(row["r"])
            if r < 2:
                continue
            key = (int(row["y"] or 0), text(row["measurement_date"]), text(row["locomotive"]), text(row["repair_type"]), r)
            grouped.setdefault(key, [""] * 12)
            c = int(row["c"])
            if 0 <= c < 12:
                grouped[key][c] = text(row["v"])

        kp_cache: dict[str, dict[tuple[int, int], str]] = {}
        export_rows: list[list[str]] = []
        for (_, measurement_date, locomotive, repair_type, r), values in sorted(grouped.items()):
            series = series_for_locomotive(cur, locomotive)
            if locomotive not in kp_cache:
                kp_rows = cur.execute(
                    "SELECT r, c, v FROM kp_data WHERE locomotive=? AND c IN (2, 3)",
                    (locomotive,),
                ).fetchall()
                kp_cache[locomotive] = {(int(row["r"]), int(row["c"])): text(row["v"]).strip() for row in kp_rows}

            kp_values = kp_cache.get(locomotive, {})
            kp_row_index = r - 1
            bandage_left = values[8] or ""
            bandage_right = values[9] or ""
            diameter_left = values[10] or ""
            diameter_right = values[11] or ""

            if not diameter_left:
                kp_left = parse_float_value(kp_values.get((kp_row_index, 2), ""))
                bandage_left_value = parse_float_value(bandage_left)
                if kp_left is not None and bandage_left_value is not None:
                    diameter_left = str(int(round(kp_left + bandage_left_value * 2)))
            if not diameter_right:
                kp_right = parse_float_value(kp_values.get((kp_row_index, 3), ""))
                bandage_right_value = parse_float_value(bandage_right)
                if kp_right is not None and bandage_right_value is not None:
                    diameter_right = str(int(round(kp_right + bandage_right_value * 2)))

            export_rows.append(
                [
                    format_excel_export_date(measurement_date),
                    locomotive,
                    repair_type,
                    series,
                    values[0] or "1",
                    values[1] or str(r - 1),
                    excel_num_text(values[2]),
                    excel_num_text(values[3]),
                    excel_num_text(values[4]),
                    excel_num_text(values[5]),
                    excel_num_text(values[6]),
                    excel_num_text(values[7]),
                    excel_num_text(bandage_left),
                    excel_num_text(bandage_right),
                    excel_num_text(diameter_left),
                    excel_num_text(diameter_right),
                ]
            )
        return export_rows


def archive_excel_export_bytes(selected_locomotives: list[str] | None = None, date_from: str = "", date_to: str = "") -> tuple[bytes, int]:
    _, _, Alignment, _, _, _, _, _ = require_openpyxl()
    from openpyxl import load_workbook

    template = archive_excel_template_bytes()
    wb = load_workbook(io.BytesIO(template))
    ws = wb.active
    rows = build_archive_export_rows(selected_locomotives, date_from, date_to)
    out_row = 2
    for row_data in rows:
        for col, value in enumerate(row_data, start=1):
            cell = ws.cell(out_row, col, value)
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        out_row += 1
    ws.auto_filter.ref = f"A1:P{max(1, out_row - 1)}"
    output = io.BytesIO()
    wb.save(output)
    return output.getvalue(), len(rows)


def upsert_inventory_locomotive(
    cur: sqlite3.Cursor,
    series: str,
    locomotive: str,
    inv: str = "",
    wheel_pair_count: int = 0,
    section_count: int = 0,
    eight_digit_number: str = "",
    sort_order: int = 0,
    updated_at: int | None = None,
    deleted_at: int | None = None,
) -> None:
    locomotive = text(locomotive).strip()
    if not locomotive:
        return
    series = text(series).strip().upper()
    inv = text(inv).strip()
    eight_digit_number = text(eight_digit_number).strip()
    year = dt.date.today().year
    sort_order_value = int(sort_order or 0)
    updated_at = int(updated_at or int(dt.datetime.now().timestamp() * 1000))
    if sort_order_value <= 0:
        existing = cur.execute(
            "SELECT COALESCE(sort_order, 0) AS sort_order FROM inventory WHERE UPPER(TRIM(COALESCE(num, ''))) = UPPER(TRIM(?)) ORDER BY COALESCE(updated_at, 0) DESC, COALESCE(deleted_at, 0) DESC, COALESCE(sort_order, 0) ASC, rowid DESC LIMIT 1",
            (locomotive,),
        ).fetchone()
        if existing:
            sort_order_value = int(existing["sort_order"] or 0)
    if sort_order_value <= 0:
        max_row = cur.execute(
            "SELECT COALESCE(MAX(sort_order), 0) AS max_sort_order FROM inventory"
        ).fetchone()
        sort_order_value = int(max_row["max_sort_order"] or 0) + 1
    exact = cur.execute(
        "SELECT rowid, inv, COALESCE(sort_order, 0) AS sort_order, COALESCE(wheel_pair_count, 0) AS wheel_pair_count, COALESCE(section_count, 0) AS section_count, COALESCE(eight_digit_number, '') AS eight_digit_number, COALESCE(deleted_at, 0) AS deleted_at "
        "FROM inventory WHERE y=? AND UPPER(TRIM(COALESCE(ser, ''))) = UPPER(TRIM(?)) AND TRIM(COALESCE(num, ''))=? "
        "ORDER BY COALESCE(updated_at, 0) DESC, COALESCE(deleted_at, 0) DESC, rowid DESC LIMIT 1",
        (year, series, locomotive),
    ).fetchone()
    if exact:
        if sort_order_value <= 0:
            sort_order_value = int(exact["sort_order"] or 0)
        if not wheel_pair_count:
            wheel_pair_count = int(exact["wheel_pair_count"] or 0)
        if not section_count:
            section_count = int(exact["section_count"] or 0)
        if not eight_digit_number:
            eight_digit_number = text(exact["eight_digit_number"]).strip()
        if deleted_at is None:
            deleted_at = int(exact["deleted_at"] or 0)
        cur.execute(
            """
            UPDATE inventory
            SET ser=?, num=?, inv=?, wheel_pair_count=?, section_count=?, eight_digit_number=?, sort_order=?, updated_at=?, deleted_at=?
            WHERE rowid=?
            """,
            (series, locomotive, inv, wheel_pair_count or None, section_count or None, eight_digit_number, sort_order_value, updated_at, int(deleted_at or 0), int(exact["rowid"])),
        )
        cur.execute(
            "DELETE FROM inventory WHERE y=? AND UPPER(TRIM(COALESCE(ser, ''))) = UPPER(TRIM(?)) AND TRIM(COALESCE(num, ''))=? AND rowid<>?",
            (year, series, locomotive, int(exact["rowid"])),
        )
        return
    if deleted_at is None:
        deleted_at = 0
    cur.execute(
        """
        INSERT INTO inventory (y, ser, num, inv, wheel_pair_count, section_count, eight_digit_number, sort_order, updated_at, deleted_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (year, series, locomotive, inv, wheel_pair_count or None, section_count or None, eight_digit_number, sort_order_value, updated_at, int(deleted_at or 0)),
    )


def phone_reference_export_payload() -> dict:
    with DB_LOCK, connect() as conn:
        cur = conn.cursor()
        locomotives = load_inventory_records(cur, include_deleted=True)
        kp_rows = cur.execute(
            "SELECT locomotive, r, c, v FROM kp_data WHERE TRIM(COALESCE(locomotive, '')) <> '' ORDER BY locomotive, r, c"
        ).fetchall()

    kp_map: dict[str, dict[int, dict[int, str]]] = {}
    for row in kp_rows:
        locomotive = text(row["locomotive"]).strip()
        kp_map.setdefault(locomotive, {}).setdefault(int(row["r"]), {})[int(row["c"])] = text(row["v"])

    payload_locomotives: list[dict[str, object]] = []
    for locomotive in locomotives:
        number = text(locomotive.get("number")).strip()
        series = text(locomotive.get("series")).strip()
        wheel_pair_count = max(1, locomotive_axis_count(series, number))
        row_map = kp_map.get(number, {})
        wheel_pairs: list[dict[str, object]] = []
        for pair_index in range(wheel_pair_count):
            row = row_map.get(pair_index, {})
            wheel_pairs.append(
                {
                    "number": pair_index + 1,
                    "axisNumber": parse_excel_int(row.get(1, "")) or (pair_index + 1),
                    "diameterLeft": parse_float_value(row.get(2, "")),
                    "diameterRight": parse_float_value(row.get(3, "")),
                }
            )
        payload_locomotives.append(
            {
                "series": series,
                "number": number,
                "wheelPairCount": wheel_pair_count,
                "eightDigitNumber": text(locomotive.get("eightDigitNumber") or ""),
                "sortOrder": int(locomotive.get("sortOrder") or 0),
                "updatedAt": int(locomotive.get("updatedAt") or 0),
                "deletedAt": int(locomotive.get("deletedAt") or 0),
                "wheelPairs": wheel_pairs,
            }
        )

    return {
        "formatVersion": 2,
        "exportType": "referenceData",
        "exportedAt": dt.datetime.now().isoformat(timespec="seconds"),
        "locomotives": payload_locomotives,
    }


def phone_archive_export_payload(selected_locomotives: list[str] | None = None, date_from: str = "", date_to: str = "") -> dict:
    locomotives_filter = {text(item).strip() for item in selected_locomotives or [] if text(item).strip()}
    date_from = text(date_from).strip()
    date_to = text(date_to).strip()
    query = """
        SELECT y, measurement_date, locomotive, repair_type, r, c, v
        FROM archive_data
        WHERE TRIM(COALESCE(measurement_date, '')) <> ''
    """
    params: list[str] = []
    if locomotives_filter:
        query += f" AND locomotive IN ({','.join('?' for _ in locomotives_filter)})"
        params.extend(sorted(locomotives_filter))
    if date_from:
        query += " AND measurement_date >= ?"
        params.append(date_from)
    if date_to:
        query += " AND measurement_date <= ?"
        params.append(date_to)
    query += " ORDER BY y, measurement_date, locomotive, repair_type, r, c"

    with DB_LOCK, connect() as conn:
        cur = conn.cursor()
        rows = cur.execute(query, params).fetchall()
        grouped: dict[tuple[int, str, str, str], dict[int, list[str]]] = {}
        series_cache: dict[str, str] = {}
        kp_cache: dict[str, dict[tuple[int, int], str]] = {}
        for row in rows:
            key = (
                int(row["y"] or 0),
                text(row["measurement_date"]).strip(),
                text(row["locomotive"]).strip(),
                text(row["repair_type"]).strip(),
            )
            grouped.setdefault(key, {})[int(row["r"])] = grouped.setdefault(key, {}).get(int(row["r"]), [""] * 12)
            grouped[key][int(row["r"])][int(row["c"])] = text(row["v"])

        archive_items: list[dict[str, object]] = []
        for (year, measurement_date, locomotive, repair_type), rows_by_r in sorted(grouped.items()):
            series = series_cache.get(locomotive)
            if series is None:
                series = series_for_locomotive(cur, locomotive)
                series_cache[locomotive] = series
            wheel_pair_count = max(1, locomotive_axis_count(series, locomotive))
            if locomotive not in kp_cache:
                kp_rows = cur.execute(
                    "SELECT r, c, v FROM kp_data WHERE locomotive=? AND c IN (2, 3)",
                    (locomotive,),
                ).fetchall()
                kp_cache[locomotive] = {(int(row["r"]), int(row["c"])): text(row["v"]).strip() for row in kp_rows}
            kp_values = kp_cache.get(locomotive, {})
            wheel_pairs: list[dict[str, object]] = []
            for row_index in sorted(rows_by_r):
                row = rows_by_r[row_index]
                pair_number = parse_excel_int(row[1]) or max(1, row_index - 1)
                left_band = row[8] or ""
                right_band = row[9] or ""
                diameter_left = row[10] or ""
                diameter_right = row[11] or ""
                if not diameter_left:
                    kp_left = parse_float_value(kp_values.get((pair_number - 1, 2), ""))
                    bandage_left_value = parse_float_value(left_band)
                    if kp_left is not None and bandage_left_value is not None:
                        diameter_left = str(int(round(kp_left + bandage_left_value * 2)))
                if not diameter_right:
                    kp_right = parse_float_value(kp_values.get((pair_number - 1, 3), ""))
                    bandage_right_value = parse_float_value(right_band)
                    if kp_right is not None and bandage_right_value is not None:
                        diameter_right = str(int(round(kp_right + bandage_right_value * 2)))

                wheel_pairs.append(
                    {
                        "number": pair_number,
                        "left": {
                            "flangeThickness": parse_float_value(row[2]),
                            "flangeWear": parse_float_value(row[4]),
                            "flangeSteepness": parse_float_value(row[6]),
                            "bandageThickness": parse_float_value(left_band),
                            "bandageDiameter": parse_float_value(diameter_left),
                        },
                        "right": {
                            "flangeThickness": parse_float_value(row[3]),
                            "flangeWear": parse_float_value(row[5]),
                            "flangeSteepness": parse_float_value(row[7]),
                            "bandageThickness": parse_float_value(right_band),
                            "bandageDiameter": parse_float_value(diameter_right),
                        },
                    }
                )

            archive_items.append(
                {
                    "formatVersion": 1,
                    "createdAt": dt.datetime.now().isoformat(timespec="seconds"),
                    "measurementId": f"{year}:{measurement_date}:{locomotive}:{repair_type}",
                    "locomotive": {
                        "series": series,
                        "number": locomotive,
                        "wheelPairCount": wheel_pair_count,
                        "comment": "",
                        "isNew": False,
                    },
                    "repairType": repair_type,
                    "measurementDate": measurement_date,
                    "wheelPairs": wheel_pairs,
                }
            )

    return {
        "formatVersion": 1,
        "exportType": "archiveData",
        "exportedAt": dt.datetime.now().isoformat(timespec="seconds"),
        "archive": archive_items,
    }


def phone_export_payload(kind: str, selected_locomotives: list[str] | None = None, date_from: str = "", date_to: str = "") -> dict:
    kind = text(kind).strip().lower()
    if kind == "reference":
        return phone_reference_export_payload()
    if kind == "archive":
        return phone_archive_export_payload(selected_locomotives, date_from, date_to)
    raise ValueError("Неизвестный тип экспорта.")


def parse_phone_json_payload(raw: bytes) -> object:
    data = json.loads(raw.decode("utf-8"))
    if isinstance(data, dict) and "payload" in data:
        payload = data.get("payload")
        if isinstance(payload, str):
            return json.loads(payload)
        return payload
    if isinstance(data, str):
        text_data = data.strip()
        if text_data.startswith("{") or text_data.startswith("["):
            try:
                return json.loads(text_data)
            except Exception:
                pass
        try:
            decoded = base64.b64decode(text_data)
            try:
                return json.loads(zlib.decompress(decoded).decode("utf-8"))
            except Exception:
                return json.loads(decoded.decode("utf-8"))
        except Exception:
            return data
    return data


def import_phone_reference_payload(payload: dict) -> dict:
    reference = payload.get("referenceData") if isinstance(payload.get("referenceData"), dict) else payload
    locomotives = reference.get("locomotives") if isinstance(reference, dict) else None
    if not isinstance(locomotives, list):
        return {"error": "Некорректный справочник локомотивов."}, HTTPStatus.BAD_REQUEST

    grouped: dict[str, dict[str, object]] = {}
    for item in locomotives:
        if not isinstance(item, dict):
            continue
        series = text(item.get("series")).strip().upper()
        number = text(item.get("number")).strip()
        if not number:
            continue
        key = f"{series}|{number}"
        candidate = {
            "series": series,
            "number": number,
            "wheelPairCount": parse_excel_int(item.get("wheelPairCount")) or len(item.get("wheelPairs") or []) or locomotive_axis_count(series, number),
            "sortOrder": parse_excel_int(item.get("sortOrder")) or 0,
            "updatedAt": parse_excel_int(item.get("updatedAt")) or 0,
            "deletedAt": parse_excel_int(item.get("deletedAt")) or 0,
            "eightDigitNumber": text(item.get("eightDigitNumber")).strip(),
            "wheelPairs": item.get("wheelPairs") if isinstance(item.get("wheelPairs"), list) else [],
        }
        current = grouped.get(key)
        if current is None or (
            candidate["updatedAt"],
            candidate["deletedAt"],
            candidate["sortOrder"],
        ) > (
            current["updatedAt"],
            current["deletedAt"],
            current["sortOrder"],
        ):
            grouped[key] = candidate

    imported_locomotives = 0
    imported_wheel_pairs = 0
    with DB_LOCK, connect() as conn:
        cur = conn.cursor()
        cur.execute("BEGIN")
        for item in grouped.values():
            series = text(item["series"]).strip().upper()
            number = text(item["number"]).strip()
            wheel_pair_count = int(item["wheelPairCount"] or 0)
            sort_order = int(item["sortOrder"] or 0)
            updated_at = int(item["updatedAt"] or 0)
            deleted_at = int(item["deletedAt"] or 0)
            eight_digit_number = text(item["eightDigitNumber"]).strip()
            upsert_inventory_locomotive(
                cur,
                series,
                number,
                "",
                wheel_pair_count=wheel_pair_count,
                eight_digit_number=eight_digit_number,
                sort_order=sort_order,
                updated_at=updated_at or None,
                deleted_at=deleted_at,
            )
            if deleted_at <= 0:
                cur.execute("DELETE FROM kp_data WHERE locomotive=?", (number,))
            wheel_pairs = item.get("wheelPairs")
            if not isinstance(wheel_pairs, list) or not wheel_pairs:
                wheel_pairs = [{"number": index + 1, "axisNumber": index + 1} for index in range(max(1, wheel_pair_count))]
            for pair in wheel_pairs:
                if not isinstance(pair, dict):
                    continue
                pair_number = parse_excel_int(pair.get("number")) or 0
                if pair_number <= 0:
                    continue
                axis_number = parse_excel_int(pair.get("axisNumber")) or pair_number
                cur.execute(
                    "INSERT OR REPLACE INTO kp_data(locomotive, r, c, v) VALUES(?, ?, ?, ?)",
                    (number, pair_number - 1, 1, str(axis_number)),
                )
                diameter_left = parse_float_value(pair.get("diameterLeft"))
                diameter_right = parse_float_value(pair.get("diameterRight"))
                if diameter_left is not None:
                    cur.execute(
                        "INSERT OR REPLACE INTO kp_data(locomotive, r, c, v) VALUES(?, ?, ?, ?)",
                        (number, pair_number - 1, 2, str(diameter_left)),
                    )
                if diameter_right is not None:
                    cur.execute(
                        "INSERT OR REPLACE INTO kp_data(locomotive, r, c, v) VALUES(?, ?, ?, ?)",
                        (number, pair_number - 1, 3, str(diameter_right)),
                    )
            imported_locomotives += 1
            imported_wheel_pairs += len(wheel_pairs)
        conn.commit()

    return {"ok": True, "imported_locomotives": imported_locomotives, "imported_wheel_pairs": imported_wheel_pairs}


def import_phone_measurement_payload(payload: dict) -> dict:
    measurement = payload.get("measurement") if isinstance(payload.get("measurement"), dict) else payload
    if not isinstance(measurement, dict):
        return {"error": "Некорректный замер."}, HTTPStatus.BAD_REQUEST

    locomotive = measurement.get("locomotive")
    if not isinstance(locomotive, dict):
        return {"error": "Не найден локомотив в замере."}, HTTPStatus.BAD_REQUEST

    series = text(locomotive.get("series")).strip()
    number = text(locomotive.get("number")).strip()
    measurement_date = text(measurement.get("measurementDate")).strip() or dt.date.today().isoformat()
    repair_type = text(measurement.get("repairType")).strip()
    measurement_id = text(measurement.get("measurementId")).strip() or f"{measurement_date}:{number}:{repair_type}"
    wheel_pairs = measurement.get("wheelPairs")
    if not isinstance(wheel_pairs, list) or not wheel_pairs:
        return {"error": "В замере нет колесных пар."}, HTTPStatus.BAD_REQUEST

    try:
        year = int(measurement_date[:4])
    except Exception:
        year = dt.date.today().year

    wheel_pair_count = parse_excel_int(locomotive.get("wheelPairCount")) or len(wheel_pairs) or locomotive_axis_count(series, number)
    section_count = default_section_count(wheel_pair_count)
    section_sizes: list[int] = []
    base = max(1, wheel_pair_count) // max(1, section_count)
    remainder = max(1, wheel_pair_count) % max(1, section_count)
    for index in range(max(1, section_count)):
        section_sizes.append(base + (1 if index < remainder else 0))

    archive_rows: list[tuple[int, str, str, str, int, int, str]] = []
    imported_cells = 0
    with DB_LOCK, connect() as conn:
        cur = conn.cursor()
        cur.execute("BEGIN")
        upsert_inventory_locomotive(cur, series, number)
        cur.execute(
            "DELETE FROM archive_data WHERE y=? AND measurement_date=? AND locomotive=? AND repair_type=?",
            (year, measurement_date, number, repair_type),
        )
        for pair in wheel_pairs:
            if not isinstance(pair, dict):
                continue
            pair_number = parse_excel_int(pair.get("number")) or 0
            if pair_number <= 0:
                continue
            row_index = pair_number - 1
            running = 0
            section_value = "1"
            for section_index, span in enumerate(section_sizes, start=1):
                running += span
                if row_index < running:
                    section_value = str(section_index)
                    break
            left = pair.get("left") if isinstance(pair.get("left"), dict) else {}
            right = pair.get("right") if isinstance(pair.get("right"), dict) else {}
            values = {
                0: section_value,
                1: str(pair_number),
                2: excel_num_text(left.get("flangeThickness")),
                3: excel_num_text(right.get("flangeThickness")),
                4: excel_num_text(left.get("flangeWear")),
                5: excel_num_text(right.get("flangeWear")),
                6: excel_num_text(left.get("flangeSteepness")),
                7: excel_num_text(right.get("flangeSteepness")),
                8: excel_num_text(left.get("bandageThickness")),
                9: excel_num_text(right.get("bandageThickness")),
                10: excel_num_text(left.get("bandageDiameter")),
                11: excel_num_text(right.get("bandageDiameter")),
            }
            for col, value in values.items():
                value = text(value).strip()
                if value:
                    archive_rows.append((year, measurement_date, number, repair_type, row_index + 2, col, value))
                    imported_cells += 1
        cur.executemany(
            "INSERT OR REPLACE INTO archive_data (y, measurement_date, locomotive, repair_type, r, c, v) VALUES (?, ?, ?, ?, ?, ?, ?)",
            archive_rows,
        )
        conn.commit()

    return {
        "ok": True,
        "imported_measurements": 1,
        "imported_cells": imported_cells,
        "measurement_id": measurement_id,
    }


def import_phone_payload(payload: object) -> dict:
    if isinstance(payload, dict):
        export_type = text(payload.get("exportType")).strip()
        if payload.get("archiveData") is not None or export_type == "archiveData":
            archive = payload.get("archiveData") if isinstance(payload.get("archiveData"), dict) else payload
            archive_items = archive.get("archive") if isinstance(archive, dict) else None
            if isinstance(archive_items, list):
                imported_measurements = 0
                imported_cells = 0
                for item in archive_items:
                    result = import_phone_measurement_payload(item)
                    if isinstance(result, tuple):
                        return result[0], result[1]
                    imported_measurements += int(result.get("imported_measurements", 0))
                    imported_cells += int(result.get("imported_cells", 0))
                return {"ok": True, "imported_measurements": imported_measurements, "imported_cells": imported_cells}
            return import_phone_measurement_payload(archive if isinstance(archive, dict) else payload)
        if payload.get("referenceData") is not None or export_type == "referenceData":
            reference = payload.get("referenceData") if isinstance(payload.get("referenceData"), dict) else payload
            return import_phone_reference_payload(reference)
        if payload.get("measurement") is not None:
            measurement = payload.get("measurement")
            if isinstance(measurement, dict):
                return import_phone_measurement_payload(measurement)
        if "locomotives" in payload:
            return import_phone_reference_payload(payload)
        if "wheelPairs" in payload and "measurementDate" in payload:
            return import_phone_measurement_payload(payload)
    return {"error": "Не удалось распознать телефонные данные."}, HTTPStatus.BAD_REQUEST


def ensure_import_locomotive(cur: sqlite3.Cursor, series: str, locomotive: str, wheel_pair_count: int) -> None:
    locomotive = text(locomotive).strip()
    if not locomotive:
        return
    series = text(series).strip().upper()
    upsert_inventory_locomotive(cur, series, locomotive)
    for index in range(max(1, int(wheel_pair_count or 1))):
        cur.execute("INSERT OR IGNORE INTO kp_data (locomotive, r, c, v) VALUES (?, ?, 0, ?)", (locomotive, index, str(index + 1)))
        cur.execute("INSERT OR IGNORE INTO kp_data (locomotive, r, c, v) VALUES (?, ?, 1, ?)", (locomotive, index, str(index + 1)))


def import_archive_excel_bytes(data: bytes) -> dict:
    _, load_workbook, *_ = require_openpyxl()
    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    ws = wb.active

    aliases = {
        "measurement_date": {"датазамера", "датавыполненияобмера", "датаобмера", "measurementdate"},
        "series": {"серия", "series"},
        "locomotive": {"локомотив", "номерлокомотива", "locomotive"},
        "repair_type": {"видремонта", "видрем", "repairtype"},
        "wheel_pair": {"номеркп", "wheelpair", "wheelpairnumber", "ось", "номероси", "kp"},
        "section": {"секция", "вагон", "section"},
        "prokat_left": {"прокатлев", "левпрокат", "prokatleft", "flangewearleft"},
        "prokat_right": {"прокатправ", "правпрокат", "prokatright", "flangewearright"},
        "greben_left": {"толщинагребнялев", "левтолщинагребня", "grebenleft", "flangethicknessleft"},
        "greben_right": {"толщинагребняправ", "правтолщинагребня", "grebenright", "flangethicknessright"},
        "krut_left": {"крутизнагребнялев", "левкрутизнагребня", "krutleft", "flangesteepnessleft"},
        "krut_right": {"крутизнагребняправ", "правкрутизнагребня", "krutright", "flangesteepnessright"},
        "bandage_thickness_left": {"толщинабандажалева", "толщинабандажалев", "leftbandagethickness", "bandagethicknessleft"},
        "bandage_thickness_right": {"толщинабандажаправ", "rightbandagethickness", "bandagethicknessright"},
        "bandage_diameter_left": {"диаметрбандажалева", "диаметрбандажалев", "leftbandagediameter", "bandagediameterleft"},
        "bandage_diameter_right": {"диаметрбандажаправ", "rightbandagediameter", "bandagediameterright"},
    }

    header_row_index = None
    header_columns: dict[str, int] = {}
    for row_index, row in enumerate(ws.iter_rows(min_row=1, max_row=10, values_only=True), start=1):
        normalized = [normalize_excel_header(value) for value in row]
        found: dict[str, int] = {}
        for key, alias_set in aliases.items():
            for idx, header in enumerate(normalized):
                if header in alias_set:
                    found[key] = idx
                    break
        if len(found) >= 5:
            header_row_index = row_index
            header_columns = found
            break

    if header_row_index is None:
        return {"error": "Не найдена строка заголовков."}, HTTPStatus.BAD_REQUEST

    missing_headers = [name for name in ("measurement_date", "locomotive", "repair_type", "wheel_pair") if name not in header_columns]
    if missing_headers:
        return {"error": "В Excel не найдены обязательные колонки: " + ", ".join(missing_headers)}, HTTPStatus.BAD_REQUEST

    required_metric_columns = {
        "prokat_left": 2,
        "prokat_right": 3,
        "greben_left": 4,
        "greben_right": 5,
        "krut_left": 6,
        "krut_right": 7,
        "bandage_thickness_left": 8,
        "bandage_thickness_right": 9,
    }
    optional_metric_columns = {"bandage_diameter_left": 10, "bandage_diameter_right": 11}

    measurements: dict[tuple[str, str, str], dict] = {}
    errors: list[str] = []
    current_series = current_date = current_loco = current_repair = current_section = ""

    def row_value(row, column_name: str) -> str:
        idx = header_columns.get(column_name)
        if idx is None or idx >= len(row):
            return ""
        return excel_cell_text(row[idx])

    for row_index, row in enumerate(ws.iter_rows(min_row=header_row_index + 1, values_only=True), start=header_row_index + 1):
        if not row or all(cell is None or text(cell).strip() == "" for cell in row):
            continue
        row_date = parse_excel_date(row_value(row, "measurement_date")) or current_date
        row_loco = row_value(row, "locomotive") or current_loco
        row_repair = row_value(row, "repair_type") or current_repair
        row_series = row_value(row, "series") or current_series
        row_section = row_value(row, "section") or current_section
        wheel_pair_number = parse_excel_int(row_value(row, "wheel_pair"))

        if row_value(row, "measurement_date"):
            current_date = row_date
        if row_value(row, "locomotive"):
            current_loco = row_loco
        if row_value(row, "repair_type"):
            current_repair = row_repair
        if row_value(row, "series"):
            current_series = row_series
        if row_value(row, "section"):
            current_section = row_section

        if not row_date or not row_loco or not row_repair:
            errors.append(f"Строка {row_index}: не заполнены дата, локомотив или вид ремонта.")
            continue
        if wheel_pair_number is None or wheel_pair_number <= 0:
            errors.append(f"Строка {row_index}: не указан корректный номер КП.")
            continue

        values: dict[int, str] = {}
        missing_fields = []
        for column_name, db_col in required_metric_columns.items():
            value = row_value(row, column_name)
            if value == "":
                missing_fields.append(column_name)
            else:
                values[db_col] = value
        for column_name, db_col in optional_metric_columns.items():
            value = row_value(row, column_name)
            if value != "":
                values[db_col] = value
        if missing_fields:
            errors.append(f"Строка {row_index}: не заполнены поля " + ", ".join(missing_fields))
            continue

        group = measurements.setdefault((row_date, row_loco, row_repair), {"series": row_series, "rows": {}, "sections": {}})
        if row_series and not group["series"]:
            group["series"] = row_series
        if row_section:
            group["sections"][wheel_pair_number] = row_section
        group["rows"][wheel_pair_number] = values

    if not measurements:
        return {"error": "Не удалось импортировать ни одного замера.", "errors": errors[:20]}, HTTPStatus.BAD_REQUEST

    imported_measurements = 0
    imported_cells = 0
    with DB_LOCK, connect() as conn:
        cur = conn.cursor()
        kp_cache: dict[str, dict[tuple[int, int], str]] = {}
        cur.execute("BEGIN")
        for (measurement_date, locomotive, repair_type), meta in sorted(measurements.items()):
            wheel_pair_numbers = sorted(meta["rows"].keys())
            if not wheel_pair_numbers:
                continue
            year = int(measurement_date[:4]) if len(measurement_date) >= 4 and measurement_date[:4].isdigit() else dt.date.today().year
            series = meta["series"] or series_for_locomotive(cur, locomotive)
            ensure_import_locomotive(cur, series, locomotive, max(wheel_pair_numbers))
            if locomotive not in kp_cache:
                kp_rows = cur.execute("SELECT r, c, v FROM kp_data WHERE locomotive=? AND c IN (2, 3)", (locomotive,)).fetchall()
                kp_cache[locomotive] = {(int(row["r"]), int(row["c"])): text(row["v"]).strip() for row in kp_rows}

            axis_count = locomotive_axis_count(series_for_locomotive(cur, locomotive), locomotive)
            db_rows: list[tuple[int, str, str, str, int, int, str]] = []
            for wheel_pair_number in wheel_pair_numbers:
                row_values = meta["rows"][wheel_pair_number]
                table_row = wheel_pair_number + 1
                section_value = meta["sections"].get(wheel_pair_number, "1" if axis_count == 6 else str(((wheel_pair_number - 1) // 4) + 1))
                kp_index = wheel_pair_number - 1
                bandage_left = row_values.get(8, "")
                bandage_right = row_values.get(9, "")
                diameter_left = row_values.get(10, "")
                diameter_right = row_values.get(11, "")
                if not diameter_left:
                    kp_left = parse_float_value(kp_cache[locomotive].get((kp_index, 2), ""))
                    bandage_left_value = parse_float_value(bandage_left)
                    if kp_left is not None and bandage_left_value is not None:
                        diameter_left = str(int(round(kp_left + bandage_left_value * 2)))
                if not diameter_right:
                    kp_right = parse_float_value(kp_cache[locomotive].get((kp_index, 3), ""))
                    bandage_right_value = parse_float_value(bandage_right)
                    if kp_right is not None and bandage_right_value is not None:
                        diameter_right = str(int(round(kp_right + bandage_right_value * 2)))

                full_values = {
                    0: section_value,
                    1: str(wheel_pair_number),
                    2: row_values.get(2, ""),
                    3: row_values.get(3, ""),
                    4: row_values.get(4, ""),
                    5: row_values.get(5, ""),
                    6: row_values.get(6, ""),
                    7: row_values.get(7, ""),
                    8: bandage_left,
                    9: bandage_right,
                    10: diameter_left,
                    11: diameter_right,
                }
                for col, value in full_values.items():
                    if value != "":
                        db_rows.append((year, measurement_date, locomotive, repair_type, table_row, col, value))
            if not db_rows:
                continue
            cur.execute(
                "DELETE FROM archive_data WHERE y=? AND measurement_date=? AND locomotive=? AND repair_type=?",
                (year, measurement_date, locomotive, repair_type),
            )
            cur.executemany(
                "INSERT OR REPLACE INTO archive_data (y, measurement_date, locomotive, repair_type, r, c, v) VALUES (?, ?, ?, ?, ?, ?, ?)",
                db_rows,
            )
            imported_measurements += 1
            imported_cells += len(db_rows)
        conn.commit()

    return {"ok": True, "imported_measurements": imported_measurements, "imported_cells": imported_cells, "errors": errors[:10]}


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
    .top { display:flex; justify-content:space-between; gap:12px; align-items:flex-start; background:#fff; border:1px solid #2f6fed; border-radius:16px; padding:14px 16px; }
    h1 { margin:0; font-size:24px; }
    .muted { color:var(--muted); font-size:13px; }
    .actions, .filters { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
    button, a { border:1px solid #2f6fed; border-radius:8px; padding:9px 11px; background:#fff; color:#1f57d6; font:inherit; text-decoration:none; }
    input, select { border:1px solid #2f6fed; border-radius:8px; padding:9px 11px; background:#fff; color:var(--text); font:inherit; }
    button { cursor:pointer; font-weight:400; }
    button:hover, a:hover { box-shadow:0 0 0 2px rgba(47,111,237,.10); }
    .primary { background:var(--blue); border-color:var(--blue); color:#fff; }
    .meta { display:none; }
    .badge { display:inline-flex; align-items:center; gap:6px; padding:8px 10px; background:#fff; border:1px solid var(--line); border-radius:8px; font-size:13px; }
    .badge strong { font-weight:700; }
    #saveBtn { margin-left:auto; }
    .tabs { display:flex; gap:8px; margin-top:12px; margin-bottom:-1px; padding-left:17px; }
    .tab { background:#fff; border:1px solid #2f6fed; border-bottom-color:#2f6fed; padding:10px 14px; border-radius:10px 10px 0 0; font-weight:400; cursor:pointer; color:#1f57d6; }
    .tab.active { background:#2f6fed; color:#fff; border-color:#2f6fed; border-bottom-color:#2f6fed; }
    .panel { display:none; background:#fff; border:1px solid #2f6fed; border-radius:16px; padding:12px; }
    .panel.active { display:block; }
    .archive-controls { display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin-bottom:12px; }
    .archive-actions-menu { position:relative; display:inline-flex; }
    .archive-actions-menu .menu-panel {
      position:absolute;
      top:calc(100% + 6px);
      right:0;
      min-width:220px;
      background:#fff;
      border:1px solid var(--line);
      border-radius:10px;
      box-shadow:0 14px 36px rgba(0,27,61,.14);
      padding:6px;
      display:none;
      z-index:12;
    }
    .archive-actions-menu.open .menu-panel { display:flex; flex-direction:column; gap:6px; }
    .archive-actions-menu .menu-panel button { width:100%; justify-content:flex-start; }
    .archive-controls label { display:flex; align-items:center; gap:8px; }
    .archive-controls input { width:240px; }
    .input-locomotive-filter { display:flex; align-items:center; gap:8px; }
    .table-shell { background:#fff; border:1px solid #2f6fed; border-radius:18px; padding:12px; overflow:hidden; display:flex; justify-content:center; margin-top:16px; }
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
    table { border-collapse:collapse; width:max-content; table-layout:fixed; border-radius:18px; overflow:hidden; }
    th, td { border:1px solid var(--line); padding:0; text-align:center; height:34px; vertical-align:middle; }
    thead th { background:#eef3f8; font-weight:700; font-size:14px; line-height:1.1; }
    table thead tr:first-child th:first-child { border-top-left-radius:18px; }
    table thead tr:first-child th:last-child { border-top-right-radius:18px; }
    table tbody tr:last-child td:first-child { border-bottom-left-radius:18px; }
    table tbody tr:last-child td:last-child { border-bottom-right-radius:18px; }
    th.small { font-size:14px; line-height:1.1; }
    th.measure-head, td.measure-cell { width:60px; }
    th.section-col, td.section-col { width:80px; }
    th.number-col, td.number-col { width:80px; }
    td.fixed { background:#f7fafc; font-weight:600; }
    td.measure-cell input { width:100%; height:34px; border:0; text-align:center; background:transparent; padding:0; font-size:12px; line-height:34px; display:block; box-sizing:border-box; }
    td.measure-cell.selected { box-shadow: inset 0 0 0 2px #2f6fed; }
    td input { width:100%; height:34px; border:0; text-align:center; background:transparent; padding:0; line-height:34px; display:block; box-sizing:border-box; }
    td input.left { text-align:left; }
    td.warn { background:var(--warn); }
    td.bad { background:var(--bad); }
    .archive-table th, .archive-table td { font-size:12px !important; text-align:center; vertical-align:middle; height:12px !important; padding:0 !important; line-height:12px !important; }
    .archive-table td { white-space:pre-line; }
    .archive-table tr { height:12px !important; }
    .archive-table td.raw { width:60px; }
    .archive-table td.axis-col { width:80px; background:#f7fafc; font-weight:600; }
    .archive-table td.section-merged,
    .archive-table td.summary-merged,
    .archive-table td.axis-col,
    .archive-table td.first-col {
      vertical-align:middle;
      padding-top:0 !important;
      padding-bottom:0 !important;
      line-height:1.0 !important;
    }
    .archive-table td.archive-raw { width:60px; }
    .archive-table td.archive-raw input {
      width:100%;
      height:12px !important;
      border:0;
      text-align:center;
      background:transparent;
      padding:0 !important;
      margin:0;
      font-size:12px !important;
      line-height:12px !important;
      display:block;
      box-sizing:border-box;
    }
    .archive-table-shell { margin-top:0; padding-top:0; }
    .archive-table td.summary { width:110px; }
    .archive-table td.first-col { width:220px; }
    .archive-table tr.measurement-start td { border-top:2px solid #2f6fed; }
    .archive-table tr.measurement-start td:first-child { border-left:2px solid #2f6fed; }
    .archive-table tr.measurement-row td:last-child { border-right:2px solid #2f6fed; }
    .archive-table tr.measurement-end td { border-bottom:2px solid #2f6fed; }
    .modal-backdrop {
      position:fixed;
      inset:0;
      z-index:80;
      display:none;
      align-items:center;
      justify-content:center;
      padding:24px;
      background:rgba(16,32,51,.38);
    }
    .modal-backdrop.open { display:flex; }
    .modal {
      width:min(800px, 100%);
      max-height:calc(100vh - 48px);
      overflow:auto;
      background:#fff;
      border:1px solid var(--line);
      border-radius:10px;
      box-shadow:0 18px 44px rgba(16,32,51,.2);
      padding:14px;
    }
    .modal-head { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:10px; }
    .modal-head h2 { margin:0; font-size:20px; }
    .modal-actions { display:flex; justify-content:flex-end; gap:8px; margin-top:12px; }
    .norms-toolbar { display:flex; gap:8px; align-items:center; margin-bottom:10px; }
    .norms-table { width:100%; table-layout:fixed; }
    .norms-table th, .norms-table td { height:38px; padding:4px; }
    .norms-table th { font-size:13px; }
    .norms-table input, .norms-table select { width:100%; height:30px; padding:4px 6px; border-radius:6px; }
    .status { min-height:20px; margin-top:10px; font-size:13px; color:var(--muted); }
    .input-meta { display:none; }
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
        <button id="normsBtn" type="button" onclick="openNormsDialog()">Нормы</button>
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
        <label class="input-locomotive-filter">Локомотив
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
        <button id="archiveDeleteBtn" type="button" onclick="deleteSelectedArchiveMeasurement()">Удалить из архива</button>
        <div class="archive-actions-menu" id="archiveActionsMenu">
          <button id="archiveActionsBtn" type="button" onclick="toggleArchiveActionsMenu(event)">Импорт / экспорт ▾</button>
          <div class="menu-panel" role="menu" aria-label="Импорт и экспорт архива">
            <button type="button" onclick="chooseArchiveExcelFile(); closeArchiveActionsMenu()">Импорт из Excel</button>
            <button type="button" onclick="openArchiveExportDialog(); closeArchiveActionsMenu()">Экспорт в Excel</button>
            <button type="button" onclick="downloadArchiveTemplate(); closeArchiveActionsMenu()">Шаблон Excel</button>
          </div>
          <input id="archiveExcelFile" type="file" accept=".xlsx,.xlsm" style="display:none">
        </div>
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

  <div id="normsModal" class="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="normsTitle">
    <div class="modal">
      <div class="modal-head">
        <h2 id="normsTitle">Нормы колесных пар</h2>
        <button type="button" title="Закрыть" aria-label="Закрыть" onclick="closeNormsDialog()">×</button>
      </div>
      <div class="norms-toolbar">
        <button id="addNormBtn" type="button" onclick="addNormRow()">Добавить показатель</button>
      </div>
      <table class="norms-table" aria-label="Нормы колесных пар">
        <colgroup>
          <col style="width:300px">
          <col style="width:170px">
          <col style="width:130px">
          <col style="width:130px">
        </colgroup>
        <thead>
          <tr>
            <th>Показатель (название)</th>
            <th>Условие</th>
            <th>Желтый порог</th>
            <th>Красный порог</th>
          </tr>
        </thead>
        <tbody id="normsBody"></tbody>
      </table>
      <div id="normsStatus" class="status"></div>
      <div class="modal-actions">
        <button type="button" onclick="closeNormsDialog()">Отмена</button>
        <button id="saveNormsBtn" class="primary" type="button" onclick="saveNormsDialog()">Сохранить</button>
      </div>
    </div>
  </div>

  <div id="archiveExportModal" class="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="archiveExportTitle">
    <div class="modal">
      <div class="modal-head">
        <h2 id="archiveExportTitle">Экспорт архива в Excel</h2>
        <button type="button" title="Закрыть" aria-label="Закрыть" onclick="closeArchiveExportDialog()">×</button>
      </div>
      <div class="filters" style="align-items:flex-start;">
        <label>Локомотивы
          <select id="archiveExportLocomotives" multiple size="8" style="width:260px"></select>
        </label>
        <label>Дата с
          <input id="archiveExportDateFrom" type="date" style="width:160px">
        </label>
        <label>Дата по
          <input id="archiveExportDateTo" type="date" style="width:160px">
        </label>
      </div>
      <div id="archiveExportStatus" class="status">Если локомотивы не выбраны, экспортируются все.</div>
      <div class="modal-actions">
        <button type="button" onclick="closeArchiveExportDialog()">Отмена</button>
        <button class="primary" type="button" onclick="downloadArchiveExport()">Экспорт</button>
      </div>
    </div>
  </div>

<script>
const API = '{{APP_PREFIX}}';
const CAN_EDIT = {{CAN_EDIT}};
const LOCOMOTIVE_CHOICES = {{LOCOMOTIVE_CHOICES}};
const INPUT_ROWS = 12;
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
let kpSelectionAnchor = null;
let kpSelectionFocus = null;
let kpSuppressFocusSelection = false;
let archiveRows = [];
let archiveSortDesc = true;
let archiveSelectedMeasurementKey = null;
let selectionAnchor = null;
let selectionFocus = null;
let clipboardCache = '';
let archiveSelectionAnchor = null;
let archiveSelectionFocus = null;
let locomotiveInputSource = 'loaded';
let initialLoadPromise = null;
let locomotiveSwitchPromise = null;
let normsRows = [];

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
function renderNormsTable(){
  const body = document.getElementById('normsBody');
  if (!body) return;
  body.innerHTML = normsRows.map((row, index) => `
    <tr data-index="${index}">
      <td>
        <input
          value="${esc(row.label)}"
          data-field="label"
          data-index="${index}"
          ${row.is_default || !CAN_EDIT ? 'readonly' : ''}
        >
      </td>
      <td>
        <select data-field="condition" data-index="${index}" ${CAN_EDIT ? '' : 'disabled'}>
          <option value="меньше или равно" ${row.condition === 'меньше или равно' ? 'selected' : ''}>меньше или равно</option>
          <option value="больше или равно" ${row.condition === 'больше или равно' ? 'selected' : ''}>больше или равно</option>
        </select>
      </td>
      <td><input value="${esc(row.yellow_value)}" data-field="yellow_value" data-index="${index}" ${CAN_EDIT ? '' : 'readonly'}></td>
      <td><input value="${esc(row.red_value)}" data-field="red_value" data-index="${index}" ${CAN_EDIT ? '' : 'readonly'}></td>
    </tr>
  `).join('');
}
async function openNormsDialog(){
  const modal = document.getElementById('normsModal');
  const status = document.getElementById('normsStatus');
  const saveBtn = document.getElementById('saveNormsBtn');
  const addBtn = document.getElementById('addNormBtn');
  if (saveBtn) saveBtn.disabled = !CAN_EDIT;
  if (addBtn) addBtn.disabled = !CAN_EDIT;
  if (status) status.textContent = 'Загрузка...';
  if (modal) modal.classList.add('open');
  try {
    const res = await fetch(`${API}/api/norms`, { cache: 'no-store' });
    if (!res.ok) throw new Error('Не удалось загрузить нормы');
    const payload = await res.json();
    normsRows = payload.rows || [];
    renderNormsTable();
    if (status) status.textContent = CAN_EDIT ? '' : 'Режим просмотра';
  } catch (error) {
    normsRows = [];
    renderNormsTable();
    if (status) status.textContent = error.message || 'Не удалось загрузить нормы';
  }
}
function closeNormsDialog(){
  const modal = document.getElementById('normsModal');
  if (modal) modal.classList.remove('open');
}
function addNormRow(){
  if (!CAN_EDIT) return;
  const suffix = Math.random().toString(16).slice(2, 10);
  normsRows.push({
    metric_key: `custom_${suffix}`,
    label: 'Новый показатель',
    condition: 'меньше или равно',
    yellow_value: '',
    red_value: '',
    is_default: false,
  });
  renderNormsTable();
  const index = normsRows.length - 1;
  const input = document.querySelector(`#normsBody input[data-index="${index}"][data-field="label"]`);
  if (input) input.focus();
}
function collectNormsRows(){
  const rows = normsRows.map(row => ({ ...row }));
  document.querySelectorAll('#normsBody [data-index][data-field]').forEach(input => {
    const index = Number(input.dataset.index);
    const field = input.dataset.field;
    if (!rows[index] || !field) return;
    rows[index][field] = input.value;
  });
  return rows;
}
function applyNormRows(rows){
  if (!state) return;
  const map = {};
  (rows || []).forEach(row => {
    map[row.metric_key] = {
      label: row.label || '',
      condition: row.condition || '',
      yellow_value: row.yellow_value || '',
      red_value: row.red_value || '',
    };
  });
  state.norms = map;
  renderTable();
}
async function saveNormsDialog(){
  if (!CAN_EDIT) return;
  const status = document.getElementById('normsStatus');
  const saveBtn = document.getElementById('saveNormsBtn');
  const rows = collectNormsRows();
  if (status) status.textContent = 'Сохранение...';
  if (saveBtn) saveBtn.disabled = true;
  try {
    const res = await fetch(`${API}/api/norms`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rows }),
    });
    const payload = await res.json();
    if (!res.ok || payload.error) throw new Error(payload.error || 'Не удалось сохранить нормы');
    normsRows = payload.rows || [];
    applyNormRows(normsRows);
    renderNormsTable();
    if (status) status.textContent = 'Сохранено';
    closeNormsDialog();
  } catch (error) {
    if (status) status.textContent = error.message || 'Не удалось сохранить нормы';
  } finally {
    if (saveBtn) saveBtn.disabled = !CAN_EDIT;
  }
}
async function downloadBlob(url, fallbackName, statusElement){
  const res = await fetch(url, { cache: 'no-store' });
  if (!res.ok) {
    const payload = await res.json().catch(() => ({}));
    throw new Error(payload.error || 'Не удалось скачать файл');
  }
  const blob = await res.blob();
  const link = document.createElement('a');
  link.href = URL.createObjectURL(blob);
  link.download = fallbackName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  if (statusElement) statusElement.textContent = 'Файл скачан';
}
async function downloadArchiveTemplate(){
  const status = document.getElementById('archiveStatus');
  try {
    if (status) status.textContent = 'Файл готовится...';
    await downloadBlob(`${API}/api/archive-excel-template`, 'Шаблон_импорта_архива.xlsx', status);
  } catch (error) {
    if (status) status.textContent = error.message || 'Не удалось скачать шаблон';
  }
}
function toggleArchiveActionsMenu(event){
  if (event) event.stopPropagation();
  const menu = document.getElementById('archiveActionsMenu');
  if (!menu) return;
  menu.classList.toggle('open');
}
function closeArchiveActionsMenu(){
  const menu = document.getElementById('archiveActionsMenu');
  if (menu) menu.classList.remove('open');
}
document.addEventListener('click', (event) => {
  const menu = document.getElementById('archiveActionsMenu');
  if (!menu || !menu.classList.contains('open')) return;
  if (menu.contains(event.target)) return;
  closeArchiveActionsMenu();
});
function renderArchiveExportLocomotives(){
  const select = document.getElementById('archiveExportLocomotives');
  if (!select) return;
  const numbers = [];
  const seen = new Set();
  archiveRows.forEach(row => {
    const number = String(row.locomotive || '').trim();
    if (number && !seen.has(number)) {
      seen.add(number);
      numbers.push(number);
    }
  });
  (state?.locomotives || LOCOMOTIVE_CHOICES || []).forEach(item => {
    const number = String(item.number || '').trim();
    if (number && !seen.has(number)) {
      seen.add(number);
      numbers.push(number);
    }
  });
  select.innerHTML = numbers.map(number => `<option value="${esc(number)}">${esc(number)}</option>`).join('');
}
function openArchiveExportDialog(){
  const modal = document.getElementById('archiveExportModal');
  const status = document.getElementById('archiveExportStatus');
  renderArchiveExportLocomotives();
  if (status) status.textContent = 'Если локомотивы не выбраны, экспортируются все.';
  if (modal) modal.classList.add('open');
  closeArchiveActionsMenu();
}
function closeArchiveExportDialog(){
  const modal = document.getElementById('archiveExportModal');
  if (modal) modal.classList.remove('open');
}
function selectedArchiveExportLocomotives(){
  const select = document.getElementById('archiveExportLocomotives');
  if (!select) return [];
  return Array.from(select.selectedOptions || []).map(option => option.value).filter(Boolean);
}
function downloadArchiveExport(){
  const status = document.getElementById('archiveExportStatus');
  const params = new URLSearchParams();
  selectedArchiveExportLocomotives().forEach(loco => params.append('locomotive', loco));
  const dateFrom = document.getElementById('archiveExportDateFrom')?.value || '';
  const dateTo = document.getElementById('archiveExportDateTo')?.value || '';
  if (dateFrom) params.set('date_from', dateFrom);
  if (dateTo) params.set('date_to', dateTo);
  if (status) status.textContent = 'Файл готовится...';
  downloadBlob(`${API}/api/archive-excel-export?${params.toString()}`, 'Экспорт_архива.xlsx', status)
    .then(() => closeArchiveExportDialog())
    .catch(error => {
      if (status) status.textContent = error.message || 'Не удалось скачать экспорт';
    });
}
function chooseArchiveExcelFile(){
  if (!CAN_EDIT) return;
  const input = document.getElementById('archiveExcelFile');
  if (!input) return;
  input.value = '';
  input.click();
}
function readFileAsBase64(file){
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const value = String(reader.result || '');
      resolve(value.includes(',') ? value.split(',').pop() : value);
    };
    reader.onerror = () => reject(reader.error || new Error('Не удалось прочитать файл'));
    reader.readAsDataURL(file);
  });
}
async function importArchiveExcelFile(file){
  if (!CAN_EDIT || !file) return;
  const status = document.getElementById('archiveStatus');
  if (status) status.textContent = 'Импорт Excel...';
  try {
    const data = await readFileAsBase64(file);
    const res = await fetch(`${API}/api/archive-excel-import`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json; charset=utf-8' },
      body: JSON.stringify({ filename: file.name, data }),
    });
    const payload = await res.json();
    if (!res.ok || payload.error) throw new Error(payload.error || 'Не удалось импортировать Excel');
    await loadState(getCurrentLoco());
    await loadArchive();
    const skipped = payload.errors?.length ? ` Пропущено строк: ${payload.errors.length}.` : '';
    if (status) status.textContent = `Импортировано замеров: ${payload.imported_measurements}; ячеек: ${payload.imported_cells}.${skipped}`;
  } catch (error) {
    if (status) status.textContent = error.message || 'Не удалось импортировать Excel';
  }
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
function archiveMeasurementKey(meta){
  if (!meta) return '';
  return [meta.year, meta.measurement_date, meta.locomotive, meta.repair_type].map(value => String(value ?? '')).join('|');
}
function setArchiveSelectedMeasurement(rowIndex){
  const meta = archiveRowMeta(rowIndex);
  archiveSelectedMeasurementKey = archiveMeasurementKey(meta) || null;
  renderArchiveMeasurementSelection();
}
function renderArchiveMeasurementSelection(){
  document.querySelectorAll('#archiveBody tr').forEach(tr => {
    tr.classList.remove('selected-measurement', 'selected-measurement-start', 'selected-measurement-end');
  });
  if (!archiveSelectedMeasurementKey) return;
  document.querySelectorAll('#archiveBody tr').forEach(tr => {
    const rowIndex = Number(tr.dataset.row || -1);
    const row = archiveRows[rowIndex];
    if (!row) return;
    const key = archiveMeasurementKey(row);
    if (key !== archiveSelectedMeasurementKey) return;
    const prev = archiveRows[rowIndex - 1];
    const next = archiveRows[rowIndex + 1];
    const prevKey = prev ? archiveMeasurementKey(prev) : '';
    const nextKey = next ? archiveMeasurementKey(next) : '';
    tr.classList.add('selected-measurement');
    if (prevKey !== archiveSelectedMeasurementKey) tr.classList.add('selected-measurement-start');
    if (nextKey !== archiveSelectedMeasurementKey) tr.classList.add('selected-measurement-end');
  });
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
  setArchiveSelectedMeasurement(row);
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
  setArchiveSelectedMeasurement(row);
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
function getInventoryItem(number){
  const target = String(number || '').trim();
  if (!target) return null;
  const items = state?.locomotives || LOCOMOTIVE_CHOICES || [];
  return items.find(item => String(item.number || '').trim() === target) || null;
}
function currentWheelPairCount(number){
  if (state && String(number || '').trim() === String(state.locomotive || '').trim() && Number.isFinite(Number(state.wheel_pair_count))) {
    return Number(state.wheel_pair_count) || 12;
  }
  const item = getInventoryItem(number);
  if (item && Number.isFinite(Number(item.wheelPairCount)) && Number(item.wheelPairCount) > 0) {
    return Math.max(1, Number(item.wheelPairCount) || 12);
  }
  return 12;
}
function currentSectionCount(number){
  if (state && String(number || '').trim() === String(state.locomotive || '').trim() && Number.isFinite(Number(state.section_count))) {
    return Math.max(1, Number(state.section_count) || 1);
  }
  const item = getInventoryItem(number);
  if (item && Number.isFinite(Number(item.sectionCount)) && Number(item.sectionCount) > 0) {
    return Math.max(1, Number(item.sectionCount) || 1);
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
  const item = getInventoryItem(number);
  if (item && Number.isFinite(Number(item.wheelPairCount)) && Number(item.wheelPairCount) > 0) {
    return Math.max(1, Number(item.wheelPairCount) || 12);
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
  const items = (LOCOMOTIVE_CHOICES && LOCOMOTIVE_CHOICES.length ? LOCOMOTIVE_CHOICES : (state?.locomotives || []));
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
  renderLocoDropdown('', true);
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
  if (allMode) clearKpSelection();
  const headers = allMode
    ? ['Локомотив', '№ КП', '№ оси', 'Диаметр КЦ<br>лев', 'Диаметр КЦ<br>прав']
    : ['№ КП', '№ оси', 'Диаметр КЦ<br>лев', 'Диаметр КЦ<br>прав'];
  const widths = allMode ? [120, 120, 160, 160, 160] : [160, 160, 160, 160];
  colgroup.innerHTML = widths.map(w => `<col style="width:${w}px">`).join('');
  head.innerHTML = `<tr>${headers.map(value => `<th>${value}</th>`).join('')}</tr>`;

  if (!kpRows.length) {
    clearKpSelection();
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
          <td data-col="${colIndex}">
            <input
              value="${esc(values[colIndex] ?? '')}"
              ${editable ? '' : 'readonly'}
              data-row="${rowIndex}"
              data-col="${colIndex}"
              onfocus="handleKpCellFocus(${rowIndex}, ${colIndex}, this)"
              onmousedown="return handleKpCellMouseDown(event, ${rowIndex}, ${colIndex})"
              onchange="handleKpCellChange(${rowIndex}, ${colIndex}, this.value, this)"
              onkeydown="handleKpKeydown(event, ${rowIndex}, ${colIndex})"
            >
          </td>`).join('')}
      </tr>`;
  }).join('');
  applyKpSearchFilter();
  renderKpSelectionHighlight();
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
function kpCellInBounds(row, col){
  return row >= 0 && row < kpRows.length && col >= 1 && col <= 3 && !kpAllMode;
}
function clearKpSelection(){
  kpSelectionAnchor = null;
  kpSelectionFocus = null;
  document.querySelectorAll('#kpBody td.selected').forEach(td => td.classList.remove('selected'));
}
function kpSelectionRect(){
  if (!kpSelectionAnchor || !kpSelectionFocus) return null;
  return {
    top: Math.min(kpSelectionAnchor.row, kpSelectionFocus.row),
    bottom: Math.max(kpSelectionAnchor.row, kpSelectionFocus.row),
    left: Math.min(kpSelectionAnchor.col, kpSelectionFocus.col),
    right: Math.max(kpSelectionAnchor.col, kpSelectionFocus.col),
  };
}
function renderKpSelectionHighlight(){
  document.querySelectorAll('#kpBody td.selected').forEach(td => td.classList.remove('selected'));
  const rect = kpSelectionRect();
  if (!rect) return;
  for (let r = rect.top; r <= rect.bottom; r += 1) {
    for (let c = rect.left; c <= rect.right; c += 1) {
      const td = document.querySelector(`#kpBody tr[data-row="${r}"] td[data-col="${c}"]`);
      if (td) td.classList.add('selected');
    }
  }
}
function selectKpCell(row, col, extend = false){
  if (!kpCellInBounds(row, col)) return;
  const cell = { row, col };
  if (!extend || !kpSelectionAnchor) {
    kpSelectionAnchor = cell;
  }
  kpSelectionFocus = cell;
  renderKpSelectionHighlight();
}
function focusKpCell(row, col, extend = false){
  if (!kpCellInBounds(row, col)) return;
  selectKpCell(row, col, extend);
  const input = kpCellElement(row, col);
  if (input) {
    kpSuppressFocusSelection = true;
    input.focus();
    kpSuppressFocusSelection = false;
  }
}
function kpCellValue(row, col){
  const input = kpCellElement(row, col);
  if (input) return input.value || '';
  return kpRows[row]?.values?.[col] ?? '';
}
function setKpCellValue(row, col, value){
  if (!kpRows[row] || !kpCellInBounds(row, col)) return false;
  const next = String(value ?? '').trim();
  kpRows[row].values[col] = next;
  const input = kpCellElement(row, col);
  if (input && input.value !== next) input.value = next;
  return true;
}
async function copyKpSelectionToClipboard(){
  const rect = kpSelectionRect();
  const start = rect ? { row: rect.top, col: rect.left } : (kpSelectionFocus || kpSelectionAnchor);
  if (!start || !kpCellInBounds(start.row, start.col)) return;
  const end = rect ? { row: rect.bottom, col: rect.right } : start;
  const lines = [];
  for (let r = start.row; r <= end.row; r += 1) {
    const rowValues = [];
    for (let c = start.col; c <= end.col; c += 1) {
      rowValues.push(kpCellValue(r, c));
    }
    lines.push(rowValues.join('\\t'));
  }
  await writeClipboardText(lines.join('\\n'));
  renderKpStatus('Скопировано');
}
async function pasteKpClipboard(row, col){
  if (!CAN_EDIT || kpAllMode || kpLoading) return;
  const text = await readClipboardText();
  if (!text) return;
  const rect = kpSelectionRect();
  const start = rect ? { row: rect.top, col: rect.left } : { row, col };
  const lines = String(text).replace(/\\r/g, '').split('\\n');
  if (lines.length && lines[lines.length - 1] === '') lines.pop();
  let touched = false;
  for (let r = 0; r < lines.length; r += 1) {
    const cells = lines[r].split('\\t');
    for (let c = 0; c < cells.length; c += 1) {
      const targetRow = start.row + r;
      const targetCol = start.col + c;
      if (!kpCellInBounds(targetRow, targetCol)) continue;
      touched = setKpCellValue(targetRow, targetCol, cells[c]) || touched;
    }
  }
  if (!touched) return;
  focusKpCell(start.row, start.col);
  await saveKpDataChanges();
}
async function clearKpSelectedCells(row, col){
  if (!CAN_EDIT || kpAllMode || kpLoading) return;
  const rect = kpSelectionRect();
  const start = rect ? { row: rect.top, col: rect.left } : (kpSelectionFocus || kpSelectionAnchor || { row, col });
  if (!kpCellInBounds(start.row, start.col)) return;
  const end = rect ? { row: rect.bottom, col: rect.right } : start;
  let touched = false;
  for (let r = start.row; r <= end.row; r += 1) {
    for (let c = start.col; c <= end.col; c += 1) {
      touched = setKpCellValue(r, c, '') || touched;
    }
  }
  if (!touched) return;
  focusKpCell(start.row, start.col);
  await saveKpDataChanges();
}
function kpRowValues(rowIndex){
  const row = kpRows[rowIndex];
  if (!row) return [];
  return row.values || [];
}
function handleKpCellFocus(row, col, input){
  if (!kpAllMode && !kpSuppressFocusSelection) selectKpCell(row, col, false);
  if (!input) return;
  input.select?.();
}
function handleKpCellMouseDown(event, row, col){
  if (!CAN_EDIT || kpAllMode) return true;
  if (event.button !== 0) return true;
  const input = event.currentTarget;
  if (input) {
    kpSuppressFocusSelection = true;
    input.focus();
    kpSuppressFocusSelection = false;
  }
  if (event.shiftKey && kpSelectionAnchor) {
    selectKpCell(kpSelectionAnchor.row, kpSelectionAnchor.col, true);
    selectKpCell(row, col, true);
  } else {
    selectKpCell(row, col, false);
  }
  if (input) input.select?.();
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
  const ctrlOrMeta = event.ctrlKey || event.metaKey;
  if (ctrlOrMeta && key.toLowerCase() === 'c') {
    event.preventDefault();
    copyKpSelectionToClipboard();
    return;
  }
  if (ctrlOrMeta && key.toLowerCase() === 'v') {
    event.preventDefault();
    pasteKpClipboard(row, col);
    return;
  }
  if (key === 'Delete' || key === 'Backspace') {
    event.preventDefault();
    clearKpSelectedCells(row, col);
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
    focusKpCell(nextRow, nextCol, event.shiftKey);
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
  clearKpSelection();
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
  meta.textContent = '';
}
function renderArchiveTable(){
  const tbody = document.getElementById('archiveBody');
  if (!tbody) return;
  if (!archiveRows.length) {
    archiveSelectedMeasurementKey = null;
    tbody.innerHTML = '<tr><td colspan="20" style="padding:14px;color:var(--muted);">Архив пуст</td></tr>';
    return;
  }
  const measurementSpans = new Map();
  const sectionSpans = new Map();
  let start = 0;
  while (start < archiveRows.length) {
    const base = archiveRows[start];
    const key = `${base.year}|${base.measurement_date}|${base.locomotive}|${base.repair_type}`;
    let end = start + 1;
    while (end < archiveRows.length) {
      const row = archiveRows[end];
      const rowKey = `${row.year}|${row.measurement_date}|${row.locomotive}|${row.repair_type}`;
      if (rowKey !== key) break;
      end += 1;
    }
    measurementSpans.set(start, end - start);
    start = end;
  }
  start = 0;
  while (start < archiveRows.length) {
    const base = archiveRows[start];
    const key = `${base.year}|${base.measurement_date}|${base.locomotive}|${base.repair_type}`;
    const section = String(base.section || base.values?.[0] || '1').trim() || '1';
    let end = start + 1;
    while (end < archiveRows.length) {
      const row = archiveRows[end];
      const rowKey = `${row.year}|${row.measurement_date}|${row.locomotive}|${row.repair_type}`;
      const rowSection = String(row.section || row.values?.[0] || '1').trim() || '1';
      if (rowKey !== key || rowSection !== section) break;
      end += 1;
    }
    sectionSpans.set(start, end - start);
    start = end;
  }
  tbody.innerHTML = archiveRows.map((row, rowIndex) => {
    const values = row.values || [];
    const rowMeta = archiveRows[rowIndex];
    const rowKey = archiveMeasurementKey(rowMeta);
    const prevKey = rowIndex > 0 ? archiveMeasurementKey(archiveRows[rowIndex - 1]) : '';
    const nextKey = rowIndex < archiveRows.length - 1 ? archiveMeasurementKey(archiveRows[rowIndex + 1]) : '';
    const rowClasses = ['measurement-row'];
    if (rowKey && rowKey !== prevKey) rowClasses.push('measurement-start');
    if (rowKey && rowKey !== nextKey) rowClasses.push('measurement-end');
    const cells = values.map((value, index) => {
      if (index === 0) {
        const span = measurementSpans.get(rowIndex);
        if (!span) return '';
        return `<td class="first-col" data-col="${index}" rowspan="${span}">${esc(value)}</td>`;
      }
      if (index === 1) {
        const span = sectionSpans.get(rowIndex);
        if (!span) return '';
        return `<td class="section-merged" data-col="${index}" rowspan="${span}">${esc(value)}</td>`;
      }
      if (index >= 2 && index <= 8) {
        const span = measurementSpans.get(rowIndex);
        if (!span) return '';
        const summaryClass = index === 7 || index === 8 ? 'summary-merged' : 'summary-merged';
        return `<td class="${summaryClass}" data-col="${index}" rowspan="${span}">${esc(value)}</td>`;
      }
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
      const cls = index === 9 ? 'axis-col' : 'summary';
      return `<td class="${cls}" data-col="${index}">${esc(value)}</td>`;
    }).filter(Boolean).join('');
    return `<tr class="${rowClasses.join(' ')}" data-row="${rowIndex}" data-year="${esc(row.year)}" data-measurement-date="${esc(row.measurement_date)}" data-locomotive="${esc(row.locomotive)}" data-repair-type="${esc(row.repair_type)}" data-source-r="${esc(row.source_r)}" onmousedown="setArchiveSelectedMeasurement(${rowIndex})">${cells}</tr>`;
  }).join('');
  renderArchiveSelectionHighlight();
  renderArchiveMeasurementSelection();
}
function renderTable(){
  const tbody = document.getElementById('inputBody');
  const loco = getCurrentLoco();
  const axisCount = getAxisCount(loco);
  const sectionCount = (state && String(loco) === String(state.locomotive || ''))
    ? Math.max(1, Number(state.section_count) || defaultSectionCount(axisCount))
    : Math.max(1, currentSectionCount(loco) || defaultSectionCount(axisCount));
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
  if (archiveSelectedMeasurementKey && !archiveRows.some(row => archiveMeasurementKey(row) === archiveSelectedMeasurementKey)) {
    archiveSelectedMeasurementKey = null;
  }
  renderArchiveTable();
  if (status) status.textContent = archiveRows.length ? `Записей: ${archiveRows.length}` : 'Архив пуст';
}
function toggleArchiveSort(){
  archiveSortDesc = !archiveSortDesc;
  loadArchive();
}
async function deleteSelectedArchiveMeasurement(){
  if (!CAN_EDIT) return;
  const focusMeta = archiveSelectionFocus ? archiveRowMeta(archiveSelectionFocus.row) : null;
  const selectedMeta = focusMeta || archiveRows.find(row => archiveMeasurementKey(row) === archiveSelectedMeasurementKey);
  if (!selectedMeta) {
    alert('Выберите строку архива для удаления.');
    return;
  }
  const labelParts = [selectedMeta.locomotive, selectedMeta.measurement_date, selectedMeta.repair_type].filter(Boolean);
  const ok = confirm(`Удалить замер из архива?\n\n${labelParts.join(' / ')}`);
  if (!ok) return;
  const status = document.getElementById('archiveStatus');
  if (status) status.textContent = 'Удаление из архива...';
  const res = await fetch(`${API}/api/archive`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json; charset=utf-8' },
    body: JSON.stringify({
      action: 'delete',
      year: selectedMeta.year,
      measurement_date: selectedMeta.measurement_date,
      locomotive: selectedMeta.locomotive,
      repair_type: selectedMeta.repair_type,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    if (status) status.textContent = err.error || err.message || 'Не удалось удалить запись архива';
    return;
  }
  archiveSelectedMeasurementKey = null;
  clearArchiveSelection();
  await loadArchive();
  if (status) status.textContent = 'Запись архива удалена';
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
  if (locomotiveSwitchPromise) {
    await locomotiveSwitchPromise.catch(() => undefined);
  }
  locomotiveSwitchPromise = switchLocomotive(String(nextValue ?? '').trim()).finally(() => {
    locomotiveSwitchPromise = null;
  });
  return locomotiveSwitchPromise;
}
async function switchLocomotive(next){
  if (initialLoadPromise) {
    await initialLoadPromise.catch(() => undefined);
  }
  const current = state?.locomotive || '';
  if (!next) {
    const input = document.getElementById('locomotive');
    if (input) input.value = current;
    return;
  }
  if (next === current) {
    locomotiveInputSource = 'loaded';
    renderMeta();
    hideLocoDropdown();
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
  return maybeSwitchLocomotive(document.getElementById('locomotive').value);
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
  if (event.key === 'Escape') {
    hideLocoDropdown();
    return;
  }
  if (event.key === 'Enter') {
    event.preventDefault();
    onLocomotiveCommit();
  }
});
document.getElementById('locomotive').addEventListener('focus', showLocoDropdown);
document.getElementById('locomotive').addEventListener('click', showLocoDropdown);
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
document.addEventListener('mousedown', event => {
  const picker = event.target.closest?.('.loco-picker');
  if (!picker) hideLocoDropdown();
});
document.getElementById('normsModal').addEventListener('mousedown', event => {
  if (event.target.id === 'normsModal') closeNormsDialog();
});
document.getElementById('archiveExportModal').addEventListener('mousedown', event => {
  if (event.target.id === 'archiveExportModal') closeArchiveExportDialog();
});
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && document.getElementById('normsModal')?.classList.contains('open')) {
    closeNormsDialog();
  }
  if (event.key === 'Escape' && document.getElementById('archiveExportModal')?.classList.contains('open')) {
    closeArchiveExportDialog();
  }
});
document.getElementById('measurementDate').addEventListener('change', onDateChange);
document.getElementById('repairType').addEventListener('change', onRepairChange);
document.getElementById('kpLocomotive').addEventListener('change', e => loadKpData(e.target.value));
document.getElementById('kpSearch').addEventListener('input', applyKpSearchFilter);
document.getElementById('archiveLocomotive').addEventListener('change', loadArchive);
document.getElementById('archiveSearch').addEventListener('input', loadArchive);
document.getElementById('archiveExcelFile').addEventListener('change', event => {
  const file = event.target.files?.[0];
  if (file) importArchiveExcelFile(file);
});
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

        if route == "/api/norms":
            if not require_auth(self):
                return
            send_json(self, {"rows": load_norms_rows()})
            return

        if route == "/api/archive-excel-template":
            if not require_auth(self):
                return
            try:
                data = archive_excel_template_bytes()
                send_file(
                    self,
                    data,
                    "Шаблон_импорта_архива.xlsx",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            except Exception as exc:
                send_json(self, {"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return

        if route == "/api/phone-export":
            if not require_auth(self):
                return
            try:
                qs = parse_qs(parsed.query)
                kind = text(qs.get("kind", ["archive"])[0]).strip().lower()
                selected_locomotives = [text(item).strip() for item in qs.get("locomotive", []) if text(item).strip()]
                date_from = text(qs.get("date_from", [""])[0]).strip()
                date_to = text(qs.get("date_to", [""])[0]).strip()
                payload = phone_export_payload(kind, selected_locomotives, date_from, date_to)
                send_json(self, payload)
            except Exception as exc:
                send_json(self, {"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return

        if route == "/api/archive-excel-export":
            if not require_auth(self):
                return
            try:
                qs = parse_qs(parsed.query)
                selected_locomotives = [text(item).strip() for item in qs.get("locomotive", []) if text(item).strip()]
                date_from = text(qs.get("date_from", [""])[0]).strip()
                date_to = text(qs.get("date_to", [""])[0]).strip()
                data, row_count = archive_excel_export_bytes(selected_locomotives, date_from, date_to)
                if row_count <= 0:
                    send_json(self, {"error": "По выбранным фильтрам данных нет."}, HTTPStatus.BAD_REQUEST)
                    return
                filename = f"Экспорт_архива_{dt.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.xlsx"
                send_file(self, data, filename, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            except Exception as exc:
                send_json(self, {"error": str(exc)}, HTTPStatus.BAD_REQUEST)
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
                if payload.get("action") == "delete":
                    result = delete_archive_measurement(payload)
                elif payload.get("changes"):
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

        if route == "/api/norms":
            if not require_auth(self, need_edit=True):
                return
            try:
                payload = json.loads(raw.decode("utf-8"))
                result = save_norms_rows(payload)
                if isinstance(result, tuple):
                    body, status = result
                    send_json(self, body, status)
                else:
                    send_json(self, result)
            except Exception as exc:
                send_json(self, {"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return

        if route == "/api/archive-excel-import":
            if not require_auth(self, need_edit=True):
                return
            try:
                payload = json.loads(raw.decode("utf-8"))
                encoded = text(payload.get("data")).strip()
                if not encoded:
                    send_json(self, {"error": "Файл Excel не передан."}, HTTPStatus.BAD_REQUEST)
                    return
                data = base64.b64decode(encoded)
                result = import_archive_excel_bytes(data)
                if isinstance(result, tuple):
                    body, status = result
                    send_json(self, body, status)
                else:
                    send_json(self, result)
            except Exception as exc:
                send_json(self, {"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return

        if route == "/api/phone-import":
            if not require_auth(self, need_edit=True):
                return
            try:
                payload = parse_phone_json_payload(raw)
                result = import_phone_payload(payload)
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
