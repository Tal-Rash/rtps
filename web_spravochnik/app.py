from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DB_FILE = ROOT.parent / "base" / "common_database.db"
APP_PREFIX = "/spravochnik"
SESSION_COOKIE = "grafik_ppr_session"
SESSION_TTL_SECONDS = 7 * 24 * 60 * 60
SHARED_DATA_DIR = ROOT.parent / "data"
AUTH_FILE = SHARED_DATA_DIR / "web_auth.json"
WEB_SECRET_FILE = SHARED_DATA_DIR / "web_secret.txt"
LEGACY_WEB_SECRET_FILE = DATA_DIR / "web_secret.txt"
DB_LOCK = Lock()

MONTHS = [
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]


def load_web_secret() -> str:
    return "opYbo6NB8pb7dChYQkmHEvUH6K4hAHjuzi2qEYOC024"


def load_legacy_web_secret() -> str:
    try:
        if LEGACY_WEB_SECRET_FILE.exists():
            return LEGACY_WEB_SECRET_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return ""


WEB_SECRET = load_web_secret()
LEGACY_WEB_SECRET = load_legacy_web_secret()


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
        json.dumps({"user": user, "view_password": view_password, "edit_password": edit_password}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return user, view_password, edit_password


WEB_USER, WEB_VIEW_PASSWORD, WEB_EDIT_PASSWORD = load_auth_config()


def ensure_db() -> None:
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_FILE) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS employees (
                y INT, pos TEXT, name TEXT, tab_num TEXT,
                milk INT DEFAULT 0, milk_issue INT DEFAULT 0,
                full_name TEXT DEFAULT '', milk_note TEXT DEFAULT '',
                PRIMARY KEY(y,pos,name)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS inventory (
                y INT, ser TEXT, num TEXT, inv TEXT,
                PRIMARY KEY(y,ser,num)
            )
            """
        )
        existing_inventory_cols = {row[1] for row in cur.execute("PRAGMA table_info(inventory)").fetchall()}
        if "sort_order" not in existing_inventory_cols:
            cur.execute("ALTER TABLE inventory ADD COLUMN sort_order INT")
        if "updated_at" not in existing_inventory_cols:
            cur.execute("ALTER TABLE inventory ADD COLUMN updated_at INT NOT NULL DEFAULT 0")
        if "deleted_at" not in existing_inventory_cols:
            cur.execute("ALTER TABLE inventory ADD COLUMN deleted_at INT NOT NULL DEFAULT 0")
        if "wheel_pair_count" not in existing_inventory_cols:
            cur.execute("ALTER TABLE inventory ADD COLUMN wheel_pair_count INT")
        if "section_count" not in existing_inventory_cols:
            cur.execute("ALTER TABLE inventory ADD COLUMN section_count INT")
        if "eight_digit_number" not in existing_inventory_cols:
            cur.execute("ALTER TABLE inventory ADD COLUMN eight_digit_number TEXT")
        cur.execute("UPDATE inventory SET sort_order = rowid WHERE sort_order IS NULL OR sort_order <= 0")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS ts_norms_data (
                y INT, r INT, c INT, v TEXT,
                PRIMARY KEY(y,r,c)
            )
            """
        )

        conn.commit()


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def text(value) -> str:
    return "" if value is None else str(value)



def parse_cookie_values(handler, name: str) -> list[str]:
    raw = handler.headers.get("Cookie", "")
    values = []
    for part in raw.split(";"):
        if "=" not in part: continue
        k, v = part.split("=", 1)
        if k.strip() == name: values.append(v.strip())
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
            return urllib.parse.unquote(user_id), urllib.parse.unquote(role), urllib.parse.unquote(modules), urllib.parse.unquote(safe_name)
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
    username = session[0]
    role = session[1]
    modules = session[2]
    
    if username != "legacy":
        try:
            conn = sqlite3.connect(ROOT.parent / "base" / "web_users.db")
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            user_row = cur.execute("SELECT role, allowed_modules FROM users WHERE id=?", (username,)).fetchone()
            conn.close()
            if not user_row:
                return None
            role = user_row["role"]
            modules = user_row["allowed_modules"] or ""
        except Exception:
            return None

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
        try:
            raw_cookie = handler.headers.get("Cookie", "")
            with open(ROOT.parent / "data" / "spravochnik_auth.log", "a", encoding="utf-8") as f:
                f.write(f"No session. Cookie header: {raw_cookie}\n")
        except Exception:
            pass
        handler.send_error(HTTPStatus.UNAUTHORIZED, "Unauthorized")
        return None
        
    mod_role = get_mod_role(session, "spravochnik")
    if not mod_role:
        try:
            with open(ROOT.parent / "data" / "spravochnik_auth.log", "a", encoding="utf-8") as f:
                f.write(f"Forbidden: spravochnik mod_role is none\n")
        except Exception:
            pass
        handler.send_error(HTTPStatus.FORBIDDEN, "Forbidden")
        return None
        
    if need_edit and mod_role not in ("edit", "editor", "admin"):
        try:
            with open(ROOT.parent / "data" / "spravochnik_auth.log", "a", encoding="utf-8") as f:
                f.write(f"Forbidden edit: role {mod_role} not allowed\n")
        except Exception:
            pass
        handler.send_error(HTTPStatus.FORBIDDEN, "Forbidden")
        return None
    return session

def send_html(handler: BaseHTTPRequestHandler, body: str, status: int = 200) -> None:
    data = body.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
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


def redirect(handler: BaseHTTPRequestHandler, location: str) -> None:
    handler.send_response(HTTPStatus.SEE_OTHER)
    handler.send_header("Location", location)
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()


def login_cookie(username: str) -> str:
    expiry = int(dt.datetime.now().timestamp()) + SESSION_TTL_SECONDS
    payload = f"{username}|edit|{expiry}"
    sig = hmac.new(WEB_SECRET.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    token = f"{payload}|{sig}"
    return f"{SESSION_COOKIE}={token}; HttpOnly; Path=/; SameSite=Lax; Max-Age={SESSION_TTL_SECONDS}"


def route_path(raw_path: str) -> str:
    path = urlparse(raw_path).path
    if path == APP_PREFIX:
        return "/"
    if path.startswith(APP_PREFIX + "/"):
        return path[len(APP_PREFIX):]
    return path


def load_state(year: int) -> dict:
    norms = [[MONTHS[r], "", "", "", "", "", "", ""] for r in range(12)]
    employees = []
    inventory = []
    with DB_LOCK, connect() as conn:
        cur = conn.cursor()
        for row in cur.execute("SELECT r, c, v FROM ts_norms_data WHERE y=?", (year,)):
            r, c = int(row["r"]), int(row["c"])
            if 0 <= r < 12 and 0 <= c < 8:
                norms[r][c] = text(row["v"])
        for row in cur.execute(
            "SELECT pos, name, full_name, tab_num, milk, milk_issue, milk_note FROM employees WHERE y=? ORDER BY rowid",
            (year,),
        ):
            employees.append([text(row[k]) for k in ("pos", "name", "full_name", "tab_num")] + [int(row["milk"] or 0), int(row["milk_issue"] or 0), text(row["milk_note"])])
        inventory_rows = cur.execute(
            """
            SELECT ser, num, inv, COALESCE(sort_order, 0) AS sort_order, COALESCE(updated_at, 0) AS updated_at, COALESCE(wheel_pair_count, 0) AS wheel_pair_count, COALESCE(section_count, 0) AS section_count, COALESCE(deleted_at, 0) AS deleted_at, COALESCE(eight_digit_number, '') AS eight_digit_number, rowid
            FROM inventory
            WHERE y=?
            ORDER BY COALESCE(sort_order, 0) ASC, COALESCE(updated_at, 0) DESC, rowid
            """,
            (year,),
        ).fetchall()
        best_inventory_rows: dict[str, sqlite3.Row] = {}
        for row in inventory_rows:
            ser = text(row["ser"]).strip()
            num = text(row["num"]).strip()
            if not (ser or num):
                continue
            key = f"{ser.upper()}|{num}"
            current = best_inventory_rows.get(key)
            if current is None or (
                int(row["updated_at"] or 0),
                int(row["deleted_at"] or 0),
                int(row["sort_order"] or 0),
                int(row["rowid"] or 0),
            ) > (
                int(current["updated_at"] or 0),
                int(current["deleted_at"] or 0),
                int(current["sort_order"] or 0),
                int(current["rowid"] or 0),
            ):
                best_inventory_rows[key] = row
        for row in sorted(
            best_inventory_rows.values(),
            key=lambda item: (
                int(item["sort_order"] or 0),
                -int(item["updated_at"] or 0),
                -int(item["deleted_at"] or 0),
                text(item["ser"]),
                text(item["num"]),
            ),
        ):
            inventory.append([
                text(row["ser"]),
                text(row["num"]),
                text(row["inv"]),
                int(row["wheel_pair_count"] or 0),
                int(row["section_count"] or 0),
                text(row["eight_digit_number"]),
                int(row["deleted_at"] or 0),
            ])
    return {"year": year, "norms": norms, "employees": employees, "inventory": inventory}


def save_state(payload: dict) -> None:
    year = int(payload.get("year") or dt.date.today().year)
    norms = payload.get("norms") or []
    employees = payload.get("employees") or []
    inventory = payload.get("inventory") or []
    with DB_LOCK, connect() as conn:
        cur = conn.cursor()
        cur.execute("BEGIN")
        cur.execute("DELETE FROM ts_norms_data WHERE y=?", (year,))
        norm_rows = []
        for r, row in enumerate(norms[:12]):
            for c, value in enumerate((row or [])[:8]):
                value = text(value).strip()
                if value:
                    norm_rows.append((year, r, c, value))
        cur.executemany("INSERT INTO ts_norms_data VALUES (?,?,?,?)", norm_rows)

        cur.execute("DELETE FROM employees WHERE y=?", (year,))
        emp_rows = []
        for row in employees:
            row = list(row or []) + [""] * 7
            pos, name, full_name, tab_num = [text(v).strip() for v in row[:4]]
            milk = 1 if row[4] else 0
            milk_issue = 1 if row[5] else 0
            milk_note = text(row[6]).strip()
            if pos or name:
                emp_rows.append((year, pos, name, full_name, tab_num, milk, milk_issue, milk_note))
        cur.executemany(
            """
            INSERT INTO employees (y, pos, name, full_name, tab_num, milk, milk_issue, milk_note)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            emp_rows,
        )

        existing_rows = cur.execute(
            """
            SELECT ser, num, inv, COALESCE(sort_order, 0) AS sort_order, COALESCE(updated_at, 0) AS updated_at, COALESCE(deleted_at, 0) AS deleted_at, COALESCE(wheel_pair_count, 0) AS wheel_pair_count, COALESCE(section_count, 0) AS section_count, COALESCE(eight_digit_number, '') AS eight_digit_number, rowid
            FROM inventory
            WHERE y=?
            """,
            (year,),
        ).fetchall()
        existing_map: dict[tuple[str, str], sqlite3.Row] = {}
        duplicate_rowids: list[int] = []
        for row in sorted(
            existing_rows,
            key=lambda item: (
                -int(item["updated_at"] or 0),
                -int(item["deleted_at"] or 0),
                int(item["sort_order"] or 0),
                int(item["rowid"] or 0),
            ),
        ):
            ser = text(row["ser"]).strip()
            num = text(row["num"]).strip()
            if not (ser or num):
                continue
            key = (ser.upper(), num)
            if key in existing_map:
                duplicate_rowids.append(int(row["rowid"]))
                continue
            existing_map[key] = row
        if duplicate_rowids:
            placeholders = ",".join("?" for _ in duplicate_rowids)
            cur.execute(f"DELETE FROM inventory WHERE rowid IN ({placeholders})", duplicate_rowids)
        submitted_keys: set[tuple[str, str]] = set()
        now = int(dt.datetime.now().timestamp() * 1000)
        for order_index, row in enumerate(inventory, start=1):
            row = list(row or []) + [""] * 7
            ser, num = [text(v).strip() for v in row[:2]]
            try:
                wheel_pair_count = int(row[3] or 0)
            except Exception:
                wheel_pair_count = 0
            try:
                section_count = int(row[4] or 0)
            except Exception:
                section_count = 0
            inv = text(row[2]).strip()
            eight_digit_number = text(row[5]).strip()
            try:
                deleted_at = int(row[6] or 0)
            except Exception:
                deleted_at = 0
            if not (ser or num):
                continue
            key = (ser.upper(), num)
            submitted_keys.add(key)
            if key in existing_map:
                existing_inv = text(existing_map[key]["inv"]).strip()
                inv_value = inv if inv else existing_inv
                cur.execute(
                    """
                    UPDATE inventory
                    SET inv=?, wheel_pair_count=?, section_count=?, eight_digit_number=?, sort_order=?, updated_at=?, deleted_at=?
                    WHERE y=? AND ser=? AND num=?
                    """,
                    (
                        inv_value,
                        wheel_pair_count or None,
                        section_count or None,
                        eight_digit_number,
                        order_index,
                        now,
                        deleted_at,
                        year,
                        text(existing_map[key]["ser"]).strip(),
                        num,
                    ),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO inventory (y, ser, num, inv, wheel_pair_count, section_count, eight_digit_number, sort_order, updated_at, deleted_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                    """,
                    (year, ser.upper(), num, inv, wheel_pair_count or None, section_count or None, eight_digit_number, order_index, now, deleted_at),
                )
        for (ser_key, num_key), row in existing_map.items():
            if (ser_key, num_key) in submitted_keys:
                continue
            if int(row["deleted_at"] or 0) > 0:
                continue
            cur.execute(
                """
                UPDATE inventory
                SET updated_at=?, deleted_at=?, sort_order=COALESCE(sort_order, ?)
                WHERE y=? AND ser=? AND num=?
                """,
                (now, now, len(inventory) + 1, year, text(row["ser"]).strip(), text(row["num"]).strip()),
            )
        conn.commit()


def purge_deleted_inventory() -> dict:
    with DB_LOCK, connect() as conn:
        cur = conn.cursor()
        deleted_rows = cur.execute(
            """
            SELECT y, ser, num
            FROM inventory
            WHERE COALESCE(deleted_at, 0) > 0
            """
        ).fetchall()
        if not deleted_rows:
            return {"ok": True, "purged": 0}
        numbers = [text(row["num"]).strip() for row in deleted_rows if text(row["num"]).strip()]
        cur.execute("DELETE FROM inventory WHERE COALESCE(deleted_at, 0) > 0")
        if numbers:
            placeholders = ",".join("?" for _ in numbers)
            cur.execute(f"DELETE FROM kp_data WHERE TRIM(COALESCE(locomotive, '')) IN ({placeholders})", numbers)
        conn.commit()
        return {"ok": True, "purged": len(deleted_rows)}


def purge_inventory_row(year: int, ser: str, num: str) -> dict:
    year = int(year)
    ser = text(ser).strip()
    num = text(num).strip()
    if not ser or not num:
        return {"ok": False, "error": "Некорректные данные локомотива."}
    with DB_LOCK, connect() as conn:
        cur = conn.cursor()
        row = cur.execute(
            """
            SELECT y, ser, num
            FROM inventory
            WHERE y=? AND TRIM(COALESCE(ser, ''))=? AND TRIM(COALESCE(num, ''))=?
            LIMIT 1
            """,
            (year, ser, num),
        ).fetchone()
        if not row:
            return {"ok": True, "purged": 0}
        cur.execute(
            "DELETE FROM inventory WHERE y=? AND TRIM(COALESCE(ser, ''))=? AND TRIM(COALESCE(num, ''))=?",
            (year, ser, num),
        )
        cur.execute("DELETE FROM kp_data WHERE TRIM(COALESCE(locomotive, ''))=?", (num,))
        conn.commit()
        return {"ok": True, "purged": 1}


HTML = """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Справочник</title>
  <style>
    :root{--line:#d9e2ef;--text:#102033;--muted:#66758a;--blue:#276ef1;--bg:#f4f7fb}
    *{box-sizing:border-box}
    body{margin:0;font-family:Segoe UI,Arial,sans-serif;background:var(--bg);color:var(--text)}
    .wrap{padding:16px;max-width:1500px;margin:0 auto}
    .top{display:flex;gap:10px;align-items:center;justify-content:space-between;background:#fff;border:1px solid #2f6fed;border-radius:18px;padding:14px 16px;margin-bottom:14px}
    h1{margin:0;font-size:24px}.muted{color:var(--muted);font-size:13px}
    .actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
    button,a,select{border:1px solid #2f6fed;border-radius:8px;padding:10px 13px;background:#fff;color:#1f57d6;font-weight:400;text-decoration:none;font:inherit}
    button:hover,a:hover{box-shadow:0 0 0 2px rgba(47,111,237,.10)}
    button.primary{background:var(--blue);border-color:var(--blue);color:#fff}
    button.primary:disabled{opacity:.78}
    .tabs{display:flex;gap:8px;margin-top:12px;flex-wrap:wrap;margin-bottom:-1px;padding-left:17px}
    .tab{background:#fff;border:1px solid #2f6fed;border-bottom-color:#2f6fed;padding:10px 14px;border-radius:10px 10px 0 0;font-weight:400;cursor:pointer;color:#1f57d6}
    .tab:hover{box-shadow:0 0 0 2px rgba(47,111,237,.10)}
    .tab.active{background:#2f6fed;color:#fff;border-color:#2f6fed;border-bottom-color:#2f6fed}
    .panel{display:none;background:#fff;border:1px solid #2f6fed;border-radius:18px;padding:14px;overflow:auto}
    .table-shell{margin-top:12px;background:#fff;border:1px solid #2f6fed;border-radius:18px;overflow:hidden}
    .panel.active{display:block}
    table{border-collapse:collapse;width:100%;min-width:760px}
    th,td{border:1px solid var(--line);padding:0;height:34px;text-align:center}
    th{background:#eef4fb;font-weight:700}
    td input{width:100%;height:34px;border:0;padding:6px 8px;font:inherit;text-align:center;background:transparent}
    td input[type=checkbox]{width:auto;height:auto}
    .left{text-align:left!important}
    .rowbar{display:flex;gap:8px;justify-content:flex-end;margin-bottom:10px}
    .inventory-actions{display:flex;gap:8px;align-items:center;justify-content:flex-end;flex-wrap:wrap;margin-bottom:10px}
    .selected-row{outline:2px solid #7aa7ff;outline-offset:-2px;background:#f3f8ff}
    .deleted-row{opacity:.55}
    .deleted-row td, .deleted-row td input{color:#8b96a8;text-decoration:line-through;text-decoration-thickness:1.5px}
    td input:focus,
    td input:focus-visible{
      outline:none;
      box-shadow:none;
    }
    .modal-backdrop{position:fixed;inset:0;background:rgba(16,32,51,.4);display:none;align-items:center;justify-content:center;padding:16px;z-index:20}
    .modal-backdrop.show{display:flex}
    .modal{width:min(520px,100%);background:#fff;border:1px solid var(--line);border-radius:18px;padding:18px;box-shadow:0 20px 60px rgba(16,32,51,.2)}
    .modal h2{margin:0 0 12px;font-size:22px}
    .modal-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}
    .modal-grid label{display:flex;flex-direction:column;gap:6px;font-weight:700}
    .modal-grid input{padding:10px 12px;border:1px solid var(--line);border-radius:10px;font:inherit}
    .modal-actions{display:flex;gap:8px;justify-content:flex-end;margin-top:14px}
    .modal-actions button{min-width:120px}
  </style>
</head>
<body>
<div class="wrap">
  <div class="top">
    <div>
      <h1>Справочник</h1>
      <div class="muted">Нормы времени, сотрудники, локомотивы. База: common_database.db</div>
    </div>
  <div class="actions">
      <a href="/">На главную</a>
      <button id="cancelBtn" title="Отмена" aria-label="Отмена" onclick="cancelChanges()">↺</button>
      <button id="restoreBtn" title="Вернуть" aria-label="Вернуть" onclick="restoreChanges()">↻</button>
      <label>Год <select id="year"></select></label>
      <button id="saveBtn" onclick="saveAll()">Сохранить</button>
    </div>
  </div>
  <div class="tabs">
    <button class="tab active" onclick="showTab('norms', this)">Нормы времени</button>
    <button class="tab" onclick="showTab('employees', this)">Сотрудники</button>
    <button class="tab" onclick="showTab('inventory', this)">Локомотивы</button>
  </div>
  <div id="norms" class="panel active"></div>
  <div id="employees" class="panel"></div>
  <div id="inventory" class="panel"></div>
</div>
<div id="addLocoModal" class="modal-backdrop" onclick="closeAddLocomotiveModal(event)">
  <div class="modal" onclick="event.stopPropagation()">
    <h2>Добавить локомотив</h2>
    <div class="modal-grid">
      <label>Серия
        <input id="newLocoSeries" autocomplete="off">
      </label>
      <label>Номер
        <input id="newLocoNumber" autocomplete="off">
      </label>
      <label>Кол-во к. пар
        <input id="newLocoWheelPairs" type="number" min="1" step="1" value="6">
      </label>
      <label>Кол-во секций
        <input id="newLocoSections" type="number" min="1" step="1" value="1">
      </label>
      <label>Инвентарный №
        <input id="newLocoInv" autocomplete="off">
      </label>
      <label style="grid-column:1 / -1">8-значный номер
        <input id="newLocoEight" autocomplete="off" inputmode="numeric" maxlength="8" placeholder="00000000">
      </label>
    </div>
    <div class="modal-actions">
      <button type="button" onclick="closeAddLocomotiveModal()">Отмена</button>
      <button type="button" class="primary" onclick="submitAddLocomotive()">Добавить</button>
    </div>
  </div>
</div>
<script>
const API = '/spravochnik';
const CAN_EDIT = {{CAN_EDIT}};
let state = null;
let savedState = null;
let canceledState = null;
const headers = {
  norms: ['Месяц','Кал. дни','Раб. дни','Вых и празд.','40-ч','36-ч','Переносы дней','Праздники'],
  employees: ['Должность','ФИО','ФИО полное','Таб. №','Молоко комп','Молоко выдача','Молоко прим.'],
  inventory: ['Серия','Номер','Инвентарный №','Кол-во КП','Ко-во секций','8-значный номер']
};

function fillYears(){
  const select = document.getElementById('year');
  const now = new Date().getFullYear();
  for(let y = now - 3; y <= now + 5; y++){
    const opt = document.createElement('option');
    opt.value = y; opt.textContent = y;
    if(y === now) opt.selected = true;
    select.appendChild(opt);
  }
  select.onchange = loadState;
}

async function loadState(){
  const year = document.getElementById('year').value;
  const res = await fetch(`${API}/api/state?year=${year}`, {cache:'no-store'});
  if(!res.ok){ alert('Не удалось загрузить справочник'); return; }
  state = await res.json();
  savedState = cloneState(state);
  canceledState = null;
  renderAll();
}

function renderAll(){
  renderTable('norms', state.norms, false);
  renderTable('employees', state.employees, true);
  renderTable('inventory', state.inventory, true);
  const saveBtn = document.getElementById('saveBtn');
  if (saveBtn) {
    saveBtn.style.display = CAN_EDIT ? '' : 'none';
  }
  updateHistoryButtons();
  updateSaveButton();
  syncInventoryActionButtons();
}

function renderTable(name, rows, editableRows){
  const panel = document.getElementById(name);
  const rowbar = (editableRows && CAN_EDIT)
    ? (
      name === 'inventory'
        ? (() => {
            const selectedRow = selected.inventory >= 0 ? state.inventory[selected.inventory] : null;
            const isDeleted = selectedRow ? Number(selectedRow[6] || 0) > 0 : false;
            return `<div class="rowbar">
              <button type="button" onclick="openAddLocomotiveModal()">Добавить локомотив</button>
              <button id="inventoryDeleteBtn" type="button" onclick="softDeleteInventory()" ${selected.inventory < 0 || isDeleted ? 'disabled' : ''}>Удалить</button>
              <button id="inventoryRestoreBtn" type="button" onclick="restoreInventoryRow()" ${selected.inventory < 0 || !isDeleted ? 'disabled' : ''}>Восстановить</button>
              <button id="inventoryPurgeBtn" type="button" onclick="purgeSelectedInventory()" ${selected.inventory < 0 || !isDeleted ? 'disabled' : ''}>Окончательно удалить</button>
            </div>`;
          })()
        : `<div class="rowbar"><button onclick="addRow('${name}')">+ строку</button><button onclick="deleteRow('${name}')">- строку</button></div>`
    )
    : '';
  let html = rowbar + '<div class="table-shell"><table><thead><tr><th style="width:42px">№</th>' + headers[name].map(h => `<th>${h}</th>`).join('') + '</tr></thead><tbody>';
  rows.forEach((row, r) => {
    const isDeleted = name === 'inventory' && Number(row[6] || 0) > 0;
    const draggable = name === 'inventory' && CAN_EDIT
      ? ' draggable="true" ondragstart="dragStartRow(event, ' + r + ')" ondragover="dragOverRow(event, ' + r + ')" ondrop="dropRow(event, ' + r + ')" ondragend="dragEndRow(event)"'
      : '';
    const isSelected = name === 'inventory' && selected.inventory === r;
    const rowClass = [
      isDeleted ? 'deleted-row' : '',
      isSelected ? 'selected-row' : '',
    ].filter(Boolean).join(' ');
    html += `<tr class="${rowClass}" onclick="selectRow('${name}', ${r})"${draggable}><td>${r + 1}</td>`;
    headers[name].forEach((_, c) => {
      const val = row[c] ?? '';
      if(name === 'employees' && (c === 4 || c === 5)){
        html += `<td><input type="checkbox" ${val ? 'checked' : ''} ${CAN_EDIT ? `onclick="event.stopPropagation()" onchange="setCell('${name}',${r},${c},this.checked)"` : 'disabled'}></td>`;
      } else if (name === 'inventory' && c === 2) {
        const cls = 'left';
        html += `<td><input class="${cls}" value="${escapeHtml(val)}" ${CAN_EDIT ? `onclick="event.stopPropagation(); selectInventoryRow(${r});" onfocus="selectInventoryRow(${r});" onmousedown="event.stopPropagation()" oninput="setCell('${name}',${r},${c},this.value)"` : 'readonly'}></td>`;
      } else if (name === 'inventory' && c === 3) {
        html += `<td><input class="num" value="${escapeHtml(val)}" ${CAN_EDIT ? `onclick="event.stopPropagation(); selectInventoryRow(${r});" onfocus="selectInventoryRow(${r});" onmousedown="event.stopPropagation()" oninput="setCell('${name}',${r},${c},this.value)"` : 'readonly'}></td>`;
      } else if (name === 'inventory' && c === 4) {
        html += `<td><input class="num" value="${escapeHtml(val)}" ${CAN_EDIT ? `onclick="event.stopPropagation(); selectInventoryRow(${r});" onfocus="selectInventoryRow(${r});" onmousedown="event.stopPropagation()" oninput="setCell('${name}',${r},${c},this.value)"` : 'readonly'}></td>`;
      } else if (name === 'inventory' && c === 5) {
        html += `<td><input class="num" value="${escapeHtml(val)}" ${CAN_EDIT ? `onclick="event.stopPropagation(); selectInventoryRow(${r});" onfocus="selectInventoryRow(${r});" onmousedown="event.stopPropagation()" oninput="setCell('${name}',${r},${c},this.value)"` : 'readonly'}></td>`;
      } else {
        const cls = c === 0 || (name === 'employees' && c < 3) || (name === 'inventory' && c === 2) ? 'left' : '';
        html += `<td><input class="${cls}" value="${escapeHtml(val)}" ${CAN_EDIT ? `onclick="event.stopPropagation(); selectInventoryRow(${r});" onfocus="selectInventoryRow(${r});" onmousedown="event.stopPropagation()" oninput="setCell('${name}',${r},${c},this.value)"` : 'readonly'}></td>`;
      }
    });
    html += '</tr>';
  });
  html += '</tbody></table></div>';
  panel.innerHTML = html;
}

let selected = {employees: -1, inventory: -1};
let draggedRowIndex = -1;
function selectRow(name, row){
  selected[name] = row;
  if (name === 'inventory') {
    syncInventoryActionButtons();
    updateInventorySelectionHighlight();
  }
}
function selectInventoryRow(row){
  selected.inventory = row;
  syncInventoryActionButtons();
  updateInventorySelectionHighlight();
}
function syncInventoryActionButtons(){
  const current = getSelectedInventoryRow();
  const isDeleted = current ? Number(current[6] || 0) > 0 : false;
  const deleteBtn = document.getElementById('inventoryDeleteBtn');
  const restoreBtn = document.getElementById('inventoryRestoreBtn');
  const purgeBtn = document.getElementById('inventoryPurgeBtn');
  if (deleteBtn) deleteBtn.disabled = selected.inventory < 0 || isDeleted;
  if (restoreBtn) restoreBtn.disabled = selected.inventory < 0 || !isDeleted;
  if (purgeBtn) purgeBtn.disabled = selected.inventory < 0 || !isDeleted;
}
function updateInventorySelectionHighlight(){
  const panel = document.getElementById('inventory');
  if (!panel) return;
  panel.querySelectorAll('tbody tr').forEach((tr, index) => {
    tr.classList.toggle('selected-row', index === selected.inventory);
  });
}
function setCell(name, row, col, value){ if (!CAN_EDIT) return; state[name][row][col] = value; updateSaveButton(); }
function addRow(name){
  if (!CAN_EDIT) return;
  if (name === 'inventory') {
    openAddLocomotiveModal();
    return;
  }
  const cols = headers[name].length;
  state[name].push(Array(cols).fill(''));
  renderTable(name, state[name], true);
  updateSaveButton();
}
function deleteRow(name){
  if (!CAN_EDIT) return;
  if (name === 'inventory') {
    softDeleteInventory();
    return;
  }
  const row = selected[name] >= 0 ? selected[name] : state[name].length - 1;
  if(row >= 0) state[name].splice(row, 1);
  selected[name] = -1;
  renderTable(name, state[name], true);
  updateSaveButton();
}
function getSelectedInventoryRow(){
  if (selected.inventory < 0 || !state.inventory[selected.inventory]) return null;
  return state.inventory[selected.inventory];
}
function softDeleteInventory(row){
  if (!CAN_EDIT) return;
  const targetRow = Number.isInteger(row) ? row : selected.inventory;
  if (targetRow < 0) return;
  const current = state.inventory[targetRow];
  if (Number(current[6] || 0) > 0) return;
  current[6] = Date.now();
  selected.inventory = targetRow;
  renderTable('inventory', state.inventory, true);
  syncInventoryActionButtons();
  updateSaveButton();
}
function restoreInventoryRow(row){
  if (!CAN_EDIT) return;
  const targetRow = Number.isInteger(row) ? row : selected.inventory;
  const current = targetRow >= 0 ? state.inventory[targetRow] : null;
  if (!current || Number(current[6] || 0) <= 0) return;
  current[6] = 0;
  selected.inventory = targetRow;
  renderTable('inventory', state.inventory, true);
  syncInventoryActionButtons();
  updateSaveButton();
}
async function purgeSelectedInventory(row){
  if (!CAN_EDIT) return;
  const targetRowIndex = Number.isInteger(row) ? row : selected.inventory;
  const targetRow = targetRowIndex >= 0 ? state.inventory[targetRowIndex] : null;
  if (!targetRow || Number(targetRow[6] || 0) <= 0) return;
  if (!confirm('Удалить окончательно выбранный локомотив?')) return;
  const target = targetRow;
  const year = Number(document.getElementById('year').value);
  const res = await fetch(`${API}/api/purge_inventory_row`, {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({year, ser: target[0], num: target[1]})
  });
  const data = await res.json().catch(() => ({}));
  if(!res.ok || data.ok === false){
    alert(data.error || 'Не удалось удалить окончательно');
    return;
  }
  state.inventory.splice(targetRowIndex, 1);
  selected.inventory = state.inventory.length ? Math.min(targetRowIndex, state.inventory.length - 1) : -1;
  renderTable('inventory', state.inventory, true);
  syncInventoryActionButtons();
  updateInventorySelectionHighlight();
  updateSaveButton();
  return;
}
function dragStartRow(event, row){
  if (!CAN_EDIT) return;
  if ((state.inventory[row] && Number(state.inventory[row][6] || 0) > 0)) {
    event.preventDefault();
    return;
  }
  draggedRowIndex = row;
  event.dataTransfer.effectAllowed = 'move';
  event.dataTransfer.setData('text/plain', String(row));
}
function dragOverRow(event, row){
  if (!CAN_EDIT) return;
  if (draggedRowIndex < 0 || draggedRowIndex === row) return;
  event.preventDefault();
  event.dataTransfer.dropEffect = 'move';
}
function dropRow(event, row){
  if (!CAN_EDIT) return;
  event.preventDefault();
  const from = draggedRowIndex;
  if (from < 0 || from === row) return;
  const rows = state.inventory;
  const [moved] = rows.splice(from, 1);
  rows.splice(row, 0, moved);
  selected.inventory = row;
  draggedRowIndex = -1;
  renderTable('inventory', rows, true);
  updateSaveButton();
}
function dragEndRow(){
  draggedRowIndex = -1;
}
async function saveAll(){
  if (!CAN_EDIT) return;
  if (!hasUnsavedChanges()) return;
  state.year = Number(document.getElementById('year').value);
  const res = await fetch(`${API}/api/save`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(state)});
  if(!res.ok){ alert('Ошибка сохранения'); return; }
  savedState = cloneState(state);
  canceledState = null;
  updateHistoryButtons();
  updateSaveButton();
}
function cloneState(value){
  return value ? JSON.parse(JSON.stringify(value)) : null;
}
function hasUnsavedChanges(){
  return JSON.stringify(state) !== JSON.stringify(savedState);
}
function updateSaveButton(){
  const saveBtn = document.getElementById('saveBtn');
  if (!saveBtn) return;
  const dirty = CAN_EDIT && hasUnsavedChanges();
  saveBtn.classList.toggle('primary', dirty);
  saveBtn.disabled = !CAN_EDIT;
  saveBtn.title = dirty ? 'Есть несохранённые изменения' : 'Изменений нет';
}
window.addEventListener('beforeunload', (event) => {
  if (!CAN_EDIT || !hasUnsavedChanges()) return;
  event.preventDefault();
  event.returnValue = '';
});
function updateHistoryButtons(){
  const cancelBtn = document.getElementById('cancelBtn');
  const restoreBtn = document.getElementById('restoreBtn');
  if (cancelBtn) cancelBtn.style.display = '';
  if (restoreBtn) restoreBtn.style.display = '';
  if (cancelBtn) cancelBtn.disabled = !CAN_EDIT || !savedState;
  if (restoreBtn) restoreBtn.disabled = !CAN_EDIT || !canceledState;
}
function cancelChanges(){
  if (!CAN_EDIT || !savedState) return;
  canceledState = cloneState(state);
  state = cloneState(savedState);
  selected = {employees:-1, inventory:-1};
  renderAll();
  alert('Отменено');
}
function restoreChanges(){
  if (!CAN_EDIT || !canceledState) return;
  state = cloneState(canceledState);
  canceledState = null;
  selected = {employees:-1, inventory:-1};
  renderAll();
  alert('Восстановлено');
}
async function purgeDeleted(){
  if (!CAN_EDIT) return;
  if (!confirm('Удалить окончательно все помеченные как удалённые локомотивы?')) return;
  const res = await fetch(`${API}/api/purge_deleted_inventory`, {method:'POST'});
  const data = await res.json().catch(() => ({}));
  if(!res.ok || data.ok === false){
    alert(data.error || 'Не удалось удалить окончательно');
    return;
  }
  await loadState();
}
function openAddLocomotiveModal(){
  if (!CAN_EDIT) return;
  document.getElementById('newLocoSeries').value = '';
  document.getElementById('newLocoNumber').value = '';
  document.getElementById('newLocoWheelPairs').value = '6';
  document.getElementById('newLocoSections').value = '1';
  document.getElementById('newLocoInv').value = '';
  document.getElementById('newLocoEight').value = '';
  document.getElementById('addLocoModal').classList.add('show');
  setTimeout(() => document.getElementById('newLocoSeries').focus(), 0);
}
function closeAddLocomotiveModal(event){
  if (event && event.target !== event.currentTarget) return;
  document.getElementById('addLocoModal').classList.remove('show');
}
function submitAddLocomotive(){
  if (!CAN_EDIT) return;
  const series = document.getElementById('newLocoSeries').value.trim();
  const number = document.getElementById('newLocoNumber').value.trim();
  const wheelPairs = Math.max(1, Number(document.getElementById('newLocoWheelPairs').value) || 1);
  const sections = Math.max(1, Number(document.getElementById('newLocoSections').value) || 1);
  const inv = document.getElementById('newLocoInv').value.trim();
  const eightDigit = document.getElementById('newLocoEight').value.trim();
  if (!series || !number) {
    alert('Заполните серию и номер локомотива');
    return;
  }
  const exists = state.inventory.some(row => (row[0] || '').trim() === series && (row[1] || '').trim() === number);
  if (exists) {
    alert('Такой локомотив уже есть в справочнике');
    return;
  }
  state.inventory.push([series, number, inv, wheelPairs, sections, eightDigit, 0]);
  selected.inventory = state.inventory.length - 1;
  closeAddLocomotiveModal();
  renderTable('inventory', state.inventory, true);
  updateSaveButton();
}
function showTab(id, btn){
  document.querySelectorAll('.panel').forEach(x => x.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  btn.classList.add('active');
}
function escapeHtml(value){
  return String(value ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
}
fillYears();
const params = new URLSearchParams(window.location.search);
const activeTab = params.get('tab');
if (activeTab) {
  const btn = document.querySelector(`.tab[onclick="showTab('${activeTab}', this)"]`);
  if (btn) {
    showTab(activeTab, btn);
  }
}
loadState();
</script>
</body>
</html>
"""

LOGIN_HTML = """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Вход - Справочник</title>
  <style>
    body{margin:0;font-family:Segoe UI,Arial,sans-serif;background:#f4f7fb;color:#102033}
    .card{max-width:420px;margin:10vh auto;background:#fff;border:1px solid #d9e2ef;border-radius:18px;padding:24px;box-shadow:0 12px 32px rgba(16,32,51,.08)}
    input,button{width:100%;padding:12px;border-radius:8px;border:1px solid #d9e2ef;font:inherit}
    button{background:#276ef1;color:#fff;font-weight:400;cursor:pointer;border:0}
    .muted{color:#607086;font-size:13px}
  </style>
</head>
<body>
  <form class="card" method="post" action="/spravochnik/login">
    <h1 style="margin-top:0;">Вход</h1>
    <p class="muted">Введите пароль для входа.</p>
    <input name="user" placeholder="Логин" value="{{USER}}" style="margin-bottom:10px;">
    <input name="password" type="password" placeholder="Пароль" style="margin-bottom:12px;">
    <button type="submit">Войти</button>
  </form>
</body>
</html>
"""



from fastapi import FastAPI, Request, Response, Depends, Form, HTTPException, Cookie, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
import urllib.parse
import traceback

app = FastAPI(title="RTPS Spravochnik")

@app.middleware("http")
async def strip_prefix(request: Request, call_next):
    if request.scope["path"].startswith(APP_PREFIX + "/"):
        request.scope["path"] = request.scope["path"][len(APP_PREFIX):]
    return await call_next(request)

def _cookie_value_fastapi(username: str, role: str) -> str:
    payload = f"{username}:{role}:{int(dt.datetime.now().timestamp())}"
    signature = hmac.new(WEB_SECRET.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}:{signature}"

def _verify_cookie_fastapi(value: str) -> tuple[str, str, str, str] | None:
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
                
            return urllib.parse.unquote(user_id), urllib.parse.unquote(role), urllib.parse.unquote(modules), urllib.parse.unquote(safe_name)
        except Exception:
            continue
    return None

def get_current_session_fastapi(request: Request):
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        return _verify_cookie_fastapi(cookie)
    return None

def get_mod_role_fastapi(session: tuple[str, str, str, str] | None, module: str) -> str:
    if not session:
        return ""
    username = session[0]
    role = session[1]
    modules = session[2]
    
    if username != "legacy":
        try:
            conn = sqlite3.connect(ROOT.parent / "base" / "web_users.db")
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            user_row = cur.execute("SELECT role, allowed_modules FROM users WHERE id=?", (username,)).fetchone()
            conn.close()
            if not user_row:
                return ""
            role = user_row["role"]
            modules = user_row["allowed_modules"] or ""
        except Exception:
            return ""

    if role == "admin":
        return "admin"
    for part in modules.split(","):
        part = part.strip()
        if not part: continue
        if ":" in part:
            k, v = part.split(":", 1)
            if k == module: return v
        else:
            if part == module: return role
    return ""

def require_auth_fastapi(request: Request, need_edit: bool = False):
    session = get_current_session_fastapi(request)
    role = get_mod_role_fastapi(session, "spravochnik")
    if not role:
        return False, None
    if need_edit and role not in ("edit", "editor", "admin"):
        return False, None
    return True, session

def json_response(data: dict | list, status_code: int = 200) -> JSONResponse:
    return JSONResponse(content=data, status_code=status_code)

@app.get("/spravochnik", response_class=HTMLResponse)
@app.get("/", response_class=HTMLResponse)
async def home_route(request: Request):
    session = get_current_session_fastapi(request)
    mod_role = get_mod_role_fastapi(session, "spravochnik") if session else None
    
    if not session or not mod_role:
        html = LOGIN_HTML.replace("{{USER}}", WEB_USER)
        return HTMLResponse(content=html, headers={"WWW-Authenticate": 'Form realm="Spravochnik"'}, status_code=401)
        
    auth_badge = "Редактирование" if mod_role in ("edit", "editor", "admin") else "Просмотр"
    html_content = HTML.replace("{{USER}}", WEB_USER).replace("{{AUTH_BADGE}}", auth_badge).replace("{{CAN_EDIT}}", "true" if mod_role in ("edit", "editor", "admin") else "false")
    
    response = HTMLResponse(content=html_content)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response

@app.get("/login")
async def login_get(request: Request):
    session = get_current_session_fastapi(request)
    if session:
        return RedirectResponse("/", status_code=303)
    html = LOGIN_HTML.replace("{{USER}}", WEB_USER)
    return HTMLResponse(content=html)

@app.get("/logout")
async def logout_route():
    response = HTMLResponse(content='<!doctype html><meta http-equiv="refresh" content="0; url=/spravochnik/">')
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="lax")
    response.headers["Cache-Control"] = "no-store"
    return response

@app.get("/api/state")
async def get_state(request: Request, year: int = None):
    auth_ok, session = require_auth_fastapi(request)
    if not auth_ok:
        return Response("Unauthorized", status_code=401)
    if year is None:
        year = dt.date.today().year
    return json_response(load_state(year))

@app.post("/login")
async def login_post(request: Request):
    form = await request.form()
    password = form.get("password", "")
    if password == WEB_EDIT_PASSWORD:
        expiry = int(dt.datetime.now().timestamp()) + SESSION_TTL_SECONDS
        payload = f"{WEB_USER}|edit|{expiry}"
        sig = hmac.new(WEB_SECRET.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
        token = f"{payload}|{sig}"
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(SESSION_COOKIE, token, max_age=SESSION_TTL_SECONDS, path="/", httponly=True, samesite="lax")
        return response
    
    html = LOGIN_HTML.replace("{{USER}}", WEB_USER).replace("{{AUTH_BADGE}}", "Неверный логин или пароль")
    return HTMLResponse(content=html, status_code=401)

@app.post("/api/save")
async def post_save(request: Request):
    auth_ok, session = require_auth_fastapi(request, need_edit=True)
    if not auth_ok:
        return json_response({"error": "Unauthorized"}, status_code=401)
    try:
        payload = await request.json()
        save_state(payload)
        return json_response({"ok": True})
    except Exception as exc:
        return json_response({"ok": False, "error": str(exc)}, status_code=400)

@app.post("/api/purge_deleted_inventory")
async def post_purge_deleted(request: Request):
    auth_ok, session = require_auth_fastapi(request, need_edit=True)
    if not auth_ok:
        return json_response({"error": "Unauthorized"}, status_code=401)
    try:
        return json_response(purge_deleted_inventory())
    except Exception as exc:
        return json_response({"ok": False, "error": str(exc)}, status_code=400)

@app.post("/api/purge_inventory_row")
async def post_purge_row(request: Request):
    auth_ok, session = require_auth_fastapi(request, need_edit=True)
    if not auth_ok:
        return json_response({"error": "Unauthorized"}, status_code=401)
    try:
        payload = await request.json()
        y = payload.get("year", dt.date.today().year)
        ser = payload.get("ser", "")
        num = payload.get("num", "")
        return json_response(purge_inventory_row(y, ser, num))
    except Exception as exc:
        return json_response({"ok": False, "error": str(exc)}, status_code=400)

@app.get("/debug_nginx")
def debug_nginx():
    import subprocess
    from fastapi import Response
    try:
        res = subprocess.run(["cat", "/etc/nginx/sites-enabled/grafik-ppr"], capture_output=True, text=True)
        return Response(content=res.stdout + "\nSTDERR:\n" + res.stderr, media_type="text/plain")
    except Exception as e:
        return Response(content=str(e), media_type="text/plain")

def main() -> None:
    ensure_db()
    host = os.environ.get("WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("WEB_PORT", "8002"))
    url = f"http://{host}:{port}{APP_PREFIX}"
    print(f"Справочник ready (FastAPI): {url}")
    if host in {"127.0.0.1", "localhost", "0.0.0.0"}:
        import threading, webbrowser
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    uvicorn.run("app:app", host=host, port=port, reload=False)

if __name__ == "__main__":
    main()
