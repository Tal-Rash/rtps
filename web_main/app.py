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
    .toggle-link { color:#276ef1; text-decoration:none; font-weight:600; cursor:pointer; font-size:14px; text-align:center; display:block; margin-top:16px; }
    .toggle-link:hover { text-decoration:underline; }
    #request-form { display:none; }
  </style>
</head>
<body>
  <div class="card" id="login-form">
    <form method="post" action="/login">
      <h1 style="margin-top:0;">Вход</h1>
      <p class="muted">Введите пароль просмотра или редактирования.</p>
      <input name="password" type="password" placeholder="Пароль" style="margin-bottom:12px;" required>
      <button type="submit">Войти</button>
    </form>
    <a class="toggle-link" onclick="document.getElementById('login-form').style.display='none'; document.getElementById('request-form').style.display='block';">Запросить доступ / Восстановить пароль</a>
  </div>

  <div class="card" id="request-form">
    <form method="post" action="/request_access">
      <h1 style="margin-top:0;">Запрос доступа</h1>
      <p class="muted">Введите ФИО и желаемый пароль. Если вы забыли пароль, введите новое значение — доступ будет временно приостановлен до одобрения администратором.</p>
      <input name="full_name" type="text" placeholder="Фамилия И.О." style="margin-bottom:12px;" required>
      <input name="password" type="text" placeholder="Новый пароль" style="margin-bottom:12px;" required>
      <button type="submit">Запросить доступ</button>
    </form>
    <a class="toggle-link" onclick="document.getElementById('request-form').style.display='none'; document.getElementById('login-form').style.display='block';">Вернуться ко входу</a>
  </div>
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
    .card { max-width:1000px; margin:0 auto; background:#fff; border:1px solid #d9e2ef; border-radius:18px; padding:24px; box-shadow:0 12px 32px rgba(16,32,51,.08); }
    table { width:100%; border-collapse:collapse; margin-top:20px; }
    th, td { text-align:left; padding:10px; border-bottom:1px solid #d9e2ef; vertical-align:middle; }
    input, select, button { padding:8px; border-radius:6px; border:1px solid #d9e2ef; font:inherit; }
    button { background:#276ef1; color:#fff; font-weight:700; cursor:pointer; border:0; }
    .btn-danger { background:#e11d48; }
    .flex { display:flex; gap:10px; align-items:center; }
    .muted { color:#607086; font-size:13px; }
    
    table input, table select { padding:6px 8px; font-size:13px; border-radius:6px; }
    table button { padding:6px 14px; font-size:13px; }
    .mod-label { display:flex; justify-content:space-between; align-items:center; gap:8px; font-size:13px; color:#102033; }
    .mod-label select { padding:4px 6px; font-size:13px; }
  </style>
</head>
<body>
  <div class="card">
    <div class="flex" style="justify-content:space-between; margin-bottom:20px;">
        <h1 style="margin:0;">Управление доступом</h1>
        <a href="/" style="color:#276ef1; text-decoration:none; font-weight:bold;">На главную</a>
    </div>
    
    <form method="post" action="/users/add" style="background:#f8fafc; padding:20px; border-radius:12px; margin-bottom:20px; border:1px solid #d9e2ef;">
      <h3 style="margin-top:0; margin-bottom:16px;">Добавить пользователя</h3>
      <div style="display:flex; flex-direction:column; gap:16px;">
        <div style="display:flex; gap:12px; flex-wrap:wrap;">
          <input name="full_name" placeholder="Фамилия И.О." required style="flex:2; min-width:180px;">
          <input name="password" placeholder="Пароль (ПИН)" required style="flex:1; min-width:120px;">
          <select name="role" style="flex:1; min-width:140px;">
              <option value="pending">Ожидает подтверждения</option>
              <option value="viewer" selected>Зритель</option>
              <option value="editor">Редактор</option>
              <option value="admin">Администратор</option>
          </select>
        </div>
        <div style="display:flex; gap:16px; align-items:center; flex-wrap:wrap; border:1px solid #e2e8f0; padding:12px 16px; border-radius:8px; background:#fff;">
          <div style="font-weight:600; font-size:14px; margin-right:8px; color:#475569;">Доступ:</div>
          <label class="mod-label" style="cursor:pointer; margin:0;">ППР: <select name="module_grafik_ppr" style="padding:6px;"><option value="none">Нет доступа</option><option value="view">Зритель</option><option value="edit">Редактор</option></select></label>
          <label class="mod-label" style="cursor:pointer; margin:0;">Замер: <select name="module_zamer_kp" style="padding:6px;"><option value="none">Нет доступа</option><option value="view">Зритель</option><option value="edit">Редактор</option></select></label>
          <label class="mod-label" style="cursor:pointer; margin:0;">Справ: <select name="module_spravochnik" style="padding:6px;"><option value="none">Нет доступа</option><option value="view">Зритель</option><option value="edit">Редактор</option></select></label>
        </div>
        <button type="submit" style="align-self:flex-start; padding:10px 24px;">Добавить пользователя</button>
      </div>
    </form>

    <div style="overflow-x: auto;">
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
  </div>
</body>
</html>
'''

def _cookie_value(user_id: str, role: str, modules: str, full_name: str) -> str:
    import urllib.parse
    expiry = int(dt.datetime.now().timestamp()) + SESSION_TTL_SECONDS
    safe_name = urllib.parse.quote(full_name.replace(":", " "))
    payload = f"{user_id}|{role}|{modules}|{safe_name}|{expiry}"
    sig = hmac.new(WEB_SECRET.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    token = f"{payload}|{sig}"
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
        user_id, role, modules, safe_name, ts, sig = value.split("|", 5)
        payload = f"{user_id}|{role}|{modules}|{safe_name}|{ts}"
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
        if "admin" in mods:
            return f'<a href="{path}">Открыть</a>'
        for m in mods:
            if m == mod_id or m.startswith(mod_id + ":"):
                return f'<a href="{path}">Открыть</a>'
        return '<a class="disabled" href="#" aria-disabled="true" tabindex="-1">Нет доступа</a>'
    users_link = ""
    if role == "admin" or "admin" in mods:
        pending_count = 0
        try:
            import sqlite3
            with sqlite3.connect(DB_FILE) as conn:
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) FROM users WHERE role='pending'")
                pending_count = cur.fetchone()[0]
        except Exception:
            pass
            
        if pending_count > 0:
            users_link = f'<a class="badge" href="/users" style="background:#e11d48; color:#fff; border-color:#e11d48; font-weight:bold;">Управление доступом ({pending_count})</a>'
        else:
            users_link = '<a class="badge" href="/users" style="background:#276ef1; color:#fff; border-color:#276ef1;">Управление доступом</a>'
    return (
        HOME_TEMPLATE
        .replace("{{STARTED_AT}}", started_at)
        .replace("{{AUTH_BADGE}}", f"{full_name} ({role_label})")
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
            if not user_id or (role != "admin" and "admin" not in modules):
                _redirect(self, "/")
                return
            
            rows_html = ""
            try:
                import sqlite3
                with sqlite3.connect(DB_FILE) as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT id, full_name, password, role, allowed_modules FROM users ORDER BY id")
                    for u in cur.fetchall():
                        fid = f"form_{u[0]}"
                        mods = u[4] or ""
                        bg_color = "background:#fff3cd;" if u[3] == "pending" else ""
                        rows_html += f"<tr style='{bg_color}'><td>{u[0]}</td>"
                        rows_html += f"<td><input form='{fid}' name='full_name' value='{u[1]}' required style='min-width:160px; max-width:200px;'></td>"
                        rows_html += f"<td><input form='{fid}' name='password' value='{u[2]}' required style='min-width:120px; max-width:160px;'></td>"
                        rows_html += f"<td><select form='{fid}' name='role'>"
                        rows_html += f"<option value='pending' {'selected' if u[3]=='pending' else ''}>Ожидает</option>"
                        rows_html += f"<option value='viewer' {'selected' if u[3]=='viewer' else ''}>Зритель</option>"
                        rows_html += f"<option value='editor' {'selected' if u[3]=='editor' else ''}>Редактор</option>"
                        rows_html += f"<option value='admin' {'selected' if u[3]=='admin' else ''}>Администратор</option>"
                        rows_html += f"</select></td>"
                        def get_mod_role(modules_str: str, mod_name: str) -> str:
                            for part in modules_str.split(","):
                                part = part.strip()
                                if not part: continue
                                if ":" in part:
                                    k, v = part.split(":", 1)
                                    if k == mod_name: return v
                                else:
                                    if part == mod_name: return "legacy"
                            return "none"
                        def rsel(rname: str, target: str) -> str: return "selected" if rname == target else ""
                        g_r = get_mod_role(mods, "grafik_ppr")
                        if g_r == "legacy": g_r = "edit" if u[3] in ("edit", "editor", "admin") else "view"
                        z_r = get_mod_role(mods, "zamer_kp")
                        if z_r == "legacy": z_r = "edit" if u[3] in ("edit", "editor", "admin") else "view"
                        s_r = get_mod_role(mods, "spravochnik")
                        if s_r == "legacy": s_r = "edit" if u[3] in ("edit", "editor", "admin") else "view"
                        
                        rows_html += f"<td style='vertical-align:top;'>"
                        rows_html += f"<div style='display:flex; flex-direction:column; gap:6px;'>"
                        rows_html += f"<label class='mod-label'>ППР: <select form='{fid}' name='module_grafik_ppr'><option value='none' {rsel(g_r,'none')}>Нет доступа</option><option value='view' {rsel(g_r,'view')}>Зритель</option><option value='edit' {rsel(g_r,'edit')}>Редактор</option></select></label>"
                        rows_html += f"<label class='mod-label'>Замер: <select form='{fid}' name='module_zamer_kp'><option value='none' {rsel(z_r,'none')}>Нет доступа</option><option value='view' {rsel(z_r,'view')}>Зритель</option><option value='edit' {rsel(z_r,'edit')}>Редактор</option></select></label>"
                        rows_html += f"<label class='mod-label'>Справ: <select form='{fid}' name='module_spravochnik'><option value='none' {rsel(s_r,'none')}>Нет доступа</option><option value='view' {rsel(s_r,'view')}>Зритель</option><option value='edit' {rsel(s_r,'edit')}>Редактор</option></select></label>"
                        rows_html += f"</div></td>"
                        rows_html += f"<td><div class='flex'>"
                        rows_html += f"<form id='{fid}' method='post' action='/users/update' style='margin:0;'><input type='hidden' name='id' value='{u[0]}'><button type='submit'>Сохранить</button></form>"
                        rows_html += f"<form method='post' action='/users/delete' style='margin:0;'><input type='hidden' name='id' value='{u[0]}'><button class='btn-danger' type='submit'>Удалить</button></form>"
                        rows_html += f"</div></td></tr>"
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
            g_r = form.get("module_grafik_ppr", ["none"])[0]
            z_r = form.get("module_zamer_kp", ["none"])[0]
            s_r = form.get("module_spravochnik", ["none"])[0]
            
            if g_r != "none": modules.append(f"grafik_ppr:{g_r}")
            if z_r != "none": modules.append(f"zamer_kp:{z_r}")
            if s_r != "none": modules.append(f"spravochnik:{s_r}")
            
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
            g_r = form.get("module_grafik_ppr", ["none"])[0]
            z_r = form.get("module_zamer_kp", ["none"])[0]
            s_r = form.get("module_spravochnik", ["none"])[0]
            
            if g_r != "none": modules.append(f"grafik_ppr:{g_r}")
            if z_r != "none": modules.append(f"zamer_kp:{z_r}")
            if s_r != "none": modules.append(f"spravochnik:{s_r}")
            
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
            
        if parsed.path == "/users/update":
            form = parse_qs(raw.decode("utf-8", errors="ignore"))
            uid = form.get("id", ["0"])[0]
            full_name = form.get("full_name", [""])[0]
            password = form.get("password", [""])[0]
            role = form.get("role", ["viewer"])[0]
            
            modules = []
            g_r = form.get("module_grafik_ppr", ["none"])[0]
            z_r = form.get("module_zamer_kp", ["none"])[0]
            s_r = form.get("module_spravochnik", ["none"])[0]
            
            if g_r != "none": modules.append(f"grafik_ppr:{g_r}")
            if z_r != "none": modules.append(f"zamer_kp:{z_r}")
            if s_r != "none": modules.append(f"spravochnik:{s_r}")
            if role == "admin": modules.append("admin")
            modules_str = ",".join(modules)
            
            try:
                import sqlite3
                with sqlite3.connect(DB_FILE) as conn:
                    conn.execute("UPDATE users SET full_name=?, password=?, role=?, allowed_modules=? WHERE id=?", 
                        (full_name, password, role, modules_str, uid))
            except Exception as e:
                print("Error updating user:", e)
            _redirect(self, "/users")
            return

        if parsed.path == "/request_access":
            form = parse_qs(raw.decode("utf-8", errors="ignore"))
            full_name = form.get("full_name", [""])[0].strip()
            password = form.get("password", [""])[0].strip()
            if full_name and password:
                try:
                    import sqlite3
                    with sqlite3.connect(DB_FILE) as conn:
                        cur = conn.cursor()
                        cur.execute("SELECT id, role FROM users WHERE full_name=?", (full_name,))
                        existing = cur.fetchone()
                        if existing:
                            conn.execute("UPDATE users SET password=?, role='pending', allowed_modules='' WHERE id=?", (password, existing[0]))
                        else:
                            conn.execute("INSERT INTO users (full_name, password, role, allowed_modules) VALUES (?, ?, 'pending', '')",
                                (full_name, password))
                except Exception as e:
                    print("Error requesting access:", e)
            
            html = """<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Запрос отправлен</title>
            <style>body{margin:0;font-family:Segoe UI, Arial, sans-serif;background:#f4f7fb;color:#102033;text-align:center;padding:50px;} .card{background:#fff;padding:40px;border-radius:18px;max-width:400px;margin:10vh auto;box-shadow:0 12px 32px rgba(16,32,51,.08);}</style>
            </head><body><div class="card"><h2 style="margin-top:0;color:#0f172a;">Запрос отправлен</h2><p style="color:#64748b;margin-bottom:24px;">Ожидайте подтверждения администратором.</p><a href="/login" style="background:#276ef1;color:#fff;text-decoration:none;font-weight:bold;padding:12px 24px;border-radius:8px;display:inline-block;">На главную</a></div></body></html>"""
            _send_html(self, html)
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
                if u_role == "pending":
                    _send_html(
                        self,
                        LOGIN_TEMPLATE.replace("{{USER}}", "")
                        + f"<p style='text-align:center;color:#b00020;'>Учетная запись ожидает подтверждения администратором.</p>",
                        status=HTTPStatus.UNAUTHORIZED,
                    )
                    return
                u_modules = u_modules or ""
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
