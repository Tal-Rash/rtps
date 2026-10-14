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
from urllib.parse import unquote

from fastapi import FastAPI, HTTPException, Request, Response
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
        get_legacy_web_secret,
        get_web_secret,
    )
    from .storage import (
        ensure_db,
        load_state,
        lookup_private_employee,
        purge_deleted_inventory,
        purge_inventory_row,
        save_state,
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
        get_legacy_web_secret,
        get_web_secret,
    )
    from storage import (
        ensure_db,
        load_state,
        lookup_private_employee,
        purge_deleted_inventory,
        purge_inventory_row,
        save_state,
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Асинхронный контекст жизненного цикла сервиса: инициализация базы данных при старте."""
    await asyncio.to_thread(ensure_db)
    yield


app = FastAPI(title="RTPS Справочник", lifespan=lifespan)

# Монтирование статических файлов для стандартного и префиксного путей
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")
app.mount(f"{APP_PREFIX}/static", StaticFiles(directory=str(ROOT / "static")), name="spravochnik_static")

templates = Jinja2Templates(directory=str(ROOT / "templates"))


def verify_cookie(value: str) -> tuple[str, str, str, str] | None:
    """Проверка валидности подписи сессионной куки с поддержкой как актуального, так и легаси ключа."""
    if not value:
        return None

    secrets_to_try = [get_web_secret()]
    legacy = get_legacy_web_secret()
    if legacy and legacy not in secrets_to_try:
        secrets_to_try.append(legacy)

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

        matched = False
        for secret_key in secrets_to_try:
            exp_sig = hmac.new(secret_key.encode("utf-8"), raw.encode("utf-8"), hashlib.sha256).hexdigest()
            if secrets.compare_digest(sig, exp_sig):
                matched = True
                break

        if not matched:
            continue
        try:
            if float(expiry_text) < dt.datetime.now().timestamp():
                return None
        except Exception:
            return None

        return unquote(user_id), unquote(role), unquote(mods), unquote(full_name)

    return None


def get_session(request: Request) -> dict | None:
    """Извлечение и проверка прав текущей пользовательской сессии для модуля справочника."""
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
    mod_role = module_role(role, mods, "spravochnik") or ""
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
    """Главная страница интерфейса справочника."""
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
    response = templates.TemplateResponse(request=request, name="index.html", context=context)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


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


@app.get("/api/state")
@app.get(f"{APP_PREFIX}/api/state", include_in_schema=False)
async def api_get_state(request: Request, year: int = None):
    """Получение текущего состояния справочника (нормы, сотрудники, локомотивы)."""
    session = get_session(request)
    if not session:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    target_year = year if year is not None else dt.date.today().year
    state = await asyncio.to_thread(load_state, target_year)
    return JSONResponse(state)


@app.get("/api/employee-lookup")
@app.get(f"{APP_PREFIX}/api/employee-lookup", include_in_schema=False)
async def api_employee_lookup(request: Request, id: str = ""):
    """Поиск данных сотрудника по табельному номеру или коду."""
    session = get_session(request)
    if not session:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    result = await asyncio.to_thread(lookup_private_employee, id)
    return JSONResponse(result)


@app.post("/api/save")
@app.post(f"{APP_PREFIX}/api/save", include_in_schema=False)
async def api_post_save(request: Request):
    """Сохранение изменений в справочнике."""
    session = get_session(request)
    if not session or not session["can_edit"]:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    try:
        payload = await request.json()
        await asyncio.to_thread(save_state, payload)
        return JSONResponse({"ok": True})
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


@app.post("/api/purge_deleted_inventory")
@app.post(f"{APP_PREFIX}/api/purge_deleted_inventory", include_in_schema=False)
async def api_purge_deleted(request: Request):
    """Очистка всех помеченных к удалению локомотивов."""
    session = get_session(request)
    if not session or not session["can_edit"]:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    try:
        result = await asyncio.to_thread(purge_deleted_inventory)
        return JSONResponse(result)
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


@app.post("/api/purge_inventory_row")
@app.post(f"{APP_PREFIX}/api/purge_inventory_row", include_in_schema=False)
async def api_purge_row(request: Request):
    """Удаление одного конкретного локомотива."""
    session = get_session(request)
    if not session or not session["can_edit"]:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    try:
        payload = await request.json()
        y = payload.get("year", dt.date.today().year)
        ser = payload.get("ser", "")
        num = payload.get("num", "")
        result = await asyncio.to_thread(purge_inventory_row, y, ser, num)
        return JSONResponse(result)
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


if __name__ == "__main__":
    import uvicorn
    host = os.environ.get("WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("WEB_PORT", 8002))
    uvicorn.run("app:app", host=host, port=port, reload=False)
