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
DB_LOCK = Lock()

MONTHS = [
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]


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


def verify_cookie(value: str) -> tuple[str, str] | None:
    parts = value.split("|")
    if len(parts) != 4:
        return None
    username, role, expiry_text, sig = parts
    payload = f"{username}|{role}|{expiry_text}"
    expected = hmac.new(WEB_SECRET.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return None
    try:
        expiry = float(expiry_text)
    except ValueError:
        return None
    if dt.datetime.now().timestamp() > expiry:
        return None
    return username, role


def parse_cookies(handler: BaseHTTPRequestHandler) -> dict[str, str]:
    result: dict[str, str] = {}
    for part in handler.headers.get("Cookie", "").split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def verify_cookie(value: str) -> tuple[str, str] | None:
    parts = value.split("|")
    if len(parts) != 4:
        return None
    username, role, expiry_text, sig = parts
    payload = f"{username}|{role}|{expiry_text}"
    expected = hmac.new(WEB_SECRET.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return None
    try:
        expiry = float(expiry_text)
    except ValueError:
        return None
    if dt.datetime.now().timestamp() > expiry:
        return None
    return username, role


def parse_cookies(handler: BaseHTTPRequestHandler) -> dict[str, str]:
    result: dict[str, str] = {}
    for part in handler.headers.get("Cookie", "").split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def current_session(handler: BaseHTTPRequestHandler) -> tuple[str, str] | None:
    cookies = parse_cookies(handler)
    token = cookies.get(SESSION_COOKIE)
    if not token:
        return None
    return verify_cookie(token)


def require_auth(handler: BaseHTTPRequestHandler, need_edit: bool = False) -> bool:
    session = current_session(handler)
    if session and (not need_edit or session[1] == "edit"):
        return True
    handler.send_response(HTTPStatus.UNAUTHORIZED)
    handler.send_header("Content-Type", "text/plain; charset=utf-8")
    handler.send_header("WWW-Authenticate", 'Form realm="Grafik PPR"')
    handler.end_headers()
    handler.wfile.write("Требуется вход".encode("utf-8"))
    return False


def login_cookie(username: str, role: str) -> str:
    expiry = int(dt.datetime.now().timestamp()) + SESSION_TTL_SECONDS
    payload = f"{username}|{role}|{expiry}"
    sig = hmac.new(WEB_SECRET.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    token = f"{payload}|{sig}"
    return f"{SESSION_COOKIE}={token}; HttpOnly; Path=/; SameSite=Lax; Max-Age={SESSION_TTL_SECONDS}"


def send_json(handler: BaseHTTPRequestHandler, payload: dict, status: int = 200) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def send_html(handler: BaseHTTPRequestHandler, body: str, status: int = 200) -> None:
    data = body.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
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
        for row in cur.execute("SELECT ser, num, inv FROM inventory WHERE y=? ORDER BY rowid", (year,)):
            inventory.append([text(row["ser"]), text(row["num"]), text(row["inv"])])
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

        cur.execute("DELETE FROM inventory WHERE y=?", (year,))
        inv_rows = []
        for row in inventory:
            row = list(row or []) + [""] * 3
            ser, num, inv = [text(v).strip() for v in row[:3]]
            if ser or num:
                inv_rows.append((year, ser, num, inv))
        cur.executemany("INSERT INTO inventory VALUES (?,?,?,?)", inv_rows)
        conn.commit()


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
    .top{display:flex;gap:10px;align-items:center;justify-content:space-between;background:#fff;border:1px solid var(--line);border-radius:18px;padding:14px 16px;margin-bottom:14px}
    h1{margin:0;font-size:24px}.muted{color:var(--muted);font-size:13px}
    .actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
    button,a,select{border:1px solid var(--line);border-radius:8px;padding:10px 13px;background:#fff;color:#001b3d;font-weight:700;text-decoration:none;font:inherit}
    button.primary{background:var(--blue);border-color:var(--blue);color:#fff}
    .tabs{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}
    .tab{cursor:pointer}.tab.active{background:var(--blue);color:#fff;border-color:var(--blue)}
    .panel{display:none;background:#fff;border:1px solid var(--line);border-radius:18px;padding:14px;overflow:auto}
    .panel.active{display:block}
    table{border-collapse:collapse;width:100%;min-width:760px}
    th,td{border:1px solid var(--line);padding:0;height:34px;text-align:center}
    th{background:#eef4fb;font-weight:700}
    td input{width:100%;height:34px;border:0;padding:6px 8px;font:inherit;text-align:center;background:transparent}
    td input[type=checkbox]{width:auto;height:auto}
    .left{text-align:left!important}
    .rowbar{display:flex;gap:8px;justify-content:flex-end;margin-bottom:10px}
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
      <label>Год <select id="year"></select></label>
      <button class="primary" onclick="saveAll()">Сохранить</button>
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
<script>
const API = '/spravochnik';
let state = null;
const headers = {
  norms: ['Месяц','Кал. дни','Раб. дни','Вых и празд.','40-ч','36-ч','Переносы дней','Праздники'],
  employees: ['Должность','ФИО','ФИО полное','Таб. №','Молоко комп','Молоко выдача','Молоко прим.'],
  inventory: ['Серия','Номер','Инвентарный №']
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
  renderAll();
}

function renderAll(){
  renderTable('norms', state.norms, false);
  renderTable('employees', state.employees, true);
  renderTable('inventory', state.inventory, true);
}

function renderTable(name, rows, editableRows){
  const panel = document.getElementById(name);
  const rowbar = editableRows ? `<div class="rowbar"><button onclick="addRow('${name}')">+ строку</button><button onclick="deleteRow('${name}')">- строку</button></div>` : '';
  let html = rowbar + '<table><thead><tr><th style="width:42px">№</th>' + headers[name].map(h => `<th>${h}</th>`).join('') + '</tr></thead><tbody>';
  rows.forEach((row, r) => {
    html += `<tr onclick="selectRow('${name}', ${r})"><td>${r + 1}</td>`;
    headers[name].forEach((_, c) => {
      const val = row[c] ?? '';
      if(name === 'employees' && (c === 4 || c === 5)){
        html += `<td><input type="checkbox" ${val ? 'checked' : ''} onchange="setCell('${name}',${r},${c},this.checked)"></td>`;
      } else {
        const cls = c === 0 || (name === 'employees' && c < 3) ? 'left' : '';
        html += `<td><input class="${cls}" value="${escapeHtml(val)}" oninput="setCell('${name}',${r},${c},this.value)"></td>`;
      }
    });
    html += '</tr>';
  });
  html += '</tbody></table>';
  panel.innerHTML = html;
}

let selected = {employees: -1, inventory: -1};
function selectRow(name, row){ selected[name] = row; }
function setCell(name, row, col, value){ state[name][row][col] = value; }
function addRow(name){
  const cols = headers[name].length;
  state[name].push(Array(cols).fill(''));
  renderTable(name, state[name], true);
}
function deleteRow(name){
  const row = selected[name] >= 0 ? selected[name] : state[name].length - 1;
  if(row >= 0) state[name].splice(row, 1);
  selected[name] = -1;
  renderTable(name, state[name], true);
}
async function saveAll(){
  state.year = Number(document.getElementById('year').value);
  const res = await fetch(`${API}/api/save`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(state)});
  if(!res.ok){ alert('Ошибка сохранения'); return; }
  alert('Сохранено');
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
    button{background:#276ef1;color:#fff;font-weight:700;cursor:pointer;border:0}
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


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def do_GET(self):
        path = route_path(self.path)
        session = current_session(self)
        user = session[0] if session else None
        role = session[1] if session else None
        if path == "/login":
            if user:
                redirect(self, APP_PREFIX + "/")
                return
            send_html(self, HTML.replace("{{USER}}", WEB_USER).replace("{{AUTH_BADGE}}", "Вход не выполнен"))
            return
        if path == "/logout":
            handler_cookie = f"{SESSION_COOKIE}=; Max-Age=0; Path=/; SameSite=Lax"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Set-Cookie", handler_cookie)
            self.end_headers()
            self.wfile.write(b'<!doctype html><meta http-equiv="refresh" content="0; url=/spravochnik/login">')
            return
        parsed = urlparse(self.path)
        if path == "/":
            if not user:
                redirect(self, APP_PREFIX + "/login")
                return
            badge = "Просмотр" if role == "view" else "Редактирование"
            send_html(self, HTML.replace("{{USER}}", WEB_USER).replace("{{AUTH_BADGE}}", badge))
            return
        if path == "/api/state":
            if not require_auth(self):
                return
            year = int(parse_qs(parsed.query).get("year", [dt.date.today().year])[0])
            send_json(self, load_state(year))
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self):
        path = route_path(self.path)
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        if path == "/login":
            form = parse_qs(raw.decode("utf-8", errors="ignore"))
            password = form.get("password", [""])[0]
            if password == WEB_VIEW_PASSWORD:
                redirect(self, APP_PREFIX + "/", login_cookie(WEB_USER, "view"))
                return
            if password == WEB_EDIT_PASSWORD:
                redirect(self, APP_PREFIX + "/", login_cookie(WEB_USER, "edit"))
                return
            send_html(
                self,
                HTML.replace("{{USER}}", WEB_USER).replace("{{AUTH_BADGE}}", "Неверный логин или пароль"),
                status=HTTPStatus.UNAUTHORIZED,
            )
            return
        if path == "/api/save":
            if not require_auth(self, need_edit=True):
                return
            try:
                payload = json.loads(raw.decode("utf-8"))
                save_state(payload)
                send_json(self, {"ok": True})
            except Exception as exc:
                send_json(self, {"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")


def main() -> None:
    ensure_db()
    host = os.environ.get("WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("WEB_PORT", "8002"))
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    print(f"Справочник ready: http://{host}:{port}{APP_PREFIX}")
    server.serve_forever()


if __name__ == "__main__":
    main()
