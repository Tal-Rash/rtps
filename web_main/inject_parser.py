import os
from pathlib import Path

cookie_parser_code = '''
def parse_cookie_values(handler, name: str) -> list[str]:
    raw = handler.headers.get("Cookie", "")
    values = []
    for part in raw.split(";"):
        if "=" not in part: continue
        k, v = part.split("=", 1)
        if k.strip() == name: values.append(v.strip())
    return values
'''

def inject_parser(app_path):
    path = Path(app_path)
    if not path.exists(): return
    content = path.read_text("utf-8")
    if "def parse_cookie_values" not in content:
        content = content.replace("def verify_cookie(", cookie_parser_code + "\ndef verify_cookie(")
        path.write_text(content, "utf-8")
        print(f"Injected parser into {app_path}")
    else:
        print(f"Parser already exists in {app_path}")

inject_parser("G:/Мой диск/Codex/rtps/web_spravochnik/app.py")
inject_parser("G:/Мой диск/Codex/rtps/web_grafik_ppr/app.py")
