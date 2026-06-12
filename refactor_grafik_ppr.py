import re
path = r'g:\Мой диск\Codex\rtps\web_grafik_ppr\app.py'

with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Find the start of _send_html
match = re.search(r'def _send_html\(', content)
if not match:
    print("Could not find _send_html")
    exit(1)

top_part = content[:match.start()]

fastapi_code = """
from fastapi import FastAPI, Request, Response, Depends, Form, HTTPException, Cookie, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

app = FastAPI(title="RTPS Grafik PPR")

@app.middleware("http")
async def strip_prefix(request: Request, call_next):
    if request.scope["path"].startswith(APP_PREFIX + "/"):
        request.scope["path"] = request.scope["path"][len(APP_PREFIX):]
    return await call_next(request)

app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")

def _login_cookie(username: str, role: str) -> str:
    token = _cookie_value(username, role)
    SESSIONS[token] = (username, role, "", username, dt.datetime.now().timestamp())
    return f"{SESSION_COOKIE}={token}; HttpOnly; Path=/; SameSite=Lax"

def json_response(data: dict | list, status_code: int = 200) -> JSONResponse:
    return JSONResponse(content=data, status_code=status_code)

def get_current_session(request: Request):
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        return _verify_cookie(cookie)
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
async def home_route(request: Request, year: int = None):
    if year is None:
        year = dt.date.today().year
    session = get_current_session(request)
    user = session[0] if session else None
    mod_role = get_mod_role(session, "grafik_ppr")
    
    try:
        raw_cookie = request.cookies.get(SESSION_COOKIE, "")
        with open(ROOT.parent / "data" / "grafik_auth.log", "a", encoding="utf-8") as f:
            f.write(f"Access /grafik-ppr. Session: {session}. Cookie: {raw_cookie}\\n")
    except Exception:
        pass
        
    if AUTH_ENABLED and not mod_role:
        return Response(content="Требуется вход", status_code=401, headers={"WWW-Authenticate": 'Form realm="Grafik PPR"'})
        
    can_edit = mod_role in ("edit", "editor", "admin") if AUTH_ENABLED else True
    
    # We will reuse the original render_page logic, but it returned a string. We return HTMLResponse.
    html_content = render_page(load_state(year), can_edit, user)
    response = HTMLResponse(content=html_content)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response

@app.get("/login", response_class=HTMLResponse)
async def login_get(request: Request):
    if not AUTH_ENABLED:
        return RedirectResponse(APP_PREFIX, status_code=303)
    session = get_current_session(request)
    if session and session[0]:
        return RedirectResponse(APP_PREFIX, status_code=303)
    return HTMLResponse(render_login())

@app.post("/login", response_class=HTMLResponse)
async def login_post(request: Request, user: str = Form(""), password: str = Form("")):
    if not AUTH_ENABLED:
        return RedirectResponse(APP_PREFIX, status_code=303)
    username = user.strip()
    if username == WEB_USER and password == WEB_VIEW_PASSWORD:
        resp = RedirectResponse(APP_PREFIX, status_code=303)
        resp.headers["Set-Cookie"] = _login_cookie(username, "view")
        return resp
    if username == WEB_USER and password == WEB_EDIT_PASSWORD:
        resp = RedirectResponse(APP_PREFIX, status_code=303)
        resp.headers["Set-Cookie"] = _login_cookie(username, "edit")
        return resp
    return HTMLResponse(render_login("<p style='text-align:center;color:#b00020;'>Неверный логин или пароль</p>"), status_code=401)

@app.get("/logout")
async def logout_route():
    return RedirectResponse("/", status_code=303)

@app.get("/api/state")
async def get_state(year: int = None):
    if year is None: year = dt.date.today().year
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
    try:
        saved = save_state(payload)
    except Exception as exc:
        return json_response({"error": str(exc)}, status_code=400)
    return json_response(saved)

@app.get("/api/export")
async def export_state(request: Request, year: int = None):
    auth_ok, session = require_auth_fastapi(request)
    if not auth_ok:
        return Response("Unauthorized", status_code=401)
    if year is None: year = dt.date.today().year
    body = json.dumps(load_state(year), ensure_ascii=False, indent=2).encode("utf-8")
    return Response(
        content=body, 
        media_type="application/json", 
        headers={"Content-Disposition": f'attachment; filename="grafik_ppr_{year}.json"'}
    )

@app.get("/api/act-export")
async def export_act(request: Request, year: int = None, month: str = "", act: str = ""):
    auth_ok, session = require_auth_fastapi(request)
    if not auth_ok:
        return Response("Unauthorized", status_code=401)
    if year is None: year = dt.date.today().year
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
async def export_report(request: Request, year: int = None, month: str = ""):
    auth_ok, session = require_auth_fastapi(request)
    if not auth_ok:
        return Response("Unauthorized", status_code=401)
    if year is None: year = dt.date.today().year
    if not month.strip(): month = MONTHS_RU[dt.date.today().month - 1]
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
async def preview_report(request: Request, year: int = None, month: str = ""):
    auth_ok, session = require_auth_fastapi(request)
    if not auth_ok:
        return json_response({"error": "Unauthorized"}, status_code=401)
    if year is None: year = dt.date.today().year
    if not month.strip(): month = MONTHS_RU[dt.date.today().month - 1]
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
    with DB_LOCK, conn() as db:
        cur = db.cursor()
        with db:
            row = cur.execute("SELECT v FROM tu28_data WHERE y=? AND m=? AND r=? AND k='tu28_locked'", (year, month_name, r)).fetchone()
            is_locked = False
            if row and row["v"]:
                is_locked = json.loads(row["v"])
            if not is_locked:
                cur.execute("INSERT OR REPLACE INTO tu28_data VALUES (?,?,?,?,?)", (year, month_name, r, "tu28_extra", json.dumps(extra)))
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
    if not isinstance(staff_list, list): staff_list = []
    extra_repairs = payload.get("extra_repairs") or []
    if not isinstance(extra_repairs, list): extra_repairs = []
    
    try:
        body, filename = build_tu28_workbook(year, month, row_idx, staff_list, extra_repairs=extra_repairs)
    except Exception as exc:
        return json_response({"error": str(exc)}, status_code=400)
        
    return Response(
        content=body,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": content_disposition_attachment(filename)}
    )

def main() -> None:
    global SERVER_STARTED_AT
    SERVER_STARTED_AT = dt.datetime.now()
    ensure_database()
    host = os.environ.get("WEB_HOST", "127.0.0.1")
    port = int(os.environ.get("WEB_PORT", "8000"))
    url = f"http://{host}:{port}/grafik-ppr"
    print(f"График ППР web ready (FastAPI): {url} | started at {SERVER_STARTED_AT:%H:%M:%S %d.%m.%Y}")
    if host in {"127.0.0.1", "localhost", "0.0.0.0"}:
        import threading, webbrowser
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    uvicorn.run("app:app", host=host, port=port, reload=True)

if __name__ == "__main__":
    main()
"""

# Let's write the modified file
with open(path, 'w', encoding='utf-8') as f:
    f.write(top_part + fastapi_code)

print("web_grafik_ppr/app.py rewritten successfully.")
