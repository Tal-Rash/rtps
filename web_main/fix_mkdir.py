import os
from pathlib import Path

app_path = Path("G:/Мой диск/Codex/rtps/web_main/app.py")
content = app_path.read_text("utf-8")

old_init = '''def init_db() -> None:
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:'''

new_init = '''def init_db() -> None:
    try:
        DB_FILE.parent.mkdir(parents=True, exist_ok=True)'''

if old_init in content:
    content = content.replace(old_init, new_init)
    app_path.write_text(content, "utf-8")
    print("Fixed init_db mkdir")
else:
    print("Already fixed or not found")
