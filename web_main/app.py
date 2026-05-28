from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
import secrets
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
AUTH_FILE = DATA_DIR / "web_auth.json"
SHARED_DATA_DIR = ROOT.parent / "data"
WEB_SECRET_FILE = SHARED_DATA_DIR / "web_secret.txt"
SESSION_COOKIE = "grafik_ppr_session"
SESSION_TTL_SECONDS = 7 * 24 * 60 * 60


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
    secret = secrets.token_urlsafe(32)
    WEB_SECRET_FILE.write_text(secret, encoding="utf-8")
    return secret


WEB_SECRET = load_web_secret()


def load_auth_config() -> tuple[str, str, str]:
    user = os.environ.get("WEB_USER", "rtps").strip() or "rtps"
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
SESSIONS: dict[str, tuple[str, str, float]] = {}


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
        <a class="badge" href="/logout">Выйти</a>
        <div class="badge">{{AUTH_BADGE}}</div>
      </div>
    </div>

    <div class="grid">
      <div class="card">
        <div>
          <h2>График ППР</h2>
          <p>План, факт, нормы, инвентарь и акты.</p>
        </div>
        <a href="/grafik-ppr">Открыть</a>
      </div>
      <div class="card">
        <div>
          <h2>Замер КП</h2>
          <p>Следующий модуль.</p>
        </div>
        <a class="disabled" href="#">Скоро</a>
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
        <a href="/spravochnik">Открыть</a>
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


def _cookie_value(username: str, role: str) -> str:
    expiry = int(dt.datetime.now().timestamp()) + SESSION_TTL_SECONDS
    payload = f"{username}:{role}:{expiry}"
    sig = hmac.new(WEB_SECRET.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    token = f"{payload}:{sig}"
    SESSIONS[token] = (username, role, float(expiry))
    return token


def _verify_cookie(value: str) -> tuple[str, str] | None:
    try:
        username, role, ts, sig = value.rsplit(":", 3)
        payload = f"{username}:{role}:{ts}"
        expected = hmac.new(WEB_SECRET.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, sig):
            return None
        if int(ts) + SESSION_TTL_SECONDS < int(dt.datetime.now().timestamp()):
            return None
        if role not in {"view", "edit"}:
            return None
        return username, role
    except Exception:
        try:
            username, role, expiry_text, sig = value.split("|")
            payload = f"{username}|{role}|{expiry_text}"
            expected = hmac.new(WEB_SECRET.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, sig):
                return None
            if dt.datetime.now().timestamp() > float(expiry_text):
                return None
            if role not in {"view", "edit"}:
                return None
            return username, role
        except Exception:
            return None


def _parse_cookies(handler: BaseHTTPRequestHandler) -> dict[str, str]:
    raw = handler.headers.get("Cookie", "")
    cookies: dict[str, str] = {}
    for part in raw.split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        cookies[key.strip()] = value.strip()
    return cookies


def current_session(handler: BaseHTTPRequestHandler) -> tuple[str, str] | None:
    cookies = _parse_cookies(handler)
    token = cookies.get(SESSION_COOKIE)
    if not token:
        return None
    session = _verify_cookie(token)
    if session:
        username, role = session
        SESSIONS[token] = (username, role, dt.datetime.now().timestamp())
    return session


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


def _login_cookie(username: str, role: str) -> str:
    token = _cookie_value(username, role)
    return f"{SESSION_COOKIE}={token}; HttpOnly; Path=/; SameSite=Lax; Max-Age={SESSION_TTL_SECONDS}"


def render_home(username: str, role: str) -> str:
    started_at = dt.datetime.now().strftime("%H:%M:%S %d.%m.%Y")
    role_label = "Просмотр" if role == "view" else "Редактирование"
    return HOME_TEMPLATE.replace("{{STARTED_AT}}", started_at).replace("{{AUTH_BADGE}}", f"Пользователь: {username} / {role_label}")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # noqa: D401
        return

    def do_GET(self):
        parsed = urlparse(self.path)
        session = current_session(self)
        user = session[0] if session else None
        role = session[1] if session else None
        if parsed.path == "/":
            if not user:
                _redirect(self, "/login")
                return
            _send_html(self, render_home(user, role or "view"))
            return
        if parsed.path == "/grafik-ppr":
            _redirect(self, "https://yrtps.ru/grafik-ppr")
            return
        if parsed.path == "/login":
            if user:
                _redirect(self, "/")
                return
            _send_html(self, LOGIN_TEMPLATE.replace("{{USER}}", WEB_USER))
            return
        if parsed.path == "/logout":
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
        if parsed.path == "/login":
            form = parse_qs(raw.decode("utf-8", errors="ignore"))
            password = form.get("password", [""])[0]
            if password == WEB_VIEW_PASSWORD:
                _redirect(self, "/", _login_cookie(WEB_USER, "view"))
                return
            if password == WEB_EDIT_PASSWORD:
                _redirect(self, "/", _login_cookie(WEB_USER, "edit"))
                return
            _send_html(
                self,
                LOGIN_TEMPLATE.replace("{{USER}}", WEB_USER)
                + "<p style='text-align:center;color:#b00020;'>Неверный логин или пароль</p>",
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
