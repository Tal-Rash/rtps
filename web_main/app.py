from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
import sys
from http import HTTPStatus
from pathlib import Path
import re

from fastapi import FastAPI, Request, Response, Form, Depends, HTTPException, Cookie, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import uvicorn

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
from rtps_common import connect_sqlite, resolve_user_access

DATA_DIR = ROOT / "data"
SHARED_DATA_DIR = ROOT.parent / "data"
AUTH_FILE = SHARED_DATA_DIR / "web_auth.json"
ACCESS_STATE_FILE = SHARED_DATA_DIR / "web_access.json"
WEB_SECRET_FILE = SHARED_DATA_DIR / "web_secret.txt"
LEGACY_WEB_SECRET_FILE = DATA_DIR / "web_secret.txt"
SESSION_COOKIE = "rtps_session"
SESSION_TTL_SECONDS = 7 * 24 * 60 * 60
MAIN_SITE_URL = os.environ.get("MAIN_SITE_URL", "http://yrtps.ru")
ALSN_SITE_URL = os.environ.get("ALSN_SITE_URL", "http://yrtps.ru:8008")

FAILED_ATTEMPTS: dict[str, list[float]] = {}
DB_FILE = ROOT.parent / "base" / "web_users.db"
BUILD_ID = "web-main-alsn-access-2026-06-28-2"

app = FastAPI(title="RTPS Web Main")
templates = Jinja2Templates(directory=str(ROOT / "templates"))

def normalize_admin_modules(modules_str: str) -> str:
    modules = [m.strip() for m in str(modules_str or "").split(",") if m.strip()]
    by_name = {m.split(":", 1)[0]: i for i, m in enumerate(modules)}
    for module_name in ("grafik_ppr", "zamer_kp", "spravochnik", "tabel", "edu", "alsn"):
        if module_name in by_name:
            modules[by_name[module_name]] = f"{module_name}:edit"
        else:
            modules.append(f"{module_name}:edit")
    if "admin" not in modules:
        modules.append("admin")
    return ",".join(modules)

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
        with connect_sqlite(DB_FILE) as conn:
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
                    ("12345", "Администратор (Главный)", "admin", "zamer_kp,grafik_ppr,spravochnik,tabel,edu,alsn,admin")
                )
                print("Создан администратор по умолчанию. Пароль: 12345")
            else:
                cur.execute("SELECT id, allowed_modules FROM users WHERE role='admin'")
                for user_id, allowed_modules in cur.fetchall():
                    conn.execute(
                        "UPDATE users SET allowed_modules=? WHERE id=?",
                        (normalize_admin_modules(allowed_modules), user_id),
                    )
    except Exception as e:
        print("Ошибка инициализации БД:", e)

init_db()

@app.get("/_version")
async def version():
    return {"app": "web_main", "build": BUILD_ID}

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

def _session_max_age(role: str, modules: str) -> int:
    tokens = {part.strip() for part in str(modules or "").split(",") if part.strip()}
    if role == "admin" or "admin" in tokens:
        return SESSION_TTL_SECONDS
    now = dt.datetime.now()
    tomorrow = now.date() + dt.timedelta(days=1)
    midnight = dt.datetime.combine(tomorrow, dt.time.min)
    return max(60, int((midnight - now).total_seconds()))

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
            if user_id == "legacy":
                return None
            if user_id != "legacy":
                resolved = resolve_user_access(DB_FILE, user_id, role, modules)
                if not resolved:
                    return None # User deleted, invalidate session
                role, modules = resolved
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
    pending_users_count = 0
    if session["role"] == "admin" or "admin" in session["modules"]:
        with sqlite3.connect(DB_FILE) as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM users WHERE role='pending'")
            pending_users_count = int(cur.fetchone()[0] or 0)
        pending_badge = f' <span class="badge-alert">{pending_users_count}</span>' if pending_users_count > 0 else ""
        users_link = f'<a class="badge badge-users" href="/users" style="background:#276ef1; color:#fff; border-color:#276ef1;">Управление доступом{pending_badge}</a>'
        logs_link = '<a class="badge" href="/logs" style="background:#475569; color:#fff; border-color:#475569;">Журнал</a>'
        
    def has_access_to(mod_name):
        mods = session["modules"]
        role = session["role"]
        if role == "admin" or "admin" in mods: return True
        return f"{mod_name}:edit" in mods or f"{mod_name}:view" in mods or mod_name in mods.split(",")

    def link_for(mod_name, url):
        if has_access_to(mod_name):
            target_base = ALSN_SITE_URL if mod_name == "alsn" else MAIN_SITE_URL
            return f'<a href="{target_base}{url}">Открыть модуль</a>'
        return '<a class="disabled" href="#">Нет доступа</a>'
        
    context = {
        "request": request,
        "STARTED_AT": dt.datetime.now().strftime("%d.%m.%Y %H:%M"),
        "AUTH_BADGE": auth_badge,
        "USERS_LINK": users_link,
        "PENDING_USERS_COUNT": pending_users_count,
        "LOGS_LINK": logs_link,
        "HIDE_GRAFIK_PPR": ("hide_grafik_ppr:yes" in session["modules"]) or not has_access_to("grafik_ppr"),
        "HIDE_ZAMER_KP": ("hide_zamer_kp:yes" in session["modules"]) or not has_access_to("zamer_kp"),
        "HIDE_SPRAVOCHNIK": ("hide_spravochnik:yes" in session["modules"]) or not has_access_to("spravochnik"),
        "HIDE_TABEL": ("hide_tabel:yes" in session["modules"]) or not has_access_to("tabel"),
        "HIDE_EDU": ("hide_edu:yes" in session["modules"]) or not has_access_to("edu"),
        "HIDE_ALSN": ("hide_alsn:yes" in session["modules"]) or not has_access_to("alsn"),
        "GRAFIK_PPR_LINK": link_for("grafik_ppr", "/grafik-ppr"),
        "ZAMER_KP_LINK": link_for("zamer_kp", "/zamer-kp"),
        "ALSN_LINK": link_for("alsn", "/alsn"),
        "SPRAVOCHNIK_LINK": link_for("spravochnik", "/spravochnik"),
        "TABEL_LINK": link_for("tabel", "/tabel"),
        "EDU_LINK": link_for("edu", "/edu")
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
    next_url = request.query_params.get("next", "/").strip()
    if not next_url.startswith("/"):
        next_url = "/"
    return templates.TemplateResponse(request=request, name="login.html", context={"request": request, "USER": "", "NEXT_URL": next_url})

@app.post("/login", response_class=HTMLResponse)
async def login_post(request: Request, response: Response, password: str = Form(...)):
    client_ip = get_client_ip(request)
    now = time.time()
    attempts = [t for t in FAILED_ATTEMPTS.get(client_ip, []) if now - t < 86400]
    FAILED_ATTEMPTS[client_ip] = attempts
    
    if len(attempts) >= 15:
        return templates.TemplateResponse(request=request, name="login.html", context={"request": request, "USER": "", "NEXT_URL": next_url, "error_message": "Слишком много неудачных попыток. Доступ заблокирован.<br>Пожалуйста, воспользуйтесь формой 'Запросить доступ / Восстановить пароль' для сброса блокировки."}, status_code=429)
    if len(attempts) >= 10:
        time.sleep(3)
    elif len(attempts) >= 5:
        time.sleep(1)
        
    password = password.strip()
    with sqlite3.connect(DB_FILE) as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, full_name, role, allowed_modules FROM users WHERE password=?", (password,))
        user = cur.fetchone()
        
    next_url = request.query_params.get("next", "/").strip()
    if not next_url.startswith("/"):
        next_url = "/"

    if user:
        if user[2] == "pending":
            return templates.TemplateResponse(request=request, name="login.html", context={"request": request, "USER": "", "NEXT_URL": next_url, "error_message": "Ваша учетная запись еще не подтверждена администратором."}, status_code=403)
        
        if client_ip in FAILED_ATTEMPTS: del FAILED_ATTEMPTS[client_ip]
        
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute("INSERT INTO login_logs (user_name, login_time) VALUES (?, ?)", (user[1], dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            
        cookie_val = _cookie_value(str(user[0]), user[2], user[3] or "", user[1])
        redirect = RedirectResponse(next_url or "/", status_code=303)
        redirect.set_cookie(SESSION_COOKIE, cookie_val, max_age=_session_max_age(user[2], user[3] or ""), path="/", httponly=True, samesite="lax")
        return redirect

    attempts.append(now)
    FAILED_ATTEMPTS[client_ip] = attempts
    return templates.TemplateResponse(request=request, name="login.html", context={"request": request, "USER": "", "NEXT_URL": next_url, "error_message": "Неверный пароль"}, status_code=401)

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
                is_admin = u[3] == "admin"
                users.append({
                    "id": u[0], "full_name": u[1], "password": u[2], "role": u[3],
                    "g_r": "edit" if is_admin else get_mod_role(mods, "grafik_ppr", u[3]),
                    "z_r": "edit" if is_admin else get_mod_role(mods, "zamer_kp", u[3]),
                    "s_r": "edit" if is_admin else get_mod_role(mods, "spravochnik", u[3]),
                    "t_r": "edit" if is_admin else get_mod_role(mods, "tabel", u[3]),
                    "e_r": "edit" if is_admin else get_mod_role(mods, "edu", u[3]),
                    "a_r": "edit" if is_admin else get_mod_role(mods, "alsn", u[3]),
                    "h_g": "checked" if "hide_grafik_ppr:yes" in (u[4] or "") else "",
                    "h_z": "checked" if "hide_zamer_kp:yes" in (u[4] or "") else "",
                    "h_s": "checked" if "hide_spravochnik:yes" in (u[4] or "") else "",
                    "h_t": "checked" if "hide_tabel:yes" in (u[4] or "") else "",
                    "h_e": "checked" if "hide_edu:yes" in (u[4] or "") else "",
                    "h_a": "checked" if "hide_alsn:yes" in (u[4] or "") else ""
                })
    except Exception as e:
        error_message = f"Ошибка БД: {e}"
        
    return templates.TemplateResponse(request=request, name="users.html", context={"request": request, "users": users, "error_message": error_message})

@app.post("/users/add")
async def add_user(request: Request, full_name: str = Form(""), password: str = Form(""), role: str = Form("viewer"), module_grafik_ppr: str = Form("none"), module_zamer_kp: str = Form("none"), module_spravochnik: str = Form("none"), module_tabel: str = Form("none"), module_edu: str = Form("none"), module_alsn: str = Form("none")):
    session = get_current_session(request)
    if not session or (session["role"] != "admin" and "admin" not in session["modules"]):
        return RedirectResponse("/", status_code=303)
        
    form = await request.form()
    
    modules = []
    if module_grafik_ppr != "none": modules.append(f"grafik_ppr:{module_grafik_ppr}")
    if module_zamer_kp != "none": modules.append(f"zamer_kp:{module_zamer_kp}")
    if module_spravochnik != "none": modules.append(f"spravochnik:{module_spravochnik}")
    if module_tabel != "none": modules.append(f"tabel:{module_tabel}")
    if module_edu != "none": modules.append(f"edu:{module_edu}")
    if module_alsn != "none": modules.append(f"alsn:{module_alsn}")
    
    if form.get("hide_grafik_ppr") == "yes": modules.append("hide_grafik_ppr:yes")
    if form.get("hide_zamer_kp") == "yes": modules.append("hide_zamer_kp:yes")
    if form.get("hide_spravochnik") == "yes": modules.append("hide_spravochnik:yes")
    if form.get("hide_tabel") == "yes": modules.append("hide_tabel:yes")
    if form.get("hide_edu") == "yes": modules.append("hide_edu:yes")
    if form.get("hide_alsn") == "yes": modules.append("hide_alsn:yes")
    if role == "admin":
        modules = [
            "grafik_ppr:edit",
            "zamer_kp:edit",
            "spravochnik:edit",
            "tabel:edit",
            "edu:edit",
            "alsn:edit",
            "admin",
        ]
    
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute("INSERT INTO users (full_name, password, role, allowed_modules) VALUES (?, ?, ?, ?)", (full_name, password, role, ",".join(modules)))
    except Exception as e:
        print("Error adding user:", e)
    return RedirectResponse("/users", status_code=303)

@app.post("/users/update")
async def update_user(request: Request, id: int = Form(...), full_name: str = Form(""), password: str = Form(""), role: str = Form("viewer"), module_grafik_ppr: str = Form("none"), module_zamer_kp: str = Form("none"), module_spravochnik: str = Form("none"), module_tabel: str = Form("none"), module_edu: str = Form("none"), module_alsn: str = Form("none")):
    session = get_current_session(request)
    if not session or (session["role"] != "admin" and "admin" not in session["modules"]):
        return RedirectResponse("/", status_code=303)

    form = await request.form()
    posted_fields = set(form.keys())
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cur = conn.cursor()
            cur.execute("SELECT role, allowed_modules FROM users WHERE id=?", (id,))
            old_user = cur.fetchone()
        old_role = old_user[0] if old_user else role
        old_mods = parse_mods(old_user[1] if old_user else "")
        old_mods_raw = old_user[1] if old_user else ""
    except Exception:
        old_role = role
        old_mods = {}
        old_mods_raw = ""

    def posted_or_existing(field_name: str, module_name: str, value: str) -> str:
        if field_name in posted_fields:
            return value
        return get_mod_role(old_mods, module_name, old_role)

    module_grafik_ppr = posted_or_existing("module_grafik_ppr", "grafik_ppr", module_grafik_ppr)
    module_zamer_kp = posted_or_existing("module_zamer_kp", "zamer_kp", module_zamer_kp)
    module_spravochnik = posted_or_existing("module_spravochnik", "spravochnik", module_spravochnik)
    module_tabel = posted_or_existing("module_tabel", "tabel", module_tabel)
    module_edu = posted_or_existing("module_edu", "edu", module_edu)
    module_alsn = posted_or_existing("module_alsn", "alsn", module_alsn)
    
    def posted_or_existing_hide(field_name: str) -> bool:
        if field_name in posted_fields:
            return form.get(field_name) == "yes"
        return f"{field_name}:yes" in old_mods_raw

    hide_grafik_ppr = posted_or_existing_hide("hide_grafik_ppr")
    hide_zamer_kp = posted_or_existing_hide("hide_zamer_kp")
    hide_spravochnik = posted_or_existing_hide("hide_spravochnik")
    hide_tabel = posted_or_existing_hide("hide_tabel")
    hide_edu = posted_or_existing_hide("hide_edu")
    hide_alsn = posted_or_existing_hide("hide_alsn")

    modules = []
    if module_grafik_ppr != "none": modules.append(f"grafik_ppr:{module_grafik_ppr}")
    if module_zamer_kp != "none": modules.append(f"zamer_kp:{module_zamer_kp}")
    if module_spravochnik != "none": modules.append(f"spravochnik:{module_spravochnik}")
    if module_tabel != "none": modules.append(f"tabel:{module_tabel}")
    if module_edu != "none": modules.append(f"edu:{module_edu}")
    if module_alsn != "none": modules.append(f"alsn:{module_alsn}")
    
    if hide_grafik_ppr: modules.append("hide_grafik_ppr:yes")
    if hide_zamer_kp: modules.append("hide_zamer_kp:yes")
    if hide_spravochnik: modules.append("hide_spravochnik:yes")
    if hide_tabel: modules.append("hide_tabel:yes")
    if hide_edu: modules.append("hide_edu:yes")
    if hide_alsn: modules.append("hide_alsn:yes")
    
    if role == "admin":
        modules = [
            "grafik_ppr:edit",
            "zamer_kp:edit",
            "spravochnik:edit",
            "tabel:edit",
            "edu:edit",
            "alsn:edit",
            "admin",
        ]
    
    try:
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute("UPDATE users SET full_name=?, password=?, role=?, allowed_modules=? WHERE id=?", (full_name, password, role, ",".join(modules), id))
    except Exception as e:
        print("Error updating user:", e)
    
    redirect = RedirectResponse("/users", status_code=303)
    if str(id) == session.get("user_id"):
        cookie_val = _cookie_value(str(id), role, ",".join(modules), full_name)
        redirect.set_cookie(SESSION_COOKIE, cookie_val, max_age=_session_max_age(role, ",".join(modules)), path="/", httponly=True, samesite="lax")
    return redirect

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
    return RedirectResponse(f"{MAIN_SITE_URL}/grafik-ppr", status_code=303)

@app.get("/zamer-kp")
async def redir_zamer():
    return RedirectResponse(f"{MAIN_SITE_URL}/zamer-kp", status_code=303)

@app.get("/alsn")
@app.get("/alsn/")
async def redir_alsn():
    return RedirectResponse(f"{ALSN_SITE_URL}/alsn", status_code=303)

if __name__ == "__main__":
    host = os.environ.get("WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("WEB_PORT", "8001"))
    uvicorn.run("app:app", host=host, port=port, reload=False)
