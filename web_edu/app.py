from __future__ import annotations

import datetime as dt
import json
import sqlite3
import os
import sys
from pathlib import Path
from threading import Lock
from urllib.parse import unquote
import hmac
import hashlib
import re

from fastapi import FastAPI, Request, Response, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
from rtps_common import connect_sqlite, module_has_access, resolve_user_access

SHARED_DATA_DIR = ROOT.parent / "data"
WEB_SECRET_FILE = SHARED_DATA_DIR / "web_secret.txt"
DB_FILE = ROOT.parent / "base" / "common_database.db"
WEB_USERS_DB = ROOT.parent / "base" / "web_users.db"
SESSION_COOKIE = "rtps_session"
APP_PREFIX = "/edu"
APP_VERSION = "web-edu-2.9"
DB_LOCK = Lock()
MAIN_LOGIN_URL = os.environ.get("MAIN_LOGIN_URL", "/login")

def load_web_secret() -> str:
    if WEB_SECRET_FILE.exists():
        return WEB_SECRET_FILE.read_text(encoding="utf-8").strip()
    return "opYbo6NB8pb7dChYQkmHEvUH6K4hAHjuzi2qEYOC024"

WEB_SECRET = load_web_secret()

def init_db():
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        # Ensure training columns table
        cur.execute("CREATE TABLE IF NOT EXISTS training_columns (name TEXT, sort_order INTEGER, period_months INTEGER DEFAULT 12)")
        try:
            cur.execute("ALTER TABLE training_columns ADD COLUMN period_months INTEGER DEFAULT 12")
            conn.commit()
        except sqlite3.OperationalError:
            pass
            
        cur.execute("SELECT COUNT(*) FROM training_columns")
        if cur.fetchone()[0] == 0:
            default_cols = [("ПТМ", 0, 12), ("наряды-допуска\n(П 38-01-2019)", 1, 12), ("СИЗ", 2, 12), ("Высота", 3, 36), ("Стропальщик", 4, 24), ("Три шага", 5, 12)]
            cur.executemany("INSERT INTO training_columns (name, sort_order, period_months) VALUES (?, ?, ?)", default_cols)
            conn.commit()

        # Ensure employee trainings table
        cur.execute("CREATE TABLE IF NOT EXISTS employee_trainings (tab_num TEXT, training_type TEXT, last_date TEXT, period_months INTEGER, protocol_num TEXT, PRIMARY KEY (tab_num, training_type))")
        try:
            cur.execute("ALTER TABLE employee_trainings ADD COLUMN protocol_num TEXT")
            conn.commit()
        except sqlite3.OperationalError:
            pass

        cur.execute("CREATE TABLE IF NOT EXISTS position_categories (pos TEXT PRIMARY KEY, category TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS employee_row_order (tab_num TEXT PRIMARY KEY, sort_order INTEGER NOT NULL)")

def connect():
    return connect_sqlite(DB_FILE)

init_db()

app = FastAPI(title="RTPS Обучение")
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")
app.mount(f"{APP_PREFIX}/static", StaticFiles(directory=str(ROOT / "static")), name="edu_static")
templates = Jinja2Templates(directory=str(ROOT / "templates"))

def verify_cookie(value: str) -> tuple[str, str, str, str] | None:
    if not value: return None
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
        exp_sig = hmac.new(load_web_secret().encode(), raw.encode(), hashlib.sha256).hexdigest()
        import secrets
        if not secrets.compare_digest(sig, exp_sig):
            continue
        if float(expiry_text) < dt.datetime.now().timestamp():
            return None
        return unquote(user_id), unquote(role), unquote(mods), unquote(full_name)
    return None

def get_session(request: Request):
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        session = verify_cookie(cookie)
        if session:
            user_id, role, mods, full_name = session
            resolved = resolve_user_access(WEB_USERS_DB, user_id, role, mods)
            if not resolved:
                return None
            role, mods = resolved
            if module_has_access(role, mods, "edu"):
                can_edit = (
                    role == "admin"
                    or "admin" in mods
                    or "edu:edit" in mods
                    or (role in ("edit", "editor") and ("edu" in mods.split(",") or "edu:view" in mods))
                )
                return {
                    "user_id": user_id,
                    "role": role,
                    "modules": mods,
                    "full_name": full_name,
                    "can_edit": can_edit,
                }
    return None

@app.get(f"{APP_PREFIX}", include_in_schema=False)
async def prefixed_index_redirect():
    return RedirectResponse(f"{APP_PREFIX}/", status_code=303)

@app.get("/", response_class=HTMLResponse)
@app.get(f"{APP_PREFIX}/", response_class=HTMLResponse, include_in_schema=False)
async def index(request: Request):
    session = get_session(request)
    if not session:
        return RedirectResponse(f"{MAIN_LOGIN_URL}?next=/edu", status_code=303)
        
    context = {
        "request": request,
        "APP_PREFIX": APP_PREFIX,
        "APP_VERSION": APP_VERSION,
        "USER_NAME": session["full_name"],
        "CAN_EDIT": "true" if session["can_edit"] else "false"
    }
    return templates.TemplateResponse(request=request, name="index.html", context=context)

def normalize_date_iso(val: str | None) -> str:
    """Приводит дату к формату YYYY-MM-DD для надежного сравнения и отображения"""
    if not val:
        return ""
    s = str(val).strip()
    if not s:
        return ""
    if len(s) == 10 and s[4] == '-' and s[7] == '-':
        return s
    s_clean = s.replace('/', '.').replace('-', '.')
    parts = s_clean.split('.')
    if len(parts) == 3:
        p1, p2, p3 = parts[0].strip(), parts[1].strip(), parts[2].strip()
        if len(p1) == 4 and p1.isdigit():
            return f"{p1}-{p2.zfill(2)}-{p3.zfill(2)}"
        if len(p3) in (2, 4) and p3.isdigit():
            y = p3 if len(p3) == 4 else ("20" + p3)
            return f"{y}-{p2.zfill(2)}-{p1.zfill(2)}"
    return s

@app.get("/api/state")
@app.get(f"{APP_PREFIX}/api/state", include_in_schema=False)
async def api_state(request: Request):
    session = get_session(request)
    if not session: return JSONResponse({"error": "Unauthorized"}, status_code=401)
    
    with DB_LOCK, connect() as conn:
        cur = conn.cursor()
        
        # Загрузка колонок (типов обучения)
        cols = cur.execute("SELECT name, period_months FROM training_columns ORDER BY sort_order").fetchall()
        columns = [{"name": c["name"], "period_months": c["period_months"] or 12} for c in cols]
        
        # Загрузка сотрудников из справочника строго в порядке rowid (порядок справочника)
        cur_year = dt.date.today().year
        today = dt.date.today().isoformat()
        
        emp_rows = cur.execute("""
            SELECT e.rowid, e.y, e.name, e.full_name, e.tab_num, e.pos,
                   e.hire_date, e.exclude_date, e.is_excluded,
                   COALESCE(pc.category, 'workers') as category
            FROM employees e
            LEFT JOIN position_categories pc ON e.pos = pc.pos
            WHERE e.y = ? AND e.name IS NOT NULL AND TRIM(e.name) != ''
            ORDER BY e.rowid
        """, (cur_year,)).fetchall()
        
        if not emp_rows:
            emp_rows = cur.execute("""
                SELECT e.rowid, e.y, e.name, e.full_name, e.tab_num, e.pos,
                       e.hire_date, e.exclude_date, e.is_excluded,
                       COALESCE(pc.category, 'workers') as category
                FROM employees e
                LEFT JOIN position_categories pc ON e.pos = pc.pos
                WHERE e.y = (SELECT MAX(y) FROM employees) AND e.name IS NOT NULL AND TRIM(e.name) != ''
                ORDER BY e.rowid
            """).fetchall()

        employees = []
        for idx, r in enumerate(emp_rows, start=1):
            raw_tab = str(r["tab_num"] or "").strip()
            num_part = idx
            if raw_tab.startswith("ID_"):
                digits = "".join(ch for ch in raw_tab if ch.isdigit())
                if digits:
                    num_part = int(digits)
            anon_id = raw_tab if raw_tab else f"ID_{num_part:03d}"
            anon_short = f"Работник №{num_part}"
            anon_pos = f"Должность №{num_part}"

            hire_iso = normalize_date_iso(r["hire_date"])
            exc_iso = normalize_date_iso(r["exclude_date"])
            is_exc = int(r["is_excluded"] or 0) == 1

            # Сотрудник считается уволенным, если стоит флаг исключения или дата увольнения уже наступила
            is_dismissed = is_exc or (bool(exc_iso) and exc_iso <= today)
            
            # Назначено увольнение в будущем (дата увольнения еще не наступила)
            is_pending_dismissal = (not is_dismissed) and bool(exc_iso) and (exc_iso > today)
            
            # Прием на работу в будущем
            is_future_hire = bool(hire_iso) and (hire_iso > today)

            employees.append({
                "fio": anon_short,
                "tab_num": anon_id,
                "position": anon_pos,
                "category": r["category"],
                "hire_date": hire_iso,
                "exclude_date": exc_iso,
                "is_dismissed": bool(is_dismissed),
                "is_pending_dismissal": bool(is_pending_dismissal),
                "is_future_hire": bool(is_future_hire),
                "row_order": idx
            })
        
        # Загрузка записей об обучении
        t_rows = cur.execute("SELECT tab_num, training_type, last_date, period_months, protocol_num FROM employee_trainings").fetchall()
        
        trainings = {}
        for r in t_rows:
            t_tab = r["tab_num"]
            if t_tab not in trainings:
                trainings[t_tab] = {}
            trainings[t_tab][r["training_type"]] = {
                "last": r["last_date"],
                "period_months": r["period_months"] or 12,
                "protocol": r["protocol_num"] or ""
            }
            
    return {"columns": columns, "employees": employees, "trainings": trainings}

@app.post("/api/save_training")
@app.post(f"{APP_PREFIX}/api/save_training", include_in_schema=False)
async def save_training(request: Request, data: dict):
    session = get_session(request)
    if not session or not session["can_edit"]: return JSONResponse({"error": "Unauthorized"}, status_code=401)
    
    tab_num = data.get("tab_num")
    t_type = data.get("training_type")
    last_date = data.get("last_date")
    period_months = data.get("period_months", 12)
    if not tab_num or not t_type:
        return JSONResponse({"error": "Missing tab_num or training_type"}, status_code=400)
    try:
        period_months = int(period_months or 12)
    except (TypeError, ValueError):
        return JSONResponse({"error": "Invalid period_months"}, status_code=400)
    if last_date:
        try:
            dt.date.fromisoformat(last_date)
        except ValueError:
            return JSONResponse({"error": "Invalid last_date"}, status_code=400)
    
    with DB_LOCK, connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM employee_trainings WHERE tab_num=? AND training_type=?", (tab_num, t_type))
        if cur.fetchone():
            cur.execute("UPDATE employee_trainings SET last_date=?, period_months=? WHERE tab_num=? AND training_type=?", 
                        (last_date, period_months, tab_num, t_type))
        else:
            cur.execute("INSERT INTO employee_trainings (tab_num, training_type, last_date, period_months) VALUES (?, ?, ?, ?)", 
                        (tab_num, t_type, last_date, period_months))
        conn.commit()
    return {"status": "ok"}

@app.post("/api/save_protocol")
@app.post(f"{APP_PREFIX}/api/save_protocol", include_in_schema=False)
async def save_protocol(request: Request, data: dict):
    session = get_session(request)
    if not session or not session["can_edit"]: return JSONResponse({"error": "Unauthorized"}, status_code=401)
    
    tab_num = data.get("tab_num")
    t_type = data.get("training_type")
    protocol = data.get("protocol")
    if not tab_num or not t_type:
        return JSONResponse({"error": "Missing tab_num or training_type"}, status_code=400)
    
    with DB_LOCK, connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM employee_trainings WHERE tab_num=? AND training_type=?", (tab_num, t_type))
        if cur.fetchone():
            cur.execute("UPDATE employee_trainings SET protocol_num=? WHERE tab_num=? AND training_type=?", 
                        (protocol, tab_num, t_type))
        else:
            cur.execute("INSERT INTO employee_trainings (tab_num, training_type, protocol_num) VALUES (?, ?, ?)", 
                        (tab_num, t_type, protocol))
        conn.commit()
    return {"status": "ok"}

@app.post("/api/settings/columns")
@app.post(f"{APP_PREFIX}/api/settings/columns", include_in_schema=False)
async def save_columns(request: Request):
    data = await request.json()
    # data is list of dicts: [{"name": "ПТМ", "period_months": 12}, ...]
    session = get_session(request)
    if not session or not session["can_edit"]: return JSONResponse({"error": "Unauthorized"}, status_code=401)
    
    with DB_LOCK, connect() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM training_columns")
        for idx, col in enumerate(data):
            name = str(col.get("name", "")).strip()
            if not name:
                continue
            try:
                period_months = int(col.get("period_months", 12) or 12)
            except (TypeError, ValueError):
                period_months = 12
            period_months = max(1, min(period_months, 1200))
            cur.execute("INSERT INTO training_columns (name, sort_order, period_months) VALUES (?, ?, ?)", 
                        (name, idx, period_months))
            # Also update periods in existing trainings
            cur.execute("UPDATE employee_trainings SET period_months=? WHERE training_type=?", (period_months, name))
        conn.commit()
    return {"status": "ok"}

@app.post("/api/settings/categories")
@app.post(f"{APP_PREFIX}/api/settings/categories", include_in_schema=False)
async def save_categories(request: Request, data: dict):
    session = get_session(request)
    if not session or not session["can_edit"]: return JSONResponse({"error": "Unauthorized"}, status_code=401)
    
    try:
        with DB_LOCK, connect() as conn:
            cur = conn.cursor()
            for pos, cat in data.items():
                cur.execute(
                    "INSERT INTO position_categories (pos, category) VALUES (?, ?) ON CONFLICT(pos) DO UPDATE SET category=excluded.category",
                    (pos, cat)
                )
        return {"ok": True}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post("/api/settings/employee_order")
@app.post(f"{APP_PREFIX}/api/settings/employee_order", include_in_schema=False)
async def save_employee_order(request: Request, data: list[str]):
    session = get_session(request)
    if not session or not session["can_edit"]:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    tab_nums = [str(tab_num).strip() for tab_num in data if str(tab_num).strip()]
    if not tab_nums:
        return {"status": "ok"}

    cur_year = dt.date.today().year
    try:
        with DB_LOCK, connect() as conn:
            cur = conn.cursor()
            # Обновление таблицы порядка employee_row_order
            cur.execute("DELETE FROM employee_row_order")
            for idx, tab_num in enumerate(tab_nums):
                cur.execute(
                    "INSERT INTO employee_row_order (tab_num, sort_order) VALUES (?, ?)",
                    (tab_num, idx)
                )

            # Синхронизация порядка с таблицей employees за текущий год (как в справочнике)
            existing = cur.execute("SELECT * FROM employees WHERE y=?", (cur_year,)).fetchall()
            if existing:
                col_names = [d[0] for d in cur.description if d[0] != 'rowid']
                by_tab = {str(r["tab_num"]).strip(): dict(r) for r in existing}
                ordered_rows = []
                for tab in tab_nums:
                    if tab in by_tab:
                        ordered_rows.append(by_tab.pop(tab))
                # Добавляем оставшихся сотрудников (если кто-то был скрыт или не передан)
                ordered_rows.extend(by_tab.values())

                cur.execute("DELETE FROM employees WHERE y=?", (cur_year,))
                placeholders = ",".join(["?"] * len(col_names))
                insert_sql = f"INSERT INTO employees ({','.join(col_names)}) VALUES ({placeholders})"
                cur.executemany(insert_sql, [[r[c] for c in col_names] for r in ordered_rows])

            conn.commit()
        return {"status": "ok"}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

if __name__ == "__main__":
    import uvicorn
    host = os.environ.get('WEB_HOST', '127.0.0.1')
    port = int(os.environ.get('WEB_PORT', 8007))
    uvicorn.run('app:app', host=host, port=port, reload=False)
