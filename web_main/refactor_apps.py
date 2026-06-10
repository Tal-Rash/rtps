import os
from pathlib import Path

apps = [
    "G:/Мой диск/Codex/rtps/web_zamer_kp/app.py",
    "G:/Мой диск/Codex/rtps/web_grafik_ppr/app.py",
    "G:/Мой диск/Codex/rtps/web_spravochnik/app.py"
]

def update_app(app_path):
    path = Path(app_path)
    if not path.exists():
        print(f"Not found: {app_path}")
        return
    
    content = path.read_text("utf-8")
    
    # 1. Update verify_cookie signature and parsing logic
    if "def verify_cookie(value: str) -> tuple[str, str] | None:" in content:
        content = content.replace(
            "def verify_cookie(value: str) -> tuple[str, str] | None:",
            "def verify_cookie(value: str) -> tuple[str, str, str, str] | None:"
        )
    elif "def _verify_cookie(value: str) -> tuple[str, str] | None:" in content:
        content = content.replace(
            "def _verify_cookie(value: str) -> tuple[str, str] | None:",
            "def _verify_cookie(value: str) -> tuple[str, str, str, str] | None:"
        )

    # Replace the body of verify_cookie parsing logic
    # Find the try block inside verify_cookie
    old_verify_body_1 = '''    for sep in (":", "|"):
        try:
            username, role, expiry_text, sig = value.rsplit(sep, 3)
            payload = f"{username}{sep}{role}{sep}{expiry_text}"'''
    new_verify_body_1 = '''    for sep in (":", "|"):
        try:
            user_id, role, modules, safe_name, expiry_text, sig = value.rsplit(sep, 5)
            payload = f"{user_id}{sep}{role}{sep}{modules}{sep}{safe_name}{sep}{expiry_text}"'''
    content = content.replace(old_verify_body_1, new_verify_body_1)

    old_verify_body_2 = '''            if role in {"view", "edit"}:
                return username, role'''
    new_verify_body_2 = '''            return user_id, role, modules, safe_name'''
    content = content.replace(old_verify_body_2, new_verify_body_2)

    # Some apps might not use the loop, but use two try blocks (like web_spravochnik)
    old_spravochnik_1 = '''    try:
        username, role, ts, sig = value.rsplit(":", 3)
        payload = f"{username}:{role}:{ts}"'''
    new_spravochnik_1 = '''    try:
        user_id, role, modules, safe_name, ts, sig = value.rsplit(":", 5)
        payload = f"{user_id}:{role}:{modules}:{safe_name}:{ts}"'''
    content = content.replace(old_spravochnik_1, new_spravochnik_1)

    old_spravochnik_2 = '''        if int(ts) + SESSION_TTL_SECONDS < int(dt.datetime.now().timestamp()):
            return None
        if role not in {"view", "edit"}:
            return None
        return username, role
    except Exception:'''
    new_spravochnik_2 = '''        if int(ts) + SESSION_TTL_SECONDS < int(dt.datetime.now().timestamp()):
            return None
        return user_id, role, modules, safe_name
    except Exception:'''
    content = content.replace(old_spravochnik_2, new_spravochnik_2)

    old_spravochnik_3 = '''        try:
            username, role, expiry_text, sig = value.split("|")
            payload = f"{username}|{role}|{expiry_text}"'''
    new_spravochnik_3 = '''        try:
            user_id, role, modules, safe_name, expiry_text, sig = value.split("|")
            payload = f"{user_id}|{role}|{modules}|{safe_name}|{expiry_text}"'''
    content = content.replace(old_spravochnik_3, new_spravochnik_3)

    old_spravochnik_4 = '''            if dt.datetime.now().timestamp() > float(expiry_text):
                return None
            if role not in {"view", "edit"}:
                return None
            return username, role'''
    new_spravochnik_4 = '''            if dt.datetime.now().timestamp() > float(expiry_text):
                return None
            return user_id, role, modules, safe_name'''
    content = content.replace(old_spravochnik_4, new_spravochnik_4)

    # 2. Update current_session
    if "def current_session(handler: BaseHTTPRequestHandler) -> tuple[str, str] | None:" in content:
        content = content.replace(
            "def current_session(handler: BaseHTTPRequestHandler) -> tuple[str, str] | None:",
            "def current_session(handler: BaseHTTPRequestHandler) -> tuple[str, str, str, str] | None:"
        )

    # find `username, role = session` or `session = _verify_cookie(token)`
    # It varies a bit, let's just do targeted replaces
    content = content.replace(
        "username, role = session",
        "user_id, role, modules, safe_name = session"
    )
    content = content.replace(
        "SESSIONS[token] = (username, role, dt.datetime.now().timestamp())",
        "SESSIONS[token] = (user_id, role, modules, safe_name, dt.datetime.now().timestamp())"
    )
    content = content.replace(
        "SESSIONS[token] = (username, role, float(expiry))",
        "SESSIONS[token] = (user_id, role, modules, safe_name, float(expiry))"
    )

    # SESSIONS type hint
    content = content.replace(
        "SESSIONS: dict[str, tuple[str, str, float]] = {}",
        "SESSIONS: dict[str, tuple[str, str, str, str, float]] = {}"
    )

    # Module permission checks!
    # Look for require_auth or similar checks
    # web_zamer_kp has:
    # def require_auth(handler: BaseHTTPRequestHandler, need_edit: bool = False) -> tuple[str, str] | None:
    #     session = current_session(handler)
    #     if session and (not need_edit or session[1] == "edit"):
    #         return session
    old_req_auth_zamer = '''def require_auth(handler: BaseHTTPRequestHandler, need_edit: bool = False) -> tuple[str, str] | None:
    session = current_session(handler)
    if session and (not need_edit or session[1] == "edit"):
        return session'''
    new_req_auth_zamer = '''def require_auth(handler: BaseHTTPRequestHandler, need_edit: bool = False) -> tuple[str, str, str, str] | None:
    session = current_session(handler)
    if not session:
        return None
    user_id, role, modules, safe_name = session
    mods = [m.strip() for m in modules.split(",")]
    if "admin" not in mods and "zamer_kp" not in mods:
        return None
    if need_edit and role != "edit" and role != "admin":
        return None
    return session'''
    content = content.replace(old_req_auth_zamer, new_req_auth_zamer)

    old_req_auth_grafik = '''    session = current_session(handler)
    if session and (not need_edit or session[1] == "edit"):
        return session'''
    new_req_auth_grafik = '''    session = current_session(handler)
    if not session:
        return None
    user_id, role, modules, safe_name = session
    mods = [m.strip() for m in modules.split(",")]
    if "admin" not in mods and "grafik_ppr" not in mods:
        return None
    if need_edit and role != "edit" and role != "admin":
        return None
    return session'''
    content = content.replace(old_req_auth_grafik, new_req_auth_grafik)

    old_req_auth_sprav = '''    session = current_session(handler)
    if session and (not need_edit or session[1] == "edit"):
        return session'''
    new_req_auth_sprav = '''    session = current_session(handler)
    if not session:
        return None
    user_id, role, modules, safe_name = session
    mods = [m.strip() for m in modules.split(",")]
    if "admin" not in mods and "spravochnik" not in mods:
        return None
    if need_edit and role != "edit" and role != "admin":
        return None
    return session'''
    content = content.replace(old_req_auth_sprav, new_req_auth_sprav)

    # In do_GET where the main HTML is served, we should show the username instead of "Выйти".
    # But wait, the individual apps might not have UI for username.
    # Let's see if we can do this later.
    
    path.write_text(content, "utf-8")
    print(f"Updated {app_path}")

for app in apps:
    update_app(app)
