from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import sys
from pathlib import Path
from threading import Lock
from urllib.parse import unquote

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
from rtps_common import connect_sqlite, module_has_access, resolve_user_access

DATA_DIR = ROOT / "data"
DB_FILE = DATA_DIR / "alsn.db"
WEB_USERS_DB = ROOT.parent / "base" / "web_users.db"
WEB_SECRET_FILE = ROOT.parent / "data" / "web_secret.txt"
LEGACY_WEB_SECRET_FILE = DATA_DIR / "web_secret.txt"
SESSION_COOKIE = "rtps_session"
APP_PREFIX = "/alsn"
APP_VERSION = "web-alsn-1.1"
DB_LOCK = Lock()
MAIN_LOGIN_URL = os.environ.get("MAIN_LOGIN_URL", "http://yrtps.ru/login")


def load_web_secret() -> str:
    if WEB_SECRET_FILE.exists():
        return WEB_SECRET_FILE.read_text(encoding="utf-8").strip()
    return "opYbo6NB8pb7dChYQkmHEvUH6K4hAHjuzi2qEYOC024"


WEB_SECRET = load_web_secret()


def _verify_cookie(value: str) -> tuple[str, str, str, str] | None:
    if not value:
        return None
    for sep in (":", "|"):
        parts = value.rsplit(sep, 5)
        if len(parts) == 6:
            user_id, role, mods, full_name, expiry_text, sig = parts
            raw = f"{user_id}{sep}{role}{sep}{mods}{sep}{full_name}{sep}{expiry_text}"
        elif len(parts) == 5:
            user_id, role, mods, full_name, sig = parts
            raw = f"{user_id}{sep}{role}{sep}{mods}{sep}{full_name}"
            expiry_text = "2000000000"
        else:
            continue
        exp_sig = hmac.new(WEB_SECRET.encode(), raw.encode(), hashlib.sha256).hexdigest()
        if not secrets.compare_digest(sig, exp_sig):
            continue
        if float(expiry_text) < dt.datetime.now().timestamp():
            return None
        return unquote(user_id), unquote(role), unquote(mods), unquote(full_name)
    return None


def get_session(request: Request):
    cookie = request.cookies.get(SESSION_COOKIE)
    if not cookie:
        return None
    session = _verify_cookie(cookie)
    if not session:
        return None
    user_id, role, mods, full_name = session
    resolved = resolve_user_access(WEB_USERS_DB, user_id, role, mods)
    if not resolved:
        return None
    role, mods = resolved
    if not module_has_access(role, mods, "alsn"):
        return None
    can_edit = (
        role == "admin"
        or "admin" in mods
        or "alsn:edit" in mods
        or (role in ("edit", "editor") and ("alsn" in mods.split(",") or "alsn:view" in mods))
    )
    return {
        "user_id": user_id,
        "role": role,
        "modules": mods,
        "full_name": full_name,
        "can_edit": can_edit,
    }


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with connect_sqlite(DB_FILE) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS locomotives (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sort_order INTEGER NOT NULL,
                series TEXT NOT NULL DEFAULT '',
                number TEXT NOT NULL DEFAULT '',
                inventory_num TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                devices_json TEXT NOT NULL DEFAULT '[]'
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS warehouse (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sort_order INTEGER NOT NULL,
                type TEXT NOT NULL DEFAULT '',
                number TEXT NOT NULL DEFAULT '',
                verification_date TEXT NOT NULL DEFAULT '',
                periodicity TEXT NOT NULL DEFAULT '',
                next_verification_date TEXT NOT NULL DEFAULT '',
                location TEXT NOT NULL DEFAULT ''
            )
            """
        )

        cur = conn.cursor()
        cur.execute("PRAGMA table_info(locomotives)")
        columns = {str(row[1]) for row in cur.fetchall()}
        if "devices_json" not in columns:
            conn.execute("ALTER TABLE locomotives ADD COLUMN devices_json TEXT NOT NULL DEFAULT '[]'")

        cur.execute("PRAGMA table_info(warehouse)")
        warehouse_columns = {str(row[1]) for row in cur.fetchall()}
        for column in [
            "type",
            "number",
            "verification_date",
            "periodicity",
            "next_verification_date",
            "location",
        ]:
            if column not in warehouse_columns:
                conn.execute(f"ALTER TABLE warehouse ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")

        cur.execute("SELECT COUNT(*) FROM locomotives")
        if int(cur.fetchone()[0] or 0) == 0:
            conn.execute(
                "INSERT INTO locomotives(sort_order, series, number, inventory_num, note, devices_json) VALUES(?,?,?,?,?,?)",
                (1, "", "", "", "", "[]"),
            )

        cur.execute("SELECT COUNT(*) FROM warehouse")
        if int(cur.fetchone()[0] or 0) == 0:
            conn.execute(
                "INSERT INTO warehouse(sort_order, type, number, verification_date, periodicity, next_verification_date, location) VALUES(?,?,?,?,?,?,?)",
                (1, "", "", "", "", "", ""),
            )
        elif {"item", "unit", "quantity", "note"} & warehouse_columns:
            conn.execute(
                """
                UPDATE warehouse
                SET
                    type = CASE WHEN type = '' AND item <> '' THEN item ELSE type END,
                    number = CASE WHEN number = '' AND unit <> '' THEN unit ELSE number END,
                    verification_date = CASE WHEN verification_date = '' AND quantity <> '' THEN quantity ELSE verification_date END,
                    location = CASE WHEN location = '' AND note <> '' THEN note ELSE location END
                """
            )


init_db()


app = FastAPI(title="RTPS ALSN")
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="alsn_static")
app.mount(f"{APP_PREFIX}/static", StaticFiles(directory=str(ROOT / "static")), name="alsn_static_prefixed")
templates = Jinja2Templates(directory=str(ROOT / "templates"))


@app.get("/", response_class=HTMLResponse)
@app.get(f"{APP_PREFIX}", include_in_schema=False)
@app.get(f"{APP_PREFIX}/", response_class=HTMLResponse, include_in_schema=False)
async def index(request: Request):
    session = get_session(request)
    if not session:
        return RedirectResponse(f"{MAIN_LOGIN_URL}?next=/alsn", status_code=303)
    context = {
        "request": request,
        "APP_PREFIX": APP_PREFIX,
        "APP_VERSION": APP_VERSION,
        "CAN_EDIT": "true" if session["can_edit"] else "false",
        "USER_NAME": session["full_name"],
    }
    return templates.TemplateResponse(request=request, name="index.html", context=context)


@app.get("/api/state")
@app.get(f"{APP_PREFIX}/api/state", include_in_schema=False)
async def api_state(request: Request):
    session = get_session(request)
    if not session:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    with DB_LOCK, connect_sqlite(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        locomotives = [
            {
                "series": row["series"],
                "number": row["number"],
                "inventory_num": row["inventory_num"],
                "note": row["note"],
                "devices": _parse_devices_json(row["devices_json"]),
            }
            for row in cur.execute("SELECT series, number, inventory_num, note, devices_json FROM locomotives ORDER BY sort_order, id").fetchall()
        ]
        warehouse = [
            {
                "type": row["type"],
                "number": row["number"],
                "verification_date": row["verification_date"],
                "periodicity": row["periodicity"],
                "next_verification_date": row["next_verification_date"],
                "location": row["location"],
            }
            for row in cur.execute(
                "SELECT type, number, verification_date, periodicity, next_verification_date, location FROM warehouse ORDER BY sort_order, id"
            ).fetchall()
        ]
    return {"locomotives": locomotives, "warehouse": warehouse}


def _normalize_rows(rows, fields):
    normalized = []
    if not isinstance(rows, list):
        return normalized
    for row in rows:
        if not isinstance(row, dict):
            continue
        normalized.append({field: str(row.get(field, "") or "") for field in fields})
    if not normalized:
        normalized.append({field: "" for field in fields})
    return normalized


def _normalize_warehouse_rows(rows):
    normalized = []
    if not isinstance(rows, list):
        rows = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        normalized.append({
            "type": str(row.get("type", "") or ""),
            "number": str(row.get("number", "") or ""),
            "verification_date": str(row.get("verification_date", "") or ""),
            "periodicity": str(row.get("periodicity", "") or ""),
            "next_verification_date": str(row.get("next_verification_date", "") or ""),
            "location": str(row.get("location", "") or ""),
        })
    if not normalized:
        normalized.append({
            "type": "",
            "number": "",
            "verification_date": "",
            "periodicity": "",
            "next_verification_date": "",
            "location": "",
        })
    return normalized


def _blank_device_rows(count: int = 5) -> list[dict[str, str]]:
    return [{"type": "", "number": ""} for _ in range(max(1, count))]


def _parse_devices_json(value) -> list[dict[str, str]]:
    try:
        parsed = json.loads(str(value or "[]"))
    except Exception:
        parsed = []
    if not isinstance(parsed, list):
        parsed = []
    normalized = []
    for row in parsed:
        if not isinstance(row, dict):
            continue
        normalized.append({
            "type": str(row.get("type", "") or ""),
            "number": str(row.get("number", "") or ""),
        })
    return normalized or _blank_device_rows()


def _normalize_locomotives(rows):
    normalized = []
    if not isinstance(rows, list):
        rows = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        devices = row.get("devices")
        if not isinstance(devices, list):
            devices = []
        normalized.append({
            "series": str(row.get("series", "") or ""),
            "number": str(row.get("number", "") or ""),
            "inventory_num": str(row.get("inventory_num", "") or ""),
            "note": str(row.get("note", "") or ""),
            "devices": [
                {
                    "type": str(device.get("type", "") or ""),
                    "number": str(device.get("number", "") or ""),
                }
                for device in devices
                if isinstance(device, dict)
            ] or _blank_device_rows(),
        })
    if not normalized:
        normalized.append({
            "series": "",
            "number": "",
            "inventory_num": "",
            "note": "",
            "devices": _blank_device_rows(),
        })
    return normalized


@app.post("/api/state")
@app.post(f"{APP_PREFIX}/api/state", include_in_schema=False)
async def api_save_state(request: Request):
    session = get_session(request)
    if not session or not session["can_edit"]:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    payload = await request.json()
    locomotives = _normalize_locomotives(payload.get("locomotives"))
    warehouse = _normalize_warehouse_rows(payload.get("warehouse"))

    with DB_LOCK, connect_sqlite(DB_FILE) as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM locomotives")
        cur.execute("DELETE FROM warehouse")
        cur.executemany(
            "INSERT INTO locomotives(sort_order, series, number, inventory_num, note, devices_json) VALUES(?,?,?,?,?,?)",
            [
                (
                    idx + 1,
                    row["series"],
                    row["number"],
                    row["inventory_num"],
                    row["note"],
                    json.dumps(row["devices"], ensure_ascii=False),
                )
                for idx, row in enumerate(locomotives)
            ],
        )
        cur.executemany(
            "INSERT INTO warehouse(sort_order, type, number, verification_date, periodicity, next_verification_date, location) VALUES(?,?,?,?,?,?,?)",
            [
                (
                    idx + 1,
                    row["type"],
                    row["number"],
                    row["verification_date"],
                    row["periodicity"],
                    row["next_verification_date"],
                    row["location"],
                )
                for idx, row in enumerate(warehouse)
            ],
        )
        conn.commit()

    return {"ok": True}


if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("WEB_PORT", "8008"))
    uvicorn.run("app:app", host=host, port=port, reload=False, log_level="info")
