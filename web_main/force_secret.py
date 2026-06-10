import re
from pathlib import Path

apps = [
    "G:/Мой диск/Codex/rtps/web_main/app.py",
    "G:/Мой диск/Codex/rtps/web_zamer_kp/app.py",
    "G:/Мой диск/Codex/rtps/web_grafik_ppr/app.py",
    "G:/Мой диск/Codex/rtps/web_spravochnik/app.py"
]

for app in apps:
    path = Path(app)
    if not path.exists(): continue
    content = path.read_text("utf-8")
    
    # Remove os.environ.get("WEB_SECRET") logic and force reading from web_secret.txt
    new_secret_code = '''def load_web_secret() -> str:
    try:
        secret_file = Path(__file__).parent.parent / "data" / "web_secret.txt"
        if secret_file.exists():
            secret = secret_file.read_text(encoding="utf-8").strip()
            if secret: return secret
    except Exception:
        pass
    return "opYbo6NB8pb7dChYQkmHEvUH6K4hAHjuzi2qEYOC024"
'''
    content = re.sub(r'def load_web_secret\(\) -> str:.*?return [^"\n]*?opYbo6NB8pb7dChYQkmHEvUH6K4hAHjuzi2qEYOC024["\']?\n?', new_secret_code, content, flags=re.DOTALL)
    
    # In case web_main uses a different pattern
    content = re.sub(r'def load_web_secret\(\) -> str:.*?return secret\n\n', new_secret_code + "\n", content, flags=re.DOTALL)

    path.write_text(content, "utf-8")
    print(f"Fixed {path.name} in {path.parent.name}")

