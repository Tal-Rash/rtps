import asyncio
import datetime as dt
import gzip
import hashlib
import hmac
import io
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import unquote

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

# Обеспечиваем доступность путей модуля и корня проекта для общих импортов
_PKG_ROOT = Path(__file__).resolve().parent
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))
if str(_PKG_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT.parent))

from rtps_common import module_role, resolve_user_access

# Импорт локальных компонентов модуля Табель
try:
    from .constants import (
        APP_PREFIX,
        APP_VERSION,
        DB_FILE,
        DB_LOCK,
        MAIN_LOGIN_URL,
        MONTH_NAMES,
        ROOT,
        SESSION_COOKIE,
        SHARED_DATA_DIR,
        WEB_SECRET,
        WEB_USERS_DB,
    )
    from .storage import (
        conn,
        init_db,
        load_state,
        load_system_dates,
        save_state,
        text,
    )
    from .reports import (
        build_milk_details_html,
        build_milk_report_excel,
        build_sick_email_bytes,
        build_summary_html,
    )
except (ImportError, ValueError):
    from constants import (
        APP_PREFIX,
        APP_VERSION,
        DB_FILE,
        DB_LOCK,
        MAIN_LOGIN_URL,
        MONTH_NAMES,
        ROOT,
        SESSION_COOKIE,
        SHARED_DATA_DIR,
        WEB_SECRET,
        WEB_USERS_DB,
    )
    from storage import (
        conn,
        init_db,
        load_state,
        load_system_dates,
        save_state,
        text,
    )
    from reports import (
        build_milk_details_html,
        build_milk_report_excel,
        build_sick_email_bytes,
        build_summary_html,
    )

# Инициализация структуры таблиц базы данных при старте сервиса
try:
    init_db()
except Exception:
    import traceback

    with open(ROOT / "startup_error.log", "w", encoding="utf-8") as f:
        f.write(traceback.format_exc())
    print("Ошибка старта web_tabel:", traceback.format_exc())


def _verify_cookie_fastapi(value: str) -> tuple[str, str, str, str] | None:
    """Проверка подписи сессионной cookie пользователя."""
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


def get_current_session_fastapi(request: Request) -> tuple[str, str, str, str] | None:
    """Извлечение текущей проверенной сессии из cookie запроса."""
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        return _verify_cookie_fastapi(cookie)
    return None


def get_mod_role_fastapi(session: tuple[str, str, str, str] | None, module: str) -> str:
    """Определение уровня доступа пользователя к конкретному модулю."""
    if not session:
        return ""
    username = session[0]
    role = session[1]
    modules = session[2]

    resolved = resolve_user_access(WEB_USERS_DB, username, role, modules)
    if not resolved:
        return ""
    role, modules = resolved
    return module_role(role, modules, module) or ""


def json_response(data: dict | list, status_code: int = 200) -> JSONResponse:
    """Формирование JSON ответа с заданным HTTP статусом."""
    return JSONResponse(content=data, status_code=status_code)


# Создание приложения FastAPI
app = FastAPI(title="RTPS Tabel")


@app.middleware("http")
async def strip_prefix(request: Request, call_next):
    """Снятие префикса /tabel при прямом обращении через reverse proxy."""
    if request.scope["path"].startswith(APP_PREFIX + "/"):
        request.scope["path"] = request.scope["path"][len(APP_PREFIX) :]
    return await call_next(request)


# Подключение каталога со статическими файлами (стили, скрипты)
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")


@app.get("/tabel", response_class=HTMLResponse)
@app.get("/", response_class=HTMLResponse)
async def home_route(request: Request):
    """Главная страница модуля Табель."""
    session = get_current_session_fastapi(request)
    if not session:
        return RedirectResponse(f"{MAIN_LOGIN_URL}?next=/tabel", status_code=303)

    mod_role = get_mod_role_fastapi(session, "tabel")
    if not mod_role:
        return HTMLResponse(
            content=(
                "<meta charset='utf-8'>У вас нет прав для доступа к этому модулю. "
                "Обратитесь к администратору. <a href='/'>Вернуться в главное меню</a>"
            ),
            status_code=403,
        )

    can_edit = mod_role in ("edit", "editor", "admin")

    with open(ROOT / "templates" / "index.html", "r", encoding="utf-8") as f:
        html = f.read()

    html = html.replace("{{CAN_EDIT}}", "true" if can_edit else "false")
    html = html.replace("{{APP_PREFIX}}", APP_PREFIX)
    html = html.replace("{{APP_VERSION}}", APP_VERSION.replace("web-tabel-", ""))

    response = HTMLResponse(content=html)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response


@app.get("/api/debug_startup")
async def debug_startup(request: Request):
    """Диагностика ошибок старта сервиса."""
    error_file = ROOT / "startup_error.log"
    if error_file.exists():
        return {"error": error_file.read_text(encoding="utf-8")}
    return {"error": "Ошибок запуска не обнаружено."}


@app.get("/api/state")
async def api_get_state(request: Request, year: int, month: int):
    """Получение состояния табеля за указанный год и месяц."""
    session = get_current_session_fastapi(request)
    if not get_mod_role_fastapi(session, "tabel"):
        return json_response({"error": "Unauthorized"}, 401)
    return json_response(load_state(year, month))


@app.post("/api/state")
async def api_save_state(request: Request):
    """Сохранение состояния табеля, сотрудников, отпусков и норм с поддержкой gzip-сжатия."""
    t0 = time.perf_counter()
    try:
        session = get_current_session_fastapi(request)
        role = get_mod_role_fastapi(session, "tabel")
        if role not in ("edit", "editor", "admin"):
            return json_response({"error": "Forbidden"}, 403)

        try:
            # Поддержка сжатия gzip для моментальной передачи через защитник Windows и сетевые фильтры
            if request.headers.get("content-encoding") == "gzip":
                raw_body = await request.body()
                decompressed = gzip.decompress(raw_body)
                payload = json.loads(decompressed.decode("utf-8"))
            else:
                payload = await request.json()
        except Exception as exc:
            return json_response({"error": f"Некорректный JSON в теле запроса: {exc}"}, 400)

        # Выполняем сохранение в SQLite в пуле потоков для максимальной отзывчивости
        result = await asyncio.to_thread(save_state, payload)
        elapsed = time.perf_counter() - t0
        print(f"[SAVE_TABEL] Успешно сохранено за {elapsed:.3f}с")
        return json_response(result)
    except Exception as e:
        import traceback

        return json_response({"error": "Ошибка сохранения: " + str(e) + " - " + traceback.format_exc()}, 500)


@app.get("/api/export-summary", response_class=HTMLResponse)
async def export_summary(year: int, month: int, type: str):
    """Экспорт сводной ведомости (отпуска, больничные, праздничные дни)."""
    import urllib.parse

    type_unquoted = urllib.parse.unquote(type)
    html_content = build_summary_html(year, month, type_unquoted)
    return HTMLResponse(content=html_content)


@app.get("/api/export-milk")
async def export_milk(year: int, month: int, type: str):
    """Экспорт ведомости выдачи молока в формате Excel (.xlsx)."""
    import urllib.parse

    type_unquoted = urllib.parse.unquote(type)
    try:
        tmp_file, filename_formatted = build_milk_report_excel(year, month, type_unquoted)
        return FileResponse(
            tmp_file,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            filename=filename_formatted,
        )
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.get("/api/export-milk-details", response_class=HTMLResponse)
async def export_milk_details(year: int, month: int, type: str):
    """Детальный отчет по незасчитанным дням для выдачи молока."""
    import urllib.parse

    type_unquoted = urllib.parse.unquote(type)
    html_content = build_milk_details_html(year, month, type_unquoted)
    return HTMLResponse(content=html_content)


@app.get("/api/export-sick-email")
async def export_sick_email(emp: str, type: str, start: str, end: str, email: str):
    """Формирование черновика письма .eml по больничному листу."""
    import urllib.parse

    emp_unquoted = urllib.parse.unquote(emp)
    type_unquoted = urllib.parse.unquote(type)
    email_unquoted = urllib.parse.unquote(email)

    eml_data = build_sick_email_bytes(emp_unquoted, type_unquoted, start, end, email_unquoted)
    return StreamingResponse(
        io.BytesIO(eml_data),
        media_type="message/rfc822",
        headers={"Content-Disposition": "attachment; filename=SickLeaveDraft.eml"},
    )


if __name__ == "__main__":
    host = os.environ.get("WEB_HOST", "0.0.0.0")
    port = int(os.environ.get("WEB_PORT", "8005"))
    uvicorn.run("app:app", host=host, port=port, reload=False)
