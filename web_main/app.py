from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from http import HTTPStatus
from pathlib import Path
import re

from fastapi import FastAPI, Request, Response, Form, Depends, HTTPException, Cookie, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import uvicorn

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
SHARED_DATA_DIR = ROOT.parent / "data"
AUTH_FILE = SHARED_DATA_DIR / "web_auth.json"
ACCESS_STATE_FILE = SHARED_DATA_DIR / "web_access.json"
WEB_SECRET_FILE = SHARED_DATA_DIR / "web_secret.txt"
LEGACY_WEB_SECRET_FILE = DATA_DIR / "web_secret.txt"
SESSION_COOKIE = "grafik_ppr_session"
SESSION_TTL_SECONDS = 7 * 24 * 60 * 60

FAILED_ATTEMPTS: dict[str, list[float]] = {}
DB_FILE = ROOT.parent / "base" / "common_database.db"

app = FastAPI(title="RTPS Web Main")
templates = Jinja2Templates(directory=str(ROOT / "templates"))

def load_web_secret() -> str:
    if WEB_SECRET_FILE.exists():
        return WEB_SECRET_FILE.read_text(encoding="utf-8").strip()
    SHARED_DATA_DIR.mkdir(parents=True, exist_ok=True)
    sec = secrets.token_urlsafe(32)
    WEB_SECRET_FILE.write_text(sec, encoding="utf-8")
    return sec

def load_legacy_web_secret() -> str:
    if LEGACY_WEB_SECRET_FILE.exists():
        return LEGACY_WEB_SECRET_FILE.read_text(encoding="utf-8").strip()
    return ""

def load_auth_config() -> tuple[str, str, str]:
    if not AUTH_FILE.exists():
        SHARED_DATA_DIR.mkdir(parents=True, exist_ok=True)
        AUTH_FILE.write_text(json.dumps({"user": "user", "view_password": "123", "edit_password": "456"}, indent=2), encoding="utf-8")
    try:
        cfg = json.loads(AUTH_FILE.read_text(encoding="utf-8"))
        return cfg.get("user", "user"), cfg.get("view_password", "123"), cfg.get("edit_password", "456")
    except Exception:
        return "user", "123", "456"

WEB_USER, WEB_VIEW_PASSWORD, WEB_EDIT_PASSWORD = load_auth_config()

def init_db() -> None:
    try:
        DB_FILE.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    password TEXT UNIQUE NOT NULL,
                    full_name TEXT NOT NULL,
                    role TEXT NOT NULL,
                    allowed_modules TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS login_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_name TEXT NOT NULL,
                    login_time TEXT NOT NULL
                )
            """)
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM users")
            if cur.fetchone()[0] == 0:
                conn.execute(
                    "INSERT INTO users (password, full_name, role, allowed_modules) VALUES (?, ?, ?, ?)",
                    ("12345", "Администратор (Главный)", "admin", "zamer_kp,grafik_ppr,spravochnik,tabel,admin")
                )
                print("Создан администратор по умолчанию. Пароль: 12345")
    except Exception as e:
        print("Ошибка инициализации БД:", e)

init_db()

def _cookie_value(user_id: str, role: str, modules: str, full_name: str) -> str:
    import urllib.parse
    sec = load_web_secret()
    enc_id = urllib.parse.quote(user_id)
    enc_r = urllib.parse.quote(role)
    enc_m = urllib.parse.quote(modules)
    enc_f = urllib.parse.quote(full_name)
    raw = f"{enc_id}|{enc_r}|{enc_m}|{enc_f}"
    sig = hmac.new(sec.encode(), raw.encode(), hashlib.sha256).hexdigest()
    return f"{raw}|{sig}"

def _verify_cookie(value: str) -> tuple[str, str, str, str] | None:
    if not value: return None
    import urllib.parse
    parts = value.split("|")
    if len(parts) != 5:
        # Check legacy web_main formats (3 or 4 parts)
        # This part handles backward compatibility if needed, omitting for brevity or simplifying
        pass
    if len(parts) == 5:
        sec = load_web_secret()
        raw = "|".join(parts[:4])
        sig = parts[4]
        exp_sig = hmac.new(sec.encode(), raw.encode(), hashlib.sha256).hexdigest()
        if secrets.compare_digest(sig, exp_sig):
            return urllib.parse.unquote(parts[0]), urllib.parse.unquote(parts[1]), urllib.parse.unquote(parts[2]), urllib.parse.unquote(parts[3])
    # Also support legacy secrets
    legacy_sec = load_legacy_web_secret()
    if legacy_sec and len(parts) == 4:
        raw = "|".join(parts[:3])
        sig = parts[3]
        exp_sig = hmac.new(legacy_sec.encode(), raw.encode(), hashlib.sha256).hexdigest()
        if secrets.compare_digest(sig, exp_sig):
             return urllib.parse.unquote(parts[0]), urllib.parse.unquote(parts[1]), urllib.parse.unquote(parts[2]), ""
    return None

def get_current_session(request: Request):
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        session = _verify_cookie(cookie)
        if session:
            user_id = session[0]
            role = session[1]
            modules = session[2]
            if user_id != "legacy":
                try:
                    conn = sqlite3.connect(DB_FILE)
                    conn.row_factory = sqlite3.Row
                    cur = conn.cursor()
                    user_row = cur.execute("SELECT role, allowed_modules FROM users WHERE id=?", (user_id,)).fetchone()
                    conn.close()
                    if user_row:
                        role = user_row["role"]
                        modules = user_row["allowed_modules"] or ""
                except Exception as e:
                    import traceback
                    print("DB check error:", traceback.format_exc())
            return {"user_id": user_id, "role": role, "modules": modules, "full_name": session[3]}
    return None

# Helpers for users template
def parse_mods(modules_str):
    mods = {}
    for part in modules_str.split(","):
        part = part.strip()
        if not part: continue
        if ":" in part:
            k, v = part.split(":", 1)
            mods[k] = v
        else:
            mods[part] = "legacy"
    return mods

def get_mod_role(mods, mod_name, user_role):
    r = mods.get(mod_name, "none")
    if r == "legacy":
        r = "edit" if user_role in ("edit", "editor", "admin") else "view"
    return r

def get_client_ip(request: Request):
    x_real = request.headers.get("X-Real-IP")
    if x_real: return x_real.split(",")[0].strip()
    x_fwd = request.headers.get("X-Forwarded-For")
    if x_fwd: return x_fwd.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


@app.get("/debug_logs")
def debug_logs():
    import subprocess
    try:
        res = subprocess.run(["cat", "/etc/nginx/sites-enabled/default"], capture_output=True, text=True)
        return Response(content=res.stdout + "\nSTDERR:\n" + res.stderr, media_type="text/plain")
    except Exception as e:
        return Response(content=str(e), media_type="text/plain")


@app.get("/", response_class=HTMLResponse)
async def home_page(request: Request):
    session = get_current_session(request)
    if not session:
        return RedirectResponse("/login", status_code=303)
    
    role_label = {
        "admin": "Администратор", "editor": "Редактор", "viewer": "Зритель", "pending": "Ожидает"
    }.get(session["role"], session["role"])
    
    auth_badge = f"{session['full_name']} ({role_label})"
    
    users_link = ""
    logs_link = ""
    if session["role"] == "admin" or "admin" in session["modules"]:
        users_link = '<a class="badge" href="/users" style="background:#276ef1; color:#fff; border-color:#276ef1;">Управление доступом</a>'
        logs_link = '<a class="badge" href="/logs" style="background:#475569; color:#fff; border-color:#475569;">Журнал</a>'
        
    def link_for(mod_name, url):
        mods = session["modules"]
        role = session["role"]
        has_access = False
        if role == "admin" or "admin" in mods: has_access = True
        elif f"{mod_name}:edit" in mods or f"{mod_name}:view" in mods or mod_name in mods.split(","): has_access = True
        if has_access: return f'<a href="{url}">Открыть модуль →</a>'
        return '<a class="disabled" href="#">Нет доступа</a>'
        
    context = {
        "request": request,
        "STARTED_AT": dt.datetime.now().strftime("%d.%m.%Y %H:%M"),
        "AUTH_BADGE": auth_badge,
        "USERS_LINK": users_link,
        "LOGS_LINK": logs_link,
        "GRAFIK_PPR_LINK": link_for("grafik_ppr", "/grafik-ppr"),
        "ZAMER_KP_LINK": link_for("zamer_kp", "/zamer-kp"),
        "SPRAVOCHNIK_LINK": link_for("spravochnik", "/spravochnik"),
        "TABEL_LINK": link_for("tabel", "/tabel")
    }
    try:
        return templates.TemplateResponse(request=request, name="home.html", context=context)
    except TypeError:
        return templates.TemplateResponse("home.html", context)

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    session = get_current_session(request)
    if session:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request=request, name="login.html", context={"request": request, "USER": ""})

@app.post("/login", response_class=HTMLResponse)
async def login_post(request: Request, response: Response, password: str = Form(...)):
    client_ip = get_client_ip(request)
    now = time.time()
    attempts = [t for t in FAILED_ATTEMPTS.get(client_ip, []) if now - t < 86400]
    FAILED_ATTEMPTS[client_ip] = attempts
    
    if len(attempts) >= 15:
        return templates.TemplateResponse(request=request, name="login.html", context={"request": request, "USER": "", "error_message": "Слишком много неудачных попыток. Доступ заблокирован.<br>Пожалуйста, воспользуйтесь формой 'Запросить доступ / Восстановить пароль' для сброса блокировки."}, status_code=429)
    if len(attempts) >= 10:
        time.sleep(3)
    elif len(attempts) >= 5:
        time.sleep(1)
        
    password = password.strip()
    with sqlite3.connect(DB_FILE) as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, full_name, role, allowed_modules FROM users WHERE password=?", (password,))
        user = cur.fetchone()
        
    if user:
        if user[2] == "pending":
            return templates.TemplateResponse(request=request, name="login.html", context={"request": request, "USER": "", "error_message": "Ваша учетная запись еще не подтверждена администратором."}, status_code=403)
        
        if client_ip in FAILED_ATTEMPTS: del FAILED_ATTEMPTS[client_ip]
        
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute("INSERT INTO login_logs (user_name, login_time) VALUES (?, ?)", (user[1], dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            
        cookie_val = _cookie_value(str(user[0]), user[2], user[3] or "", user[1])
        redirect = RedirectResponse("/", status_code=303)
        redirect.set_cookie(SESSION_COOKIE, cookie_val, max_age=SESSION_TTL_SECONDS, path="/", httponly=True, samesite="lax")
        return redirect

    if password in (WEB_VIEW_PASSWORD, WEB_EDIT_PASSWORD):
        # Legacy passwords support
        role = "editor" if password == WEB_EDIT_PASSWORD else "viewer"
        cookie_val = _cookie_value("legacy", role, "zamer_kp,grafik_ppr,spravochnik,tabel", "Старый пароль")
        if client_ip in FAILED_ATTEMPTS: del FAILED_ATTEMPTS[client_ip]
        redirect = RedirectResponse("/", status_code=303)
        redirect.set_cookie(SESSION_COOKIE, cookie_val, max_age=SESSION_TTL_SECONDS, path="/", httponly=True, samesite="lax")
        return redirect

    attempts.append(now)
    FAILED_ATTEMPTS[client_ip] = attempts
    return templates.TemplateResponse(request=request, name="login.html", context={"request": request, "USER": "", "error_message": "Неверный пароль"}, status_code=401)

@app.post("/request_access", response_class=HTMLResponse)
async def request_access(request: Request, full_name: str = Form(...), password: str = Form(...)):
    full_name = full_name.strip()
    password = password.strip()
    if len(password) < 8 or not re.search(r'[A-Za-zА-Яа-яЁё]', password) or not re.search(r'[A-ZА-ЯЁ]', password):
        return HTMLResponse("""<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>Ошибка</title>
            <style>body{margin:0;font-family:Segoe UI, Arial, sans-serif;background:#f4f7fb;color:#102033;text-align:center;padding:50px;} .card{background:#fff;padding:40px;border-radius:18px;max-width:400px;margin:10vh auto;box-shadow:0 12px 32px rgba(16,32,51,.08);}</style>
            </head><body><div class="card"><h2 style="margin-top:0;color:#b00020;">Ошибка</h2><p style="color:#64748b;margin-bottom:24px;">Пароль должен быть не короче 8 символов, содержать буквы и хотя бы одну заглавную букву.</p><a href="/login" style="background:#276ef1;color:#fff;text-decoration:none;font-weight:bold;padding:12px 24px;border-radius:8px;display:inline-block;">Назад</a></div></body></html>""", status_code=400)
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM users WHERE full_name=?", (full_name,))
            existing = cur.fetchone()
            if existing:
                conn.execute("UPDATE users SET password=?, role='pending', allowed_modules='' WHERE id=?", (password, existing[0]))
            else:
                conn.execute("INSERT INTO users (full_name, password, role, allowed_modules) VALUES (?, ?, 'pending', '')", (full_name, password))
        client_ip = get_client_ip(request)
        if client_ip in FAILED_ATTEMPTS: del FAILED_ATTEMPTS[client_ip]
    except Exception as e:
        print("Error requesting access:", e)
    
    return HTMLResponse("""<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>Запрос отправлен</title>
        <style>body{margin:0;font-family:Segoe UI, Arial, sans-serif;background:#f4f7fb;color:#102033;text-align:center;padding:50px;} .card{background:#fff;padding:40px;border-radius:18px;max-width:400px;margin:10vh auto;box-shadow:0 12px 32px rgba(16,32,51,.08);}</style>
        </head><body><div class="card"><h2 style="margin-top:0;color:#0f172a;">Запрос отправлен</h2><p style="color:#64748b;margin-bottom:24px;">Ожидайте подтверждения администратором.</p><a href="/login" style="background:#276ef1;color:#fff;text-decoration:none;font-weight:bold;padding:12px 24px;border-radius:8px;display:inline-block;">На главную</a></div></body></html>""")

@app.get("/logout")
async def logout():
    redirect = RedirectResponse("/login", status_code=303)
    redirect.delete_cookie(SESSION_COOKIE)
    return redirect

@app.get("/users", response_class=HTMLResponse)
async def users_page(request: Request):
    session = get_current_session(request)
    if not session or (session["role"] != "admin" and "admin" not in session["modules"]):
        return RedirectResponse("/", status_code=303)
        
    users = []
    error_message = ""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, full_name, password, role, allowed_modules FROM users ORDER BY id")
            for u in cur.fetchall():
                mods = parse_mods(u[4] or "")
                users.append({
                    "id": u[0], "full_name": u[1], "password": u[2], "role": u[3],
                    "g_r": get_mod_role(mods, "grafik_ppr", u[3]),
                    "z_r": get_mod_role(mods, "zamer_kp", u[3]),
                    "s_r": get_mod_role(mods, "spravochnik", u[3]),
                    "t_r": get_mod_role(mods, "tabel", u[3])
                })
    except Exception as e:
        error_message = f"Ошибка БД: {e}"
        
    return templates.TemplateResponse(request=request, name="users.html", context={"request": request, "users": users, "error_message": error_message})

@app.post("/users/add")
async def add_user(request: Request, full_name: str = Form(""), password: str = Form(""), role: str = Form("viewer"), module_grafik_ppr: str = Form("none"), module_zamer_kp: str = Form("none"), module_spravochnik: str = Form("none"), module_tabel: str = Form("none")):
    session = get_current_session(request)
    if not session or (session["role"] != "admin" and "admin" not in session["modules"]):
        return RedirectResponse("/", status_code=303)
        
    modules = []
    if module_grafik_ppr != "none": modules.append(f"grafik_ppr:{module_grafik_ppr}")
    if module_zamer_kp != "none": modules.append(f"zamer_kp:{module_zamer_kp}")
    if module_spravochnik != "none": modules.append(f"spravochnik:{module_spravochnik}")
    if module_tabel != "none": modules.append(f"tabel:{module_tabel}")
    if role == "admin": modules.append("admin")
    
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute("INSERT INTO users (full_name, password, role, allowed_modules) VALUES (?, ?, ?, ?)", (full_name, password, role, ",".join(modules)))
    except Exception as e:
        print("Error adding user:", e)
    return RedirectResponse("/users", status_code=303)

@app.post("/users/update")
async def update_user(request: Request, id: int = Form(...), full_name: str = Form(""), password: str = Form(""), role: str = Form("viewer"), module_grafik_ppr: str = Form("none"), module_zamer_kp: str = Form("none"), module_spravochnik: str = Form("none"), module_tabel: str = Form("none")):
    session = get_current_session(request)
    if not session or (session["role"] != "admin" and "admin" not in session["modules"]):
        return RedirectResponse("/", status_code=303)
        
    modules = []
    if module_grafik_ppr != "none": modules.append(f"grafik_ppr:{module_grafik_ppr}")
    if module_zamer_kp != "none": modules.append(f"zamer_kp:{module_zamer_kp}")
    if module_spravochnik != "none": modules.append(f"spravochnik:{module_spravochnik}")
    if module_tabel != "none": modules.append(f"tabel:{module_tabel}")
    if role == "admin": modules.append("admin")
    
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute("UPDATE users SET full_name=?, password=?, role=?, allowed_modules=? WHERE id=?", (full_name, password, role, ",".join(modules), id))
    except Exception as e:
        print("Error updating user:", e)
    return RedirectResponse("/users", status_code=303)

@app.post("/users/delete")
async def delete_user(request: Request, id: int = Form(...)):
    session = get_current_session(request)
    if not session or (session["role"] != "admin" and "admin" not in session["modules"]):
        return RedirectResponse("/", status_code=303)
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute("DELETE FROM users WHERE id=?", (id,))
    except Exception as e:
        print("Error deleting user:", e)
    return RedirectResponse("/users", status_code=303)

@app.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request):
    session = get_current_session(request)
    if not session or (session["role"] != "admin" and "admin" not in session["modules"]):
        return RedirectResponse("/", status_code=303)
        
    logs = []
    error_message = ""
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, user_name, login_time FROM login_logs ORDER BY id DESC LIMIT 100")
            for l in cur.fetchall():
                logs.append({"id": l[0], "user_name": l[1], "login_time": l[2]})
    except Exception as e:
        error_message = f"Ошибка БД: {e}"
        
    return templates.TemplateResponse(request=request, name="logs.html", context={"request": request, "logs": logs, "error_message": error_message})

@app.get("/grafik-ppr")
async def redir_grafik():
    return RedirectResponse("https://yrtps.ru/grafik-ppr", status_code=303)

@app.get("/zamer-kp")
async def redir_zamer():
    return RedirectResponse("https://yrtps.ru/zamer-kp", status_code=303)

if __name__ == "__main__":
    host = os.environ.get("WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("WEB_PORT", "8001"))
    uvicorn.run("app:app", host=host, port=port, reload=True)
