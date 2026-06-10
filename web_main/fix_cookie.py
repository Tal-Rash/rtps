import os
from pathlib import Path

app_path = Path("G:/Мой диск/Codex/rtps/web_main/app.py")
content = app_path.read_text("utf-8")

old_cookie_value = '''def _cookie_value(user_id: str, role: str, modules: str, full_name: str) -> str:
    expiry = int(dt.datetime.now().timestamp()) + SESSION_TTL_SECONDS
    safe_name = full_name.replace(":", " ")
    payload = f"{user_id}:{role}:{modules}:{safe_name}:{expiry}"'''

new_cookie_value = '''def _cookie_value(user_id: str, role: str, modules: str, full_name: str) -> str:
    import urllib.parse
    expiry = int(dt.datetime.now().timestamp()) + SESSION_TTL_SECONDS
    safe_name = urllib.parse.quote(full_name.replace(":", " "))
    payload = f"{user_id}:{role}:{modules}:{safe_name}:{expiry}"'''

content = content.replace(old_cookie_value, new_cookie_value)

# Update verify_cookie in web_main
old_verify_ret1 = '''        return user_id, role, modules, safe_name'''
new_verify_ret1 = '''        import urllib.parse
        return user_id, role, modules, urllib.parse.unquote(safe_name)'''

# Replace it inside _verify_cookie. It occurs twice in web_main/app.py because of two try blocks.
content = content.replace(old_verify_ret1, new_verify_ret1)

app_path.write_text(content, "utf-8")
print("Fixed web_main cookie encode")
