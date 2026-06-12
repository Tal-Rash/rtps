import re
path = r'g:\Мой диск\Codex\rtps\web_zamer_kp\app.py'

with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Find where helper functions start
match = re.search(r'def send_html\(', content)
if not match:
    print("Could not find send_html")
    exit(1)

top_part = content[:match.start()]

fastapi_code = """
from fastapi import FastAPI, Request, Response, Depends, Form, HTTPException, Cookie, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
import urllib.parse
import traceback

app = FastAPI(title="RTPS Zamer KP")

@app.middleware("http")
async def strip_prefix(request: Request, call_next):
    if request.scope["path"].startswith(APP_PREFIX + "/"):
        request.scope["path"] = request.scope["path"][len(APP_PREFIX):]
    return await call_next(request)

app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")

def _cookie_value(username: str, role: str) -> str:
    payload = f"{username}:{role}:{int(dt.datetime.now().timestamp())}"
    signature = hmac.new(WEB_SECRET.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}:{signature}"

def _verify_cookie(value: str) -> tuple[str, str, str, str] | None:
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
            elif len(parts) == 4:
                username, role, expiry_text, sig = parts
                payload = f"{username}{sep}{role}{sep}{expiry_text}"
                user_id, modules, safe_name = username, "", username
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
                
            return user_id, role, modules, urllib.parse.unquote(safe_name)
        except Exception:
            continue
    return None

def get_current_session(request: Request):
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        return _verify_cookie(cookie)
    return None

def get_mod_role(session: tuple[str, str, str, str] | None, module: str) -> str:
    if not session:
        return ""
    _, role, modules, _ = session
    if role == "admin":
        return "admin"
    if role == "viewer":
        return "viewer"
    if module in modules.split(","):
        return "edit" if role == "editor" else role
    return ""

def require_auth_fastapi(request: Request, need_edit: bool = False):
    if not AUTH_ENABLED:
        return True, None
    session = get_current_session(request)
    role = get_mod_role(session, "zamer_kp")
    if not role:
        return False, None
    if need_edit and role not in ("edit", "editor", "admin"):
        return False, None
    return True, session

def json_response(data: dict | list, status_code: int = 200) -> JSONResponse:
    return JSONResponse(content=data, status_code=status_code)

@app.get("/zamer-kp", response_class=HTMLResponse)
@app.get("/", response_class=HTMLResponse)
async def home_route(request: Request):
    session = get_current_session(request)
    mod_role = get_mod_role(session, "zamer_kp")
    
    if not session or not mod_role:
        with open(ROOT / "templates" / "login.html", "r", encoding="utf-8") as f:
            html = f.read().replace("{{APP_PREFIX}}", APP_PREFIX)
        return HTMLResponse(content=html, headers={"WWW-Authenticate": 'Form realm="Zamer KP"'}, status_code=401)
        
    html_content = render_page(mod_role)
    response = HTMLResponse(content=html_content)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response

@app.get("/logout")
async def logout_route():
    return RedirectResponse("/", status_code=303)

@app.get("/api/state")
async def get_state(request: Request, locomotive: str = ""):
    auth_ok, session = require_auth_fastapi(request)
    if not auth_ok:
        return Response("Unauthorized", status_code=401)
    return json_response(load_state(locomotive.strip()))

@app.get("/api/archive")
async def get_archive(request: Request, locomotive: str = "", search: str = "", sort: str = "desc"):
    auth_ok, session = require_auth_fastapi(request)
    if not auth_ok:
        return Response("Unauthorized", status_code=401)
    rows = load_archive_rows(locomotive.strip(), search.strip(), sort.strip().lower() != "asc")
    return json_response({"rows": rows})

@app.get("/api/kp-data")
async def get_kp_data(request: Request, locomotive: str = ""):
    auth_ok, session = require_auth_fastapi(request)
    if not auth_ok:
        return Response("Unauthorized", status_code=401)
    return json_response(load_kp_view(locomotive.strip()))

@app.get("/api/norms")
async def get_norms(request: Request):
    auth_ok, session = require_auth_fastapi(request)
    if not auth_ok:
        return Response("Unauthorized", status_code=401)
    return json_response({"rows": load_norms_rows()})

@app.get("/api/archive-excel-template")
async def export_archive_template(request: Request):
    auth_ok, session = require_auth_fastapi(request)
    if not auth_ok:
        return Response("Unauthorized", status_code=401)
    try:
        data = archive_excel_template_bytes()
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename*=UTF-8''%D0%A8%D0%B0%D0%B1%D0%BB%D0%BE%D0%BD_%D0%B8%D0%BC%D0%BF%D0%BE%D1%80%D1%82%D0%B0_%D0%B0%D1%80%D1%85%D0%B8%D0%B2%D0%B0.xlsx"}
        )
    except Exception as exc:
        return json_response({"error": str(exc)}, status_code=400)

@app.get("/api/phone-export")
async def export_phone(request: Request, kind: str = "archive", date_from: str = "", date_to: str = ""):
    try:
        query_params = request.query_params
        selected_locomotives = [item.strip() for item in query_params.getlist("locomotive") if item.strip()]
        payload = phone_export_payload(kind.strip().lower(), selected_locomotives, date_from.strip(), date_to.strip())
        return json_response(payload)
    except Exception as exc:
        return json_response({"error": str(exc)}, status_code=400)

@app.get("/api/archive-excel-export")
async def export_archive_excel(request: Request, date_from: str = "", date_to: str = ""):
    auth_ok, session = require_auth_fastapi(request)
    if not auth_ok:
        return Response("Unauthorized", status_code=401)
    try:
        query_params = request.query_params
        selected_locomotives = [item.strip() for item in query_params.getlist("locomotive") if item.strip()]
        data, row_count = archive_excel_export_bytes(selected_locomotives, date_from.strip(), date_to.strip())
        if row_count <= 0:
            return json_response({"error": "По выбранным фильтрам данных нет."}, status_code=400)
        filename = f"Экспорт_архива_{dt.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.xlsx"
        from urllib.parse import quote
        safe_filename = quote(filename)
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{safe_filename}"}
        )
    except Exception as exc:
        return json_response({"error": str(exc)}, status_code=400)

@app.post("/api/state")
async def post_state(request: Request):
    auth_ok, session = require_auth_fastapi(request, need_edit=True)
    if not auth_ok:
        return json_response({"error": "Unauthorized"}, status_code=401)
    try:
        payload = await request.json()
        saved = save_state(payload, full_name=session[3] if session and len(session) > 3 else "")
        return json_response(saved)
    except Exception as exc:
        return json_response({"error": str(exc)}, status_code=400)

@app.post("/api/archive")
async def post_archive(request: Request):
    auth_ok, session = require_auth_fastapi(request, need_edit=True)
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

@app.post("/api/kp-data")
async def post_kp_data(request: Request):
    auth_ok, session = require_auth_fastapi(request, need_edit=True)
    if not auth_ok:
        return json_response({"error": "Unauthorized"}, status_code=401)
    try:
        payload = await request.json()
        result = save_kp_data(payload)
        if isinstance(result, tuple):
            return json_response(result[0], status_code=result[1])
        return json_response(result)
    except Exception as exc:
        return json_response({"error": str(exc)}, status_code=400)

@app.post("/api/norms")
async def post_norms(request: Request):
    auth_ok, session = require_auth_fastapi(request, need_edit=True)
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

@app.post("/api/archive-excel-import")
async def post_archive_import(request: Request):
    auth_ok, session = require_auth_fastapi(request, need_edit=True)
    if not auth_ok:
        return json_response({"error": "Unauthorized"}, status_code=401)
    try:
        payload = await request.json()
        encoded = text(payload.get("data")).strip()
        if not encoded:
            return json_response({"error": "Файл Excel не передан."}, status_code=400)
        import base64
        data = base64.b64decode(encoded)
        result = import_archive_excel_bytes(data)
        if isinstance(result, tuple):
            return json_response(result[0], status_code=result[1])
        return json_response(result)
    except Exception as exc:
        return json_response({"error": str(exc)}, status_code=400)

@app.post("/api/phone-import")
async def post_phone_import(request: Request):
    try:
        raw = await request.body()
        payload = parse_phone_json_payload(raw)
        result = import_phone_payload(payload)
        if isinstance(result, tuple):
            return json_response(result[0], status_code=result[1])
        return json_response(result)
    except Exception as exc:
        return json_response({"error": str(exc)}, status_code=400)

def main() -> None:
    ensure_db()
    host = os.environ.get("WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("WEB_PORT", "8003"))
    url = f"http://{host}:{port}{APP_PREFIX}"
    print(f"Замер КП ready (FastAPI): {url}")
    if host in {"127.0.0.1", "localhost", "0.0.0.0"}:
        import threading, webbrowser
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    uvicorn.run("app:app", host=host, port=port, reload=True)

if __name__ == "__main__":
    main()
"""

with open(path, 'w', encoding='utf-8') as f:
    f.write(top_part + fastapi_code)

print("web_zamer_kp/app.py rewritten successfully.")
