import os
import re
from pathlib import Path

def get_new_verify_cookie(func_name="verify_cookie"):
    return f'''def {func_name}(value: str) -> tuple[str, str, str, str] | None:
    for sep in (":", "|"):
        try:
            parts = value.rsplit(sep, 5)
            if len(parts) == 6:
                user_id, role, modules, safe_name, expiry_text, sig = parts
                payload = f"{{user_id}}{{sep}}{{role}}{{sep}}{{modules}}{{sep}}{{safe_name}}{{sep}}{{expiry_text}}"
            elif len(parts) == 4:
                # legacy
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
    return None'''

def get_new_current_session(cookie_parser="parse_cookie_values", func_name="verify_cookie"):
    return f'''def current_session(handler) -> tuple[str, str, str, str] | None:
    for token in {cookie_parser}(handler, SESSION_COOKIE):
        session = {func_name}(token)
        if session:
            return session
    return None'''

def get_new_require_auth(mod_name):
    return f'''def require_auth(handler, need_edit: bool = False) -> tuple[str, str, str, str] | None:
    session = current_session(handler)
    if not session:
        return None
    user_id, role, modules, safe_name = session
    mods = [m.strip() for m in modules.split(",")]
    if "admin" not in mods and "{mod_name}" not in mods:
        return None
    if need_edit and role not in ("edit", "editor", "admin"):
        return None
    return session'''

def fix_app(app_path, mod_name):
    path = Path(app_path)
    if not path.exists():
        return
    content = path.read_text("utf-8")
    
    # Replace verify_cookie
    if "def _verify_cookie" in content:
        content = re.sub(r'def _verify_cookie.*?return None\n', get_new_verify_cookie('_verify_cookie') + '\n', content, flags=re.DOTALL)
        v_func = '_verify_cookie'
    else:
        content = re.sub(r'def verify_cookie.*?return None\n', get_new_verify_cookie('verify_cookie') + '\n', content, flags=re.DOTALL)
        v_func = 'verify_cookie'
        
    # Replace current_session
    c_func = "_parse_cookie_values" if "_parse_cookie_values" in content else "parse_cookie_values"
    content = re.sub(r'def current_session\(.*?\).*?return None\n', get_new_current_session(c_func, v_func) + '\n', content, flags=re.DOTALL)
    
    # Replace require_auth
    if "def require_auth" in content:
        content = re.sub(r'def require_auth\(.*?\).*?return session\n', get_new_require_auth(mod_name) + '\n', content, flags=re.DOTALL)
        content = re.sub(r'def require_auth\(.*?\).*?return None\n', get_new_require_auth(mod_name) + '\n', content, flags=re.DOTALL)
    
    path.write_text(content, "utf-8")
    print(f"Fixed {mod_name}")

fix_app("G:/Мой диск/Codex/rtps/web_zamer_kp/app.py", "zamer_kp")
fix_app("G:/Мой диск/Codex/rtps/web_grafik_ppr/app.py", "grafik_ppr")
fix_app("G:/Мой диск/Codex/rtps/web_spravochnik/app.py", "spravochnik")
