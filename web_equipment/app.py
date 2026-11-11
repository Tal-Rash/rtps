from __future__ import annotations

import asyncio
import csv
import datetime as dt
import gzip
import hashlib
import hmac
import io
import json
import os
import secrets
import sys
import time
from pathlib import Path
from urllib.parse import unquote

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Обеспечиваем доступность директории модуля и корня проекта для системных импортов
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_ROOT.parent))

from rtps_common import module_has_access, module_role, resolve_user_access

try:
    from .constants import (
        APP_PREFIX,
        APP_VERSION,
        DEFAULT_CATEGORIES,
        DEFAULT_TEST_TYPES,
        MAIN_LOGIN_URL,
        MAIN_SITE_URL,
        ROOT,
        SESSION_COOKIE,
        WEB_USERS_DB,
        get_web_secret,
    )
    from .storage import (
        init_db,
        load_equipment_from_db,
        save_equipment_to_db,
    )
except (ImportError, ValueError):
    from constants import (
        APP_PREFIX,
        APP_VERSION,
        DEFAULT_CATEGORIES,
        DEFAULT_TEST_TYPES,
        MAIN_LOGIN_URL,
        MAIN_SITE_URL,
        ROOT,
        SESSION_COOKIE,
        WEB_USERS_DB,
        get_web_secret,
    )
    from storage import (
        init_db,
        load_equipment_from_db,
        save_equipment_to_db,
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
    """Извлечение и валидация текущей сессии пользователя с проверкой прав доступа к модулю Оборудование."""
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
    mod_role = module_role(role, mods, "equipment")
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


# Инициализируем структуру базы данных при старте
init_db()

# Создаем приложение FastAPI
app = FastAPI(title="RTPS Оборудование и инструмент", version=APP_VERSION)
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="equipment_static")
app.mount(f"{APP_PREFIX}/static", StaticFiles(directory=str(ROOT / "static")), name="equipment_static_prefixed")
templates = Jinja2Templates(directory=str(ROOT / "templates"))


@app.get("/", include_in_schema=False)
async def root_redirect():
    """При обращении к корню перенаправляем на главную страницу портала."""
    return RedirectResponse(f"{MAIN_SITE_URL}/", status_code=303)


@app.get(f"{APP_PREFIX}", include_in_schema=False)
@app.get(f"{APP_PREFIX}/", response_class=HTMLResponse)
async def index(request: Request):
    """Главная страница модуля учета проверок и испытаний оборудования."""
    session = get_session(request)
    if not session:
        return RedirectResponse(f"{MAIN_LOGIN_URL}?next=/equipment", status_code=303)
    context = {
        "request": request,
        "APP_PREFIX": APP_PREFIX,
        "APP_VERSION": APP_VERSION,
        "MAIN_SITE_URL": MAIN_SITE_URL,
        "CAN_EDIT": "true" if session["can_edit"] else "false",
        "USER_NAME": session["full_name"],
        "USER_ROLE": "Редактор" if session["can_edit"] else "Просмотр",
        "CATEGORIES": DEFAULT_CATEGORIES,
        "TEST_TYPES": DEFAULT_TEST_TYPES,
    }
    return templates.TemplateResponse(request=request, name="index.html", context=context)


@app.get("/api/items")
@app.get(f"{APP_PREFIX}/api/items", include_in_schema=False)
async def api_items(request: Request):
    """Получение списка оборудования, справочников и текущей даты сервера."""
    session = get_session(request)
    if not session:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    items = await asyncio.to_thread(load_equipment_from_db)
    return {
        "items": items,
        "categories": DEFAULT_CATEGORIES,
        "test_types": DEFAULT_TEST_TYPES,
        "today": dt.date.today().strftime("%d.%m.%Y"),
    }


@app.post("/api/items")
@app.post(f"{APP_PREFIX}/api/items", include_in_schema=False)
async def api_save_items(request: Request):
    """Сохранение изменений списка оборудования с поддержкой прямого JSON и gzip."""
    t0 = time.perf_counter()
    session = get_session(request)
    if not session or not session["can_edit"]:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    try:
        raw_body = await request.body()
        if request.headers.get("content-encoding") == "gzip":
            try:
                decompressed = gzip.decompress(raw_body).decode("utf-8")
                payload = json.loads(decompressed)
            except Exception:
                payload = json.loads(raw_body.decode("utf-8"))
        else:
            payload = json.loads(raw_body.decode("utf-8"))
    except Exception as exc:
        return JSONResponse({"error": f"Некорректный JSON в теле запроса: {exc}"}, status_code=400)

    items = payload.get("items")
    if not isinstance(items, list):
        items = []

    await asyncio.to_thread(save_equipment_to_db, items)
    elapsed = time.perf_counter() - t0
    print(f"[SAVE_EQUIPMENT] Успешно сохранено {len(items)} единиц за {elapsed:.3f}с")
    return {"ok": True, "count": len(items)}


@app.get(f"{APP_PREFIX}/export/csv")
async def export_csv(request: Request):
    """Экспорт перечня оборудования в формате CSV (Excel-совместимый UTF-8 с BOM)."""
    session = get_session(request)
    if not session:
        return RedirectResponse(f"{MAIN_LOGIN_URL}?next=/equipment", status_code=303)

    items = await asyncio.to_thread(load_equipment_from_db)

    output = io.StringIO()
    # Записываем UTF-8 BOM для корректного открытия в русском Microsoft Excel
    output.write("\ufeff")
    writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_MINIMAL)

    writer.writerow([
        "№ п/п",
        "Категория",
        "Наименование оборудования",
        "Инв. / Зав. №",
        "Местонахождение / Участок",
        "Ответственный",
        "Вид проверки / испытания",
        "Периодичность (мес.)",
        "Дата последней проверки",
        "Дата следующей проверки",
        "В ремонте",
        "Результат проверки",
        "№ акта / протокола",
        "Примечание",
    ])

    for idx, item in enumerate(items, 1):
        writer.writerow([
            idx,
            item.get("category", ""),
            item.get("name", ""),
            item.get("inv_number", ""),
            item.get("location", ""),
            item.get("responsible", ""),
            item.get("test_type", ""),
            item.get("periodicity", ""),
            item.get("last_test_date", ""),
            item.get("next_test_date", ""),
            "Да" if item.get("in_repair") else "Нет",
            item.get("test_result", ""),
            item.get("protocol_num", ""),
            item.get("notes", ""),
        ])

    filename = f"equipment_{dt.date.today().strftime('%Y%m%d')}.csv"
    return Response(
        content=output.getvalue().encode("utf-8"),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("WEB_PORT", "8009"))
    uvicorn.run("app:app", host=host, port=port, reload=False, log_level="info")
