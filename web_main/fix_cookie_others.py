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
    
    old_verify_ret = '''            return user_id, role, modules, safe_name'''
    new_verify_ret = '''            import urllib.parse
            return user_id, role, modules, urllib.parse.unquote(safe_name)'''
    
    # Do replacing
    if old_verify_ret in content:
        content = content.replace(old_verify_ret, new_verify_ret)
        path.write_text(content, "utf-8")
        print(f"Updated {app_path}")
    else:
        print(f"Already updated or not found in {app_path}")

for app in apps:
    update_app(app)
