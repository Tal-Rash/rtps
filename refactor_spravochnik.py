import re
import os

path = r'g:\Мой диск\Codex\rtps\web_spravochnik\app.py'

with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

parts = content.split("class Handler(BaseHTTPRequestHandler):")
if len(parts) < 2:
    print("Could not find class Handler")
    exit(1)

top_part = parts[0]

fastapi_code = """
from fastapi import FastAPI, Request, Response, Depends, Form, HTTPException, Cookie, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
import urllib.parse
import traceback

app = FastAPI(title="RTPS Spravochnik")

@app.middleware("http")
async def strip_prefix(request: Request, call_next):
    if request.scope["path"].startswith(APP_PREFIX + "/"):
        request.scope["path"] = request.scope["path"][len(APP_PREFIX):]
    return await call_next(request)

def _cookie_value_fastapi(username: str, role: str) -> str:
    payload = f"{username}:{role}:{int(dt.datetime.now().timestamp())}"
    signature = hmac.new(WEB_SECRET.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}:{signature}"

def _verify_cookie_fastapi(value: str) -> tuple[str, str, str, str] | None:
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
            if LEGACY_WEB_SECRET and LEGACY_WEB_SECRET not in secrets_to_try:
                secrets_to_try.append(LEGACY_WEB_SECRET)
                
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

def get_current_session_fastapi(request: Request):
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        return _verify_cookie_fastapi(cookie)
    return None

def get_mod_role_fastapi(session: tuple[str, str, str, str] | None, module: str) -> str:
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
    session = get_current_session_fastapi(request)
    role = get_mod_role_fastapi(session, "spravochnik")
    if not role:
        return False, None
    if need_edit and role not in ("edit", "editor", "admin"):
        return False, None
    return True, session

def json_response(data: dict | list, status_code: int = 200) -> JSONResponse:
    return JSONResponse(content=data, status_code=status_code)

@app.get("/spravochnik", response_class=HTMLResponse)
@app.get("/", response_class=HTMLResponse)
async def home_route(request: Request):
    session = get_current_session_fastapi(request)
    mod_role = get_mod_role_fastapi(session, "spravochnik") if session else None
    
    if not session or not mod_role:
        html = LOGIN_HTML.replace("{{USER}}", WEB_USER)
        return HTMLResponse(content=html, headers={"WWW-Authenticate": 'Form realm="Spravochnik"'}, status_code=401)
        
    auth_badge = "Редактирование" if mod_role in ("edit", "editor", "admin") else "Просмотр"
    html_content = HTML.replace("{{USER}}", WEB_USER).replace("{{AUTH_BADGE}}", auth_badge).replace("{{CAN_EDIT}}", "true" if mod_role in ("edit", "editor", "admin") else "false")
    
    response = HTMLResponse(content=html_content)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response

@app.get("/login")
async def login_get(request: Request):
    session = get_current_session_fastapi(request)
    if session:
        return RedirectResponse("/", status_code=303)
    html = LOGIN_HTML.replace("{{USER}}", WEB_USER)
    return HTMLResponse(content=html)

@app.get("/logout")
async def logout_route():
    response = HTMLResponse(content='<!doctype html><meta http-equiv="refresh" content="0; url=/spravochnik/">')
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="lax")
    response.headers["Cache-Control"] = "no-store"
    return response

@app.get("/api/state")
async def get_state(request: Request, year: int = None):
    auth_ok, session = require_auth_fastapi(request)
    if not auth_ok:
        return Response("Unauthorized", status_code=401)
    if year is None:
        year = dt.date.today().year
    return json_response(load_state(year))

@app.post("/login")
async def login_post(request: Request):
    form = await request.form()
    password = form.get("password", "")
    if password == WEB_EDIT_PASSWORD:
        expiry = int(dt.datetime.now().timestamp()) + SESSION_TTL_SECONDS
        payload = f"{WEB_USER}|edit|{expiry}"
        sig = hmac.new(WEB_SECRET.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
        token = f"{payload}|{sig}"
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(SESSION_COOKIE, token, max_age=SESSION_TTL_SECONDS, path="/", httponly=True, samesite="lax")
        return response
    
    html = LOGIN_HTML.replace("{{USER}}", WEB_USER).replace("{{AUTH_BADGE}}", "Неверный логин или пароль")
    return HTMLResponse(content=html, status_code=401)

@app.post("/api/save")
async def post_save(request: Request):
    auth_ok, session = require_auth_fastapi(request, need_edit=True)
    if not auth_ok:
        return json_response({"error": "Unauthorized"}, status_code=401)
    try:
        payload = await request.json()
        save_state(payload)
        return json_response({"ok": True})
    except Exception as exc:
        return json_response({"ok": False, "error": str(exc)}, status_code=400)

@app.post("/api/purge_deleted_inventory")
async def post_purge_deleted(request: Request):
    auth_ok, session = require_auth_fastapi(request, need_edit=True)
    if not auth_ok:
        return json_response({"error": "Unauthorized"}, status_code=401)
    try:
        return json_response(purge_deleted_inventory())
    except Exception as exc:
        return json_response({"ok": False, "error": str(exc)}, status_code=400)

@app.post("/api/purge_inventory_row")
async def post_purge_row(request: Request):
    auth_ok, session = require_auth_fastapi(request, need_edit=True)
    if not auth_ok:
        return json_response({"error": "Unauthorized"}, status_code=401)
    try:
        payload = await request.json()
        y = payload.get("year", dt.date.today().year)
        ser = payload.get("ser", "")
        num = payload.get("num", "")
        return json_response(purge_inventory_row(y, ser, num))
    except Exception as exc:
        return json_response({"ok": False, "error": str(exc)}, status_code=400)

def main() -> None:
    ensure_db()
    host = os.environ.get("WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("WEB_PORT", "8002"))
    url = f"http://{host}:{port}{APP_PREFIX}"
    print(f"Справочник ready (FastAPI): {url}")
    if host in {"127.0.0.1", "localhost", "0.0.0.0"}:
        import threading, webbrowser
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    uvicorn.run("app:app", host=host, port=port, reload=True)

if __name__ == "__main__":
    main()
"""

with open(path, 'w', encoding='utf-8') as f:
    f.write(top_part + fastapi_code)

print("web_spravochnik/app.py rewritten successfully.")
