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
APP_VERSION = "web-zkp-1.85"
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


ROOT = Path(__file__).parent
SHARED_DATA_DIR = ROOT.parent / "data"

def load_web_secret() -> str:
    return "opYbo6NB8pb7dChYQkmHEvUH6K4hAHjuzi2qEYOC024"

WEB_SECRET = load_web_secret()
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
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS app_meta (
                k TEXT PRIMARY KEY,
                v TEXT
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


def verify_cookie(value: str) -> tuple[str, str, str, str] | None:
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
            if LEGACY_WEB_SECRET and LEGACY_WEB_SECRET not in secrets_to_try:
                secrets_to_try.append(LEGACY_WEB_SECRET)
                
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

def current_session(handler) -> tuple[str, str, str, str] | None:
    for token in parse_cookie_values(handler, SESSION_COOKIE):
        session = verify_cookie(token)
        if session:
            return session
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

def require_auth(handler, need_edit: bool = False) -> tuple[str, str, str, str] | None:
    session = current_session(handler)
    if not session:
        handler.send_error(HTTPStatus.UNAUTHORIZED, "Unauthorized")
        return None
    mod_role = get_mod_role(session, "zamer_kp")
    if not mod_role:
        handler.send_error(HTTPStatus.FORBIDDEN, "Forbidden")
        return None
    if need_edit and mod_role not in ("edit", "editor", "admin"):
        handler.send_error(HTTPStatus.FORBIDDEN, "Forbidden")
        return None
    return session

def route_path(path: str) -> str:
    if path == APP_PREFIX:
        return "/"
    if path.startswith(APP_PREFIX + "/"):
        return path[len(APP_PREFIX) :] or "/"
    return path



from fastapi import FastAPI, Request, Response, Depends, Form, HTTPException, Cookie, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
import urllib.parse
import traceback

app = FastAPI(title="RTPS Zamer KP")

@app.middleware("http")
async def strip_prefix(request: Request, call_next):
    if request.scope["path"].startswith(APP_PREFIX + "/"):
        request.scope["path"] = request.scope["path"][len(APP_PREFIX):]
    return await call_next(request)

app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")

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
            elif len(parts) == 5:
                user_id, role, modules, safe_name, sig = parts
                payload = f"{user_id}{sep}{role}{sep}{modules}{sep}{safe_name}"
                expiry_text = "2000000000"
            elif len(parts) == 4:
                username, role, expiry_text, sig = parts
                payload = f"{username}{sep}{role}{sep}{expiry_text}"
                user_id, modules, safe_name = username, "", username
            else:
                continue
                
            secrets_to_try = [WEB_SECRET]
                
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
                
            return user_id, role, modules, urllib.parse.unquote(safe_name)
        except Exception:
            continue
    return None

def get_current_session(request: Request):
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        return _verify_cookie(cookie)
    return None

def get_mod_role(session: tuple[str, str, str, str] | None, module: str) -> str:
    if not session:
        return ""
    _, role, modules, _ = session
    if role == "admin":
        return "admin"
    if role == "viewer":
        return "viewer"
    if module in modules.split(","):
        return "edit" if role == "editor" else role
    return ""

def require_auth_fastapi(request: Request, need_edit: bool = False):
    if not AUTH_ENABLED:
        return True, None
    session = get_current_session(request)
    role = get_mod_role(session, "zamer_kp")
    if not role:
        return False, None
    if need_edit and role not in ("edit", "editor", "admin"):
        return False, None
    return True, session

def json_response(data: dict | list, status_code: int = 200) -> JSONResponse:
    return JSONResponse(content=data, status_code=status_code)

@app.get("/zamer-kp", response_class=HTMLResponse)
@app.get("/", response_class=HTMLResponse)
async def home_route(request: Request):
    session = get_current_session(request)
    mod_role = get_mod_role(session, "zamer_kp")
    
    if not session or not mod_role:
        with open(ROOT / "templates" / "login.html", "r", encoding="utf-8") as f:
            html = f.read().replace("{{APP_PREFIX}}", APP_PREFIX)
        return HTMLResponse(content=html, headers={"WWW-Authenticate": 'Form realm="Zamer KP"'}, status_code=401)
        
    html_content = render_page(mod_role)
    response = HTMLResponse(content=html_content)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response

@app.get("/logout")
async def logout_route():
    return RedirectResponse("/", status_code=303)

@app.get("/api/state")
async def get_state(request: Request, locomotive: str = ""):
    auth_ok, session = require_auth_fastapi(request)
    if not auth_ok:
        return Response("Unauthorized", status_code=401)
    return json_response(load_state(locomotive.strip()))

@app.get("/api/archive")
async def get_archive(request: Request, locomotive: str = "", search: str = "", sort: str = "desc"):
    auth_ok, session = require_auth_fastapi(request)
    if not auth_ok:
        return Response("Unauthorized", status_code=401)
    rows = load_archive_rows(locomotive.strip(), search.strip(), sort.strip().lower() != "asc")
    return json_response({"rows": rows})

@app.get("/api/kp-data")
async def get_kp_data(request: Request, locomotive: str = ""):
    auth_ok, session = require_auth_fastapi(request)
    if not auth_ok:
        return Response("Unauthorized", status_code=401)
    return json_response(load_kp_view(locomotive.strip()))

@app.get("/api/norms")
async def get_norms(request: Request):
    auth_ok, session = require_auth_fastapi(request)
    if not auth_ok:
        return Response("Unauthorized", status_code=401)
    return json_response({"rows": load_norms_rows()})

@app.get("/api/archive-excel-template")
async def export_archive_template(request: Request):
    auth_ok, session = require_auth_fastapi(request)
    if not auth_ok:
        return Response("Unauthorized", status_code=401)
    try:
        data = archive_excel_template_bytes()
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename*=UTF-8''%D0%A8%D0%B0%D0%B1%D0%BB%D0%BE%D0%BD_%D0%B8%D0%BC%D0%BF%D0%BE%D1%80%D1%82%D0%B0_%D0%B0%D1%80%D1%85%D0%B8%D0%B2%D0%B0.xlsx"}
        )
    except Exception as exc:
        return json_response({"error": str(exc)}, status_code=400)

@app.get("/api/phone-export")
async def export_phone(request: Request, kind: str = "archive", date_from: str = "", date_to: str = ""):
    try:
        query_params = request.query_params
        selected_locomotives = [item.strip() for item in query_params.getlist("locomotive") if item.strip()]
        payload = phone_export_payload(kind.strip().lower(), selected_locomotives, date_from.strip(), date_to.strip())
        return json_response(payload)
    except Exception as exc:
        return json_response({"error": str(exc)}, status_code=400)

@app.get("/api/archive-excel-export")
async def export_archive_excel(request: Request, date_from: str = "", date_to: str = ""):
    auth_ok, session = require_auth_fastapi(request)
    if not auth_ok:
        return Response("Unauthorized", status_code=401)
    try:
        query_params = request.query_params
        selected_locomotives = [item.strip() for item in query_params.getlist("locomotive") if item.strip()]
        data, row_count = archive_excel_export_bytes(selected_locomotives, date_from.strip(), date_to.strip())
        if row_count <= 0:
            return json_response({"error": "По выбранным фильтрам данных нет."}, status_code=400)
        filename = f"Экспорт_архива_{dt.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.xlsx"
        from urllib.parse import quote
        safe_filename = quote(filename)
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{safe_filename}"}
        )
    except Exception as exc:
        return json_response({"error": str(exc)}, status_code=400)

@app.post("/api/state")
async def post_state(request: Request):
    auth_ok, session = require_auth_fastapi(request, need_edit=True)
    if not auth_ok:
        return json_response({"error": "Unauthorized"}, status_code=401)
    try:
        payload = await request.json()
        saved = save_state(payload, full_name=session[3] if session and len(session) > 3 else "")
        return json_response(saved)
    except Exception as exc:
        return json_response({"error": str(exc)}, status_code=400)

@app.post("/api/archive")
async def post_archive(request: Request):
    auth_ok, session = require_auth_fastapi(request, need_edit=True)
    if not auth_ok:
        return json_response({"error": "Unauthorized"}, status_code=401)
    try:
        payload = await request.json()
        if payload.get("action") == "delete":
            result = delete_archive_measurement(payload)
        elif payload.get("changes"):
            result = update_archive_cells(payload)
        else:
            result = save_archive(payload)
            
        if isinstance(result, tuple):
            return json_response(result[0], status_code=result[1])
        return json_response(result)
    except Exception as exc:
        return json_response({"error": str(exc)}, status_code=400)

@app.post("/api/kp-data")
async def post_kp_data(request: Request):
    auth_ok, session = require_auth_fastapi(request, need_edit=True)
    if not auth_ok:
        return json_response({"error": "Unauthorized"}, status_code=401)
    try:
        payload = await request.json()
        result = save_kp_data(payload)
        if isinstance(result, tuple):
            return json_response(result[0], status_code=result[1])
        return json_response(result)
    except Exception as exc:
        return json_response({"error": str(exc)}, status_code=400)

@app.post("/api/norms")
async def post_norms(request: Request):
    auth_ok, session = require_auth_fastapi(request, need_edit=True)
    if not auth_ok:
        return json_response({"error": "Unauthorized"}, status_code=401)
    try:
        payload = await request.json()
        result = save_norms_rows(payload)
        if isinstance(result, tuple):
            return json_response(result[0], status_code=result[1])
        return json_response(result)
    except Exception as exc:
        return json_response({"error": str(exc)}, status_code=400)

@app.post("/api/archive-excel-import")
async def post_archive_import(request: Request):
    auth_ok, session = require_auth_fastapi(request, need_edit=True)
    if not auth_ok:
        return json_response({"error": "Unauthorized"}, status_code=401)
    try:
        payload = await request.json()
        encoded = text(payload.get("data")).strip()
        if not encoded:
            return json_response({"error": "Файл Excel не передан."}, status_code=400)
        import base64
        data = base64.b64decode(encoded)
        result = import_archive_excel_bytes(data)
        if isinstance(result, tuple):
            return json_response(result[0], status_code=result[1])
        return json_response(result)
    except Exception as exc:
        return json_response({"error": str(exc)}, status_code=400)

@app.post("/api/phone-import")
async def post_phone_import(request: Request):
    try:
        raw = await request.body()
        payload = parse_phone_json_payload(raw)
        result = import_phone_payload(payload)
        if isinstance(result, tuple):
            return json_response(result[0], status_code=result[1])
        return json_response(result)
    except Exception as exc:
        return json_response({"error": str(exc)}, status_code=400)

def main() -> None:
    ensure_db()
    host = os.environ.get("WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("WEB_PORT", "8003"))
    url = f"http://{host}:{port}{APP_PREFIX}"
    print(f"Замер КП ready (FastAPI): {url}")
    if host in {"127.0.0.1", "localhost", "0.0.0.0"}:
        import threading, webbrowser
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    uvicorn.run("app:app", host=host, port=port, reload=True)

if __name__ == "__main__":
    main()
