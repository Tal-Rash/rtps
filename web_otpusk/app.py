from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import hmac
import os
import secrets
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote, unquote

from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Обеспечиваем системные пути для гарантированного импорта модулей
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_ROOT.parent))

from rtps_common import module_role, resolve_user_access

# Универсальный импорт для поддержки запуска как пакета, так и напрямую через systemd
try:
    from .constants import (
        APP_PREFIX,
        APP_VERSION,
        MAIN_LOGIN_URL,
        MAIN_SITE_URL,
        ROOT,
        SESSION_COOKIE,
        WEB_USERS_DB,
        get_web_secret,
    )
    from .excel import create_archive_excel, create_schedule_excel
    from .storage import (
        activate_version,
        create_version,
        delete_version,
        import_archive_file,
        init_db,
        load_archive,
        load_history_matrix,
        load_holidays,
        load_vacations,
        load_version_by_id,
        load_versions,
        map_version_data_to_ciphers,
        save_archive,
        save_holidays,
        save_vacations,
    )
except (ImportError, ValueError):
    from constants import (
        APP_PREFIX,
        APP_VERSION,
        MAIN_LOGIN_URL,
        MAIN_SITE_URL,
        ROOT,
        SESSION_COOKIE,
        WEB_USERS_DB,
        get_web_secret,
    )
    from excel import create_archive_excel, create_schedule_excel
    from storage import (
        activate_version,
        create_version,
        delete_version,
        import_archive_file,
        init_db,
        load_archive,
        load_history_matrix,
        load_holidays,
        load_vacations,
        load_version_by_id,
        load_versions,
        map_version_data_to_ciphers,
        save_archive,
        save_holidays,
        save_vacations,
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Асинхронный контекст жизненного цикла сервиса: инициализация базы данных при старте."""
    await asyncio.to_thread(init_db)
    yield


app = FastAPI(title="RTPS График Отпусков", lifespan=lifespan)

# Монтирование статических файлов для стандартного и префиксного путей
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")
app.mount(f"{APP_PREFIX}/static", StaticFiles(directory=str(ROOT / "static")), name="otpusk_static")

templates = Jinja2Templates(directory=str(ROOT / "templates"))


def verify_cookie(value: str) -> tuple[str, str, str, str] | None:
    """Проверка валидности подписи сессионной куки."""
    if not value:
        return None
    for sep in (":", "|"):
        parts = value.rsplit(sep, 5)
        if len(parts) == 6:
            user_id, role, mods, full_name, expiry_text, sig = parts
            raw = f"{user_id}{sep}{role}{sep}{mods}{sep}{full_name}{sep}{expiry_text}"
        elif len(parts) == 5:
            user_id, role, mods, full_name, sig = parts
            raw = f"{user_id}{sep}{role}{sep}{mods}{sep}{full_name}"
            expiry_text = "2000000000"
        else:
            continue
        exp_sig = hmac.new(get_web_secret().encode("utf-8"), raw.encode("utf-8"), hashlib.sha256).hexdigest()
        if not secrets.compare_digest(sig, exp_sig):
            continue
        try:
            if float(expiry_text) < dt.datetime.now().timestamp():
                return None
        except Exception:
            return None
        return unquote(user_id), unquote(role), unquote(mods), unquote(full_name)
    return None


def get_session(request: Request) -> dict | None:
    """Извлечение и проверка прав текущей пользовательской сессии для графика отпусков."""
    cookie = request.cookies.get(SESSION_COOKIE)
    if not cookie:
        return None
    session = verify_cookie(cookie)
    if not session:
        return None
    user_id, role, mods, full_name = session
    resolved = resolve_user_access(WEB_USERS_DB, user_id, role, mods)
    if not resolved:
        return None
    role, mods = resolved
    mod_role = module_role(role, mods, "otpusk") or ""
    if not mod_role:
        return None
    can_edit = mod_role in ("edit", "editor", "admin")
    return {
        "user_id": user_id,
        "role": role,
        "mod_role": mod_role,
        "modules": mods,
        "full_name": full_name,
        "can_edit": can_edit,
    }


@app.get(f"{APP_PREFIX}", include_in_schema=False)
async def prefixed_index_redirect():
    """Перенаправление со слеша префикса на главную страницу модуля."""
    return RedirectResponse(f"{APP_PREFIX}/", status_code=303)


@app.get("/", response_class=HTMLResponse)
@app.get(f"{APP_PREFIX}/", response_class=HTMLResponse, include_in_schema=False)
async def index(request: Request):
    """Главная страница интерфейса графика отпусков."""
    session = get_session(request)
    if not session:
        return RedirectResponse(f"{MAIN_LOGIN_URL}?next={APP_PREFIX}", status_code=303)

    context = {
        "request": request,
        "APP_PREFIX": APP_PREFIX,
        "APP_VERSION": APP_VERSION,
        "USER_NAME": session["full_name"],
        "USER_ROLE": session["mod_role"],
        "CAN_EDIT": "true" if session["can_edit"] else "false",
        "MAIN_SITE_URL": MAIN_SITE_URL,
    }
    return templates.TemplateResponse(request=request, name="index.html", context=context)


@app.get("/login")
@app.post("/login")
async def login_redirect():
    """Перенаправление на единую страницу входа."""
    return RedirectResponse(f"{MAIN_LOGIN_URL}?next={APP_PREFIX}", status_code=303)


@app.get("/logout")
async def logout_route():
    """Выход из системы с очисткой авторизационной куки."""
    response = RedirectResponse(MAIN_LOGIN_URL, status_code=303)
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="lax")
    return response


@app.get("/api/vacations")
@app.get(f"{APP_PREFIX}/api/vacations", include_in_schema=False)
async def api_get_vacations(request: Request, year: int = 2026):
    """Получение графика отпусков за выбранный год."""
    session = get_session(request)
    if not session:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    result = await asyncio.to_thread(load_vacations, year)
    return JSONResponse(result)


@app.post("/api/vacations")
@app.post(f"{APP_PREFIX}/api/vacations", include_in_schema=False)
async def api_save_vacations(request: Request, year: int = 2026):
    """Сохранение графика отпусков за выбранный год."""
    session = get_session(request)
    if not session or not session["can_edit"]:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    items = await request.json()
    result = await asyncio.to_thread(save_vacations, year, items)
    return JSONResponse(result)


@app.get("/api/holidays")
@app.get(f"{APP_PREFIX}/api/holidays", include_in_schema=False)
async def api_get_holidays(request: Request, year: int = 2026):
    """Получение праздничных дней за выбранный год."""
    session = get_session(request)
    if not session:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    holidays = await asyncio.to_thread(load_holidays, year)
    return JSONResponse(holidays)


@app.post("/api/holidays")
@app.post(f"{APP_PREFIX}/api/holidays", include_in_schema=False)
async def api_save_holidays(request: Request, year: int = 2026):
    """Сохранение праздничных дней за выбранный год."""
    session = get_session(request)
    if not session or not session["can_edit"]:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    holidays_list = await request.json()
    result = await asyncio.to_thread(save_holidays, year, holidays_list)
    return JSONResponse(result)


@app.get("/api/vacations/history_matrix")
@app.get(f"{APP_PREFIX}/api/vacations/history_matrix", include_in_schema=False)
async def api_get_history_matrix(request: Request, year: int = 2026):
    """Получение исторической матрицы отпусков по годам для анализа сезонности."""
    session = get_session(request)
    if not session:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    matrix = await asyncio.to_thread(load_history_matrix, year)
    return JSONResponse(matrix)


@app.get("/api/vacations/archive")
@app.get(f"{APP_PREFIX}/api/vacations/archive", include_in_schema=False)
async def api_get_archive(request: Request, year: int = None):
    """Получение записей архива отпусков."""
    session = get_session(request)
    if not session:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    archive = await asyncio.to_thread(load_archive, year)
    return JSONResponse(archive)


@app.post("/api/vacations/archive")
@app.post(f"{APP_PREFIX}/api/vacations/archive", include_in_schema=False)
async def api_save_archive(request: Request):
    """Сохранение отредактированного архива отпусков."""
    session = get_session(request)
    if not session or not session["can_edit"]:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    rows = await request.json()
    result = await asyncio.to_thread(save_archive, rows)
    return JSONResponse(result)


@app.get("/api/vacations/archive/export")
@app.get(f"{APP_PREFIX}/api/vacations/archive/export", include_in_schema=False)
async def api_export_archive(request: Request, year: int = None):
    """Выгрузка записей архива отпусков в Excel (.xlsx)."""
    session = get_session(request)
    if not session:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    rows_data = await asyncio.to_thread(load_archive, year)
    excel_bytes = await asyncio.to_thread(create_archive_excel, rows_data)

    filename = f"vacations_archive_{year}.xlsx" if year else "vacations_archive_all.xlsx"
    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@app.get("/api/vacations/archive/template")
@app.get(f"{APP_PREFIX}/api/vacations/archive/template", include_in_schema=False)
async def api_archive_template(request: Request):
    """Скачивание эталонного шаблона Excel для импорта архива отпусков."""
    session = get_session(request)
    if not session:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    template_rows = [
        {"y": 2025, "name": "Иванов Иван Иванович", "tab_num": "4001234", "start_date": "2025-06-01", "end_date": "2025-06-14", "days": 14, "note": "Основной отпуск"},
        {"y": 2025, "name": "Петров Петр Петрович", "tab_num": "4005678", "start_date": "2025-07-15", "end_date": "2025-07-28", "days": 14, "note": "Вторая часть"},
    ]
    excel_bytes = await asyncio.to_thread(create_archive_excel, template_rows, "Шаблон импорта архива")
    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=vacations_archive_template.xlsx"}
    )


@app.post("/api/vacations/archive/import")
@app.post(f"{APP_PREFIX}/api/vacations/archive/import", include_in_schema=False)
async def api_import_archive(request: Request, file: UploadFile = File(...), mode: str = "append"):
    """Импорт записей архива отпусков из загруженного файла Excel."""
    session = get_session(request)
    if not session or not session["can_edit"]:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="Файл должен быть в формате Excel (.xlsx)")

    contents = await file.read()
    try:
        result = await asyncio.to_thread(import_archive_file, contents, mode)
        return JSONResponse(result)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/vacations/schedule/export")
@app.get(f"{APP_PREFIX}/api/vacations/schedule/export", include_in_schema=False)
async def api_export_schedule_get(request: Request, year: int = 2026, include_carried: bool = False):
    """Выгрузка текущего сохраненного графика отпусков в Excel (GET-запрос)."""
    session = get_session(request)
    if not session:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    items = await asyncio.to_thread(load_vacations, year)
    holidays = await asyncio.to_thread(load_holidays, year)
    excel_bytes = await asyncio.to_thread(create_schedule_excel, year, items, holidays, include_carried)

    filename_ascii = f"grafik_otpuskov_{year}.xlsx"
    filename_utf8 = f"График_отпусков_{year}.xlsx"
    encoded_utf8 = quote(filename_utf8)

    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=\"{filename_ascii}\"; filename*=UTF-8''{encoded_utf8}"}
    )


@app.post("/api/vacations/schedule/export")
@app.post(f"{APP_PREFIX}/api/vacations/schedule/export", include_in_schema=False)
async def api_export_schedule_post(request: Request):
    """Выгрузка графика отпусков в Excel на основе переданных данных из таблицы (POST-запрос)."""
    session = get_session(request)
    if not session:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    payload = await request.json()
    year = int(payload.get("year", 2026))
    items = payload.get("items", [])
    include_carried = bool(payload.get("include_carried", False))
    holidays = await asyncio.to_thread(load_holidays, year)

    excel_bytes = await asyncio.to_thread(create_schedule_excel, year, items, holidays, include_carried)

    filename_ascii = f"grafik_otpuskov_{year}.xlsx"
    filename_utf8 = f"График_отпусков_{year}.xlsx"
    encoded_utf8 = quote(filename_utf8)

    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=\"{filename_ascii}\"; filename*=UTF-8''{encoded_utf8}"}
    )


@app.get("/api/versions")
@app.get(f"{APP_PREFIX}/api/versions", include_in_schema=False)
async def api_get_versions(request: Request, year: int = 2026):
    """Получение списка сохраненных версий графика отпусков."""
    session = get_session(request)
    if not session:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    versions = await asyncio.to_thread(load_versions, year)
    return JSONResponse(versions)


@app.get("/api/versions/{version_id}")
@app.get(f"{APP_PREFIX}/api/versions/{{version_id}}", include_in_schema=False)
async def api_get_version_by_id(request: Request, version_id: int):
    """Получение детальной информации о сохраненной версии."""
    session = get_session(request)
    if not session:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    ver = await asyncio.to_thread(load_version_by_id, version_id)
    if not ver:
        raise HTTPException(status_code=404, detail="Версия не найдена")

    # Синхронизируем шифры сотрудников при загрузке версии
    ver["data"] = await asyncio.to_thread(map_version_data_to_ciphers, ver["data"])
    return JSONResponse(ver)


@app.post("/api/versions")
@app.post(f"{APP_PREFIX}/api/versions", include_in_schema=False)
async def api_create_version(request: Request):
    """Создание контрольной версии графика отпусков."""
    session = get_session(request)
    if not session or not session["can_edit"]:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    payload = await request.json()
    year = int(payload.get("year", 2026))
    version_name = str(payload.get("version_name", "")).strip()
    data = payload.get("data", [])

    result = await asyncio.to_thread(create_version, year, version_name, data)
    return JSONResponse(result)


@app.post("/api/versions/{version_id}/activate")
@app.post(f"{APP_PREFIX}/api/versions/{{version_id}}/activate", include_in_schema=False)
async def api_activate_version(request: Request, version_id: int):
    """Активация выбранной версии графика отпусков."""
    session = get_session(request)
    if not session or not session["can_edit"]:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    try:
        result = await asyncio.to_thread(activate_version, version_id)
        return JSONResponse(result)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.delete("/api/versions/{version_id}")
@app.delete(f"{APP_PREFIX}/api/versions/{{version_id}}", include_in_schema=False)
async def api_delete_version(request: Request, version_id: int):
    """Удаление сохраненной версии графика отпусков."""
    session = get_session(request)
    if not session or not session["can_edit"]:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    result = await asyncio.to_thread(delete_version, version_id)
    return JSONResponse(result)


if __name__ == "__main__":
    import uvicorn
    host = os.environ.get("WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("WEB_PORT", 8085))
    uvicorn.run("app:app", host=host, port=port, reload=False)
