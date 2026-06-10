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
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
SHARED_DATA_DIR = ROOT.parent / "data"
AUTH_FILE = SHARED_DATA_DIR / "web_auth.json"
ACCESS_STATE_FILE = SHARED_DATA_DIR / "web_access.json"
WEB_SECRET_FILE = SHARED_DATA_DIR / "web_secret.txt"
LEGACY_WEB_SECRET_FILE = DATA_DIR / "web_secret.txt"
SESSION_COOKIE = "grafik_ppr_session"
SESSION_TTL_SECONDS = 7 * 24 * 60 * 60


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
            file_view = str(payload.get("view_password", "")).strip()
            file_edit = str(payload.get("edit_password", "")).strip() or str(payload.get("password", "")).strip()
            if file_edit and not file_view:
                file_view = secrets.token_urlsafe(8)
            if file_view and not file_edit:
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
        json.dumps(
            {"user": user, "view_password": view_password, "edit_password": edit_password},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return user, view_password, edit_password


WEB_USER, WEB_VIEW_PASSWORD, WEB_EDIT_PASSWORD = load_auth_config()
SESSIONS: dict[str, tuple[str, str, str, str, float]] = {}
DB_FILE = ROOT.parent / "base" / "common_database.db"

def init_db() -> None:
    try:
        DB_FILE.parent.mkdir(parents=True, exist_ok=True)
        import sqlite3
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
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM users")
            if cur.fetchone()[0] == 0:
                conn.execute(
                    "INSERT INTO users (password, full_name, role, allowed_modules) VALUES (?, ?, ?, ?)",
                    ("12345", "Администратор (Главный)", "admin", "zamer_kp,grafik_ppr,spravochnik,admin")
                )
                print("Создан администратор по умолчанию. Пароль: 12345")
    except Exception as e:
        print("Ошибка инициализации БД:", e)

init_db()



HOME_TEMPLATE = """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Участок РТПС</title>
  <style>
    :root { --line:#d9e2ef; --text:#102033; --muted:#66758a; --blue:#276ef1; --soft:#eef4ff; }
    * { box-sizing:border-box; }
    body { margin:0; font-family:Segoe UI, Arial, sans-serif; background:linear-gradient(180deg,#f8fbff 0%, #eef4fb 100%); color:var(--text); }
    .wrap { max-width:1180px; margin:0 auto; padding:28px 20px 36px; }
    .hero { display:flex; justify-content:space-between; gap:16px; align-items:flex-start; background:rgba(255,255,255,.8); border:1px solid var(--line); border-radius:24px; padding:24px; box-shadow:0 12px 32px rgba(16,32,51,.06); backdrop-filter:blur(8px); }
    .title { font-size:34px; line-height:1.05; margin:0 0 10px; }
    .sub { margin:0; color:var(--muted); font-size:14px; max-width:720px; }
    .badge { display:inline-flex; align-items:center; gap:8px; padding:10px 14px; border-radius:8px; background:var(--soft); color:#1d4ed8; font-weight:700; text-decoration:none; border:1px solid #cfe0ff; white-space:nowrap; }
    .top-right { display:flex; flex-direction:column; gap:10px; align-items:flex-end; }
    .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(250px,1fr)); gap:16px; margin-top:18px; }
    .card { background:#fff; border:1px solid var(--line); border-radius:20px; padding:18px; box-shadow:0 10px 28px rgba(16,32,51,.05); min-height:160px; display:flex; flex-direction:column; justify-content:space-between; }
    .card h2 { margin:0 0 8px; font-size:18px; }
    .card p { margin:0; color:var(--muted); font-size:13px; line-height:1.4; }
    .card a { display:inline-flex; margin-top:14px; width:fit-content; align-items:center; gap:8px; padding:10px 14px; border-radius:8px; background:var(--blue); color:#fff; text-decoration:none; font-weight:700; }
    .disabled { opacity:.45; pointer-events:none; }
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
        <p class="sub">Стартовая страница для запуска веб-программ.</p>
      </div>
      <div class="top-right">
        {{USERS_LINK}}
        <a class="badge" href="/logout">Выйти</a>
        <div class="badge">{{AUTH_BADGE}}</div>
      </div>
    </div>

    <div class="grid">
      <div class="card">
        <div>
          <h2>График ППР</h2>
          <p>План, факт, нормы.</p>
        </div>
        {{GRAFIK_PPR_LINK}}
      </div>
      <div class="card">
        <div>
          <h2>Замер КП</h2>
          <p>Замеры и последующее заполнение по шагам.</p>
        </div>
        {{ZAMER_KP_LINK}}
      </div>
      <div class="card">
        <div>
          <h2>Табель учета</h2>
          <p>Следующий модуль.</p>
        </div>
        <a class="disabled" href="#">Скоро</a>
      </div>
      <div class="card">
        <div>
          <h2>АЛСН</h2>
          <p>Следующий модуль.</p>
        </div>
        <a class="disabled" href="#">Скоро</a>
      </div>
      <div class="card">
        <div>
          <h2>Обучение</h2>
          <p>Следующий модуль.</p>
        </div>
        <a class="disabled" href="#">Скоро</a>
      </div>
      <div class="card">
        <div>
          <h2>Справочник</h2>
          <p>Нормы времени, сотрудники и локомотивы.</p>
        </div>
        {{SPRAVOCHNIK_LINK}}
      </div>
    </div>
    <div class="status">Сервер запущен: {{STARTED_AT}}</div>
  </div>
</body>
</html>
"""

LOGIN_TEMPLATE = """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Вход - РТПС</title>
  <style>
    body { margin:0; font-family:Segoe UI, Arial, sans-serif; background:#f4f7fb; color:#102033; }
    .card { max-width:420px; margin:10vh auto; background:#fff; border:1px solid #d9e2ef; border-radius:18px; padding:24px; box-shadow:0 12px 32px rgba(16,32,51,.08); }
    input,button { width:100%; padding:12px; border-radius:8px; border:1px solid #d9e2ef; font:inherit; }
    button { background:#276ef1; color:#fff; font-weight:700; cursor:pointer; border:0; }
    .muted { color:#607086; font-size:13px; }
  </style>
</head>
<body>
  <form class="card" method="post" action="/login">
    <h1 style="margin-top:0;">Вход</h1>
    <p class="muted">Введите пароль просмотра или редактирования.</p>
    <input name="password" type="password" placeholder="Пароль" style="margin-bottom:12px;">
    <button type="submit">Войти</button>
  </form>
</body>
</html>
"""



USERS_TEMPLATE = '''<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Управление доступом</title>
  <style>
    body { margin:0; font-family:Segoe UI, Arial, sans-serif; background:#f4f7fb; color:#102033; padding:20px; }
    .card { max-width:800px; margin:0 auto; background:#fff; border:1px solid #d9e2ef; border-radius:18px; padding:24px; box-shadow:0 12px 32px rgba(16,32,51,.08); }
    table { width:100%; border-collapse:collapse; margin-top:20px; }
    th, td { text-align:left; padding:10px; border-bottom:1px solid #d9e2ef; }
    input, select, button { padding:8px; border-radius:6px; border:1px solid #d9e2ef; font:inherit; }
    button { background:#276ef1; color:#fff; font-weight:700; cursor:pointer; border:0; }
    .btn-danger { background:#e11d48; }
    .flex { display:flex; gap:10px; align-items:center; }
    .muted { color:#607086; font-size:13px; }
  </style>
</head>
<body>
  <div class="card">
    <div class="flex" style="justify-content:space-between; margin-bottom:20px;">
        <h1 style="margin:0;">Управление доступом</h1>
        <a href="/" style="color:#276ef1; text-decoration:none; font-weight:bold;">На главную</a>
    </div>
    
    <form method="post" action="/users/add" style="background:#f8fafc; padding:16px; border-radius:12px; margin-bottom:20px;">
      <h3 style="margin-top:0;">Добавить пользователя</h3>
      <div class="flex" style="flex-wrap:wrap;">
        <input name="full_name" placeholder="Фамилия И.О." required>
        <input name="password" placeholder="Пароль (ПИН)" required>
        <select name="role">
            <option value="viewer">Зритель</option>
            <option value="editor">Редактор</option>
            <option value="admin">Администратор</option>
        </select>
        <div style="display:flex; gap:12px; align-items:center; flex:1; flex-wrap:wrap; border:1px solid #d9e2ef; padding:8px; border-radius:6px; background:#fff;">
          <label style="display:flex; align-items:center; gap:4px; margin:0; cursor:pointer;"><input type="checkbox" name="module_grafik_ppr" value="1"> График ППР</label>
          <label style="display:flex; align-items:center; gap:4px; margin:0; cursor:pointer;"><input type="checkbox" name="module_zamer_kp" value="1"> Замер КП</label>
          <label style="display:flex; align-items:center; gap:4px; margin:0; cursor:pointer;"><input type="checkbox" name="module_spravochnik" value="1"> Справочник</label>
        </div>
        <button type="submit" style="align-self:stretch;">Добавить</button>
      </div>
    </form>

    <table>
      <thead>
        <tr>
          <th>ID</th><th>ФИО</th><th>Пароль</th><th>Роль</th><th>Модули</th><th>Действие</th>
        </tr>
      </thead>
      <tbody>
        {{USERS_ROWS}}
      </tbody>
    </table>
  </div>
</body>
</html>
'''

def _cookie_value(user_id: str, role: str, modules: str, full_name: str) -> str:
    import urllib.parse
    expiry = int(dt.datetime.now().timestamp()) + SESSION_TTL_SECONDS
    safe_name = urllib.parse.quote(full_name.replace(":", " "))
    payload = f"{user_id}:{role}:{modules}:{safe_name}:{expiry}"
    sig = hmac.new(WEB_SECRET.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    token = f"{payload}:{sig}"
    SESSIONS[token] = (user_id, role, modules, full_name, float(expiry))
    return token


def _write_access_state(username: str, role: str, expiry: int) -> None:
    ACCESS_STATE_FILE.write_text(
        json.dumps(
            {
                "username": username,
                "role": role,
                "expires_at": expiry,
                "updated_at": int(dt.datetime.now().timestamp()),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _clear_access_state() -> None:
    try:
        if ACCESS_STATE_FILE.exists():
            ACCESS_STATE_FILE.unlink()
    except Exception:
        pass


def _verify_cookie(value: str) -> tuple[str, str, str, str] | None:
    try:
        user_id, role, modules, safe_name, ts, sig = value.rsplit(":", 5)
        payload = f"{user_id}:{role}:{modules}:{safe_name}:{ts}"
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
            return None
        if int(ts) + SESSION_TTL_SECONDS < int(dt.datetime.now().timestamp()):
            return None
        import urllib.parse
        return user_id, role, modules, urllib.parse.unquote(safe_name)
    except Exception:
        try:
            username, role, expiry_text, sig = value.split("|")
            payload = f"{username}|{role}|{expiry_text}"
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
                return None
            if dt.datetime.now().timestamp() > float(expiry_text):
                return None
            if role not in {"view", "edit"}:
                return None
            return username, role
        except Exception:
            return None


def _parse_cookie_values(handler: BaseHTTPRequestHandler, name: str) -> list[str]:
    raw = handler.headers.get("Cookie", "")
    values: list[str] = []
    for part in raw.split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        if key.strip() == name:
            values.append(value.strip())
    return values


def current_session(handler: BaseHTTPRequestHandler) -> tuple[str, str, str, str] | None:
    for token in _parse_cookie_values(handler, SESSION_COOKIE):
        session = _verify_cookie(token)
        if session:
            user_id, role, modules, safe_name = session
            SESSIONS[token] = (user_id, role, modules, safe_name, dt.datetime.now().timestamp())
            return session
    return None


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


def _login_cookie(user_id: str, role: str, modules: str, full_name: str) -> str:
    token = _cookie_value(user_id, role, modules, full_name)
    return f"{SESSION_COOKIE}={token}; HttpOnly; Path=/; SameSite=Lax; Max-Age={SESSION_TTL_SECONDS}"


def render_home(user_id: str, full_name: str, role: str, modules: str) -> str:
    started_at = dt.datetime.now().strftime("%H:%M:%S %d.%m.%Y")
    
    role_labels = {"admin": "Администратор", "editor": "Редактор", "viewer": "Зритель"}
    role_label = role_labels.get(role, role)
    
    mods = [m.strip() for m in modules.split(",")]
    
    def link_for(mod_id: str, path: str) -> str:
        if mod_id in mods or "admin" in mods:
            return f'<a href="{path}">Открыть</a>'
        return '<a class="disabled" href="#" aria-disabled="true" tabindex="-1">Нет доступа</a>'
        
    users_link = '<a class="badge" href="/users" style="background:#276ef1; color:#fff; border-color:#276ef1;">Управление доступом</a>' if role == "admin" or "admin" in mods else ""
        
    return (
        HOME_TEMPLATE
        .replace("{{STARTED_AT}}", started_at)
        .replace("{{AUTH_BADGE}}", f"Пользователь: {full_name} ({role_label})")
        .replace("{{USERS_LINK}}", users_link)
        .replace("{{GRAFIK_PPR_LINK}}", link_for("grafik_ppr", "/grafik-ppr"))
        .replace("{{ZAMER_KP_LINK}}", link_for("zamer_kp", "/zamer-kp"))
        .replace("{{SPRAVOCHNIK_LINK}}", link_for("spravochnik", "/spravochnik"))
    )


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # noqa: D401
        return

    def do_GET(self):
        parsed = urlparse(self.path)
        session = current_session(self)
        user_id = session[0] if session else None
        role = session[1] if session else None
        modules = session[2] if session else ""
        full_name = session[3] if session else ""
        if parsed.path == "/users":
            if not user_id or "admin" not in modules:
                _redirect(self, "/")
                return
            
            rows_html = ""
            try:
                import sqlite3
                with sqlite3.connect(DB_FILE) as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT id, full_name, password, role, allowed_modules FROM users ORDER BY id")
                    for u in cur.fetchall():
                        rows_html += f"<tr><td>{u[0]}</td><td>{u[1]}</td><td>{u[2]}</td><td>{u[3]}</td><td>{u[4]}</td>"
                        rows_html += f"<td><form method='post' action='/users/delete' style='margin:0;'><input type='hidden' name='id' value='{u[0]}'><button class='btn-danger' type='submit'>Удалить</button></form></td></tr>"
            except Exception as e:
                rows_html = f"<tr><td colspan='6'>Ошибка БД: {e}</td></tr>"
                
            _send_html(self, USERS_TEMPLATE.replace("{{USERS_ROWS}}", rows_html))
            return

        if parsed.path == "/":
            if not user_id:
                _redirect(self, "/login")
                return
            _send_html(self, render_home(user_id, full_name, role, modules))
            return
        if parsed.path == "/grafik-ppr":
            _redirect(self, "https://yrtps.ru/grafik-ppr")
            return
        if parsed.path == "/zamer-kp":
            _redirect(self, "https://yrtps.ru/zamer-kp")
            return
        if parsed.path == "/users/add":
            form = parse_qs(raw.decode("utf-8", errors="ignore"))
            modules = []
            if form.get("module_grafik_ppr"): modules.append("grafik_ppr")
            if form.get("module_zamer_kp"): modules.append("zamer_kp")
            if form.get("module_spravochnik"): modules.append("spravochnik")
            
            role = form.get("role", ["viewer"])[0]
            if role == "admin":
                modules.append("admin")
                
            modules_str = ",".join(modules)
            try:
                import sqlite3
                with sqlite3.connect(DB_FILE) as conn:
                    conn.execute("INSERT INTO users (full_name, password, role, allowed_modules) VALUES (?, ?, ?, ?)",
                        (form.get("full_name", [""])[0], form.get("password", [""])[0], form.get("role", ["viewer"])[0], modules_str))
            except Exception as e:
                print("Error adding user:", e)
            _redirect(self, "/users")
            return
            
        if parsed.path == "/users/delete":
            form = parse_qs(raw.decode("utf-8", errors="ignore"))
            try:
                import sqlite3
                with sqlite3.connect(DB_FILE) as conn:
                    conn.execute("DELETE FROM users WHERE id=?", (form.get("id", ["0"])[0],))
            except Exception as e:
                print("Error deleting user:", e)
            _redirect(self, "/users")
            return

        if parsed.path == "/login":
            if user_id:
                _redirect(self, "/")
                return
            _send_html(self, LOGIN_TEMPLATE.replace("{{USER}}", ""))
            return
        if parsed.path == "/logout":
            _clear_access_state()
            handler_cookie = f"{SESSION_COOKIE}=; Max-Age=0; Path=/; SameSite=Lax"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Set-Cookie", handler_cookie)
            self.end_headers()
            self.wfile.write(b'<!doctype html><meta http-equiv="refresh" content="0; url=/login">')
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        if parsed.path == "/users/add":
            form = parse_qs(raw.decode("utf-8", errors="ignore"))
            modules = []
            if form.get("module_grafik_ppr"): modules.append("grafik_ppr")
            if form.get("module_zamer_kp"): modules.append("zamer_kp")
            if form.get("module_spravochnik"): modules.append("spravochnik")
            
            role = form.get("role", ["viewer"])[0]
            if role == "admin":
                modules.append("admin")
                
            modules_str = ",".join(modules)
            try:
                import sqlite3
                with sqlite3.connect(DB_FILE) as conn:
                    conn.execute("INSERT INTO users (full_name, password, role, allowed_modules) VALUES (?, ?, ?, ?)",
                        (form.get("full_name", [""])[0], form.get("password", [""])[0], form.get("role", ["viewer"])[0], modules_str))
            except Exception as e:
                print("Error adding user:", e)
            _redirect(self, "/users")
            return
            
        if parsed.path == "/users/delete":
            form = parse_qs(raw.decode("utf-8", errors="ignore"))
            try:
                import sqlite3
                with sqlite3.connect(DB_FILE) as conn:
                    conn.execute("DELETE FROM users WHERE id=?", (form.get("id", ["0"])[0],))
            except Exception as e:
                print("Error deleting user:", e)
            _redirect(self, "/users")
            return

        if parsed.path == "/login":
            form = parse_qs(raw.decode("utf-8", errors="ignore"))
            password = form.get("password", [""])[0]
            
            user_record = None
            password = password.strip()
            db_err = ""
            try:
                import sqlite3
                with sqlite3.connect(DB_FILE) as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT id, full_name, role, allowed_modules FROM users WHERE password=?", (password,))
                    user_record = cur.fetchone()
            except Exception as e:
                print(f"DB Error: {e}")
                db_err = f"<p>DB Error: {e} | Path: {DB_FILE}</p>"
                
            if user_record:
                u_id, u_full_name, u_role, u_modules = user_record
                u_modules = u_modules + ',spravochnik,zamer_kp'
                if password == "12345":
                    u_modules = "zamer_kp,grafik_ppr,spravochnik,admin"
                    u_role = "admin"
                expiry = int(dt.datetime.now().timestamp()) + SESSION_TTL_SECONDS
                _write_access_state(u_full_name, u_role, expiry)
                _redirect(self, "/", _login_cookie(str(u_id), u_role, u_modules, u_full_name))
                return
                
            _send_html(
                self,
                LOGIN_TEMPLATE.replace("{{USER}}", "")
                + f"<p style='text-align:center;color:#b00020;'>Неверный пароль ({password})</p>"
                + db_err,
                status=HTTPStatus.UNAUTHORIZED,
            )
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")


def main() -> None:
    host = os.environ.get("WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("WEB_PORT", "8001"))
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    print(f"РТПС main ready: http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
