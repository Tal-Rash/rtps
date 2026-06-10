import os
from pathlib import Path

def get_new_block(mod_name, v_func="verify_cookie", c_func="parse_cookie_values"):
    return f'''def {v_func}(value: str) -> tuple[str, str, str, str] | None:
    for sep in (":", "|"):
        try:
            parts = value.rsplit(sep, 5)
            if len(parts) == 6:
                user_id, role, modules, safe_name, expiry_text, sig = parts
                payload = f"{{user_id}}{{sep}}{{role}}{{sep}}{{modules}}{{sep}}{{safe_name}}{{sep}}{{expiry_text}}"
            elif len(parts) == 4:
                username, role, expiry_text, sig = parts
                payload = f"{{username}}{{sep}}{{role}}{{sep}}{{expiry_text}}"
                user_id, modules, safe_name = username, "", username
            else:
                continue
                
            secrets_to_try = [WEB_SECRET]
            if LEGACY_WEB_SECRET and LEGACY_WEB_SECRET not in secrets_to_try:
                secrets_to_try.append(LEGACY_WEB_SECRET)
                
            matched = False
            import hmac
            import hashlib
            for secret in secrets_to_try:
                expected = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
                if hmac.compare_digest(expected, sig):
                    matched = True
                    break
                    
            if not matched:
                continue
            import datetime as dt
            if float(expiry_text) < dt.datetime.now().timestamp():
                return None
                
            import urllib.parse
            return user_id, role, modules, urllib.parse.unquote(safe_name)
        except Exception:
            continue
    return None

def current_session(handler) -> tuple[str, str, str, str] | None:
    for token in {c_func}(handler, SESSION_COOKIE):
        session = {v_func}(token)
        if session:
            return session
    return None

def require_auth(handler, need_edit: bool = False) -> tuple[str, str, str, str] | None:
    session = current_session(handler)
    if not session:
        return None
    user_id, role, modules, safe_name = session
    mods = [m.strip() for m in modules.split(",")]
    if "admin" not in mods and "{mod_name}" not in mods:
        return None
    if need_edit and role not in ("edit", "editor", "admin"):
        return None
    return session
'''

def fix_app(app_path, mod_name):
    path = Path(app_path)
    if not path.exists():
        return
    lines = path.read_text("utf-8").splitlines()
    
    new_lines = []
    skip = False
    v_func = "verify_cookie"
    c_func = "parse_cookie_values"
    
    for line in lines:
        if line.startswith("def _verify_cookie("):
            skip = True
            v_func = "_verify_cookie"
        elif line.startswith("def verify_cookie("):
            skip = True
            v_func = "verify_cookie"
            
        if line.startswith("def _parse_cookie_values("):
            c_func = "_parse_cookie_values"
            
        if skip:
            if line.startswith("def route_path(") or line.startswith("def _parse_cookies(") or line.startswith("def send_html(") or line.startswith("def _redirect("):
                skip = False
                new_lines.append(get_new_block(mod_name, v_func, c_func))
            else:
                continue
                
        if not skip:
            new_lines.append(line)
            
    path.write_text("\n".join(new_lines), "utf-8")
    print(f"Fixed {mod_name}")

fix_app("G:/Мой диск/Codex/rtps/web_zamer_kp/app.py", "zamer_kp")
fix_app("G:/Мой диск/Codex/rtps/web_grafik_ppr/app.py", "grafik_ppr")
fix_app("G:/Мой диск/Codex/rtps/web_spravochnik/app.py", "spravochnik")
