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

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Обеспечиваем системные пути для гарантированного импорта модулей
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_ROOT.parent))

from rtps_common import module_has_access, resolve_user_access

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
    from .storage import (
        init_db,
        load_edu_state,
        save_categories_settings,
        save_columns_settings,
        save_employee_order_settings,
        save_protocol_entry,
        save_training_entry,
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
    from storage import (
        init_db,
        load_edu_state,
        save_categories_settings,
        save_columns_settings,
        save_employee_order_settings,
        save_protocol_entry,
        save_training_entry,
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Асинхронный контекст жизненного цикла сервиса: инициализация базы данных при старте."""
    await asyncio.to_thread(init_db)
    yield


app = FastAPI(title="RTPS Обучение", lifespan=lifespan)

# Монтирование статических файлов для стандартного и префиксного путей
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")
app.mount(f"{APP_PREFIX}/static", StaticFiles(directory=str(ROOT / "static")), name="edu_static")

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
        exp_sig = hmac.new(get_web_secret().encode(), raw.encode(), hashlib.sha256).hexdigest()
        if not secrets.compare_digest(sig, exp_sig):
            continue
        if float(expiry_text) < dt.datetime.now().timestamp():
            return None
        return unquote(user_id), unquote(role), unquote(mods), unquote(full_name)
    return None


def get_session(request: Request) -> dict | None:
    """Извлечение и проверка прав текущей пользовательской сессии."""
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
    if not module_has_access(role, mods, "edu"):
        return None
    can_edit = (
        role == "admin"
        or "admin" in mods
        or "edu:edit" in mods
        or (role in ("edit", "editor") and ("edu" in mods.split(",") or "edu:view" in mods))
    )
    return {
        "user_id": user_id,
        "role": role,
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
    """Главная страница интерфейса обучения."""
    session = get_session(request)
    if not session:
        return RedirectResponse(f"{MAIN_LOGIN_URL}?next={APP_PREFIX}", status_code=303)

    context = {
        "request": request,
        "APP_PREFIX": APP_PREFIX,
        "APP_VERSION": APP_VERSION,
        "USER_NAME": session["full_name"],
        "USER_ROLE": session["role"],
        "CAN_EDIT": "true" if session["can_edit"] else "false",
        "MAIN_SITE_URL": MAIN_SITE_URL,
    }
    return templates.TemplateResponse(request=request, name="index.html", context=context)


@app.get("/api/state")
@app.get(f"{APP_PREFIX}/api/state", include_in_schema=False)
async def api_state(request: Request):
    """Получение текущего состояния данных модуля обучения."""
    session = get_session(request)
    if not session:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    state = await asyncio.to_thread(load_edu_state)
    return JSONResponse(state)


@app.post("/api/save_training")
@app.post(f"{APP_PREFIX}/api/save_training", include_in_schema=False)
async def api_save_training(request: Request, data: dict):
    """Сохранение даты и периодичности прохождения курса обучения."""
    session = get_session(request)
    if not session or not session["can_edit"]:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    tab_num = data.get("tab_num")
    t_type = data.get("training_type")
    last_date = data.get("last_date")
    period_months = data.get("period_months", 12)
    if not tab_num or not t_type:
        return JSONResponse({"error": "Missing tab_num or training_type"}, status_code=400)
    try:
        period_months = int(period_months or 12)
    except (TypeError, ValueError):
        return JSONResponse({"error": "Invalid period_months"}, status_code=400)
    if last_date:
        try:
            dt.date.fromisoformat(last_date)
        except ValueError:
            return JSONResponse({"error": "Invalid last_date"}, status_code=400)

    await asyncio.to_thread(save_training_entry, tab_num, t_type, last_date, period_months)
    return {"status": "ok"}


@app.post("/api/save_protocol")
@app.post(f"{APP_PREFIX}/api/save_protocol", include_in_schema=False)
async def api_save_protocol(request: Request, data: dict):
    """Сохранение номера протокола обучения."""
    session = get_session(request)
    if not session or not session["can_edit"]:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    tab_num = data.get("tab_num")
    t_type = data.get("training_type")
    protocol = data.get("protocol")
    if not tab_num or not t_type:
        return JSONResponse({"error": "Missing tab_num or training_type"}, status_code=400)

    await asyncio.to_thread(save_protocol_entry, tab_num, t_type, protocol)
    return {"status": "ok"}


@app.post("/api/settings/columns")
@app.post(f"{APP_PREFIX}/api/settings/columns", include_in_schema=False)
async def api_save_columns(request: Request):
    """Сохранение списка колонок видов обучения."""
    session = get_session(request)
    if not session or not session["can_edit"]:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    data = await request.json()
    if not isinstance(data, list):
        return JSONResponse({"error": "Invalid payload format"}, status_code=400)

    await asyncio.to_thread(save_columns_settings, data)
    return {"status": "ok"}


@app.post("/api/settings/categories")
@app.post(f"{APP_PREFIX}/api/settings/categories", include_in_schema=False)
async def api_save_categories(request: Request, data: dict):
    """Сохранение соответствия должностей категориям (ИТР/рабочие)."""
    session = get_session(request)
    if not session or not session["can_edit"]:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    try:
        await asyncio.to_thread(save_categories_settings, data)
        return {"ok": True}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/settings/employee_order")
@app.post(f"{APP_PREFIX}/api/settings/employee_order", include_in_schema=False)
async def api_save_employee_order(request: Request, data: list[str]):
    """Сохранение пользовательского порядка сортировки сотрудников."""
    session = get_session(request)
    if not session or not session["can_edit"]:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    try:
        await asyncio.to_thread(save_employee_order_settings, data)
        return {"status": "ok"}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


if __name__ == "__main__":
    import uvicorn
    host = os.environ.get("WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("WEB_PORT", 8007))
    uvicorn.run("app:app", host=host, port=port, reload=False)
