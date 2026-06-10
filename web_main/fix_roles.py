import os
from pathlib import Path

apps = [
    "G:/Мой диск/Codex/rtps/web_main/app.py",
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
    
    old_check = '''        if role not in {"view", "edit"}:
            return None'''
    
    if old_check in content:
        content = content.replace(old_check + "\n", "")
        content = content.replace(old_check, "")
        path.write_text(content, "utf-8")
        print(f"Fixed {app_path}")
    else:
        print(f"Not found in {app_path}")

for app in apps:
    update_app(app)
