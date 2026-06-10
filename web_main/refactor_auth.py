import os
from pathlib import Path

app_path = Path("G:/Мой диск/Codex/rtps/web_main/app.py")
content = app_path.read_text("utf-8")

# Add sqlite3 import
if "import sqlite3" not in content:
    content = content.replace("import secrets", "import secrets\nimport sqlite3")

# Update SESSIONS and add DB_FILE
content = content.replace(
    'SESSIONS: dict[str, tuple[str, str, float]] = {}',
    'SESSIONS: dict[str, tuple[str, str, str, str, float]] = {}\nDB_FILE = ROOT.parent / "base" / "common_database.db"'
)

# Update HOME_TEMPLATE
content = content.replace(
    '<a href="/grafik-ppr">Открыть</a>',
    '{{GRAFIK_PPR_LINK}}'
)
content = content.replace(
    '<a href="/zamer-kp">Открыть</a>',
    '{{ZAMER_KP_LINK}}'
)

# Update _cookie_value
content = content.replace(
    '''def _cookie_value(username: str, role: str) -> str:
    expiry = int(dt.datetime.now().timestamp()) + SESSION_TTL_SECONDS
    payload = f"{username}:{role}:{expiry}"
    sig = hmac.new(WEB_SECRET.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    token = f"{payload}:{sig}"
    SESSIONS[token] = (username, role, float(expiry))
    return token''',
    '''def _cookie_value(user_id: str, role: str, modules: str, full_name: str) -> str:
    expiry = int(dt.datetime.now().timestamp()) + SESSION_TTL_SECONDS
    safe_name = full_name.replace(":", " ")
    payload = f"{user_id}:{role}:{modules}:{safe_name}:{expiry}"
    sig = hmac.new(WEB_SECRET.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    token = f"{payload}:{sig}"
    SESSIONS[token] = (user_id, role, modules, full_name, float(expiry))
    return token'''
)

# Update _verify_cookie
content = content.replace(
    '''def _verify_cookie(value: str) -> tuple[str, str] | None:
    try:
        username, role, ts, sig = value.rsplit(":", 3)
        payload = f"{username}:{role}:{ts}"''',
    '''def _verify_cookie(value: str) -> tuple[str, str, str, str] | None:
    try:
        user_id, role, modules, safe_name, ts, sig = value.rsplit(":", 5)
        payload = f"{user_id}:{role}:{modules}:{safe_name}:{ts}"'''
)
content = content.replace(
    '''        return username, role
    except Exception:
        try:''',
    '''        return user_id, role, modules, safe_name
    except Exception:
        try:'''
)
content = content.replace(
    '''def current_session(handler: BaseHTTPRequestHandler) -> tuple[str, str] | None:
    for token in _parse_cookie_values(handler, SESSION_COOKIE):
        session = _verify_cookie(token)
        if session:
            username, role = session
            SESSIONS[token] = (username, role, dt.datetime.now().timestamp())
            return session
    return None''',
    '''def current_session(handler: BaseHTTPRequestHandler) -> tuple[str, str, str, str] | None:
    for token in _parse_cookie_values(handler, SESSION_COOKIE):
        session = _verify_cookie(token)
        if session:
            user_id, role, modules, safe_name = session
            SESSIONS[token] = (user_id, role, modules, safe_name, dt.datetime.now().timestamp())
            return session
    return None'''
)

content = content.replace(
    '''def _login_cookie(username: str, role: str) -> str:
    token = _cookie_value(username, role)''',
    '''def _login_cookie(user_id: str, role: str, modules: str, full_name: str) -> str:
    token = _cookie_value(user_id, role, modules, full_name)'''
)

content = content.replace(
    '''def render_home(username: str, role: str) -> str:
    started_at = dt.datetime.now().strftime("%H:%M:%S %d.%m.%Y")
    role_label = "Просмотр" if role == "view" else "Редактирование"
    spravochnik_link = (
        '<a class="disabled" href="#" aria-disabled="true" tabindex="-1">Открыть</a>'
        if role == "view"
        else '<a href="/spravochnik">Открыть</a>'
    )
    return (
        HOME_TEMPLATE
        .replace("{{STARTED_AT}}", started_at)
        .replace("{{AUTH_BADGE}}", f"Пользователь: {username} / {role_label}")
        .replace("{{SPRAVOCHNIK_LINK}}", spravochnik_link)
    )''',
    '''def render_home(user_id: str, full_name: str, role: str, modules: str) -> str:
    started_at = dt.datetime.now().strftime("%H:%M:%S %d.%m.%Y")
    
    role_labels = {"admin": "Администратор", "editor": "Редактор", "viewer": "Зритель"}
    role_label = role_labels.get(role, role)
    
    mods = [m.strip() for m in modules.split(",")]
    
    def link_for(mod_id: str, path: str) -> str:
        if mod_id in mods or "admin" in mods:
            return f'<a href="{path}">Открыть</a>'
        return '<a class="disabled" href="#" aria-disabled="true" tabindex="-1">Нет доступа</a>'
        
    return (
        HOME_TEMPLATE
        .replace("{{STARTED_AT}}", started_at)
        .replace("{{AUTH_BADGE}}", f"Пользователь: {full_name} ({role_label})")
        .replace("{{GRAFIK_PPR_LINK}}", link_for("grafik_ppr", "/grafik-ppr"))
        .replace("{{ZAMER_KP_LINK}}", link_for("zamer_kp", "/zamer-kp"))
        .replace("{{SPRAVOCHNIK_LINK}}", link_for("spravochnik", "/spravochnik"))
    )'''
)

content = content.replace(
    '''        session = current_session(self)
        user = session[0] if session else None
        role = session[1] if session else None
        if parsed.path == "/":
            if not user:
                _redirect(self, "/login")
                return
            _send_html(self, render_home(user, role or "view"))''',
    '''        session = current_session(self)
        user_id = session[0] if session else None
        role = session[1] if session else None
        modules = session[2] if session else ""
        full_name = session[3] if session else ""
        if parsed.path == "/":
            if not user_id:
                _redirect(self, "/login")
                return
            _send_html(self, render_home(user_id, full_name, role, modules))'''
)

content = content.replace(
    '''        if parsed.path == "/login":
            if user:
                _redirect(self, "/")
                return
            _send_html(self, LOGIN_TEMPLATE.replace("{{USER}}", WEB_USER))
            return''',
    '''        if parsed.path == "/login":
            if user_id:
                _redirect(self, "/")
                return
            _send_html(self, LOGIN_TEMPLATE.replace("{{USER}}", ""))
            return'''
)

old_login_post = '''        if parsed.path == "/login":
            form = parse_qs(raw.decode("utf-8", errors="ignore"))
            password = form.get("password", [""])[0]
            if password == WEB_VIEW_PASSWORD:
                expiry = int(dt.datetime.now().timestamp()) + SESSION_TTL_SECONDS
                _write_access_state(WEB_USER, "view", expiry)
                _redirect(self, "/", _login_cookie(WEB_USER, "view"))
                return
            if password == WEB_EDIT_PASSWORD:
                expiry = int(dt.datetime.now().timestamp()) + SESSION_TTL_SECONDS
                _write_access_state(WEB_USER, "edit", expiry)
                _redirect(self, "/", _login_cookie(WEB_USER, "edit"))
                return
            _send_html(
                self,
                LOGIN_TEMPLATE.replace("{{USER}}", WEB_USER)
                + "<p style='text-align:center;color:#b00020;'>Неверный логин или пароль</p>",
                status=HTTPStatus.UNAUTHORIZED,
            )
            return'''

new_login_post = '''        if parsed.path == "/login":
            form = parse_qs(raw.decode("utf-8", errors="ignore"))
            password = form.get("password", [""])[0]
            
            user_record = None
            try:
                with sqlite3.connect(DB_FILE) as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT id, full_name, role, allowed_modules FROM users WHERE password=?", (password,))
                    user_record = cur.fetchone()
            except Exception as e:
                print(f"DB Error: {e}")
                
            if user_record:
                u_id, u_full_name, u_role, u_modules = user_record
                expiry = int(dt.datetime.now().timestamp()) + SESSION_TTL_SECONDS
                _write_access_state(u_full_name, u_role, expiry)
                _redirect(self, "/", _login_cookie(str(u_id), u_role, u_modules, u_full_name))
                return
                
            _send_html(
                self,
                LOGIN_TEMPLATE.replace("{{USER}}", "")
                + "<p style='text-align:center;color:#b00020;'>Неверный пароль</p>",
                status=HTTPStatus.UNAUTHORIZED,
            )
            return'''

content = content.replace(old_login_post, new_login_post)

app_path.write_text(content, "utf-8")
print("Updated app.py!")
