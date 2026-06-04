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
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
SHARED_DATA_DIR = ROOT.parent / "data"
AUTH_FILE = SHARED_DATA_DIR / "web_auth.json"
WEB_SECRET_FILE = SHARED_DATA_DIR / "web_secret.txt"
SESSION_COOKIE = "grafik_ppr_session"
SESSION_TTL_SECONDS = 7 * 24 * 60 * 60
APP_PREFIX = "/zamer-kp"
APP_VERSION = "web-zkp-0.1"
SESSIONS: dict[str, tuple[str, str, float]] = {}


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
            if file_view and file_edit:
                return file_user, file_view, file_edit
        except Exception:
            pass
    return user, view_password or secrets.token_urlsafe(8), edit_password or secrets.token_urlsafe(8)


WEB_SECRET = load_web_secret()
WEB_USER, WEB_VIEW_PASSWORD, WEB_EDIT_PASSWORD = load_auth_config()


def _verify_cookie(value: str) -> tuple[str, str] | None:
    try:
        username, role, ts, sig = value.rsplit(":", 3)
        payload = f"{username}:{role}:{ts}"
        expected = hmac.new(WEB_SECRET.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature := sig, expected):
            return None
        if int(ts) + SESSION_TTL_SECONDS < int(dt.datetime.now().timestamp()):
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
    token = _parse_cookies(handler).get(SESSION_COOKIE)
    if not token:
        return None
    session = _verify_cookie(token)
    if session:
        SESSIONS[token] = (session[0], session[1], dt.datetime.now().timestamp())
    return session


def _route_path(path: str) -> str:
    if path == APP_PREFIX:
        return APP_PREFIX
    if path.startswith(APP_PREFIX + "/"):
        return path[len(APP_PREFIX):] or "/"
    return path


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


def _redirect(handler: BaseHTTPRequestHandler, location: str) -> None:
    handler.send_response(HTTPStatus.SEE_OTHER)
    handler.send_header("Location", location)
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()


HTML_TEMPLATE = """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Замер КП {{APP_VERSION}}</title>
  <style>
    :root { --line:#d9e2ef; --text:#102033; --muted:#66758a; --blue:#276ef1; --bg:#f4f7fb; }
    * { box-sizing:border-box; }
    body { margin:0; font-family:Segoe UI, Arial, sans-serif; background:var(--bg); color:var(--text); }
    .shell { padding:18px; }
    .topbar,.panel { background:rgba(255,255,255,.9); border:1px solid var(--line); border-radius:20px; box-shadow:0 12px 32px rgba(16,32,51,.06); }
    .topbar { display:flex; align-items:center; justify-content:space-between; gap:16px; padding:18px 22px; }
    h1 { margin:0; font-size:24px; }
    .sub { margin-top:4px; color:var(--muted); font-size:13px; }
    .controls,.tabs { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
    a,button { border:1px solid var(--line); border-radius:8px; padding:10px 14px; background:#fff; color:var(--text); text-decoration:none; font:inherit; cursor:pointer; }
    .primary { background:var(--blue); color:#fff; border-color:var(--blue); font-weight:700; }
    .panel { margin-top:16px; padding:14px; }
    .tabs button { min-width:140px; font-weight:600; }
    .tabs button.active { background:var(--blue); border-color:var(--blue); color:#fff; }
  </style>
</head>
<body>
  <div class="shell">
    <div class="topbar">
      <div>
        <h1>Замер КП</h1>
        <div class="sub">Версия {{APP_VERSION}}</div>
      </div>
      <div class="controls">
        <a href="/">На главную</a>
      </div>
    </div>
    <div class="panel">
      <div class="tabs">
        <button class="active">Ввод замера</button>
        <button>Архив замеров</button>
        <button>КП данные</button>
      </div>
    </div>
  </div>
</body>
</html>
"""


def render_page() -> str:
    return HTML_TEMPLATE.replace("{{APP_VERSION}}", APP_VERSION)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # noqa: D401
        return

    def do_GET(self):
        parsed = urlparse(self.path)
        route = _route_path(parsed.path)
        if not current_session(self):
            _redirect(self, "/login")
            return
        if route in {APP_PREFIX, "/"}:
            _send_html(self, render_page())
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")


def main() -> None:
    host = os.environ.get("WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("WEB_PORT", "8003"))
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    print(f"Замер КП ready: http://{host}:{port}{APP_PREFIX}")
    server.serve_forever()


if __name__ == "__main__":
    main()
