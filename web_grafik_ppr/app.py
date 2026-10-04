from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import hmac
import json
import os
import sys
import threading
import webbrowser
from pathlib import Path
from urllib.parse import unquote

from fastapi import FastAPI, Request, Response, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

# Добавляем пути к родительским каталогам для импорта общих модулей
_PKG_ROOT = Path(__file__).resolve().parent
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))
if str(_PKG_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT.parent))

from rtps_common import module_role, resolve_user_access

try:
    from .constants import (
        APP_VERSION,
        MONTHS_RU,
        TEM_NORM_ROWS,
        AGR_NORM_ROWS,
        ROOT,
        DATA_DIR,
        SHARED_DATA_DIR,
        WEB_SECRET_FILE,
        SESSION_COOKIE,
        SESSION_TTL_SECONDS,
        MAIN_LOGIN_URL,
        APP_PREFIX,
        AUTH_ENABLED,
    )
    from .calculations import (
        calculate_report_data_from_state,
        build_report_preview,
    )
    from .storage import (
        ensure_database,
        load_state,
        save_state,
        conn,
        DB_LOCK,
        get_all_employee_names,
        get_employee_vacations,
    )
    from .reports import (
        build_act_workbook,
        build_report_workbook,
        build_tu28_workbook,
        content_disposition_attachment,
    )
except (ImportError, ValueError):
    from constants import (
        APP_VERSION,
        MONTHS_RU,
        TEM_NORM_ROWS,
        AGR_NORM_ROWS,
        ROOT,
        DATA_DIR,
        SHARED_DATA_DIR,
        WEB_SECRET_FILE,
        SESSION_COOKIE,
        SESSION_TTL_SECONDS,
        MAIN_LOGIN_URL,
        APP_PREFIX,
        AUTH_ENABLED,
    )
    from calculations import (
        calculate_report_data_from_state,
        build_report_preview,
    )
    from storage import (
        ensure_database,
        load_state,
        save_state,
        conn,
        DB_LOCK,
        get_all_employee_names,
        get_employee_vacations,
    )
    from reports import (
        build_act_workbook,
        build_report_workbook,
        build_tu28_workbook,
        content_disposition_attachment,
    )

def load_web_secret() -> str:
    # Загрузка общего секретного ключа для проверки подписей кук
    if WEB_SECRET_FILE.exists():
        try:
            return WEB_SECRET_FILE.read_text(encoding="utf-8").strip()
        except Exception:
            pass
    return "secret-key-change-me"


WEB_SECRET = load_web_secret()
SESSIONS: dict[str, tuple[str, str, str, str, float]] = {}
SERVER_STARTED_AT = None


def _verify_cookie(value: str) -> tuple[str, str, str, str] | None:
    # Проверка подписи сессионной куки rtps_session
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
            else:
                continue

            secrets_to_try = [WEB_SECRET]
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

            return unquote(user_id), unquote(role), unquote(modules), unquote(safe_name)
        except Exception:
            continue
    return None


def get_mod_role(session: tuple[str, str, str, str] | None, mod_name: str) -> str | None:
    # Проверка роли пользователя для модуля
    if not session:
        return None
    username = session[0]
    role = session[1]
    modules = session[2]

    resolved = resolve_user_access(ROOT.parent / "base" / "web_users.db", username, role, modules)
    if not resolved:
        return None
    role, modules = resolved
    return module_role(role, modules, mod_name)


EDIT_TOOLBAR = """
      <div class="toolbar">
        <label>Год <select id="yearInput" onchange="loadYearFromInput()"></select></label>
        <button onclick="openReport()">Отчет</button>
        <button id="saveButton" onclick="saveState()">Сохранить</button>
        <div class="json-menu" id="jsonMenuWrap">
          <button type="button" onclick="toggleJsonMenu(event)">JSON</button>
          <div class="json-menu-panel" id="jsonMenuPanel" aria-hidden="true">
            <button type="button" onclick="downloadJson(); closeJsonMenu()">Экспорт JSON</button>
            <button type="button" onclick="triggerImportJson()">Импорт JSON</button>
          </div>
        </div>
        <input id="importFile" type="file" accept=".json,application/json" style="display:none" onchange="importJson(event)">
      </div>
"""

READONLY_TOOLBAR = """
      <div class="toolbar">
        <label>Год <select id="yearInput" onchange="loadYearFromInput()"></select></label>
        <button onclick="openReport()">Отчет</button>
      </div>
"""


def render_page(state: dict, can_edit: bool, username: str | None) -> str:
    # Рендеринг основного HTML-шаблона со встроенным состоянием
    state_json = json.dumps(state, ensure_ascii=False).replace("</", "<\\/")
    employees_json = json.dumps(get_all_employee_names(), ensure_ascii=False).replace("</", "<\\/")
    employee_vacations_json = json.dumps(get_employee_vacations(), ensure_ascii=False).replace("</", "<\\/")
    started_at = SERVER_STARTED_AT.strftime("%H:%M:%S %d.%m.%Y") if SERVER_STARTED_AT else "неизвестно"
    toolbar = EDIT_TOOLBAR if can_edit else READONLY_TOOLBAR
    with open(ROOT / "templates" / "index.html", "r", encoding="utf-8") as f:
        html_template = f.read()
    return (
        html_template.replace("{{STATE_JSON}}", state_json)
        .replace("{{EMPLOYEE_NAMES}}", employees_json)
        .replace("{{EMPLOYEE_VACATIONS}}", employee_vacations_json)
        .replace("{{STARTED_AT}}", started_at)
        .replace("{{APP_VERSION}}", APP_VERSION)
        .replace("{{TOOLBAR}}", toolbar)
        .replace("{{CAN_EDIT}}", "true" if can_edit else "false")
        .replace("{{APP_PREFIX}}", APP_PREFIX)
        .replace("{{TEM_NORM_ROWS}}", json.dumps(TEM_NORM_ROWS, ensure_ascii=False))
        .replace("{{AGR_NORM_ROWS}}", json.dumps(AGR_NORM_ROWS, ensure_ascii=False))
    )


app = FastAPI(title="RTPS Grafik PPR")


@app.middleware("http")
async def handle_request_middleware(request: Request, call_next):
    # Префикс роутинга и кэширование статики
    if request.scope["path"].startswith(APP_PREFIX + "/"):
        request.scope["path"] = request.scope["path"][len(APP_PREFIX):]

    response = await call_next(request)

    path = request.scope.get("path", "")
    if path.startswith("/static/"):
        response.headers["Cache-Control"] = "public, max-age=86400"

    return response


app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")


def json_response(data: dict | list, status_code: int = 200) -> JSONResponse:
    return JSONResponse(content=data, status_code=status_code)


def get_current_session(request: Request) -> tuple[str, str, str, str] | None:
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        session = _verify_cookie(cookie)
        if session:
            user_id, role, modules, safe_name = session
            SESSIONS[cookie] = (user_id, role, modules, safe_name, dt.datetime.now().timestamp())
            return session
    return None


def require_auth_fastapi(request: Request, need_edit: bool = False):
    if not AUTH_ENABLED:
        return True, None
    session = get_current_session(request)
    role = get_mod_role(session, "grafik_ppr")
    if not role:
        return False, None
    if need_edit and role not in ("edit", "editor", "admin"):
        return False, None
    return True, session


@app.get("/grafik-ppr", response_class=HTMLResponse)
@app.get("/", response_class=HTMLResponse)
def home_route(request: Request, year: int = None):
    if year is None:
        year = dt.date.today().year
    session = get_current_session(request)
    user = session[0] if session else None
    mod_role = get_mod_role(session, "grafik_ppr")

    if AUTH_ENABLED and not mod_role:
        return RedirectResponse(f"{MAIN_LOGIN_URL}?next=/grafik-ppr", status_code=303)

    can_edit = mod_role in ("edit", "editor", "admin") if AUTH_ENABLED else True

    html_content = render_page(load_state(year), can_edit, user)
    response = HTMLResponse(content=html_content)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.get("/login", response_class=HTMLResponse)
def login_get(request: Request):
    return RedirectResponse(f"{MAIN_LOGIN_URL}?next=/grafik-ppr", status_code=303)


@app.post("/login", response_class=HTMLResponse)
def login_post(request: Request, user: str = Form(""), password: str = Form("")):
    return RedirectResponse(f"{MAIN_LOGIN_URL}?next=/grafik-ppr", status_code=303)


@app.get("/logout")
def logout_route():
    resp = RedirectResponse(MAIN_LOGIN_URL, status_code=303)
    resp.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="lax")
    return resp


@app.get("/api/state")
def get_state(year: int = None):
    if year is None:
        year = dt.date.today().year
    return json_response(load_state(year))


@app.post("/api/state")
@app.post("/api/import")
async def post_state(request: Request):
    auth_ok, session = require_auth_fastapi(request, need_edit=True)
    if not auth_ok:
        return json_response({"error": "Unauthorized"}, status_code=401)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        return json_response({"error": "Некорректный формат данных"}, status_code=400)
    try:
        saved = await asyncio.to_thread(save_state, payload)
    except Exception as exc:
        return json_response({"error": str(exc)}, status_code=400)
    return json_response(saved)


@app.get("/api/export")
def export_state(request: Request, year: int = None):
    auth_ok, session = require_auth_fastapi(request)
    if not auth_ok:
        return Response("Unauthorized", status_code=401)
    if year is None:
        year = dt.date.today().year
    body = json.dumps(load_state(year), ensure_ascii=False, indent=2).encode("utf-8")
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="grafik_ppr_{year}.json"'}
    )


@app.get("/api/act-export")
def export_act(request: Request, year: int = None, month: str = "", act: str = ""):
    auth_ok, session = require_auth_fastapi(request)
    if not auth_ok:
        return Response("Unauthorized", status_code=401)
    if year is None:
        year = dt.date.today().year
    try:
        body, filename = build_act_workbook(year, act.strip())
    except Exception as exc:
        return json_response({"error": str(exc)}, status_code=400)
    return Response(
        content=body,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": content_disposition_attachment(filename)}
    )


@app.get("/api/report-export")
def export_report(request: Request, year: int = None, month: str = ""):
    auth_ok, session = require_auth_fastapi(request)
    if not auth_ok:
        return Response("Unauthorized", status_code=401)
    if year is None:
        year = dt.date.today().year
    if not month.strip():
        month = MONTHS_RU[dt.date.today().month - 1]
    try:
        body, filename = build_report_workbook(year, month.strip())
    except Exception as exc:
        return json_response({"error": str(exc)}, status_code=400)
    return Response(
        content=body,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": content_disposition_attachment(filename)}
    )


@app.get("/api/report-preview")
def preview_report(request: Request, year: int = None, month: str = ""):
    auth_ok, session = require_auth_fastapi(request)
    if not auth_ok:
        return json_response({"error": "Unauthorized"}, status_code=401)
    if year is None:
        year = dt.date.today().year
    if not month.strip():
        month = MONTHS_RU[dt.date.today().month - 1]
    try:
        state = load_state(year)
        data = calculate_report_data_from_state(state, month.strip())
        saved_notes = state.get("notes", {}).get(month.strip(), {}) or {}
        return json_response(build_report_preview(month.strip(), data, saved_notes))
    except Exception as exc:
        return json_response({"error": str(exc)}, status_code=400)


@app.post("/api/tu28_extra")
async def post_tu28_extra(request: Request):
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    year = payload.get("year")
    month_name = payload.get("month_name")
    r = payload.get("r")
    extra = payload.get("extra", [])

    def db_op():
        with DB_LOCK, conn() as db:
            cur = db.cursor()
            with db:
                row = cur.execute(
                    "SELECT v FROM tu28_data WHERE y=? AND m=? AND r=? AND k='tu28_locked'",
                    (year, month_name, r)
                ).fetchone()
                is_locked = False
                if row and row["v"]:
                    is_locked = json.loads(row["v"])
                if not is_locked:
                    cur.execute(
                        "INSERT OR REPLACE INTO tu28_data VALUES (?,?,?,?,?)",
                        (year, month_name, r, "tu28_extra", json.dumps(extra))
                    )

    await asyncio.to_thread(db_op)
    return json_response({"status": "ok"})


@app.post("/api/tu28-export")
async def export_tu28(request: Request):
    auth_ok, session = require_auth_fastapi(request)
    if not auth_ok:
        return Response("Unauthorized", status_code=401)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    year = int(payload.get("year") or dt.date.today().year)
    month = str(payload.get("month", "")).strip() or MONTHS_RU[dt.date.today().month - 1]
    row_raw = payload.get("row", None)
    if row_raw in (None, ""):
        return json_response({"error": "В месяце нет ремонтов для ТУ-28"}, status_code=400)
    try:
        row_idx = int(row_raw)
    except Exception:
        return json_response({"error": "Не удалось определить строку ремонта"}, status_code=400)

    staff_list = payload.get("staff") or []
    if not isinstance(staff_list, list):
        staff_list = []
    extra_repairs = payload.get("extra_repairs") or []
    if not isinstance(extra_repairs, list):
        extra_repairs = []

    try:
        body, filename = await asyncio.to_thread(
            build_tu28_workbook, year, month, row_idx, staff_list, extra_repairs=extra_repairs
        )
    except Exception as exc:
        return json_response({"error": str(exc)}, status_code=400)

    return Response(
        content=body,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": content_disposition_attachment(filename)}
    )


def main() -> None:
    # Запуск сервера
    global SERVER_STARTED_AT
    SERVER_STARTED_AT = dt.datetime.now()
    ensure_database()
    host = os.environ.get("WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("WEB_PORT", "8000"))
    url = f"http://{host}:{port}/grafik-ppr"
    print(f"График ППР web ready (FastAPI): {url} | started at {SERVER_STARTED_AT:%H:%M:%S %d.%m.%Y}")
    if host in {"127.0.0.1", "localhost", "0.0.0.0"}:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    uvicorn.run("app:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
