from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import html
import io
import json
import os
import sys
import threading
import urllib.parse
import webbrowser
from pathlib import Path

from fastapi import (
    Cookie,
    Depends,
    FastAPI,
    Form,
    HTTPException,
    Request,
    Response,
    status,
)
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
import uvicorn

# Подключение общих утилит RTPS
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rtps_common import module_role, resolve_user_access

from constants import (
    APP_PREFIX,
    APP_VERSION,
    DB_LOCK,
    MAIN_LOGIN_URL,
    ROOT,
    SESSION_COOKIE,
    WEB_SECRET,
    WEAR_TREND_METRICS,
)
from storage import (
    connect,
    create_kp_data_version,
    delete_archive_measurement,
    ensure_db,
    load_archive_rows,
    load_kp_versions,
    load_kp_view,
    load_locomotives,
    load_norms_rows,
    load_state,
    load_wear_analysis_rows,
    save_archive,
    save_kp_data,
    save_norms_rows,
    save_state,
    text,
    update_archive_cells,
    update_kp_version,
)
from reports import (
    archive_excel_export_bytes,
    archive_excel_template_bytes,
    build_schedule_eml_bytes,
    import_archive_excel_bytes,
    import_phone_payload,
    parse_phone_json_payload,
    phone_export_payload,
)

app = FastAPI(title="RTPS Zamer KP")


@app.middleware("http")
async def strip_prefix(request: Request, call_next):
    # Префикс роутинга и кэширование статики
    raw_path = request.scope.get("path", "")
    if raw_path == APP_PREFIX:
        request.scope["path"] = "/"
    elif raw_path.startswith(APP_PREFIX + "/"):
        request.scope["path"] = raw_path[len(APP_PREFIX):]

    response = await call_next(request)

    path = request.scope.get("path", "")
    if path.startswith("/static/"):
        response.headers["Cache-Control"] = "public, max-age=86400"

    return response


app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")


def _verify_cookie_fastapi(value: str) -> tuple[str, str, str, str] | None:
    """Проверка цифровой подписи и срока действия cookie авторизации."""
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

            expected = hmac.new(WEB_SECRET.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, sig):
                continue
            if float(expiry_text) < dt.datetime.now().timestamp():
                return None

            return (
                urllib.parse.unquote(user_id),
                urllib.parse.unquote(role),
                urllib.parse.unquote(modules),
                urllib.parse.unquote(safe_name),
            )
        except Exception:
            continue
    return None


def get_current_session_fastapi(request: Request) -> tuple[str, str, str, str] | None:
    """Получение текущей проверенной сессии из cookies запроса."""
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        return _verify_cookie_fastapi(cookie)
    return None


def get_mod_role_fastapi(session: tuple[str, str, str, str] | None, module: str) -> str:
    """Определение роли пользователя для указанного модуля."""
    if not session:
        return ""
    username, role, modules = session[0], session[1], session[2]
    resolved = resolve_user_access(ROOT.parent / "base" / "web_users.db", username, role, modules)
    if not resolved:
        return ""
    role, modules = resolved
    return module_role(role, modules, module) or ""


def require_auth_fastapi(request: Request, need_edit: bool = False) -> tuple[bool, tuple[str, str, str, str] | None]:
    """Проверка прав доступа к модулю 'zamer_kp' с опциональным требованием прав редактирования."""
    session = get_current_session_fastapi(request)
    role = get_mod_role_fastapi(session, "zamer_kp")
    if not role:
        return False, None
    if need_edit and role not in ("edit", "editor", "admin"):
        return False, None
    return True, session


def json_response(data: dict | list, status_code: int = 200) -> JSONResponse:
    """Вспомогательная функция отправки JSON ответа."""
    return JSONResponse(content=data, status_code=status_code)


def render_page(role: str, template_name: str = "index.html", extra: dict[str, str] | None = None) -> str:
    """Рендеринг HTML-шаблона с подстановкой глобальных конфигурационных переменных."""
    with DB_LOCK, connect() as conn:
        loco_choices = load_locomotives(conn.cursor())
    with open(ROOT / "templates" / template_name, "r", encoding="utf-8") as f:
        content = f.read()
    replacements = {
        "{{APP_PREFIX}}": APP_PREFIX,
        "{{APP_VERSION}}": APP_VERSION,
        "{{CAN_EDIT}}": "true" if role in ("edit", "editor", "admin") else "false",
        "{{TAB_INPUT_STYLE}}": "" if role in ("edit", "editor", "admin") else 'style="display:none"',
        "{{LOCOMOTIVE_CHOICES}}": json.dumps(loco_choices, ensure_ascii=False),
    }
    if extra:
        replacements.update(extra)
    return (
        content
        .replace("{{APP_PREFIX}}", replacements["{{APP_PREFIX}}"])
        .replace("{{APP_VERSION}}", replacements["{{APP_VERSION}}"])
        .replace("{{CAN_EDIT}}", replacements["{{CAN_EDIT}}"])
        .replace("{{TAB_INPUT_STYLE}}", replacements["{{TAB_INPUT_STYLE}}"])
        .replace("{{LOCOMOTIVE_CHOICES}}", replacements["{{LOCOMOTIVE_CHOICES}}"])
        .replace("{{WEAR_LOCOMOTIVE}}", replacements.get("{{WEAR_LOCOMOTIVE}}", ""))
        .replace("{{WEAR_DATE_FROM}}", replacements.get("{{WEAR_DATE_FROM}}", ""))
        .replace("{{WEAR_DATE_TO}}", replacements.get("{{WEAR_DATE_TO}}", ""))
        .replace("{{WEAR_CHART_MODE}}", replacements.get("{{WEAR_CHART_MODE}}", "pair"))
    )


# ==============================================================================
# Маршруты веб-страниц (HTML)
# ==============================================================================

@app.get("/zamer-kp", response_class=HTMLResponse)
@app.get("/", response_class=HTMLResponse)
async def home_route(request: Request):
    """Главная страница журнала замеров колесных пар."""
    session = get_current_session_fastapi(request)
    mod_role = get_mod_role_fastapi(session, "zamer_kp")
    if not session or not mod_role:
        return RedirectResponse(f"{MAIN_LOGIN_URL}?next=/zamer-kp", status_code=303)

    html_content = render_page(mod_role)
    response = HTMLResponse(content=html_content)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.get("/wear-charts", response_class=HTMLResponse)
async def wear_charts_route(request: Request, locomotive: str = "", date_from: str = "", date_to: str = "", mode: str = "pair"):
    """Страница графиков и анализа износа колесных пар."""
    session = get_current_session_fastapi(request)
    mod_role = get_mod_role_fastapi(session, "zamer_kp")
    if not session or not mod_role:
        return RedirectResponse(f"{MAIN_LOGIN_URL}?next=/zamer-kp/wear-charts", status_code=303)

    extra = {
        "{{WEAR_LOCOMOTIVE}}": html.escape(text(locomotive), quote=True),
        "{{WEAR_DATE_FROM}}": html.escape(text(date_from), quote=True),
        "{{WEAR_DATE_TO}}": html.escape(text(date_to), quote=True),
        "{{WEAR_CHART_MODE}}": "all" if text(mode).strip().lower() == "all" else "pair",
    }
    html_content = render_page(mod_role, "wear_charts.html", extra)
    response = HTMLResponse(content=html_content)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.get("/logout")
async def logout_route():
    """Выход из системы с удалением cookie сессии."""
    resp = RedirectResponse(MAIN_LOGIN_URL, status_code=303)
    resp.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="lax")
    return resp


# ==============================================================================
# API маршруты (JSON / Excel / EML)
# ==============================================================================

@app.get("/api/state")
async def get_state(request: Request, locomotive: str = ""):
    """Получение текущего состояния журнала замеров."""
    auth_ok, _ = require_auth_fastapi(request)
    if not auth_ok:
        return Response("Unauthorized", status_code=401)
    return json_response(load_state(locomotive.strip()))


@app.post("/api/state")
async def post_state(request: Request):
    """Сохранение текущего бланка замера колесных пар."""
    auth_ok, session = require_auth_fastapi(request, need_edit=True)
    if not auth_ok:
        return json_response({"error": "Unauthorized"}, status_code=401)
    try:
        payload = await request.json()
        saved = save_state(payload, full_name=session[3] if session and len(session) > 3 else "")
        return json_response(saved)
    except Exception as exc:
        return json_response({"error": str(exc)}, status_code=400)


@app.get("/api/archive")
async def get_archive(request: Request, locomotive: str = "", search: str = "", sort: str = "desc"):
    """Получение строк архива замеров с фильтрацией и поиском."""
    auth_ok, _ = require_auth_fastapi(request)
    if not auth_ok:
        return Response("Unauthorized", status_code=401)
    rows = load_archive_rows(locomotive.strip(), search.strip(), sort.strip().lower() != "asc")
    return json_response({"rows": rows})


@app.post("/api/archive")
async def post_archive(request: Request):
    """Операции с архивом: создание, точечное редактирование ячеек, удаление."""
    auth_ok, _ = require_auth_fastapi(request, need_edit=True)
    if not auth_ok:
        return json_response({"error": "Unauthorized"}, status_code=401)
    try:
        payload = await request.json()
        if payload.get("action") == "delete":
            result = delete_archive_measurement(payload)
        elif payload.get("changes"):
            result = update_archive_cells(payload)
        else:
            result = save_archive(payload)

        if isinstance(result, tuple):
            return json_response(result[0], status_code=result[1])
        return json_response(result)
    except Exception as exc:
        return json_response({"error": str(exc)}, status_code=400)


@app.get("/api/export-schedule-email")
async def export_schedule_email(request: Request, filter: str = "all"):
    """Скачивание черновика письма .eml с рассылкой графика замеров."""
    auth_ok, _ = require_auth_fastapi(request)
    if not auth_ok:
        return Response("Unauthorized", status_code=401)
    eml_data = build_schedule_eml_bytes(filter)
    return StreamingResponse(
        io.BytesIO(eml_data),
        media_type="message/rfc822",
        headers={"Content-Disposition": "attachment; filename=ScheduleKP_Draft.eml"},
    )


@app.get("/api/kp-data")
async def get_kp_data(request: Request, locomotive: str = "", version_id: int | None = None):
    """Получение паспортных данных и версий колесных пар локомотива."""
    auth_ok, _ = require_auth_fastapi(request)
    if not auth_ok:
        return Response("Unauthorized", status_code=401)
    return json_response(load_kp_view(locomotive.strip(), version_id))


@app.post("/api/kp-data")
async def post_kp_data(request: Request):
    """Сохранение паспортных данных КП или создание/обновление версии."""
    auth_ok, _ = require_auth_fastapi(request, need_edit=True)
    if not auth_ok:
        return json_response({"error": "Unauthorized"}, status_code=401)
    try:
        payload = await request.json()
        action = text(payload.get("action")).strip()
        if action == "new_version":
            result = create_kp_data_version(payload)
        elif action == "update_version":
            result = update_kp_version(payload)
        else:
            result = save_kp_data(payload)
        if isinstance(result, tuple):
            return json_response(result[0], status_code=result[1])
        return json_response(result)
    except Exception as exc:
        return json_response({"error": str(exc)}, status_code=400)


@app.get("/api/wear-analysis")
async def get_wear_analysis(request: Request, locomotive: str = "", date_from: str = "", date_to: str = ""):
    """Анализ динамики и темпов износа элементов колесных пар."""
    auth_ok, _ = require_auth_fastapi(request)
    if not auth_ok:
        return Response("Unauthorized", status_code=401)
    return json_response(load_wear_analysis_rows(locomotive.strip(), date_from.strip(), date_to.strip()))


@app.get("/api/norms")
async def get_norms(request: Request):
    """Получение таблицы настроек норм износа колесных пар."""
    auth_ok, _ = require_auth_fastapi(request)
    if not auth_ok:
        return Response("Unauthorized", status_code=401)
    return json_response({"rows": load_norms_rows()})


@app.post("/api/norms")
async def post_norms(request: Request):
    """Сохранение пользовательских норм предельного износа."""
    auth_ok, _ = require_auth_fastapi(request, need_edit=True)
    if not auth_ok:
        return json_response({"error": "Unauthorized"}, status_code=401)
    try:
        payload = await request.json()
        result = save_norms_rows(payload)
        if isinstance(result, tuple):
            return json_response(result[0], status_code=result[1])
        return json_response(result)
    except Exception as exc:
        return json_response({"error": str(exc)}, status_code=400)


@app.get("/api/archive-excel-template")
async def export_archive_template(request: Request):
    """Скачивание чистого шаблона Excel для импорта архива замеров."""
    auth_ok, _ = require_auth_fastapi(request)
    if not auth_ok:
        return Response("Unauthorized", status_code=401)
    try:
        data = archive_excel_template_bytes()
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename*=UTF-8''%D0%A8%D0%B0%D0%B1%D0%BB%D0%BE%D0%BD_%D0%B8%D0%BC%D0%BF%D0%BE%D1%80%D1%82%D0%B0_%D0%B0%D1%80%D1%85%D0%B8%D0%B2%D0%B0.xlsx"},
        )
    except Exception as exc:
        return json_response({"error": str(exc)}, status_code=400)


@app.get("/api/archive-excel-export")
async def export_archive_excel(request: Request, date_from: str = "", date_to: str = ""):
    """Выгрузка отфильтрованных строк архива в файл Excel."""
    auth_ok, _ = require_auth_fastapi(request)
    if not auth_ok:
        return Response("Unauthorized", status_code=401)
    try:
        query_params = request.query_params
        selected_locomotives = [item.strip() for item in query_params.getlist("locomotive") if item.strip()]
        data, row_count = archive_excel_export_bytes(selected_locomotives, date_from.strip(), date_to.strip())
        if row_count <= 0:
            return json_response({"error": "По выбранным фильтрам данных нет."}, status_code=400)
        filename = f"Экспорт_архива_{dt.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.xlsx"
        safe_filename = urllib.parse.quote(filename)
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{safe_filename}"},
        )
    except Exception as exc:
        return json_response({"error": str(exc)}, status_code=400)


@app.post("/api/archive-excel-import")
async def post_archive_import(request: Request):
    """Импорт замеров из переданного файла Excel (в формате base64)."""
    auth_ok, _ = require_auth_fastapi(request, need_edit=True)
    if not auth_ok:
        return json_response({"error": "Unauthorized"}, status_code=401)
    try:
        payload = await request.json()
        encoded = text(payload.get("data")).strip()
        if not encoded:
            return json_response({"error": "Файл Excel не передан."}, status_code=400)
        data = base64.b64decode(encoded)
        result = import_archive_excel_bytes(data)
        if isinstance(result, tuple):
            return json_response(result[0], status_code=result[1])
        return json_response(result)
    except Exception as exc:
        return json_response({"error": str(exc)}, status_code=400)


@app.get("/api/phone-export")
async def export_phone(request: Request, kind: str = "archive", date_from: str = "", date_to: str = ""):
    """Экспорт данных в JSON для мобильного приложения."""
    try:
        query_params = request.query_params
        selected_locomotives = [item.strip() for item in query_params.getlist("locomotive") if item.strip()]
        payload = phone_export_payload(kind.strip().lower(), selected_locomotives, date_from.strip(), date_to.strip())
        return json_response(payload)
    except Exception as exc:
        return json_response({"error": str(exc)}, status_code=400)


@app.post("/api/phone-import")
async def post_phone_import(request: Request):
    """Импорт данных замера или справочника из мобильного приложения."""
    try:
        raw = await request.body()
        payload = parse_phone_json_payload(raw)
        result = import_phone_payload(payload)
        if isinstance(result, tuple):
            return json_response(result[0], status_code=result[1])
        return json_response(result)
    except Exception as exc:
        return json_response({"error": str(exc)}, status_code=400)


# ==============================================================================
# Точка входа сервера
# ==============================================================================

def main() -> None:
    """Инициализация базы данных и запуск веб-сервера FastAPI."""
    ensure_db()
    host = os.environ.get("WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("WEB_PORT", "8003"))
    url = f"http://{host}:{port}{APP_PREFIX}"
    print(f"Замер КП ready (FastAPI): {url}")
    if host in {"127.0.0.1", "localhost", "0.0.0.0"}:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    uvicorn.run("app:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
