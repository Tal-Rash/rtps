from __future__ import annotations

import asyncio
import datetime as dt
import gzip
import hashlib
import hmac
import json
import os
import secrets
import sys
import time
from pathlib import Path
from urllib.parse import unquote

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Обеспечиваем доступность директории модуля и корня проекта для системных импортов
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_ROOT.parent))

from rtps_common import module_has_access, resolve_user_access

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
        load_state_from_db,
        normalize_locomotives,
        normalize_warehouse_rows,
        save_state_to_db,
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
        load_state_from_db,
        normalize_locomotives,
        normalize_warehouse_rows,
        save_state_to_db,
    )


def _verify_cookie(value: str) -> tuple[str, str, str, str] | None:
    """Проверка криптографической подписи куки авторизации и срока её действия."""
    if not value:
        return None
    secret = get_web_secret()
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
        exp_sig = hmac.new(secret.encode(), raw.encode(), hashlib.sha256).hexdigest()
        if not secrets.compare_digest(sig, exp_sig):
            continue
        if float(expiry_text) < dt.datetime.now().timestamp():
            return None
        return unquote(user_id), unquote(role), unquote(mods), unquote(full_name)
    return None


def get_session(request: Request) -> dict | None:
    """Извлечение и валидация текущей сессии пользователя с проверкой прав доступа к модулю АЛСН."""
    cookie = request.cookies.get(SESSION_COOKIE)
    if not cookie:
        return None
    session = _verify_cookie(cookie)
    if not session:
        return None
    user_id, role, mods, full_name = session
    resolved = resolve_user_access(WEB_USERS_DB, user_id, role, mods)
    if not resolved:
        return None
    role, mods = resolved
    if not module_has_access(role, mods, "alsn"):
        return None
    can_edit = (
        role == "admin"
        or "admin" in mods
        or "alsn:edit" in mods
        or (role in ("edit", "editor") and ("alsn" in mods.split(",") or "alsn:view" in mods))
    )
    return {
        "user_id": user_id,
        "role": role,
        "modules": mods,
        "full_name": full_name,
        "can_edit": can_edit,
    }


# Инициализируем структуру базы данных при старте
init_db()

# Создаем приложение FastAPI
app = FastAPI(title="RTPS ALSN", version=APP_VERSION)
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="alsn_static")
app.mount(f"{APP_PREFIX}/static", StaticFiles(directory=str(ROOT / "static")), name="alsn_static_prefixed")
templates = Jinja2Templates(directory=str(ROOT / "templates"))


@app.get("/", include_in_schema=False)
async def root_redirect():
    """При обращении к корню перенаправляем на главную страницу портала."""
    return RedirectResponse(f"{MAIN_SITE_URL}/", status_code=303)


@app.get(f"{APP_PREFIX}", include_in_schema=False)
@app.get(f"{APP_PREFIX}/", response_class=HTMLResponse)
async def index(request: Request):
    """Главная страница модуля АЛСН с отображением текущей сессии."""
    session = get_session(request)
    if not session:
        return RedirectResponse(f"{MAIN_LOGIN_URL}?next=/alsn", status_code=303)
    context = {
        "request": request,
        "APP_PREFIX": APP_PREFIX,
        "APP_VERSION": APP_VERSION,
        "MAIN_SITE_URL": MAIN_SITE_URL,
        "CAN_EDIT": "true" if session["can_edit"] else "false",
        "USER_NAME": session["full_name"],
        "USER_ROLE": "Редактор" if session["can_edit"] else "Просмотр",
    }
    return templates.TemplateResponse(request=request, name="index.html", context=context)


@app.get("/api/state")
@app.get(f"{APP_PREFIX}/api/state", include_in_schema=False)
async def api_state(request: Request):
    """Асинхронное чтение состояния локомотивов и склада без блокировки event loop."""
    session = get_session(request)
    if not session:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    state = await asyncio.to_thread(load_state_from_db)
    return state


@app.post("/api/state")
@app.post(f"{APP_PREFIX}/api/state", include_in_schema=False)
async def api_save_state(request: Request):
    """Сохранение состояния АЛСН с поддержкой gzip-сжатия и асинхронного выполнения."""
    t0 = time.perf_counter()
    session = get_session(request)
    if not session or not session["can_edit"]:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    try:
        if request.headers.get("content-encoding") == "gzip":
            raw_body = await request.body()
            payload = json.loads(gzip.decompress(raw_body).decode("utf-8"))
        else:
            payload = await request.json()
    except Exception as exc:
        return JSONResponse({"error": f"Некорректный JSON в теле запроса: {exc}"}, status_code=400)

    locomotives = normalize_locomotives(payload.get("locomotives"))
    warehouse = normalize_warehouse_rows(payload.get("warehouse"))

    # Выполняем строго атомарное сохранение в SQLite в пуле потоков
    await asyncio.to_thread(save_state_to_db, locomotives, warehouse)
    elapsed = time.perf_counter() - t0
    print(f"[SAVE_ALSN] Успешно сохранено за {elapsed:.3f}с")
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("WEB_PORT", "8008"))
    uvicorn.run("app:app", host=host, port=port, reload=False, log_level="info")
